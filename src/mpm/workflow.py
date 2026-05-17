from __future__ import annotations

import json
import re
from pathlib import Path


def parse_key_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        values[key.strip().lower()] = value.strip()
    return values


def resolved_preflight_backend(selected_backend: str, preflight_output: str) -> str:
    values = parse_key_values(preflight_output)
    return values.get("backend") or selected_backend or "auto"


def preflight_requires_host_confirmation(selected_backend: str, preflight_output: str) -> bool:
    return resolved_preflight_backend(selected_backend, preflight_output) in {"pacman", "aur"}


def format_catalog_detail(entry: dict[str, str] | None) -> str:
    if not entry:
        return "Select a local catalog app."

    backend = entry.get("backend", "") or "auto"
    app_id = entry.get("app_id", "")
    lines = [
        f"name: {entry.get('name', '')}",
        f"target: {entry.get('target', '')}",
        f"backend: {backend}",
        f"source: {entry.get('source', '') or 'unknown'}",
        f"summary: {entry.get('summary', '') or 'none'}",
        f"tags: {entry.get('tags', '') or 'none'}",
    ]
    if app_id:
        lines.append(f"app_id: {app_id}")
    lines.extend(
        [
            "",
            "delegation:",
            "MPM passes target, backend, and optional app id to mpm-pkg.",
            "Backend policy and resolver behavior stay in mpm-pkg.",
        ]
    )
    return "\n".join(lines)


def parse_doctor_summary(output: str) -> dict[str, object]:
    summary: dict[str, object] = {
        "backend": "unknown",
        "box": "unknown",
        "missing_libraries": "unknown",
        "electron_like": "unknown",
        "repair_plan": [],
    }
    in_repair_plan = False
    repair_plan: list[str] = []

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped == "repair-plan:":
            in_repair_plan = True
            continue

        if in_repair_plan:
            if line.startswith("  - "):
                repair_plan.append(line[4:].strip())
                continue
            in_repair_plan = False

        if ":" not in line or line.startswith((" ", "\t")):
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "backend":
            summary["backend"] = value or "unknown"
        elif key == "box":
            summary["box"] = value or "unknown"
        elif key == "missing-libraries":
            summary["missing_libraries"] = value or "unknown"
        elif key == "electron-like":
            summary["electron_like"] = value or "unknown"
        elif key == "repair-plan" and value:
            repair_plan.append(value)

    summary["repair_plan"] = repair_plan
    return summary


def format_doctor_summary(summary: dict[str, object]) -> str:
    repair_plan = summary.get("repair_plan")
    plan_items = repair_plan if isinstance(repair_plan, list) else []
    lines = [
        f"backend: {summary.get('backend', 'unknown')}",
        f"box: {summary.get('box', 'unknown')}",
        f"missing libraries: {summary.get('missing_libraries', 'unknown')}",
        f"electron-like: {summary.get('electron_like', 'unknown')}",
        "repair-plan:",
    ]
    if plan_items:
        lines.extend(f"- {item}" for item in plan_items)
    else:
        lines.append("- none")
    return "\n".join(lines)


def format_preflight_confirmation(
    target: str,
    backend: str,
    explain_output: str,
    install_command: str,
) -> str:
    explained = parse_key_values(explain_output)
    resolved_backend = resolved_preflight_backend(backend, explain_output)
    source = explained.get("source", "unknown")
    kind = explained.get("kind", "unknown")
    reason = explained.get("reason", "No policy reason returned.")
    host_mutation = explained.get("host-mutation", "no")
    snapshot_status = explained.get("snapshot-status", "")
    lines = [
        f"Target: {target}",
        f"Backend: {resolved_backend}",
        f"Source: {source}",
        f"Kind: {kind}",
        f"Command: {install_command}",
        "",
        f"Policy: {reason}",
    ]
    if resolved_backend in {"pacman", "aur"}:
        lines.extend(
            [
                "",
                "Host-level backend selected. MPM will only continue after this explicit confirmation.",
                "This operation modifies the real host package database and may require sudo.",
            ]
        )
        if snapshot_status:
            lines.append(f"Snapshot: {snapshot_status}")
        elif host_mutation == "yes":
            lines.append("Snapshot: unknown; review the dry-run plan before continuing.")
    if resolved_backend == "aur":
        lines.extend(
            [
                "AUR packages are community supplied.",
                "Review the PKGBUILD and install scripts before accepting the helper prompts.",
            ]
        )
    return "\n".join(lines)


def format_uninstall_confirmation(dry_run_output: str) -> str:
    values = parse_key_values(dry_run_output)
    record_id = values.get("record-id", "unknown")
    target = values.get("target", "unknown")
    backend = values.get("backend", "unknown")
    app_id = values.get("app-id", "")
    data_policy = values.get("data-policy", "User data is preserved by default.")

    commands: list[str] = []
    in_commands = False
    for line in dry_run_output.splitlines():
        stripped = line.strip()
        if stripped == "commands:":
            in_commands = True
            continue
        if in_commands:
            if line.startswith("  - "):
                commands.append(line[4:].strip())
                continue
            if stripped and not line.startswith((" ", "\t")):
                in_commands = False

    lines = [
        f"Record: {record_id}",
        f"Target: {target}",
        f"Backend: {backend}",
    ]
    if app_id:
        lines.append(f"App ID: {app_id}")
    lines.extend(
        [
            f"Data policy: {data_policy}",
            "",
            "Commands:",
        ]
    )
    lines.extend(f"- {command}" for command in commands) if commands else lines.append("- none")
    if backend in {"pacman", "aur"}:
        lines.extend(
            [
                "",
                "Host-level backend selected. MPM will pass --yes only after this confirmation.",
            ]
        )
    return "\n".join(lines)


def parse_history_output(output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("No mpm-pkg history"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        row = {str(key): "" if value is None else str(value) for key, value in raw.items()}
        if row.get("operation") in {"install", "uninstall", "repair"}:
            rows.append(row)
    return rows


def format_history_detail(entry: dict[str, str] | None, operation_log_path: str = "") -> str:
    if not entry:
        return "Select a history record."

    preferred = [
        "operation",
        "record_id",
        "install_id",
        "timestamp",
        "target",
        "backend",
        "result",
        "kind",
        "source",
        "app_id",
        "desktop_id",
        "box",
        "log_path",
    ]
    lines = [f"{key.replace('_', '-')}: {entry.get(key, '')}" for key in preferred if entry.get(key)]
    if operation_log_path:
        lines.append(f"operation-log-path: {operation_log_path}")
    detail = entry.get("detail", "")
    if detail:
        lines.extend(["", "detail:", detail])
    return "\n".join(lines)


def appimage_desktop_id(target: str) -> str | None:
    if not target.lower().endswith(".appimage"):
        return None
    return f"mpm-appimage-{Path(target).stem.lower().replace(' ', '-')}.desktop"


def infer_doctor_target(install_output: str, target: str, app_id: str) -> str | None:
    if app_id.strip():
        return app_id.strip()

    export_matches = re.findall(r"Exporting\s+(.+?)\s+from\s+(mpm-[^\s]+)", install_output)
    if export_matches:
        return export_matches[-1][0].strip()

    desktop_match = re.search(r"(mpm-appimage-[^\s/]+\.desktop)", install_output)
    if desktop_match:
        return desktop_match.group(1)

    return appimage_desktop_id(target)
