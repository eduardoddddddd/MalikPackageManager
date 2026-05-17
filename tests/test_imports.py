"""Smoke-test: all mpm modules compile without SyntaxError.

main.py imports PySide6 at module level, so we check it with py_compile
instead of importing it directly — this validates syntax without requiring
the Qt libraries to be installed.
"""
from __future__ import annotations

import py_compile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


class TestModuleSyntax(unittest.TestCase):
    def _check(self, rel: str) -> None:
        path = SRC / rel
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"SyntaxError in {rel}: {e}")

    def test_init(self) -> None:
        self._check("mpm/__init__.py")

    def test_catalog(self) -> None:
        self._check("mpm/catalog.py")

    def test_catalog_providers(self) -> None:
        self._check("mpm/catalog_providers.py")

    def test_search(self) -> None:
        self._check("mpm/search.py")

    def test_workflow(self) -> None:
        self._check("mpm/workflow.py")

    def test_advisor(self) -> None:
        self._check("mpm/advisor.py")

    def test_main(self) -> None:
        self._check("mpm/main.py")


class TestNonGuiImports(unittest.TestCase):
    """Modules that do NOT import PySide6 must be importable directly."""

    def test_catalog_importable(self) -> None:
        from mpm import catalog  # noqa: F401

    def test_search_importable(self) -> None:
        from mpm import search  # noqa: F401

    def test_workflow_importable(self) -> None:
        from mpm import workflow  # noqa: F401

    def test_advisor_importable(self) -> None:
        from mpm import advisor  # noqa: F401
