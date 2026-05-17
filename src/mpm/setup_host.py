from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
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
class SetupReport:
    info: HostInfo
    checks: list[SetupCheck]
    actions: list[str]


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
        "arch": "python-pyside6",
        "debian": "python3-pyside6.qtwidgets",
        "fedora": "python3-pyside6",
        "suse": "python3-pyside6",
    }.get(info.family, "PySide6")


def _flatpak_package(info: HostInfo) -> str:
    return "flatpak"


def _podman_distrobox_packages(info: HostInfo) -> tuple[str, str]:
    if info.family == "arch":
        return ("podman", "distrobox")
    return ("podman", "distrobox")


def _box_names_from_output(output: str) -> set[str]:
    names: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        if set(stripped.replace("|", "").strip()) <= {"-", "+"}:
            continue
        columns = [part.strip() for part in stripped.split("|")]
        lower_columns = [column.casefold() for column in columns]
        if "name" in lower_columns and "image" in lower_columns:
            continue
        name = columns[1] if len(columns) >= 2 else ""
        if name:
            names.add(name)
    return names


def build_setup_report() -> SetupReport:
    info = detect_host()
    checks: list[SetupCheck] = []
    actions: list[str] = []

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
                actions.append(f"create box {name}: distrobox create --name {name} --image {image}")

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

    return SetupReport(info=info, checks=checks, actions=actions)


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
