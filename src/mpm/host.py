from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
from typing import Callable, Mapping


HOST_COMMANDS = (
    "pacman",
    "yay",
    "paru",
    "flatpak",
    "distrobox",
    "podman",
    "apt",
    "dnf",
    "zypper",
    "snapper",
)

DESKTOP_COMMANDS = (
    "update-desktop-database",
    "kbuildsycoca6",
    "kbuildsycoca5",
)

TERMINAL_CANDIDATES = (
    "konsole",
    "gnome-terminal",
    "xfce4-terminal",
    "alacritty",
    "kitty",
    "wezterm",
    "foot",
    "st",
    "xterm",
)

ARCH_IDS = {"arch", "archlinux", "manjaro", "endeavouros", "endeavour", "garuda"}
DEBIAN_IDS = {"debian", "ubuntu", "linuxmint", "pop", "elementary", "raspbian"}
FEDORA_IDS = {"fedora", "rhel", "centos", "rocky", "almalinux", "nobara"}
SUSE_IDS = {"opensuse", "opensuse-tumbleweed", "opensuse-leap", "suse", "sles"}


@dataclass(frozen=True)
class HostInfo:
    os_release: dict[str, str]
    family: str
    native_manager: str | None
    commands: dict[str, str | None]
    host_backends: list[str]
    portable_backends: list[str]
    snapshot: str
    desktop: str
    terminal: str | None

    @property
    def is_arch_like(self) -> bool:
        return self.family == "arch"

    def to_dict(self) -> dict[str, object]:
        return {
            "os_release": self.os_release,
            "host_family": self.family,
            "native_manager": self.native_manager,
            "commands_available": {name: bool(path) for name, path in self.commands.items()},
            "command_paths": self.commands,
            "host_backends": self.host_backends,
            "portable_backends": self.portable_backends,
            "snapshot": self.snapshot,
            "desktop": self.desktop,
            "terminal": self.terminal,
        }


def parse_os_release_text(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if value:
            try:
                parsed = shlex.split(value, comments=False, posix=True)
            except ValueError:
                parsed = []
            if len(parsed) == 1:
                value = parsed[0]
            else:
                value = value.strip("'\"")
        data[key] = value
    return data


def os_release_path_from_env(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    return Path(env.get("MPM_HOST_OS_RELEASE", "/etc/os-release"))


def load_os_release(path: Path | None = None) -> dict[str, str]:
    path = path or os_release_path_from_env()
    try:
        return parse_os_release_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def classify_host_family(os_release: Mapping[str, str]) -> str:
    tokens: list[str] = []
    for key in ("ID", "ID_LIKE"):
        value = os_release.get(key, "")
        tokens.extend(part.strip().lower() for part in value.split() if part.strip())

    if any(token in ARCH_IDS for token in tokens):
        return "arch"
    if any(token in DEBIAN_IDS for token in tokens):
        return "debian"
    if any(token in FEDORA_IDS for token in tokens):
        return "fedora"
    if any(token in SUSE_IDS for token in tokens):
        return "suse"
    return "unknown"


def command_paths(
    names: tuple[str, ...] = HOST_COMMANDS + DESKTOP_COMMANDS + TERMINAL_CANDIDATES,
    *,
    finder: Callable[[str], str | None] = shutil.which,
) -> dict[str, str | None]:
    return {name: finder(name) for name in names}


def native_manager_for_family(family: str, commands: Mapping[str, str | None]) -> str | None:
    preferred = {
        "arch": "pacman",
        "debian": "apt",
        "fedora": "dnf",
        "suse": "zypper",
    }.get(family)
    if preferred and commands.get(preferred):
        return preferred
    for candidate in ("pacman", "apt", "dnf", "zypper"):
        if commands.get(candidate):
            return candidate
    return None


def snapshot_status(commands: Mapping[str, str | None], root_config: Path | None = None) -> str:
    root_config = root_config or Path(os.environ.get("MPM_SNAPPER_ROOT_CONFIG", "/etc/snapper/configs/root"))
    if not commands.get("snapper"):
        return "snapper-missing"
    if root_config.exists():
        return "snapper-root-ready"
    return "snapper-root-missing"


def detect_desktop(env: Mapping[str, str] | None = None) -> str:
    env = env or os.environ
    raw = " ".join(
        value
        for value in [
            env.get("XDG_CURRENT_DESKTOP", ""),
            env.get("DESKTOP_SESSION", ""),
            env.get("GDMSESSION", ""),
        ]
        if value
    ).lower()
    if not raw:
        return "unknown"
    if "kde" in raw or "plasma" in raw:
        return "kde"
    if "gnome" in raw:
        return "gnome"
    if "xfce" in raw:
        return "xfce"
    if "lxqt" in raw:
        return "lxqt"
    if "mate" in raw:
        return "mate"
    if "cinnamon" in raw:
        return "cinnamon"
    return raw.split()[0].replace(":", "-")


def _terminal_command_from_env(value: str) -> str:
    try:
        parts = shlex.split(value, comments=False, posix=True)
    except ValueError:
        parts = value.split()
    if not parts:
        return ""
    return Path(parts[0]).name


def choose_terminal(
    commands: Mapping[str, str | None],
    *,
    env: Mapping[str, str] | None = None,
    finder: Callable[[str], str | None] = shutil.which,
) -> str | None:
    env = env or os.environ
    for env_name in ("MPM_TERMINAL", "TERMINAL"):
        terminal = _terminal_command_from_env(env.get(env_name, ""))
        if terminal and (commands.get(terminal) or finder(terminal)):
            return terminal
    for terminal in TERMINAL_CANDIDATES:
        if commands.get(terminal):
            return terminal
    return None


def host_backends_for(family: str, commands: Mapping[str, str | None]) -> list[str]:
    if family != "arch":
        return []
    backends: list[str] = []
    if commands.get("pacman"):
        backends.append("pacman")
    if commands.get("yay") or commands.get("paru"):
        backends.append("aur")
    return backends


def portable_backends_for(commands: Mapping[str, str | None]) -> list[str]:
    backends: list[str] = []
    if commands.get("flatpak"):
        backends.append("flatpak")
    backends.append("appimage")
    if commands.get("distrobox") and commands.get("podman"):
        backends.append("distrobox")
    return backends


def detect_host(
    *,
    os_release_path: Path | None = None,
    finder: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] | None = None,
    snapper_root_config: Path | None = None,
) -> HostInfo:
    env = env or os.environ
    os_release = load_os_release(os_release_path or os_release_path_from_env(env))
    family = classify_host_family(os_release)
    commands = command_paths(finder=finder)
    return HostInfo(
        os_release=dict(os_release),
        family=family,
        native_manager=native_manager_for_family(family, commands),
        commands=commands,
        host_backends=host_backends_for(family, commands),
        portable_backends=portable_backends_for(commands),
        snapshot=snapshot_status(commands, snapper_root_config),
        desktop=detect_desktop(env),
        terminal=choose_terminal(commands, env=env, finder=finder),
    )


def format_host_info(info: HostInfo) -> str:
    def csv(values: list[str]) -> str:
        return ", ".join(values) if values else "none"

    lines = [
        f"host-family: {info.family}",
        f"native-manager: {info.native_manager or 'none'}",
        f"host-backends: {csv(info.host_backends)}",
        f"portable-backends: {csv(info.portable_backends)}",
        f"snapshot: {info.snapshot}",
        f"desktop: {info.desktop}",
        f"terminal: {info.terminal or 'none'}",
        "commands:",
    ]
    for name in HOST_COMMANDS:
        path = info.commands.get(name)
        lines.append(f"  - {name}: {path or 'missing'}")
    return "\n".join(lines)


def host_info_json(info: HostInfo) -> str:
    return json.dumps(info.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)


def arch_only_backend_error(backend: str, info: HostInfo) -> str:
    return (
        f"{backend} backend is Arch-only, but this host is '{info.family}'. "
        "Use portable backends such as flatpak, appimage, or distrobox on this host."
    )


def ensure_host_backend_available(backend: str, info: HostInfo | None = None) -> None:
    if backend not in {"pacman", "aur"}:
        return
    info = info or detect_host()
    if not info.is_arch_like:
        raise SystemExit(arch_only_backend_error(backend, info))
    if backend == "pacman" and not info.commands.get("pacman"):
        raise SystemExit("pacman backend requested on an Arch-like host, but pacman is not installed.")
    if backend == "aur" and not (info.commands.get("yay") or info.commands.get("paru")):
        raise SystemExit("AUR backend requested on an Arch-like host, but neither yay nor paru is installed.")
