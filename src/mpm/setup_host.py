from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .host import HostInfo, detect_host


FLATHUB_URL = "https://flathub.org/repo/flathub.flatpakrepo"

STANDARD_BOXES = {
    "mpm-ubuntu-apps": "docker.io/library/ubuntu:24.04",
    "mpm-debian-apps": "docker.io/library/debian:stable",
    "mpm-fedora-apps": "registry.fedoraproject.org/fedora:latest",
}


@dataclass(frozen=True)
class SetupCheck:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class SetupApplyAction:
    action_id: str
    label: str
    command: list[str]


@dataclass(frozen=True)
class SetupApplyResult:
    action_id: str
    label: str
    command: list[str]
    state: str
    detail: str


@dataclass(frozen=True)
class SetupReport:
    info: HostInfo
    checks: list[SetupCheck]
    actions: list[str]
    apply_actions: list[SetupApplyAction]


def _run_stdout(argv: list[str], *, timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def _install_command(info: HostInfo, *packages: str) -> str | None:
    if not packages:
        return None
    joined = " ".join(packages)
    if info.family == "arch":
        return f"sudo pacman -S {joined}"
    if info.family == "debian":
        return f"sudo apt install {joined}"
    if info.family == "fedora":
        return f"sudo dnf install {joined}"
    if info.family == "suse":
        return f"sudo zypper install {joined}"
    return None


def _pyside_package(info: HostInfo) -> str:
    return {
        "arch": "pyside6",
        "debian": "python3-pyside6.qtwidgets",
        "fedora": "python3-pyside6",
        "suse": "python3-pyside6",
    }.get(info.family, "PySide6")


def _flatpak_package(info: HostInfo) -> str:
    return "flatpak"


def _podman_distrobox_packages(info: HostInfo) -> tuple[str, str]:
    return ("podman", "distrobox")


def _box_names_from_output(output: str) -> set[str]:
    names: set[str] = set()
    name_index = 1
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        separator = stripped.replace("|", "").replace("+", "").strip()
        if separator and set(separator) <= {"-"}:
            continue

        columns = [part.strip() for part in stripped.split("|")] if "|" in stripped else stripped.split()
        lower_columns = [column.casefold() for column in columns]
        if "name" in lower_columns:
            name_index = lower_columns.index("name")
            continue
        if "id" in lower_columns and "status" in lower_columns:
            continue

        name = columns[name_index] if len(columns) > name_index else ""
        if name:
            names.add(name)
    return names


def build_setup_report() -> SetupReport:
    info = detect_host()
    checks: list[SetupCheck] = []
    actions: list[str] = []
    apply_actions: list[SetupApplyAction] = []

    pretty_name = info.os_release.get("PRETTY_NAME") or info.os_release.get("ID") or "unknown"
    checks.append(SetupCheck("distro", "ok" if info.family != "unknown" else "warning", f"{pretty_name} ({info.family})"))
    checks.append(SetupCheck("native-manager", "ok" if info.native_manager else "warning", info.native_manager or "not detected"))

    python_detail = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_state = "ok" if sys.version_info >= (3, 11) else "missing"
    checks.append(SetupCheck("python", python_state, python_detail))

    if importlib.util.find_spec("PySide6"):
        checks.append(SetupCheck("pyside6", "ok", "PySide6 importable"))
    else:
        package = _pyside_package(info)
        checks.append(SetupCheck("pyside6", "missing", f"{package} not importable"))
        command = _install_command(info, package)
        actions.append(f"install PySide6: {command}" if command else f"install PySide6 manually: {package}")

    if info.commands.get("flatpak"):
        checks.append(SetupCheck("flatpak", "ok", info.commands["flatpak"] or "available"))
        code, stdout, stderr = _run_stdout(["flatpak", "remotes", "--columns=name"])
        if code == 0 and any(line.strip().casefold() == "flathub" for line in stdout.splitlines()):
            checks.append(SetupCheck("flathub", "ok", "remote configured"))
        else:
            detail = stderr.strip() or "remote not configured"
            checks.append(SetupCheck("flathub", "warning", detail))
            actions.append(f"add flathub: flatpak remote-add --if-not-exists flathub {FLATHUB_URL}")
            apply_actions.append(
                SetupApplyAction(
                    action_id="add-flathub",
                    label="add flathub",
                    command=["flatpak", "remote-add", "--if-not-exists", "flathub", FLATHUB_URL],
                )
            )
    else:
        checks.append(SetupCheck("flatpak", "missing", "flatpak command not found"))
        command = _install_command(info, _flatpak_package(info))
        actions.append(f"install flatpak: {command}" if command else "install flatpak manually")

    if info.family == "arch":
        helper = "yay" if info.commands.get("yay") else "paru" if info.commands.get("paru") else ""
        if helper:
            checks.append(SetupCheck("aur-helper", "ok", helper))
        else:
            checks.append(SetupCheck("aur-helper", "missing", "neither yay nor paru found"))
            actions.append("install AUR helper: review and install yay or paru manually")
    else:
        checks.append(SetupCheck("aur-helper", "skipped", "AUR is Arch-only"))

    snapper_state = "ok" if info.snapshot == "snapper-root-ready" else "warning"
    checks.append(SetupCheck("snapper", snapper_state, info.snapshot))
    if info.family == "arch" and info.snapshot != "snapper-root-ready":
        actions.append("review snapper: configure Snapper root or use --no-snapshot explicitly per install")

    podman = bool(info.commands.get("podman"))
    distrobox = bool(info.commands.get("distrobox"))
    checks.append(SetupCheck("podman", "ok" if podman else "missing", info.commands.get("podman") or "podman command not found"))
    checks.append(SetupCheck("distrobox", "ok" if distrobox else "missing", info.commands.get("distrobox") or "distrobox command not found"))
    if not (podman and distrobox):
        command = _install_command(info, *_podman_distrobox_packages(info))
        actions.append(f"install podman and distrobox: {command}" if command else "install podman and distrobox manually")

    existing_boxes: set[str] = set()
    if distrobox:
        code, stdout, stderr = _run_stdout(["distrobox", "list", "--no-color"])
        if code == 0:
            existing_boxes = _box_names_from_output(stdout)
        else:
            checks.append(SetupCheck("distrobox-list", "warning", stderr.strip() or "distrobox list failed"))

    if podman and distrobox:
        for name, image in STANDARD_BOXES.items():
            if name in existing_boxes:
                checks.append(SetupCheck(f"container:{name}", "ok", "exists"))
            else:
                checks.append(SetupCheck(f"container:{name}", "missing", image))
                actions.append(f"create box {name}: distrobox create --yes --unshare-devsys --name {name} --image {image}")
                apply_actions.append(
                    SetupApplyAction(
                        action_id=f"create-box:{name}",
                        label=f"create box {name}",
                        command=["distrobox", "create", "--yes", "--unshare-devsys", "--name", name, "--image", image],
                    )
                )

    if info.terminal:
        checks.append(SetupCheck("terminal", "ok", info.terminal))
    else:
        checks.append(SetupCheck("terminal", "missing", "no supported terminal found"))
        actions.append("install terminal: install one of konsole, gnome-terminal, xfce4-terminal, alacritty, kitty, or xterm")

    available = ", ".join([*info.host_backends, *info.portable_backends]) or "none"
    unavailable = []
    for backend in ("pacman", "aur", "flatpak", "distrobox"):
        if backend not in info.host_backends and backend not in info.portable_backends:
            unavailable.append(backend)
    checks.append(SetupCheck("backends-available", "ok", available))
    checks.append(SetupCheck("backends-unavailable", "ok" if not unavailable else "warning", ", ".join(unavailable) or "none"))

    return SetupReport(info=info, checks=checks, actions=actions, apply_actions=apply_actions)


def format_setup_check(report: SetupReport) -> str:
    lines = ["setup-host-check:"]
    for check in report.checks:
        lines.append(f"- {check.name}: {check.state} - {check.detail}")
    return "\n".join(lines)


def format_setup_plan(report: SetupReport) -> str:
    lines = ["setup-host-plan:"]
    if not report.actions:
        lines.append("- no actions needed")
    else:
        for action in dict.fromkeys(report.actions):
            lines.append(f"- {action}")
    return "\n".join(lines)


def _dedupe_apply_actions(actions: list[SetupApplyAction]) -> list[SetupApplyAction]:
    seen: set[str] = set()
    deduped: list[SetupApplyAction] = []
    for action in actions:
        if action.action_id in seen:
            continue
        seen.add(action.action_id)
        deduped.append(action)
    return deduped


def apply_setup_report(report: SetupReport) -> list[SetupApplyResult]:
    results: list[SetupApplyResult] = []
    for action in _dedupe_apply_actions(report.apply_actions):
        try:
            completed = subprocess.run(action.command, check=False, capture_output=True, text=True)
        except OSError as exc:
            results.append(
                SetupApplyResult(
                    action_id=action.action_id,
                    label=action.label,
                    command=action.command,
                    state="failed",
                    detail=str(exc),
                )
            )
            continue

        detail = (completed.stderr or completed.stdout).strip()
        if completed.returncode == 0:
            results.append(
                SetupApplyResult(
                    action_id=action.action_id,
                    label=action.label,
                    command=action.command,
                    state="applied",
                    detail=detail or "ok",
                )
            )
        else:
            results.append(
                SetupApplyResult(
                    action_id=action.action_id,
                    label=action.label,
                    command=action.command,
                    state="failed",
                    detail=detail or f"exit status {completed.returncode}",
                )
            )
    return results


def _manual_actions(report: SetupReport) -> list[str]:
    automated = {f"{action.label}: {shlex.join(action.command)}" for action in report.apply_actions}
    return [action for action in dict.fromkeys(report.actions) if action not in automated]


def format_setup_apply(report: SetupReport, results: list[SetupApplyResult]) -> str:
    lines = ["setup-host-apply:"]
    if not results:
        lines.append("- no automated actions to apply")
    else:
        for result in results:
            lines.append(f"- {result.label}: {result.state} - {result.detail}")

    manual = _manual_actions(report)
    if manual:
        lines.append("manual-actions:")
        for action in manual:
            lines.append(f"- {action}")
    return "\n".join(lines)


def setup_report_json(report: SetupReport, *, mode: str) -> str:
    return json.dumps(
        {
            "mode": mode,
            "host": report.info.to_dict(),
            "checks": [
                {
                    "name": check.name,
                    "state": check.state,
                    "detail": check.detail,
                }
                for check in report.checks
            ],
            "actions": list(dict.fromkeys(report.actions)),
            "apply_actions": [
                {
                    "id": action.action_id,
                    "label": action.label,
                    "command": action.command,
                }
                for action in _dedupe_apply_actions(report.apply_actions)
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def setup_apply_json(report: SetupReport, results: list[SetupApplyResult]) -> str:
    return json.dumps(
        {
            "mode": "apply",
            "host": report.info.to_dict(),
            "results": [
                {
                    "id": result.action_id,
                    "label": result.label,
                    "command": result.command,
                    "state": result.state,
                    "detail": result.detail,
                }
                for result in results
            ],
            "manual_actions": _manual_actions(report),
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
