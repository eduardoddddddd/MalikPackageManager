from __future__ import annotations

import os
import py_compile
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PythonSyntaxTests(unittest.TestCase):
    def test_python_entrypoints_and_modules_compile(self) -> None:
        paths = [
            ROOT / "bin" / "mpm",
            ROOT / "bin" / "mpm-pkg",
            *sorted((ROOT / "src" / "mpm").glob("*.py")),
        ]

        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                py_compile.compile(str(path), doraise=True)

    def test_shell_entrypoints_parse(self) -> None:
        paths = [
            ROOT / "install.sh",
            ROOT / "bin" / "mpm-open",
            ROOT / "bin" / "mpm-host-open-url",
            ROOT / "scripts" / "distrobox" / "mpm-distrobox-bridge.sh",
        ]

        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                subprocess.run(["bash", "-n", str(path)], check=True)

    def test_distrobox_bridge_bootstrap_does_not_install_host_packages(self) -> None:
        bridge = ROOT / "scripts" / "distrobox" / "mpm-distrobox-bridge.sh"
        text = bridge.read_text(encoding="utf-8")

        self.assertNotIn("pacman -S --needed --noconfirm", text)

    def test_distrobox_bridge_refuses_missing_install_box_without_explicit_lazy_create(self) -> None:
        bridge = ROOT / "scripts" / "distrobox" / "mpm-distrobox-bridge.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            package = tmp / "cool.deb"
            package.write_bytes(b"deb")
            (fake_bin / "podman").write_text(
                "#!/bin/sh\n[ \"$1 $2 $3\" = 'container exists mpm-ubuntu-apps' ] && exit 1\nexit 0\n",
                encoding="utf-8",
            )
            (fake_bin / "distrobox").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "podman").chmod(0o755)
            (fake_bin / "distrobox").chmod(0o755)

            result = subprocess.run(
                [str(bridge), "install-deb", str(package), "cool"],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MPM_CREATE_MISSING_BOX=1", result.stderr)


if __name__ == "__main__":
    unittest.main()
