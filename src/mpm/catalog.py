from __future__ import annotations

import json
import os
from pathlib import Path


EXPECTED_CATALOG_VERSION = 1
ALLOWED_BACKENDS = {
    "",
    "pacman",
    "aur",
    "flatpak",
    "appimage",
    "distrobox-deb",
    "distrobox-rpm",
    "distrobox-apt",
    "distrobox-dnf",
}
REQUIRED_ENTRY_FIELDS = ("name", "target", "backend", "source", "summary", "tags")


class CatalogValidationError(ValueError):
    pass


def repo_root() -> Path | None:
    current = Path(__file__).resolve()
    for parent in [current.parent, *current.parents]:
        if (parent / "configs/mpm/catalog.json").exists():
            return parent
    return None


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def catalog_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("MPM_CATALOG")
    if override:
        candidates.append(Path(override))

    root = repo_root()
    if root:
        candidates.append(root / "configs/mpm/catalog.json")

    candidates.extend(
        [
            xdg_config_home() / "mpm/catalog.json",
            xdg_data_home() / "mpm/catalog.json",
            Path("/usr/share/mpm/catalog.json"),
        ]
    )
    return candidates


def normalize_tags(value: object, entry_label: str) -> str:
    if isinstance(value, list):
        tags: list[str] = []
        for index, tag in enumerate(value):
            if not isinstance(tag, str):
                raise CatalogValidationError(f"{entry_label} tags[{index}] must be a string")
            normalized = tag.strip()
            if not normalized:
                raise CatalogValidationError(f"{entry_label} tags[{index}] must not be empty")
            tags.append(normalized)
        return ", ".join(tags)

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise CatalogValidationError(f"{entry_label} tags must not be empty")
        return normalized

    raise CatalogValidationError(f"{entry_label} tags must be a list of strings or a string")


def require_string_field(entry: dict[str, object], field: str, entry_label: str) -> str:
    if field not in entry:
        raise CatalogValidationError(f"{entry_label} missing required field: {field}")
    value = entry[field]
    if not isinstance(value, str):
        raise CatalogValidationError(f"{entry_label} field {field} must be a string")
    if field == "backend":
        return value.strip()

    normalized = value.strip()
    if not normalized:
        raise CatalogValidationError(f"{entry_label} field {field} must not be empty")
    return normalized


def normalize_catalog_entry(entry: object, index: int) -> dict[str, str]:
    entry_label = f"entry {index}"
    if not isinstance(entry, dict):
        raise CatalogValidationError(f"{entry_label} must be an object")

    typed_entry: dict[str, object] = entry
    for field in REQUIRED_ENTRY_FIELDS:
        if field not in typed_entry:
            raise CatalogValidationError(f"{entry_label} missing required field: {field}")

    backend = require_string_field(typed_entry, "backend", entry_label)
    if backend not in ALLOWED_BACKENDS:
        allowed = ", ".join(sorted(name or "auto" for name in ALLOWED_BACKENDS))
        raise CatalogValidationError(
            f"{entry_label} backend {backend!r} is not allowed; expected one of: {allowed}"
        )

    app_id = typed_entry.get("app_id", "")
    if not isinstance(app_id, str):
        raise CatalogValidationError(f"{entry_label} field app_id must be a string")
    normalized_app_id = app_id.strip()
    if "app_id" in typed_entry and not normalized_app_id:
        raise CatalogValidationError(f"{entry_label} field app_id must not be empty when present")

    return {
        "name": require_string_field(typed_entry, "name", entry_label),
        "target": require_string_field(typed_entry, "target", entry_label),
        "backend": backend,
        "summary": require_string_field(typed_entry, "summary", entry_label),
        "source": require_string_field(typed_entry, "source", entry_label),
        "tags": normalize_tags(typed_entry["tags"], entry_label),
        "app_id": normalized_app_id,
    }


def validate_catalog_data(
    data: object,
    *,
    expected_version: int = EXPECTED_CATALOG_VERSION,
) -> list[dict[str, str]]:
    if not isinstance(data, dict):
        raise CatalogValidationError("catalog must be an object with version and entries")

    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != expected_version:
        raise CatalogValidationError(f"catalog version {version!r} is invalid; expected version {expected_version}")

    entries = data.get("entries")
    if not isinstance(entries, list):
        raise CatalogValidationError("catalog entries must be a list")

    normalized: list[dict[str, str]] = []
    seen_names: dict[str, int] = {}
    seen_targets: dict[str, int] = {}
    for index, entry in enumerate(entries):
        normalized_entry = normalize_catalog_entry(entry, index)
        name_key = normalized_entry["name"].casefold()
        if name_key in seen_names:
            raise CatalogValidationError(
                f"entry {index} duplicates name {normalized_entry['name']!r} from entry {seen_names[name_key]}"
            )
        seen_names[name_key] = index
        target = normalized_entry["target"]
        if target in seen_targets:
            raise CatalogValidationError(
                f"entry {index} duplicates target {target!r} from entry {seen_targets[target]}"
            )
        seen_targets[target] = index
        normalized.append(normalized_entry)

    return normalized


def load_catalog_entries() -> tuple[list[dict[str, str]], Path | None, str | None]:
    for candidate in catalog_candidates():
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], candidate, f"invalid catalog JSON: {exc}"
        try:
            return validate_catalog_data(data), candidate, None
        except CatalogValidationError as exc:
            return [], candidate, f"invalid catalog: {exc}"
    return [], None, "catalog not found"
