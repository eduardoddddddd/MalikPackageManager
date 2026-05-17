from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mpm.host import (  # noqa: E402
    choose_terminal,
    classify_host_family,
    detect_host,
    parse_os_release_text,
)


class HostDetectionTests(unittest.TestCase):
    def test_parse_os_release_handles_quotes_and_id_like(self) -> None:
        parsed = parse_os_release_text(
            """
            NAME="EndeavourOS"
            ID=endeavouros
            ID_LIKE="arch linux"
            PRETTY_NAME='EndeavourOS rolling'
            """
        )

        self.assertEqual(parsed["ID"], "endeavouros")
        self.assertEqual(parsed["ID_LIKE"], "arch linux")
        self.assertEqual(parsed["PRETTY_NAME"], "EndeavourOS rolling")
        self.assertEqual(classify_host_family(parsed), "arch")

    def test_detect_host_reports_debian_native_and_distrobox_portable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            os_release = tmp / "os-release"
            os_release.write_text("ID=ubuntu\nID_LIKE=debian\n", encoding="utf-8")

            available = {
                "apt": "/bin/apt",
                "flatpak": "/bin/flatpak",
                "distrobox": "/bin/distrobox",
                "podman": "/bin/podman",
                "kitty": "/bin/kitty",
            }

            info = detect_host(
                os_release_path=os_release,
                finder=lambda name: available.get(name),
                env={"XDG_CURRENT_DESKTOP": "GNOME"},
                snapper_root_config=tmp / "missing-root",
            )

        self.assertEqual(info.family, "debian")
        self.assertEqual(info.native_manager, "apt")
        self.assertEqual(info.host_backends, [])
        self.assertEqual(info.portable_backends, ["flatpak", "appimage", "distrobox"])
        self.assertEqual(info.snapshot, "snapper-missing")
        self.assertEqual(info.desktop, "gnome")
        self.assertEqual(info.terminal, "kitty")

    def test_choose_terminal_prefers_known_order(self) -> None:
        commands = {
            "konsole": None,
            "gnome-terminal": None,
            "xfce4-terminal": "/bin/xfce4-terminal",
            "alacritty": "/bin/alacritty",
            "kitty": "/bin/kitty",
            "xterm": "/bin/xterm",
        }

        self.assertEqual(choose_terminal(commands), "xfce4-terminal")


if __name__ == "__main__":
    unittest.main()
