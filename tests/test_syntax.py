from __future__ import annotations

import py_compile
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


if __name__ == "__main__":
    unittest.main()
