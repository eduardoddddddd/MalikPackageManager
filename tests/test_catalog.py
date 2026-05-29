from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mpm.catalog import (  # noqa: E402
    CatalogValidationError,
    EXPECTED_CATALOG_VERSION,
    load_catalog_entries,
    validate_catalog_data,
)


def catalog_with(*entries: dict[str, object], version: object = EXPECTED_CATALOG_VERSION) -> dict[str, object]:
    return {"version": version, "entries": list(entries)}


def entry(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "Firefox",
        "target": "org.mozilla.firefox",
        "backend": "flatpak",
        "source": "Flathub",
        "summary": "Web browser installed as a user Flatpak.",
        "tags": ["browser", "web", "flatpak"],
    }
    value.update(overrides)
    return value


class CatalogValidationTests(unittest.TestCase):
    def test_validate_catalog_data_normalizes_gui_entries(self) -> None:
        entries = validate_catalog_data(catalog_with(entry(app_id=" firefox ")))

        self.assertEqual(
            entries,
            [
                {
                    "name": "Firefox",
                    "target": "org.mozilla.firefox",
                    "backend": "flatpak",
                    "source": "Flathub",
                    "summary": "Web browser installed as a user Flatpak.",
                    "tags": "browser, web, flatpak",
                    "app_id": "firefox",
                }
            ],
        )

    def test_rejects_wrong_catalog_version(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "expected version 1"):
            validate_catalog_data(catalog_with(entry(), version=2))

    def test_rejects_missing_required_field(self) -> None:
        bad_entry = entry()
        del bad_entry["summary"]

        with self.assertRaisesRegex(CatalogValidationError, "entry 0 missing required field: summary"):
            validate_catalog_data(catalog_with(bad_entry))

    def test_rejects_unknown_backend(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "backend 'snap' is not allowed"):
            validate_catalog_data(catalog_with(entry(backend="snap")))

    def test_rejects_duplicate_targets(self) -> None:
        duplicate = entry(name="Firefox ESR")

        with self.assertRaisesRegex(CatalogValidationError, "duplicates target 'org.mozilla.firefox'"):
            validate_catalog_data(catalog_with(entry(), duplicate))

    def test_rejects_duplicate_names(self) -> None:
        duplicate = entry(target="org.mozilla.firefox-esr")

        with self.assertRaisesRegex(CatalogValidationError, "duplicates name 'Firefox'"):
            validate_catalog_data(catalog_with(entry(), duplicate))

    def test_rejects_empty_app_id_when_present(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "app_id must not be empty"):
            validate_catalog_data(catalog_with(entry(app_id=" ")))

    def test_rejects_non_object_catalog(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "catalog must be an object"):
            validate_catalog_data([entry()])

    def test_load_catalog_entries_reports_invalid_existing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "catalog.json"
            catalog_path.write_text(json.dumps(catalog_with(entry(), version=99)), encoding="utf-8")

            with mock.patch.dict(os.environ, {"MPM_CATALOG": str(catalog_path)}):
                entries, path, error = load_catalog_entries()

        self.assertEqual(entries, [])
        self.assertEqual(path, catalog_path)
        self.assertIsNotNone(error)
        self.assertIn("invalid catalog", error or "")
        self.assertIn("expected version 1", error or "")

    def test_load_catalog_entries_uses_xdg_config_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_home = Path(tmpdir) / "config"
            catalog_path = config_home / "mpm" / "catalog.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps(catalog_with(entry())), encoding="utf-8")

            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
                with mock.patch("mpm.catalog.repo_root", return_value=None):
                    entries, path, error = load_catalog_entries()

        self.assertIsNone(error)
        self.assertEqual(path, catalog_path)
        self.assertEqual(entries[0]["name"], "Firefox")

    def test_bundled_catalog_has_1_0_baseline_size(self) -> None:
        entries, path, error = load_catalog_entries()

        self.assertIsNone(error)
        self.assertEqual(path, ROOT / "configs" / "mpm" / "catalog.json")
        self.assertGreaterEqual(len(entries), 25)


if __name__ == "__main__":
    unittest.main()
