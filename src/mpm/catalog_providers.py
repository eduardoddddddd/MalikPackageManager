from __future__ import annotations

import json
from dataclasses import dataclass, field
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .catalog import load_catalog_entries, repo_root
from .host import detect_host


try:
    from .search import CatalogRoute  # type: ignore
    from .search import ProviderStatus  # type: ignore
except ImportError:

    @dataclass
    class CatalogRoute:  # type: ignore[no-redef]
        route_id: str
        provider: str
        backend: str
        source: str
        display_name: str
        package_name: str
        app_id: str = ""
        version: str = ""
        summary: str = ""
        description: str = ""
        homepage: str = ""
        license: str = ""
        publisher: str = ""
        install_target: str = ""
        install_backend: str = ""
        install_app_id: str = ""
        requires_host_mutation: bool = False
        requires_container: bool = False
        requires_snapshot: bool = False
        is_official: bool = False
        is_community: bool = False
        risk_level: str = "low"
        quality_score: float = 0.0
        match_score: float = 0.0
        recommendation_score: float = 0.0
        badges: list[str] = field(default_factory=list)
        warnings: list[str] = field(default_factory=list)
        raw: dict[str, object] = field(default_factory=dict)

    @dataclass(frozen=True)
    class ProviderStatus:  # type: ignore[no-redef]
        provider: str
        state: str = "ok"
        message: str = ""
        duration_ms: int = 0
        result_count: int = 0


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
UrlFetcher = Callable[[str, float | None], str]

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
FLATPAK_APP_ID_RE = re.compile(r"\b[A-Za-z0-9_]+(?:\.[A-Za-z0-9_][A-Za-z0-9_-]*){2,}\b")


@dataclass(frozen=True)
class FlatpakSearchEntry:
    name: str
    app_id: str
    version: str = ""
    summary: str = ""
    source: str = "Flathub"


@dataclass(frozen=True)
class PacmanSearchEntry:
    repo: str
    name: str
    version: str
    summary: str = ""


@dataclass(frozen=True)
class DistroboxBox:
    name: str
    status: str = ""
    image: str = ""


@dataclass(frozen=True)
class AptSearchEntry:
    name: str
    summary: str = ""


@dataclass(frozen=True)
class AptShowEntry:
    package: str
    version: str = ""
    architecture: str = ""
    summary: str = ""
    description: str = ""
    homepage: str = ""
    depends: str = ""
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DnfSearchEntry:
    name: str
    arch: str = ""
    summary: str = ""
    match_section: str = ""


@dataclass(frozen=True)
class DnfInfoEntry:
    name: str
    arch: str = ""
    version: str = ""
    release: str = ""
    epoch: str = ""
    repository: str = ""
    summary: str = ""
    url: str = ""
    license: str = ""
    description: str = ""
    installed: bool = False
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AurSearchEntry:
    name: str
    package_base: str = ""
    version: str = ""
    description: str = ""
    homepage: str = ""
    maintainer: str = ""
    votes: int = 0
    popularity: float = 0.0
    out_of_date: bool = False
    url_path: str = ""
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VendorRouteEntry:
    app_id: str
    app_name: str
    route_id: str
    kind: str
    url: str
    version: str = ""
    source: str = ""
    arch: tuple[str, ...] = ()
    sha256: str = ""
    signature_url: str = ""
    channel: str = ""
    box: str = ""
    warnings: tuple[str, ...] = ()
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VendorAppEntry:
    app_id: str
    name: str
    summary: str
    description: str = ""
    homepage: str = ""
    publisher: str = ""
    license: str = ""
    aliases: tuple[str, ...] = ()
    trust: str = "unknown-url"
    update_policy: str = "unknown"
    uninstall_policy: str = "unknown"
    routes: tuple[VendorRouteEntry, ...] = ()
    raw: dict[str, object] = field(default_factory=dict)


def _strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value)


def _normalize_remote(value: str) -> str:
    value = value.strip()
    if not value:
        return "Flathub"
    first = value.split(",", 1)[0].strip()
    if first.casefold() == "flathub":
        return "Flathub"
    return first


def _match_score(query: str, *values: str) -> float:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return 0.1
    for value in values:
        normalized_value = value.casefold()
        if normalized_value == normalized_query:
            return 1.0
        if normalized_value.startswith(normalized_query):
            return 0.85
        if normalized_query in normalized_value:
            return 0.65
    return 0.25


def _route(**fields: object) -> CatalogRoute:
    return CatalogRoute(**fields)


def _route_part(value: object, fallback: str = "unknown") -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9._+-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or fallback


def _split_flatpak_tsv_line(header: list[str], line: str) -> FlatpakSearchEntry | None:
    values = [value.strip() for value in line.split("\t")]
    row = dict(zip(header, values, strict=False))
    name = row.get("name") or row.get("Name") or ""
    app_id = row.get("application") or row.get("Application") or row.get("Application ID") or ""
    summary = row.get("description") or row.get("Description") or row.get("summary") or ""
    version = row.get("version") or row.get("Version") or ""
    source = row.get("remotes") or row.get("Remotes") or row.get("remote") or ""
    if not name or not app_id:
        return None
    return FlatpakSearchEntry(
        name=name,
        app_id=app_id,
        version=version,
        summary=summary,
        source=_normalize_remote(source),
    )


def _parse_flatpak_aligned_line(line: str) -> FlatpakSearchEntry | None:
    match = FLATPAK_APP_ID_RE.search(line)
    if not match:
        return None

    before = line[: match.start()].rstrip()
    after = line[match.end() :].strip()
    app_id = match.group(0).strip()

    name = before
    summary = ""
    before_parts = [part.strip() for part in re.split(r"\s{2,}", before) if part.strip()]
    if before_parts:
        name = before_parts[0]
        summary = " ".join(before_parts[1:])

    version = ""
    source = "Flathub"
    after_parts = after.split()
    if after_parts:
        source = _normalize_remote(after_parts[-1])
        if len(after_parts) >= 3:
            version = after_parts[0]
        elif len(after_parts) == 2 and after_parts[0] not in {"stable", "beta"}:
            version = after_parts[0]

    if not name or not app_id:
        return None
    return FlatpakSearchEntry(
        name=name,
        app_id=app_id,
        version=version,
        summary=summary,
        source=source,
    )


def parse_flatpak_search_output(output: str) -> list[FlatpakSearchEntry]:
    entries: list[FlatpakSearchEntry] = []
    tsv_header: list[str] | None = None

    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).rstrip()
        if not line.strip():
            continue

        if "\t" in line:
            columns = [column.strip() for column in line.split("\t")]
            lower_columns = [column.casefold() for column in columns]
            if "name" in lower_columns and (
                "application" in lower_columns or "application id" in lower_columns
            ):
                tsv_header = columns
                continue
            if tsv_header:
                entry = _split_flatpak_tsv_line(tsv_header, line)
                if entry:
                    entries.append(entry)
                continue
            if len(columns) >= 3 and FLATPAK_APP_ID_RE.fullmatch(columns[2]):
                entries.append(
                    FlatpakSearchEntry(
                        name=columns[0],
                        summary=columns[1],
                        app_id=columns[2],
                        version=columns[3] if len(columns) > 3 else "",
                        source=_normalize_remote(columns[4] if len(columns) > 4 else ""),
                    )
                )
                continue

        if "application id" in line.casefold() and "name" in line.casefold():
            continue

        entry = _parse_flatpak_aligned_line(line)
        if entry:
            entries.append(entry)

    return entries


def parse_pacman_search_output(output: str) -> list[PacmanSearchEntry]:
    entries: list[PacmanSearchEntry] = []
    current: PacmanSearchEntry | None = None

    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).rstrip()
        if not line.strip():
            continue

        if line[:1].isspace():
            if current is None:
                continue
            summary = " ".join(part for part in (current.summary, line.strip()) if part)
            current = PacmanSearchEntry(
                repo=current.repo,
                name=current.name,
                version=current.version,
                summary=summary,
            )
            entries[-1] = current
            continue

        match = re.match(r"^([^/\s]+)/([^\s]+)\s+(.+)$", line)
        if not match:
            current = None
            continue
        repo, name, version_text = match.groups()
        version = version_text.split()[0]
        current = PacmanSearchEntry(repo=repo, name=name, version=version)
        entries.append(current)

    return entries


def parse_distrobox_list_output(output: str) -> list[DistroboxBox]:
    boxes: list[DistroboxBox] = []
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).strip()
        if not line or "|" not in line:
            continue
        columns = [column.strip() for column in line.split("|")]
        if len(columns) < 2:
            continue
        lower_columns = [column.casefold() for column in columns]
        if "name" in lower_columns and "image" in lower_columns:
            continue
        if set(line.replace("|", "").strip()) <= {"-", "+"}:
            continue
        name = columns[1] if len(columns) >= 2 else ""
        status = columns[2] if len(columns) >= 3 else ""
        image = columns[3] if len(columns) >= 4 else ""
        if name:
            boxes.append(DistroboxBox(name=name, status=status, image=image))
    return boxes


APT_SEARCH_RE = re.compile(r"^(\S+)\s+-\s+(.*)$")


def parse_apt_cache_search_output(output: str) -> list[AptSearchEntry]:
    entries: list[AptSearchEntry] = []
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).strip()
        if not line:
            continue
        match = APT_SEARCH_RE.match(line)
        if not match:
            continue
        name, summary = match.groups()
        entries.append(AptSearchEntry(name=name, summary=summary.strip()))
    return entries


def _parse_deb822_paragraphs(output: str) -> list[dict[str, str]]:
    paragraphs: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key = ""

    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).rstrip()
        if not line:
            if current:
                paragraphs.append(current)
                current = {}
                last_key = ""
            continue
        if line[:1].isspace() and last_key:
            current[last_key] = "\n".join([current[last_key], line.strip()])
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        last_key = key.strip()
        current[last_key] = value.strip()

    if current:
        paragraphs.append(current)
    return paragraphs


def parse_apt_cache_show_output(output: str) -> list[AptShowEntry]:
    entries: list[AptShowEntry] = []
    for fields in _parse_deb822_paragraphs(output):
        description = fields.get("Description-en") or fields.get("Description") or ""
        summary = description.splitlines()[0].strip() if description else ""
        entries.append(
            AptShowEntry(
                package=fields.get("Package", ""),
                version=fields.get("Version", ""),
                architecture=fields.get("Architecture", ""),
                summary=summary,
                description=description,
                homepage=fields.get("Homepage", ""),
                depends=fields.get("Depends", ""),
                raw=fields,
            )
        )
    return entries


KNOWN_DNF_ARCHES = {
    "aarch64",
    "i386",
    "i486",
    "i586",
    "i686",
    "noarch",
    "ppc64le",
    "s390x",
    "src",
    "x86_64",
}


def _split_dnf_nevra_name(value: str) -> tuple[str, str]:
    if "." not in value:
        return value, ""
    name, arch = value.rsplit(".", 1)
    if arch in KNOWN_DNF_ARCHES:
        return name, arch
    return value, ""


def parse_dnf_search_output(output: str) -> list[DnfSearchEntry]:
    entries: list[DnfSearchEntry] = []
    match_section = ""
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).strip()
        if not line:
            continue
        lower = line.casefold()
        if lower.startswith("matched fields:"):
            match_section = line.split(":", 1)[1].strip()
            continue
        if lower in {"no matches found.", "repositories loaded."}:
            continue
        if lower.startswith("updating and loading repositories"):
            continue
        if ":" in line:
            name_arch, summary = line.split(":", 1)
        else:
            parts = re.split(r"\s{2,}|\t+", line, maxsplit=1)
            if len(parts) != 2:
                continue
            name_arch, summary = parts
        name, arch = _split_dnf_nevra_name(name_arch.strip())
        if name:
            entries.append(
                DnfSearchEntry(
                    name=name,
                    arch=arch,
                    summary=summary.strip(),
                    match_section=match_section,
                )
            )
    return entries


DNF_INFO_SECTION_HEADERS = {"available packages", "installed packages"}


def parse_dnf_info_output(output: str) -> list[DnfInfoEntry]:
    entries: list[DnfInfoEntry] = []
    current: dict[str, str] = {}
    installed = False
    last_key = ""

    def flush() -> None:
        nonlocal current, installed, last_key
        if not current:
            return
        entries.append(
            DnfInfoEntry(
                name=current.get("Name", ""),
                arch=current.get("Architecture", ""),
                version=current.get("Version", ""),
                release=current.get("Release", ""),
                epoch=current.get("Epoch", ""),
                repository=current.get("Repository", ""),
                summary=current.get("Summary", ""),
                url=current.get("URL", ""),
                license=current.get("License", ""),
                description=current.get("Description", ""),
                installed=installed,
                raw=dict(current),
            )
        )
        current = {}
        last_key = ""

    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).rstrip()
        if not line:
            flush()
            continue
        lower = line.strip().casefold()
        if lower in DNF_INFO_SECTION_HEADERS:
            flush()
            installed = lower.startswith("installed")
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key and last_key:
            current[last_key] = "\n".join(part for part in [current[last_key], value] if part)
            continue
        if key:
            last_key = key
            current[key] = value

    flush()
    return entries


def _aur_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _aur_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def parse_aur_rpc_search_response(payload: str) -> list[AurSearchEntry]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("AUR RPC response is not an object")
    if data.get("type") == "error":
        error = str(data.get("error") or "AUR RPC returned an error")
        raise ValueError(error)
    results = data.get("results", [])
    if not isinstance(results, list):
        raise ValueError("AUR RPC results are not a list")

    entries: list[AurSearchEntry] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip()
        if not name:
            continue
        entries.append(
            AurSearchEntry(
                name=name,
                package_base=str(item.get("PackageBase") or "").strip(),
                version=str(item.get("Version") or "").strip(),
                description=str(item.get("Description") or "").strip(),
                homepage=str(item.get("URL") or "").strip(),
                maintainer=str(item.get("Maintainer") or "").strip(),
                votes=_aur_int(item.get("NumVotes")),
                popularity=_aur_float(item.get("Popularity")),
                out_of_date=bool(item.get("OutOfDate")),
                url_path=str(item.get("URLPath") or "").strip(),
                raw=dict(item),
            )
        )
    return entries


def fetch_url_text(url: str, timeout: float | None = 3.0) -> str:
    request = Request(url, headers={"User-Agent": "mpm/0.15 aur-provider"})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def vendor_index_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("MPM_VENDOR_INDEX")
    if override:
        candidates.append(Path(override))

    root = repo_root()
    if root:
        candidates.append(root / "configs/mpm/vendor_index.json")

    candidates.extend(
        [
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "mpm/vendor_index.json",
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            / "mpm/vendor_index.json",
            Path("/usr/share/mpm/vendor_index.json"),
        ]
    )
    return candidates


def _string_list(value: object, *, field: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field}[{index}] must be a string")
        normalized = item.strip()
        if normalized:
            result.append(normalized)
    return tuple(result)


def _required_string(fields: dict[str, object], key: str, label: str) -> str:
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} missing required string field: {key}")
    return value.strip()


def _optional_string(fields: dict[str, object], key: str) -> str:
    value = fields.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"field {key} must be a string")
    return value.strip()


def parse_vendor_index_data(data: object) -> list[VendorAppEntry]:
    if not isinstance(data, dict):
        raise ValueError("vendor index must be an object with version and entries")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ValueError(f"vendor index version {version!r} is invalid; expected version 1")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("vendor index entries must be a list")

    apps: list[VendorAppEntry] = []
    seen_ids: set[str] = set()
    for app_index, item in enumerate(entries):
        label = f"entry {app_index}"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        app_id = _required_string(item, "id", label)
        if app_id in seen_ids:
            raise ValueError(f"{label} duplicates app id {app_id!r}")
        seen_ids.add(app_id)
        name = _required_string(item, "name", label)
        summary = _required_string(item, "summary", label)
        trust = _optional_string(item, "trust") or "unknown-url"
        routes_data = item.get("routes")
        if not isinstance(routes_data, list) or not routes_data:
            raise ValueError(f"{label} routes must be a non-empty list")

        route_ids: set[str] = set()
        routes: list[VendorRouteEntry] = []
        for route_index, route_item in enumerate(routes_data):
            route_label = f"{label} route {route_index}"
            if not isinstance(route_item, dict):
                raise ValueError(f"{route_label} must be an object")
            route_id = _required_string(route_item, "id", route_label)
            if route_id in route_ids:
                raise ValueError(f"{route_label} duplicates route id {route_id!r}")
            route_ids.add(route_id)
            kind = _required_string(route_item, "kind", route_label).casefold()
            if kind not in {"appimage", "deb", "rpm"}:
                raise ValueError(f"{route_label} kind {kind!r} is not supported")
            url = _required_string(route_item, "url", route_label)
            routes.append(
                VendorRouteEntry(
                    app_id=_optional_string(route_item, "app_id") or app_id,
                    app_name=name,
                    route_id=route_id,
                    kind=kind,
                    url=url,
                    version=_optional_string(route_item, "version"),
                    source=_optional_string(route_item, "source"),
                    arch=_string_list(route_item.get("arch"), field=f"{route_label} arch"),
                    sha256=_optional_string(route_item, "sha256"),
                    signature_url=_optional_string(route_item, "signature_url"),
                    channel=_optional_string(route_item, "channel"),
                    box=_optional_string(route_item, "box"),
                    warnings=_string_list(route_item.get("warnings"), field=f"{route_label} warnings"),
                    raw=dict(route_item),
                )
            )

        apps.append(
            VendorAppEntry(
                app_id=app_id,
                name=name,
                summary=summary,
                description=_optional_string(item, "description"),
                homepage=_optional_string(item, "homepage"),
                publisher=_optional_string(item, "publisher"),
                license=_optional_string(item, "license"),
                aliases=_string_list(item.get("aliases"), field=f"{label} aliases"),
                trust=trust,
                update_policy=_optional_string(item, "update_policy") or "unknown",
                uninstall_policy=_optional_string(item, "uninstall_policy") or "unknown",
                routes=tuple(routes),
                raw=dict(item),
            )
        )
    return apps


def load_vendor_index_entries(path: Path | None = None) -> tuple[list[VendorAppEntry], Path | None, str | None]:
    candidates = [path] if path else vendor_index_candidates()
    for candidate in candidates:
        if candidate is None or not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            return parse_vendor_index_data(data), candidate, None
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return [], candidate, f"invalid vendor index: {exc}"
    return [], None, "vendor index not found"


class DistroboxBoxIndex:
    def __init__(
        self,
        *,
        command: str = "distrobox",
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.command = command
        self.runner = runner
        self._boxes: list[DistroboxBox] | None = None
        self.last_error = ""

    def reset(self) -> None:
        self._boxes = None
        self.last_error = ""

    def boxes(self, timeout: float | None = 3.0) -> list[DistroboxBox]:
        if self._boxes is not None:
            return self._boxes
        self.last_error = ""
        try:
            completed = self.runner(
                [self.command, "list", "--no-color"],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            self.last_error = f"distrobox list timed out: {exc}"
            self._boxes = []
            return self._boxes
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"distrobox list failed: {exc}"
            self._boxes = []
            return self._boxes

        if completed.returncode != 0:
            self.last_error = completed.stderr.strip() or f"distrobox list exited with {completed.returncode}"
            self._boxes = []
            return self._boxes

        self._boxes = parse_distrobox_list_output(completed.stdout)
        return self._boxes

    def find(self, name: str, timeout: float | None = 3.0) -> DistroboxBox | None:
        for box in self.boxes(timeout=timeout):
            if box.name == name:
                return box
        return None


class DistroboxRepoProvider:
    provider_id = "distrobox"
    display_name = "Distrobox"
    source_aliases: tuple[str, ...] = ("distrobox",)

    def __init__(
        self,
        *,
        provider_id: str,
        display_name: str,
        box_name: str,
        source_name: str,
        command: str = "distrobox",
        runner: CommandRunner = subprocess.run,
        box_index: DistroboxBoxIndex | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.box_name = box_name
        self.source_name = source_name
        self.command = command
        self.runner = runner
        self.box_index = box_index or DistroboxBoxIndex(command=command, runner=runner)
        self.last_status = ProviderStatus(provider=self.provider_id, state="idle", message="not searched")

    def is_available(self) -> bool:
        return shutil.which(self.command) is not None

    def _enter_command(self, inner: list[str]) -> list[str]:
        return [self.command, "enter", "--name", self.box_name, "--", *inner]

    def _box(self, timeout: float | None) -> DistroboxBox | None:
        return self.box_index.find(self.box_name, timeout=timeout)

    def _set_status(self, state: str, message: str, started: float, result_count: int = 0) -> None:
        self.last_status = ProviderStatus(
            provider=self.provider_id,
            state=state,
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
            result_count=result_count,
        )

    def _run_inside_box(
        self,
        inner: list[str],
        *,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]:
        return self.runner(
            self._enter_command(inner),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )

    def _preflight(self, started: float, timeout: float | None) -> bool:
        if not self.is_available():
            self._set_status("warning", "distrobox command not found", started)
            return False
        box = self._box(timeout)
        if box is None:
            message = self.box_index.last_error or f"box {self.box_name} not found"
            self._set_status("warning", message, started)
            return False
        return True


def _apt_warnings(search_entry: AptSearchEntry, show_entry: AptShowEntry | None) -> list[str]:
    text = " ".join(
        [
            search_entry.summary,
            show_entry.summary if show_entry else "",
            show_entry.description if show_entry else "",
            show_entry.depends if show_entry else "",
        ]
    ).casefold()
    warnings: list[str] = ["Package install inside Distrobox is discovery-only in MVP 0.11; install support is pending."]
    if "transitional" in text or "dummy package" in text:
        warnings.append("APT package appears to be transitional/dummy; verify the real install target.")
    if "snap" in text or "snapd" in text:
        warnings.append("APT package appears to route to Snap; MalikOS should avoid silent Snap installs.")
    return warnings


class AptProvider(DistroboxRepoProvider):
    def __init__(
        self,
        *,
        provider_id: str,
        display_name: str,
        box_name: str,
        source_name: str,
        distro_badge: str,
        command: str = "distrobox",
        runner: CommandRunner = subprocess.run,
        box_index: DistroboxBoxIndex | None = None,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            display_name=display_name,
            box_name=box_name,
            source_name=source_name,
            command=command,
            runner=runner,
            box_index=box_index,
        )
        self.distro_badge = distro_badge
        self.source_aliases = ("distrobox", "apt", "deb", distro_badge)

    def _show_metadata(self, package: str, timeout: float | None) -> AptShowEntry | None:
        try:
            completed = self._run_inside_box(["apt-cache", "show", package], timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        entries = parse_apt_cache_show_output(completed.stdout)
        return next((entry for entry in entries if entry.package == package), entries[0] if entries else None)

    def search(self, query: str, limit: int = 20, timeout: float | None = 3.0) -> list[CatalogRoute]:
        started = time.monotonic()
        if not self._preflight(started, timeout):
            return []

        try:
            completed = self._run_inside_box(
                ["apt-cache", "search", "--names-only", query],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self._set_status("warning", f"apt-cache search timed out: {exc}", started)
            return []
        except (OSError, subprocess.SubprocessError) as exc:
            self._set_status("warning", f"apt-cache search failed: {exc}", started)
            return []

        if completed.returncode != 0:
            message = completed.stderr.strip() or f"apt-cache search exited with {completed.returncode}"
            self._set_status("warning", message, started)
            return []

        entries = parse_apt_cache_search_output(completed.stdout)[:limit]
        routes: list[CatalogRoute] = []
        source_slug = _route_part(self.source_name)
        for entry in entries:
            metadata = self._show_metadata(entry.name, timeout)
            routes.append(
                _route(
                    route_id=f"{self.provider_id}:{source_slug}:{entry.name}",
                    provider=self.provider_id,
                    backend="distrobox-apt",
                    source=self.source_name,
                    display_name=entry.name,
                    package_name=entry.name,
                    version=metadata.version if metadata else "",
                    summary=(metadata.summary if metadata and metadata.summary else entry.summary),
                    description=metadata.description if metadata else "",
                    homepage=metadata.homepage if metadata else "",
                    install_target=entry.name,
                    install_backend="distrobox-apt",
                    requires_host_mutation=False,
                    requires_container=True,
                    requires_snapshot=False,
                    is_official=True,
                    is_community=False,
                    risk_level="low",
                    quality_score=0.7,
                    match_score=_match_score(query, entry.name, entry.summary),
                    recommendation_score=0.62,
                    badges=["deb", "apt", self.distro_badge, "distrobox", "container", self.box_name],
                    warnings=_apt_warnings(entry, metadata),
                    raw={
                        "box": self.box_name,
                        "distro_family": self.distro_badge,
                        "package_manager": "apt",
                        "search": dict(entry.__dict__),
                        "show": dict(metadata.raw) if metadata else {},
                    },
                )
            )

        self._set_status("ok", "apt cache searched", started, len(routes))
        return routes


class AptUbuntuProvider(AptProvider):
    def __init__(
        self,
        *,
        command: str = "distrobox",
        runner: CommandRunner = subprocess.run,
        box_index: DistroboxBoxIndex | None = None,
    ) -> None:
        super().__init__(
            provider_id="apt-ubuntu",
            display_name="Ubuntu apt",
            box_name="mpm-ubuntu-apps",
            source_name="Ubuntu apt",
            distro_badge="ubuntu",
            command=command,
            runner=runner,
            box_index=box_index,
        )


class AptDebianProvider(AptProvider):
    def __init__(
        self,
        *,
        command: str = "distrobox",
        runner: CommandRunner = subprocess.run,
        box_index: DistroboxBoxIndex | None = None,
    ) -> None:
        super().__init__(
            provider_id="apt-debian",
            display_name="Debian apt",
            box_name="mpm-debian-apps",
            source_name="Debian apt",
            distro_badge="debian",
            command=command,
            runner=runner,
            box_index=box_index,
        )


class DnfProvider(DistroboxRepoProvider):
    provider_id = "dnf-fedora"
    display_name = "Fedora dnf"
    source_aliases = ("distrobox", "dnf", "rpm", "fedora")

    def __init__(
        self,
        *,
        command: str = "distrobox",
        runner: CommandRunner = subprocess.run,
        box_index: DistroboxBoxIndex | None = None,
    ) -> None:
        super().__init__(
            provider_id=self.provider_id,
            display_name=self.display_name,
            box_name="mpm-fedora-apps",
            source_name="Fedora dnf",
            command=command,
            runner=runner,
            box_index=box_index,
        )

    def _info_metadata(self, package: str, timeout: float | None) -> DnfInfoEntry | None:
        try:
            completed = self._run_inside_box(
                ["dnf", "-q", "--cacheonly", "info", package],
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        entries = parse_dnf_info_output(completed.stdout)
        return next((entry for entry in entries if entry.name == package), entries[0] if entries else None)

    def search(self, query: str, limit: int = 20, timeout: float | None = 3.0) -> list[CatalogRoute]:
        started = time.monotonic()
        if not self._preflight(started, timeout):
            return []

        try:
            completed = self._run_inside_box(
                ["dnf", "-q", "--cacheonly", "search", "--name", query],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self._set_status("warning", f"dnf cache-only search timed out: {exc}", started)
            return []
        except (OSError, subprocess.SubprocessError) as exc:
            self._set_status("warning", f"dnf cache-only search failed: {exc}", started)
            return []

        if completed.returncode != 0:
            message = completed.stderr.strip() or f"dnf cache-only search exited with {completed.returncode}"
            self._set_status("warning", message, started)
            return []

        entries = parse_dnf_search_output(completed.stdout)[:limit]
        routes: list[CatalogRoute] = []
        for entry in entries:
            metadata = self._info_metadata(entry.name, timeout)
            repository = metadata.repository if metadata and metadata.repository else "fedora-dnf"
            source = f"Fedora {repository}" if repository != "fedora-dnf" else self.source_name
            version_parts = [metadata.version, metadata.release] if metadata else ["", ""]
            routes.append(
                _route(
                    route_id=f"{self.provider_id}:{_route_part(repository)}:{entry.name}",
                    provider=self.provider_id,
                    backend="distrobox-dnf",
                    source=source,
                    display_name=entry.name,
                    package_name=entry.name,
                    version="-".join(part for part in version_parts if part),
                    summary=(metadata.summary if metadata and metadata.summary else entry.summary),
                    description=metadata.description if metadata else "",
                    homepage=metadata.url if metadata else "",
                    license=metadata.license if metadata else "",
                    install_target=entry.name,
                    install_backend="distrobox-dnf",
                    requires_host_mutation=False,
                    requires_container=True,
                    requires_snapshot=False,
                    is_official=True,
                    is_community=False,
                    risk_level="low",
                    quality_score=0.7,
                    match_score=_match_score(query, entry.name, entry.summary),
                    recommendation_score=0.62,
                    badges=["rpm", "dnf", "fedora", "distrobox", "container", self.box_name],
                    warnings=[
                        "Package install inside Distrobox is discovery-only in MVP 0.11; install support is pending."
                    ],
                    raw={
                        "box": self.box_name,
                        "distro_family": "fedora",
                        "package_manager": "dnf",
                        "search": dict(entry.__dict__),
                        "info": dict(metadata.raw) if metadata else {},
                    },
                )
            )

        self._set_status("ok", "dnf cache searched", started, len(routes))
        return routes


def _vendor_backend(kind: str) -> str:
    if kind == "appimage":
        return "appimage"
    if kind == "deb":
        return "distrobox-deb"
    if kind == "rpm":
        return "distrobox-rpm"
    return ""


def _vendor_artifact_format(kind: str) -> str:
    return {"appimage": "AppImage", "deb": "deb", "rpm": "rpm"}.get(kind, "unknown")


def _vendor_default_box(kind: str) -> str:
    if kind == "deb":
        return "mpm-ubuntu-apps"
    if kind == "rpm":
        return "mpm-fedora-apps"
    return ""


def _vendor_trust_is_official(trust: str) -> bool:
    return trust.casefold() in {"vendor-official", "official-vendor", "curated"}


def _vendor_trust_is_community(trust: str) -> bool:
    return trust.casefold() in {"community-index", "community"}


def _vendor_warnings(app: VendorAppEntry, route: VendorRouteEntry) -> list[str]:
    trust = app.trust.casefold()
    warnings: list[str] = list(route.warnings)
    if route.kind == "appimage":
        warnings.extend(
            [
                "AppImage updates may not be managed automatically by MPM; check vendor update policy.",
                "AppImage uninstall removes MPM-managed launcher/binary only; user data may remain.",
            ]
        )
    elif route.kind in {"deb", "rpm"}:
        warnings.append("Vendor DEB/RPM route installs inside Distrobox, not on the Arch host.")

    if trust in {"community-index", "community"}:
        warnings.append("Community vendor index route; verify upstream publisher before installing.")
    elif trust in {"unknown-url", "unknown"}:
        warnings.append("Unknown vendor URL trust level; only install if you trust the source.")

    if not route.sha256:
        warnings.append("Vendor artifact has no pinned sha256 in the local index; verify checksum/signature before installing.")
    if route.kind in {"deb", "rpm"} and not route.app_id:
        warnings.append("Vendor DEB/RPM route has no app id; launcher export may need manual repair.")
    return warnings


class VendorIndexProvider:
    provider_id = "vendor-index"
    display_name = "Vendor/AppImage"
    source_aliases = ("vendor", "appimage", "deb", "rpm")

    def __init__(self, *, index_path: Path | None = None) -> None:
        self.index_path = index_path
        self.last_status = ProviderStatus(provider=self.provider_id, state="idle", message="not searched")

    def is_available(self) -> bool:
        if self.index_path:
            return self.index_path.exists()
        return any(candidate.exists() for candidate in vendor_index_candidates())

    def _route_matches(self, app: VendorAppEntry, route: VendorRouteEntry, query: str) -> bool:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            return True
        haystack = " ".join(
            [
                app.app_id,
                app.name,
                app.summary,
                app.description,
                app.publisher,
                app.homepage,
                " ".join(app.aliases),
                route.route_id,
                route.kind,
                route.url,
                route.source,
                route.app_id,
                route.version,
                route.channel,
                " ".join(route.arch),
            ]
        ).casefold()
        return normalized_query in haystack

    def _to_catalog_route(self, app: VendorAppEntry, route: VendorRouteEntry, path: Path | None, query: str) -> CatalogRoute:
        backend = _vendor_backend(route.kind)
        box = route.box or _vendor_default_box(route.kind)
        is_official = _vendor_trust_is_official(app.trust)
        is_community = _vendor_trust_is_community(app.trust)
        warnings = _vendor_warnings(app, route)
        risk_level = "low" if is_official and route.sha256 and not warnings else "medium"
        source = route.source or f"{app.name} vendor {_vendor_artifact_format(route.kind)}"
        route_badges = ["vendor", route.kind, _vendor_artifact_format(route.kind).casefold()]
        if is_official:
            route_badges.append("official")
        if is_community:
            route_badges.append("community")
        if route.kind == "appimage":
            route_badges.extend(["appimage", "portable"])
        if route.kind == "deb":
            route_badges.extend(["deb", "distrobox", "container", box])
        if route.kind == "rpm":
            route_badges.extend(["rpm", "distrobox", "container", box])

        raw = {
            "box": box,
            "kind": route.kind,
            "url": route.url,
            "trust": app.trust,
            "trust_level": app.trust,
            "update_policy": app.update_policy,
            "uninstall_policy": app.uninstall_policy,
            "artifact_format": _vendor_artifact_format(route.kind),
            "artifact_url": route.url,
            "checksum": route.sha256,
            "sha256": route.sha256,
            "signature_url": route.signature_url,
            "channel": route.channel,
            "arch": list(route.arch),
            "vendor": app.publisher,
            "path": str(path) if path else "",
            "entry": dict(app.raw),
            "route": dict(route.raw),
        }
        return _route(
            route_id=f"{self.provider_id}:{_route_part(app.app_id)}:{_route_part(route.route_id)}",
            provider=self.provider_id,
            backend=backend,
            source=source,
            display_name=app.name,
            package_name=app.app_id,
            app_id=route.app_id,
            version=route.version,
            summary=app.summary,
            description=app.description,
            homepage=app.homepage,
            license=app.license,
            publisher=app.publisher,
            install_target=route.url,
            install_backend=backend,
            install_app_id=route.app_id,
            requires_host_mutation=False,
            requires_container=backend in {"distrobox-deb", "distrobox-rpm"},
            requires_snapshot=False,
            is_official=is_official,
            is_community=is_community,
            risk_level=risk_level,
            quality_score=0.72 if is_official else 0.48,
            match_score=_match_score(query, app.name, app.app_id, app.summary, route.url, *app.aliases),
            recommendation_score=0.66 if is_official else 0.42,
            badges=route_badges,
            warnings=warnings,
            aliases=[app.name, app.app_id, route.app_id, *app.aliases],
            raw=raw,
        )

    def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
        del timeout
        started = time.monotonic()
        apps, path, error = load_vendor_index_entries(self.index_path)
        if error:
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=error,
                duration_ms=int((time.monotonic() - started) * 1000),
                result_count=0,
            )
            return []

        routes: list[CatalogRoute] = []
        for app in apps:
            for route in app.routes:
                if not self._route_matches(app, route, query):
                    continue
                routes.append(self._to_catalog_route(app, route, path, query))
                if len(routes) >= limit:
                    break
            if len(routes) >= limit:
                break

        self.last_status = ProviderStatus(
            provider=self.provider_id,
            state="ok",
            message="vendor index searched read-only",
            duration_ms=int((time.monotonic() - started) * 1000),
            result_count=len(routes),
        )
        return routes


class CuratedProvider:
    provider_id = "curated"
    display_name = "MPM"
    source_aliases = ("mpm", "curated", "local")

    def __init__(self) -> None:
        self.last_status = ProviderStatus(provider=self.provider_id, state="idle", message="not searched")

    def is_available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
        entries, path, error = load_catalog_entries()
        if error:
            self.last_status = ProviderStatus(provider=self.provider_id, state="warning", message=error, result_count=0)
            return []

        normalized_query = query.strip().casefold()
        routes: list[CatalogRoute] = []
        for entry in entries:
            haystack = " ".join(
                [
                    entry["name"],
                    entry["target"],
                    entry.get("app_id", ""),
                    entry["summary"],
                    entry["tags"],
                ]
            ).casefold()
            if normalized_query and normalized_query not in haystack:
                continue
            backend = entry["backend"]
            target = entry["target"]
            app_id = entry.get("app_id") or (target if backend == "flatpak" else "")
            is_community = backend == "aur"
            warnings = (
                [AurProvider.community_warning, AurProvider.host_warning]
                if is_community
                else []
            )
            routes.append(
                _route(
                    route_id=f"curated:{backend or 'auto'}:{target}",
                    provider=self.provider_id,
                    backend=backend,
                    source=entry["source"],
                    display_name=entry["name"],
                    package_name=target,
                    app_id=app_id,
                    summary=entry["summary"],
                    install_target=target,
                    install_backend=backend,
                    install_app_id=app_id,
                    requires_host_mutation=backend in {"pacman", "aur"},
                    requires_container=backend in {"distrobox-deb", "distrobox-rpm"},
                    requires_snapshot=backend in {"pacman", "aur"},
                    is_official=not is_community,
                    is_community=is_community,
                    risk_level="medium" if is_community else "low",
                    quality_score=0.9,
                    match_score=_match_score(query, entry["name"], target, app_id, entry["tags"]),
                    recommendation_score=0.9,
                    badges=["curated", *(tag.strip() for tag in entry["tags"].split(",") if tag.strip())],
                    warnings=warnings,
                    raw={"entry": dict(entry), "path": str(path) if isinstance(path, Path) else ""},
                )
            )
            if len(routes) >= limit:
                break

        self.last_status = ProviderStatus(
            provider=self.provider_id,
            state="ok",
            message="catalog searched",
            result_count=len(routes),
        )
        return routes


class FlatpakProvider:
    provider_id = "flatpak"
    display_name = "Flatpak"
    source_aliases = ("flatpak", "flathub")

    def __init__(
        self,
        *,
        command: str = "flatpak",
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.command = command
        self.runner = runner
        self.last_status = ProviderStatus(provider=self.provider_id, state="idle", message="not searched")

    def is_available(self) -> bool:
        return shutil.which(self.command) is not None

    def search(self, query: str, limit: int = 20, timeout: float | None = 3.0) -> list[CatalogRoute]:
        if not self.is_available():
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message="flatpak command not found",
                result_count=0,
            )
            return []

        try:
            completed = self.runner(
                [self.command, "search", "--columns=name,description,application,version,remotes", query],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=f"flatpak search failed: {exc}",
                result_count=0,
            )
            return []

        if completed.returncode != 0:
            message = completed.stderr.strip() or f"flatpak search exited with {completed.returncode}"
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=message,
                result_count=0,
            )
            return []

        entries = parse_flatpak_search_output(completed.stdout)[:limit]
        routes = [
            _route(
                route_id=f"flatpak:{entry.source.casefold()}:{entry.app_id}",
                provider=self.provider_id,
                backend="flatpak",
                source=entry.source,
                display_name=entry.name,
                package_name=entry.app_id,
                app_id=entry.app_id,
                version=entry.version,
                summary=entry.summary,
                install_target=entry.app_id,
                install_backend="flatpak",
                install_app_id=entry.app_id,
                requires_host_mutation=False,
                requires_container=False,
                requires_snapshot=False,
                is_official=entry.source.casefold() == "flathub",
                risk_level="low",
                quality_score=0.8,
                match_score=_match_score(query, entry.name, entry.app_id, entry.summary),
                recommendation_score=0.75,
                badges=["flatpak", "sandbox", entry.source.casefold()],
                raw={"entry": dict(entry.__dict__)},
            )
            for entry in entries
        ]
        self.last_status = ProviderStatus(
            provider=self.provider_id,
            state="ok",
            message="flatpak searched",
            result_count=len(routes),
        )
        return routes


class PacmanProvider:
    provider_id = "pacman"
    display_name = "Arch"
    source_aliases = ("arch", "pacman", "repo", "official")

    def __init__(
        self,
        *,
        command: str = "pacman",
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.command = command
        self.runner = runner
        self.last_status = ProviderStatus(provider=self.provider_id, state="idle", message="not searched")

    def is_available(self) -> bool:
        info = detect_host()
        return info.is_arch_like and bool(info.commands.get("pacman")) and shutil.which(self.command) is not None

    def search(self, query: str, limit: int = 20, timeout: float | None = 3.0) -> list[CatalogRoute]:
        if not self.is_available():
            info = detect_host()
            message = (
                f"pacman is Arch-only; host family is {info.family}"
                if not info.is_arch_like
                else "pacman command not found"
            )
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=message,
                result_count=0,
            )
            return []

        try:
            completed = self.runner(
                [self.command, "-Ss", query],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if completed.returncode != 0 and "could not open database" in completed.stderr:
                completed = self.runner(
                    ["sudo", "-n", self.command, "-Ss", query],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=f"pacman search failed: {exc}",
                result_count=0,
            )
            return []

        if completed.returncode != 0:
            message = completed.stderr.strip() or f"pacman search exited with {completed.returncode}"
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=message,
                result_count=0,
            )
            return []

        entries = parse_pacman_search_output(completed.stdout)[:limit]
        routes = [
            _route(
                route_id=f"pacman:{entry.repo}:{entry.name}",
                provider=self.provider_id,
                backend="pacman",
                source=f"Arch {entry.repo}",
                display_name=entry.name,
                package_name=entry.name,
                version=entry.version,
                summary=entry.summary,
                install_target=entry.name,
                install_backend="pacman",
                requires_host_mutation=True,
                requires_container=False,
                requires_snapshot=True,
                is_official=True,
                risk_level="medium",
                quality_score=0.75,
                match_score=_match_score(query, entry.name, entry.summary),
                recommendation_score=0.6,
                badges=["arch", "host", "snapshot"],
                warnings=["Host package install requires Snapper protection."],
                raw={"entry": dict(entry.__dict__)},
            )
            for entry in entries
        ]
        self.last_status = ProviderStatus(
            provider=self.provider_id,
            state="ok",
            message="pacman searched",
            result_count=len(routes),
        )
        return routes


class AurProvider:
    provider_id = "aur"
    display_name = "AUR"
    source_aliases = ("aur", "arch-user-repository", "community")
    rpc_base_url = "https://aur.archlinux.org/rpc/v5/search"
    community_warning = "AUR is community-sourced; review the PKGBUILD before installing."
    host_warning = "AUR install routes mutate the Arch host and require Snapper snapshot protection."

    def __init__(
        self,
        *,
        fetcher: UrlFetcher = fetch_url_text,
        rpc_base_url: str | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.rpc_base_url = rpc_base_url or self.rpc_base_url
        self.last_status = ProviderStatus(provider=self.provider_id, state="idle", message="not searched")

    def is_available(self) -> bool:
        info = detect_host()
        return info.is_arch_like and bool(info.commands.get("yay") or info.commands.get("paru"))

    def _search_url(self, query: str) -> str:
        encoded_query = quote(query, safe="")
        return f"{self.rpc_base_url}/{encoded_query}?{urlencode({'by': 'name-desc'})}"

    def search(self, query: str, limit: int = 20, timeout: float | None = 3.0) -> list[CatalogRoute]:
        started = time.monotonic()
        query = query.strip()
        if not query:
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="ok",
                message="empty query skipped",
                result_count=0,
            )
            return []
        if not self.is_available():
            info = detect_host()
            message = (
                f"AUR is Arch-only; host family is {info.family}"
                if not info.is_arch_like
                else "AUR helper not found; install yay or paru to enable AUR routes"
            )
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=message,
                duration_ms=int((time.monotonic() - started) * 1000),
                result_count=0,
            )
            return []

        try:
            payload = self.fetcher(self._search_url(query), timeout)
            entries = parse_aur_rpc_search_response(payload)[:limit]
        except TimeoutError as exc:
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=f"AUR RPC search timed out: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
                result_count=0,
            )
            return []
        except (OSError, URLError, json.JSONDecodeError, ValueError) as exc:
            self.last_status = ProviderStatus(
                provider=self.provider_id,
                state="warning",
                message=f"AUR RPC search failed: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
                result_count=0,
            )
            return []

        routes = [
            _route(
                route_id=f"aur:aur:{entry.name}",
                provider=self.provider_id,
                backend="aur",
                source="AUR",
                display_name=entry.name,
                package_name=entry.name,
                version=entry.version,
                summary=entry.description,
                description=entry.description,
                homepage=entry.homepage,
                publisher=entry.maintainer,
                install_target=entry.name,
                install_backend="aur",
                requires_host_mutation=True,
                requires_container=False,
                requires_snapshot=True,
                is_official=False,
                is_community=True,
                risk_level="medium",
                quality_score=0.45,
                match_score=_match_score(query, entry.name, entry.description),
                recommendation_score=0.35,
                badges=["aur", "community", "arch", "host", "snapshot"],
                warnings=[
                    self.community_warning,
                    self.host_warning,
                    *(
                        ["AUR package is flagged out-of-date; verify upstream status before installing."]
                        if entry.out_of_date
                        else []
                    ),
                ],
                raw={
                    "entry": dict(entry.raw),
                    "package_base": entry.package_base,
                    "votes": entry.votes,
                    "popularity": entry.popularity,
                    "url_path": entry.url_path,
                    "rpc_url": self._search_url(query),
                },
            )
            for entry in entries
        ]
        self.last_status = ProviderStatus(
            provider=self.provider_id,
            state="ok",
            message="AUR RPC searched read-only",
            duration_ms=int((time.monotonic() - started) * 1000),
            result_count=len(routes),
        )
        return routes


def default_catalog_providers() -> list[object]:
    distrobox_index = DistroboxBoxIndex()
    return [
        CuratedProvider(),
        VendorIndexProvider(),
        FlatpakProvider(),
        PacmanProvider(),
        AurProvider(),
        AptUbuntuProvider(box_index=distrobox_index),
        AptDebianProvider(box_index=distrobox_index),
        DnfProvider(box_index=distrobox_index),
    ]
