from __future__ import annotations

import py_compile
import subprocess
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


if __name__ == "__main__":
    unittest.main()
