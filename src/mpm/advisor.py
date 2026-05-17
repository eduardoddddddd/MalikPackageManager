from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from typing import Any, Mapping

from .search import AppGroup, CatalogRoute, SearchResultSet, normalize_token


POLICY_VERSION = "mpm-catalog-policy-v1"
SUPPORTED_PROVIDERS = {"none"}


@dataclass(frozen=True)
class AdvisorWarning:
    route_id: str
    level: str
    text: str


@dataclass(frozen=True)
class AdvisorResponse:
    provider: str = "none"
    state: str = "local-only"
    message: str = "LLM Advisor disabled; local policy used."
    recommended_route_id: str = ""
    recommendation_confidence: float = 0.0
    why: str = ""
    warnings: list[AdvisorWarning] = field(default_factory=list)
    labels: dict[str, list[str]] = field(default_factory=dict)
    advisor_input: dict[str, Any] = field(default_factory=dict)


def _route_backend(route: CatalogRoute) -> str:
    return route.install_backend or route.backend or "auto"


def _spanish_route_reason(route: CatalogRoute | None, fallback: str) -> str:
    if route is None:
        return fallback
    backend = _route_backend(route)
    if route.provider == "curated":
        return "es una ruta curada por MPM y encaja con la política local."
    if backend == "flatpak":
        return "Flatpak mantiene limpio el host Arch y es una ruta habitual para apps gráficas."
    if backend == "pacman":
        return "es una ruta oficial de Arch; requiere asumir mutación del host con protección de snapshot."
    if backend in {"distrobox-deb", "distrobox-rpm", "distrobox-apt", "distrobox-dnf"}:
        return "usa Distrobox para mantener paquetes DEB/RPM o repos externos fuera del host Arch."
    if backend == "aur":
        return "está disponible, pero es comunitaria y debe revisarse antes de instalar."
    if backend == "appimage":
        return "es portable y evita mutar el host, aunque puede requerir actualizaciones manuales."
    return fallback


def _route_to_advisor_dict(route: CatalogRoute) -> dict[str, Any]:
    return {
        "route_id": route.route_id,
        "provider": route.provider,
        "backend": route.backend,
        "install_backend": _route_backend(route),
        "source": route.source,
        "display_name": route.display_name,
        "package_name": route.package_name,
        "app_id": route.app_id,
        "version": route.version,
        "summary": route.summary,
        "publisher": route.publisher,
        "homepage": route.homepage,
        "requires_host_mutation": route.requires_host_mutation,
        "requires_container": route.requires_container,
        "requires_snapshot": route.requires_snapshot,
        "is_official": route.is_official,
        "is_community": route.is_community,
        "risk_level": route.risk_level,
        "quality_score": round(route.quality_score, 2),
        "match_score": round(route.match_score, 2),
        "recommendation_score": round(route.recommendation_score, 2),
        "badges": list(route.badges),
        "warnings": list(route.warnings),
        "artifact_format": str(route.raw.get("artifact_format", "")),
        "trust_level": str(route.raw.get("trust_level", "") or route.raw.get("trust", "")),
        "update_policy": str(route.raw.get("update_policy", "")),
        "uninstall_policy": str(route.raw.get("uninstall_policy", "")),
    }


def build_advisor_input(result: SearchResultSet, *, max_candidates: int = 30) -> dict[str, Any]:
    routes_by_id = {route.route_id: route for route in result.routes}
    ordered_ids: list[str] = []
    for group in result.groups:
        ordered_ids.extend(route_id for route_id in group.routes if route_id in routes_by_id)
    if not ordered_ids:
        ordered_ids = [route.route_id for route in result.routes]

    seen: set[str] = set()
    route_dicts: list[dict[str, Any]] = []
    for route_id in ordered_ids:
        if route_id in seen:
            continue
        seen.add(route_id)
        route_dicts.append(_route_to_advisor_dict(routes_by_id[route_id]))
        if len(route_dicts) >= max_candidates:
            break

    return {
        "task": "rank_install_routes",
        "policy_version": POLICY_VERSION,
        "query": result.query,
        "system_context": {
            "host": "Arch Linux",
            "desktop": "KDE Plasma",
            "principles": [
                "Keep host clean",
                "DEB/RPM install through Distrobox",
                "Pacman is only one backend",
                "Show every viable route",
                "Recommend but do not remove choices",
                "Never bypass MPM preflight",
            ],
        },
        "groups": [
            {
                "group_id": group.group_id,
                "display_name": group.display_name,
                "route_ids": list(group.routes),
                "recommended_route_id": group.recommended_route_id,
                "confidence": round(group.confidence, 2),
                "reason": group.recommendation_reason,
            }
            for group in result.groups
        ],
        "routes": route_dicts,
    }


def advisor_cache_key(advisor_input: Mapping[str, Any], *, provider: str = "none", model: str = "local") -> str:
    payload = {
        "provider": provider,
        "model": model,
        "policy_version": advisor_input.get("policy_version", POLICY_VERSION),
        "query": advisor_input.get("query", ""),
        "groups": advisor_input.get("groups", []),
        "routes": advisor_input.get("routes", []),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def route_policy_labels(route: CatalogRoute, *, recommended: bool = False) -> list[str]:
    labels: list[str] = []
    if recommended:
        labels.append("recommended")
    backend = _route_backend(route)
    labels.append(backend)
    if route.provider:
        labels.append(route.provider)
    if route.is_official:
        labels.append("official")
    if route.is_community:
        labels.append("community")
    if route.requires_container:
        labels.append("container")
    if route.requires_host_mutation:
        labels.append("host")
    if route.requires_snapshot:
        labels.append("snapshot")
    if route.risk_level:
        labels.append(f"risk:{route.risk_level}")
    labels.extend(route.badges)

    seen: set[str] = set()
    clean: list[str] = []
    for label in labels:
        normalized = normalize_token(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        clean.append(label)
    return clean


def route_policy_warnings(route: CatalogRoute) -> list[AdvisorWarning]:
    warnings = [
        AdvisorWarning(route_id=route.route_id, level="medium", text=warning)
        for warning in route.warnings
    ]
    if route.requires_host_mutation:
        warnings.append(
            AdvisorWarning(
                route_id=route.route_id,
                level="medium",
                text="Esta ruta muta el host Arch; debe pasar por preflight y snapshot cuando aplique.",
            )
        )
    if route.is_community:
        warnings.append(
            AdvisorWarning(
                route_id=route.route_id,
                level="medium",
                text="Ruta comunitaria: revisa procedencia, mantenedor y cambios antes de instalar.",
            )
        )
    if route.backend == "appimage":
        update_policy = str(route.raw.get("update_policy", "unknown") or "unknown")
        if update_policy in {"manual", "unknown", "not-supported"}:
            warnings.append(
                AdvisorWarning(
                    route_id=route.route_id,
                    level="low",
                    text="AppImage puede requerir actualizaciones manuales o política de updates externa.",
                )
            )
    return _dedupe_warnings(warnings)


def _dedupe_warnings(warnings: list[AdvisorWarning]) -> list[AdvisorWarning]:
    seen: set[tuple[str, str]] = set()
    result: list[AdvisorWarning] = []
    for warning in warnings:
        key = (warning.route_id, normalize_token(warning.text))
        if key in seen:
            continue
        seen.add(key)
        result.append(warning)
    return result


class LocalAdvisor:
    def __init__(self, *, provider: str = "none", state: str = "local-only", message: str = "") -> None:
        self.provider = provider
        self.state = state
        self.message = message or "LLM Advisor disabled; local policy used."

    def advise(self, result: SearchResultSet) -> AdvisorResponse:
        advisor_input = build_advisor_input(result)
        model = "local-policy"
        cache_key = advisor_cache_key(advisor_input, provider=self.provider, model=model)
        advisor_input["cache"] = {
            "key": cache_key,
            "ttl_hours": 168,
            "model": model,
        }
        if not result.groups:
            return AdvisorResponse(
                provider=self.provider,
                state=self.state,
                message=self.message,
                why="No hay rutas candidatas para asesorar. La búsqueda sigue funcionando sin LLM.",
                advisor_input=advisor_input,
            )

        group = result.groups[0]
        route_by_id = {route.route_id: route for route in result.routes}
        recommended = route_by_id.get(group.recommended_route_id)
        route_name = group.display_name or (recommended.display_name if recommended else "ruta seleccionada")
        reason = _spanish_route_reason(recommended, group.recommendation_reason or "tiene la mejor puntuación local.")
        why = (
            f"LLM Advisor está desactivado; uso la política local de MPM. "
            f"Recomiendo {route_name} porque {reason} "
            "Las rutas alternativas siguen visibles y seleccionables."
        )
        labels = {
            route.route_id: route_policy_labels(route, recommended=route.route_id == group.recommended_route_id)
            for route in result.routes
        }
        warnings = [warning for route in result.routes for warning in route_policy_warnings(route)]
        return AdvisorResponse(
            provider=self.provider,
            state=self.state,
            message=self.message,
            recommended_route_id=group.recommended_route_id,
            recommendation_confidence=group.confidence,
            why=why,
            warnings=warnings,
            labels=labels,
            advisor_input=advisor_input,
        )


def advisor_from_env(env: Mapping[str, str] | None = None) -> LocalAdvisor:
    values = env if env is not None else os.environ
    provider = values.get("MPM_LLM_PROVIDER", "none").strip().casefold() or "none"
    if provider in SUPPORTED_PROVIDERS:
        return LocalAdvisor(provider=provider)
    return LocalAdvisor(
        provider=provider,
        state="warning",
        message=f"LLM provider {provider!r} is not implemented in this MVP; falling back to local policy.",
    )


def advise_search_result(result: SearchResultSet, *, env: Mapping[str, str] | None = None) -> AdvisorResponse:
    return advisor_from_env(env).advise(result)


def format_advisor_response(response: AdvisorResponse) -> str:
    lines = [
        f"Advisor: {response.provider}",
        f"State: {response.state}",
        f"Message: {response.message}",
        f"Recommended route: {response.recommended_route_id or 'none'}",
        f"Confidence: {response.recommendation_confidence:.2f}",
        "",
        "Why:",
        response.why or "none",
        "",
        "Labels:",
    ]
    if response.labels:
        for route_id, labels in response.labels.items():
            lines.append(f"- {route_id}: {', '.join(labels) if labels else 'none'}")
    else:
        lines.append("- none")

    lines.extend(["", "Warnings:"])
    if response.warnings:
        for warning in response.warnings:
            lines.append(f"- [{warning.level}] {warning.route_id}: {warning.text}")
    else:
        lines.append("- none")
    return "\n".join(lines)
