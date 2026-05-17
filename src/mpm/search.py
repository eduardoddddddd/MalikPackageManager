from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
import time
from typing import Any, Iterable, Protocol


HOST_BACKENDS = {"pacman", "aur"}
CONTAINER_BACKENDS = {
    "distrobox-deb",
    "distrobox-rpm",
    "distrobox-apt",
    "distrobox-dnf",
    "distrobox-zypper",
}
LOW_RISK_BACKENDS = {"flatpak", "pacman"}
COMMUNITY_BACKENDS = {"aur"}


def normalize_token(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _route_part(value: object, fallback: str = "unknown") -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold().strip()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9._+-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or fallback


def make_route_id(provider: str, source: str, package_name: str) -> str:
    return ":".join(
        [
            _route_part(provider),
            _route_part(source),
            _route_part(package_name),
        ]
    )


def _split_tags(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [tag.strip() for tag in str(value or "").split(",") if tag.strip()]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        stripped = str(value or "").strip()
        key = normalize_token(stripped)
        if not stripped or not key or key in seen:
            continue
        seen.add(key)
        result.append(stripped)
    return result


def _infer_risk_level(backend: str, is_community: bool, requires_host_mutation: bool) -> str:
    if is_community or backend in COMMUNITY_BACKENDS:
        return "medium"
    if requires_host_mutation and backend not in LOW_RISK_BACKENDS:
        return "medium"
    return "low"


@dataclass
class CatalogRoute:
    route_id: str = ""
    provider: str = ""
    backend: str = ""
    source: str = ""
    display_name: str = ""
    package_name: str = ""
    app_id: str = ""
    version: str = ""
    summary: str = ""
    description: str = ""
    homepage: str = ""
    license: str = ""
    publisher: str = ""
    install_target: str = ""
    install_backend: str = ""
    install_app_id: str = ""
    requires_host_mutation: bool = False
    requires_container: bool = False
    requires_snapshot: bool = False
    is_official: bool = False
    is_community: bool = False
    risk_level: str = "unknown"
    quality_score: float = 0.0
    match_score: float = 0.0
    recommendation_score: float = 0.0
    badges: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider = self.provider.strip() or self.backend.strip() or "unknown"
        self.backend = self.backend.strip()
        self.source = self.source.strip() or self.provider
        self.display_name = self.display_name.strip() or self.package_name.strip() or self.app_id.strip()
        self.package_name = self.package_name.strip() or self.install_target.strip() or self.app_id.strip()
        self.app_id = self.app_id.strip()
        self.install_target = self.install_target.strip() or self.package_name or self.app_id or self.display_name
        self.install_backend = self.install_backend.strip() or self.backend
        self.install_app_id = self.install_app_id.strip() or self.app_id
        self.requires_host_mutation = bool(self.requires_host_mutation or self.backend in HOST_BACKENDS)
        self.requires_container = bool(self.requires_container or self.backend in CONTAINER_BACKENDS)
        self.requires_snapshot = bool(self.requires_snapshot or self.requires_host_mutation)
        self.is_community = bool(self.is_community or self.backend in COMMUNITY_BACKENDS)
        self.risk_level = (self.risk_level or "").strip()
        if not self.risk_level or self.risk_level == "unknown":
            self.risk_level = _infer_risk_level(self.backend, self.is_community, self.requires_host_mutation)
        self.badges = _dedupe(self.badges)
        self.warnings = _dedupe(self.warnings)
        self.aliases = _dedupe(self.aliases)
        if not self.route_id:
            self.route_id = make_route_id(self.provider, self.source, self.package_name or self.install_target)

    @classmethod
    def from_catalog_entry(cls, entry: dict[str, str]) -> "CatalogRoute":
        backend = entry.get("backend", "").strip()
        source = entry.get("source", "").strip()
        tags = _split_tags(entry.get("tags", ""))
        target = entry.get("target", "").strip()
        app_id = entry.get("app_id", "").strip()
        is_community = backend in COMMUNITY_BACKENDS or any(normalize_token(tag) == "community" for tag in tags)
        requires_host_mutation = backend in HOST_BACKENDS
        return cls(
            provider="curated",
            backend=backend,
            source=source,
            display_name=entry.get("name", "").strip(),
            package_name=target,
            app_id=app_id,
            summary=entry.get("summary", "").strip(),
            install_target=target,
            install_backend=backend,
            install_app_id=app_id,
            requires_host_mutation=requires_host_mutation,
            requires_container=backend in CONTAINER_BACKENDS,
            requires_snapshot=requires_host_mutation,
            is_official=not is_community,
            is_community=is_community,
            risk_level=_infer_risk_level(backend, is_community, requires_host_mutation),
            badges=_dedupe(["curated", *tags]),
            aliases=_dedupe([entry.get("name", ""), target, app_id]),
            raw=dict(entry),
        )


@dataclass
class AppGroup:
    group_id: str
    display_name: str
    summary: str = ""
    aliases: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    recommended_route_id: str = ""
    recommendation_reason: str = ""
    confidence: float = 0.0


@dataclass
class ProviderStatus:
    provider: str
    state: str = "ok"
    message: str = ""
    duration_ms: int = 0
    result_count: int = 0


@dataclass
class SearchResultSet:
    query: str = ""
    routes: list[CatalogRoute] = field(default_factory=list)
    groups: list[AppGroup] = field(default_factory=list)
    provider_statuses: list[ProviderStatus] = field(default_factory=list)
    duration_ms: int = 0


class SearchProvider(Protocol):
    provider_id: str
    display_name: str
    last_status: ProviderStatus

    def is_available(self) -> bool:
        ...

    def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
        ...


def _app_id_leaf(value: str) -> str:
    parts = [part for part in re.split(r"[._-]+", value) if part]
    return parts[-1] if parts else value


def group_key(route: CatalogRoute) -> str:
    for value in [*route.aliases, route.display_name]:
        normalized = normalize_token(value)
        if normalized:
            return normalized
    for value in [route.app_id, route.package_name, route.install_target]:
        if not value:
            continue
        normalized = normalize_token(_app_id_leaf(value))
        if normalized:
            return normalized
    return normalize_token(route.route_id) or "unknown"


def _match_candidates(route: CatalogRoute) -> list[str]:
    return _dedupe(
        [
            route.display_name,
            route.package_name,
            route.app_id,
            route.install_target,
            route.summary,
            route.description,
            *route.aliases,
            *route.badges,
        ]
    )


def local_match_score(route: CatalogRoute, query: str = "") -> float:
    query_key = normalize_token(query)
    if not query_key:
        return route.match_score

    best = 0.0
    for candidate in _match_candidates(route):
        candidate_key = normalize_token(candidate)
        if not candidate_key:
            continue
        if candidate_key == query_key:
            best = max(best, 100.0)
        elif candidate_key.startswith(query_key):
            best = max(best, 85.0)
        elif query_key in candidate_key:
            best = max(best, 65.0)
    return best


def local_quality_score(route: CatalogRoute) -> float:
    score = 45.0
    if route.provider == "curated":
        score += 12.0
    if route.is_official:
        score += 12.0
    if route.is_community:
        score -= 12.0
    if route.risk_level == "low":
        score += 10.0
    elif route.risk_level == "medium":
        score -= 4.0
    elif route.risk_level == "high":
        score -= 20.0
    if route.homepage:
        score += 3.0
    if route.publisher:
        score += 3.0
    badge_keys = {normalize_token(badge) for badge in route.badges}
    if "flathub" in badge_keys:
        score += 6.0
    if "sandbox" in badge_keys or route.backend == "flatpak":
        score += 4.0
    score -= min(20.0, 5.0 * len(route.warnings))
    return max(0.0, min(100.0, score))


def local_recommendation_score(route: CatalogRoute, query: str = "") -> float:
    quality = local_quality_score(route)
    match = local_match_score(route, query)
    score = quality + (match * 0.25)

    if route.provider == "curated":
        score += 8.0
    if route.backend == "flatpak":
        score += 10.0
    elif route.backend == "pacman":
        score += 2.0
    elif route.backend in {"distrobox-deb", "distrobox-rpm", "distrobox-apt", "distrobox-dnf"}:
        score += 6.0
    elif route.backend == "aur":
        score -= 14.0
    elif route.backend == "appimage":
        score -= 3.0

    if route.requires_container:
        score += 4.0
    if route.requires_host_mutation:
        score -= 8.0
    if route.requires_snapshot:
        score += 2.0
    if route.is_official:
        score += 4.0
    if route.is_community:
        score -= 8.0

    return max(0.0, min(100.0, score))


def _recommendation_reason(route: CatalogRoute) -> str:
    if route.provider == "curated":
        return "Curated MPM route selected by local policy."
    if route.backend == "flatpak":
        return "Flatpak is a mainstream GUI route that keeps the Arch host clean."
    if route.backend == "pacman":
        return "Official Arch route selected; host mutation requires snapshot protection."
    if route.backend in CONTAINER_BACKENDS:
        return "Container route keeps DEB/RPM-style packages away from the Arch host."
    if route.backend == "aur":
        return "AUR route is available but community-sourced and should be reviewed."
    return "Highest local recommendation score."


def _apply_local_scores(route: CatalogRoute, query: str = "") -> None:
    route.match_score = local_match_score(route, query)
    route.quality_score = local_quality_score(route)
    route.recommendation_score = local_recommendation_score(route, query)


def group_routes(routes: Iterable[CatalogRoute], query: str = "") -> list[AppGroup]:
    buckets: dict[str, list[CatalogRoute]] = {}
    for route in routes:
        _apply_local_scores(route, query)
        buckets.setdefault(group_key(route), []).append(route)

    scored_groups: list[tuple[float, AppGroup]] = []
    for key, bucket in buckets.items():
        sorted_routes = sorted(
            bucket,
            key=lambda item: (-item.recommendation_score, -item.quality_score, item.route_id),
        )
        recommended = sorted_routes[0]
        aliases = _dedupe(
            value
            for route in sorted_routes
            for value in [
                route.display_name,
                route.package_name,
                route.app_id,
                route.install_target,
                *route.aliases,
            ]
        )
        group = AppGroup(
            group_id=key,
            display_name=recommended.display_name or recommended.package_name,
            summary=recommended.summary,
            aliases=aliases,
            routes=[route.route_id for route in sorted_routes],
            recommended_route_id=recommended.route_id,
            recommendation_reason=_recommendation_reason(recommended),
            confidence=max(0.0, min(1.0, recommended.recommendation_score / 100.0)),
        )
        scored_groups.append((recommended.recommendation_score, group))

    scored_groups.sort(key=lambda item: (-item[0], item[1].display_name.casefold(), item[1].group_id))
    return [group for _, group in scored_groups]


def search_all(
    query: str,
    providers: Iterable[SearchProvider],
    *,
    enabled_sources: Iterable[str] | None = None,
    limit_per_source: int = 20,
    timeout_per_source: float | None = 3.0,
) -> SearchResultSet:
    started = time.monotonic()
    enabled = {normalize_token(source) for source in enabled_sources or [] if normalize_token(source)}
    routes: list[CatalogRoute] = []
    statuses: list[ProviderStatus] = []

    for provider in providers:
        provider_key = normalize_token(getattr(provider, "provider_id", ""))
        provider_aliases = {
            normalize_token(alias)
            for alias in getattr(provider, "source_aliases", [])
            if normalize_token(alias)
        }
        if enabled and provider_key not in enabled and not (provider_aliases & enabled):
            continue

        provider_started = time.monotonic()
        try:
            provider_routes = provider.search(query, limit=limit_per_source, timeout=timeout_per_source)
            routes.extend(provider_routes)
            status = getattr(provider, "last_status", None)
            if isinstance(status, ProviderStatus):
                duration_ms = status.duration_ms or int((time.monotonic() - provider_started) * 1000)
                statuses.append(
                    ProviderStatus(
                        provider=status.provider,
                        state=status.state,
                        message=status.message,
                        duration_ms=duration_ms,
                        result_count=status.result_count,
                    )
                )
            else:
                statuses.append(
                    ProviderStatus(
                        provider=getattr(provider, "provider_id", "unknown"),
                        state="ok",
                        message="provider searched",
                        duration_ms=int((time.monotonic() - provider_started) * 1000),
                        result_count=len(provider_routes),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - provider failures must not break federated search.
            statuses.append(
                ProviderStatus(
                    provider=getattr(provider, "provider_id", "unknown"),
                    state="warning",
                    message=f"provider failed: {exc}",
                    duration_ms=int((time.monotonic() - provider_started) * 1000),
                    result_count=0,
                )
            )

    groups = group_routes(routes, query=query)
    return SearchResultSet(
        query=query,
        routes=routes,
        groups=groups,
        provider_statuses=statuses,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
