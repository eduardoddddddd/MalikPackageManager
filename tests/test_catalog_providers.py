from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mpm.catalog_providers import (  # noqa: E402
    AurProvider,
    AptUbuntuProvider,
    CuratedProvider,
    DnfProvider,
    FlatpakProvider,
    PacmanProvider,
    VendorIndexProvider,
    load_vendor_index_entries,
    parse_aur_rpc_search_response,
    parse_apt_cache_search_output,
    parse_apt_cache_show_output,
    parse_distrobox_list_output,
    parse_dnf_info_output,
    parse_dnf_search_output,
    parse_flatpak_search_output,
    parse_pacman_search_output,
    parse_vendor_index_data,
)


FIXTURES = ROOT / "tests" / "fixtures"


def fake_host(family: str = "arch", commands: dict[str, str | None] | None = None) -> SimpleNamespace:
    commands = commands or {"pacman": "/usr/bin/pacman", "yay": "/usr/bin/yay", "paru": None}
    return SimpleNamespace(is_arch_like=family == "arch", family=family, commands=commands)


class CatalogProviderParserTests(unittest.TestCase):
    def test_parse_flatpak_search_output_from_tabs(self) -> None:
        output = "\n".join(
            [
                "Name\tDescription\tApplication\tVersion\tRemotes",
                "Firefox\tFast, Private & Safe Web Browser\torg.mozilla.firefox\t126.0\tflathub",
                "VLC\tMedia player\torg.videolan.VLC\t3.0.20\tflathub",
            ]
        )

        entries = parse_flatpak_search_output(output)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "Firefox")
        self.assertEqual(entries[0].app_id, "org.mozilla.firefox")
        self.assertEqual(entries[0].version, "126.0")
        self.assertEqual(entries[0].summary, "Fast, Private & Safe Web Browser")
        self.assertEqual(entries[0].source, "Flathub")

    def test_parse_flatpak_search_output_from_no_header_tabs(self) -> None:
        output = "\n".join(
            [
                "Firefox\tFast, Private & Safe Web Browser\torg.mozilla.firefox\t150.0.3\tflathub",
                "Nvidia VAAPI driver\tVA-API implementation\torg.freedesktop.Platform.VAAPI.nvidia\t\tflathub",
            ]
        )

        entries = parse_flatpak_search_output(output)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "Firefox")
        self.assertEqual(entries[0].summary, "Fast, Private & Safe Web Browser")
        self.assertEqual(entries[0].app_id, "org.mozilla.firefox")
        self.assertEqual(entries[0].version, "150.0.3")
        self.assertEqual(entries[1].version, "")

    def test_parse_flatpak_search_output_from_aligned_table(self) -> None:
        output = "\n".join(
            [
                "Name       Description                         Application ID        Version  Branch  Remotes",
                "Firefox    Fast, Private & Safe Web Browser    org.mozilla.firefox   126.0    stable  flathub",
            ]
        )

        entries = parse_flatpak_search_output(output)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Firefox")
        self.assertEqual(entries[0].app_id, "org.mozilla.firefox")
        self.assertEqual(entries[0].source, "Flathub")

    def test_parse_pacman_search_output(self) -> None:
        output = "\n".join(
            [
                "extra/btop 1.4.4-1",
                "    A monitor of resources",
                "extra/firefox 126.0-1 [installed]",
                "    Standalone web browser from mozilla.org",
                "    Additional summary line",
            ]
        )

        entries = parse_pacman_search_output(output)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].repo, "extra")
        self.assertEqual(entries[0].name, "btop")
        self.assertEqual(entries[0].version, "1.4.4-1")
        self.assertEqual(entries[0].summary, "A monitor of resources")
        self.assertEqual(entries[1].summary, "Standalone web browser from mozilla.org Additional summary line")

    def test_parse_distrobox_list_output_from_pipe_table(self) -> None:
        output = "\n".join(
            [
                "ID           | NAME                 | STATUS  | IMAGE",
                "123456789abc | mpm-ubuntu-apps  | running | docker.io/library/ubuntu:24.04",
                "abcdef123456 | mpm-fedora-apps  | exited  | registry.fedoraproject.org/fedora:44",
            ]
        )

        boxes = parse_distrobox_list_output(output)

        self.assertEqual(len(boxes), 2)
        self.assertEqual(boxes[0].name, "mpm-ubuntu-apps")
        self.assertEqual(boxes[0].status, "running")
        self.assertEqual(boxes[1].image, "registry.fedoraproject.org/fedora:44")

    def test_parse_apt_cache_search_output(self) -> None:
        output = "\n".join(
            [
                "firefox - Safe and easy web browser from Mozilla",
                "firefox-esr - Mozilla Firefox web browser - Extended Support Release (ESR)",
                "webext-ublock-origin-firefox - lightweight and efficient ads, malware, trackers blocker (Firefox)",
                "malformed line without separator",
            ]
        )

        entries = parse_apt_cache_search_output(output)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].name, "firefox")
        self.assertEqual(entries[0].summary, "Safe and easy web browser from Mozilla")
        self.assertEqual(entries[2].name, "webext-ublock-origin-firefox")

    def test_parse_apt_cache_search_output_preserves_hyphenated_summary(self) -> None:
        entries = parse_apt_cache_search_output("foo - package summary with hyphen - keep the rest\n")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "foo")
        self.assertEqual(entries[0].summary, "package summary with hyphen - keep the rest")

    def test_parse_apt_cache_show_output(self) -> None:
        output = """Package: firefox
Version: 125.0+build3-0ubuntu0.22.04.1
Architecture: amd64
Homepage: https://www.mozilla.org/firefox/
Description-en: Safe and easy web browser from Mozilla
 Firefox delivers safe, easy web browsing.
 .
 This package installs Firefox for Ubuntu.
"""

        entries = parse_apt_cache_show_output(output)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].package, "firefox")
        self.assertEqual(entries[0].version, "125.0+build3-0ubuntu0.22.04.1")
        self.assertEqual(entries[0].summary, "Safe and easy web browser from Mozilla")
        self.assertEqual(entries[0].homepage, "https://www.mozilla.org/firefox/")
        self.assertIn("Firefox delivers safe", entries[0].description)

    def test_parse_apt_cache_show_output_multiple_versions(self) -> None:
        output = """Package: vlc
Version: 3.0.20-3build6
Description-en: multimedia player and streamer

Package: vlc
Version: 3.0.16-1build7
Description-en: older multimedia player
"""

        entries = parse_apt_cache_show_output(output)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].version, "3.0.20-3build6")
        self.assertEqual(entries[1].version, "3.0.16-1build7")

    def test_parse_dnf_search_output_from_dnf5_name_sections(self) -> None:
        output = "\n".join(
            [
                "Matched fields: name (exact)",
                " firefox.x86_64: Mozilla Firefox Web browser",
                " firefox-langpacks.x86_64: Firefox langpacks",
                "Matched fields: name",
                " firefox-wayland.x86_64: Wayland launcher for Firefox",
            ]
        )

        entries = parse_dnf_search_output(output)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].name, "firefox")
        self.assertEqual(entries[0].arch, "x86_64")
        self.assertEqual(entries[0].summary, "Mozilla Firefox Web browser")
        self.assertEqual(entries[0].match_section, "name (exact)")

    def test_parse_dnf_search_output_ignores_no_matches(self) -> None:
        self.assertEqual(parse_dnf_search_output("No matches found.\n"), [])

    def test_parse_dnf_search_output_from_tabular_dnf4_rows(self) -> None:
        output = "\n".join(
            [
                "Matched fields: name (exact)",
                " firefox.x86_64\tMozilla Firefox Web browser",
                "Matched fields: name",
                " browserpass-firefox.x86_64\tNative component for the Firefox extension",
            ]
        )

        entries = parse_dnf_search_output(output)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "firefox")
        self.assertEqual(entries[0].arch, "x86_64")
        self.assertEqual(entries[0].summary, "Mozilla Firefox Web browser")

    def test_parse_dnf_info_output_with_multiline_description(self) -> None:
        output = "\n".join(
            [
                "Available packages",
                "Name            : firefox",
                "Epoch           : 0",
                "Version         : 126.0",
                "Release         : 1.fc40",
                "Architecture    : x86_64",
                "Repository      : updates",
                "Summary         : Mozilla Firefox Web browser",
                "URL             : https://www.mozilla.org/firefox/",
                "License         : MPL-2.0",
                "Description     : Mozilla Firefox is an open-source web browser.",
                "                : It is designed for standards compliance and privacy.",
            ]
        )

        entries = parse_dnf_info_output(output)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "firefox")
        self.assertEqual(entries[0].version, "126.0")
        self.assertEqual(entries[0].release, "1.fc40")
        self.assertEqual(entries[0].repository, "updates")
        self.assertEqual(entries[0].summary, "Mozilla Firefox Web browser")
        self.assertIn("standards compliance", entries[0].description)

    def test_parse_aur_rpc_search_response(self) -> None:
        payload = (FIXTURES / "aur_rpc_search_cursor.json").read_text(encoding="utf-8")

        entries = parse_aur_rpc_search_response(payload)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "cursor-bin")
        self.assertEqual(entries[0].package_base, "cursor-bin")
        self.assertEqual(entries[0].version, "1.0.0-1")
        self.assertEqual(entries[0].homepage, "https://cursor.com/")
        self.assertEqual(entries[0].votes, 42)
        self.assertEqual(entries[0].popularity, 3.14)
        self.assertFalse(entries[0].out_of_date)
        self.assertTrue(entries[1].out_of_date)

    def test_parse_aur_rpc_error_response(self) -> None:
        payload = (FIXTURES / "aur_rpc_error.json").read_text(encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Query arg too small"):
            parse_aur_rpc_search_response(payload)

    def test_parse_vendor_index_maps_appimage_deb_and_rpm_routes(self) -> None:
        payload = json.loads((FIXTURES / "vendor_index.json").read_text(encoding="utf-8"))

        entries = parse_vendor_index_data(payload)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].app_id, "cursor")
        self.assertEqual(entries[0].trust, "vendor-official")
        self.assertEqual([route.kind for route in entries[0].routes], ["appimage", "deb", "rpm"])
        self.assertEqual(entries[0].routes[1].box, "mpm-ubuntu-apps")

    def test_parse_vendor_index_rejects_unknown_route_kind(self) -> None:
        payload = json.loads((FIXTURES / "vendor_index_invalid.json").read_text(encoding="utf-8"))

        with self.assertRaisesRegex(ValueError, "not supported"):
            parse_vendor_index_data(payload)


class CatalogProviderTests(unittest.TestCase):
    def test_curated_provider_searches_catalog_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entries": [
                            {
                                "name": "Firefox",
                                "target": "org.mozilla.firefox",
                                "backend": "flatpak",
                                "source": "Flathub",
                                "summary": "Web browser.",
                                "tags": ["browser", "flatpak"],
                            },
                            {
                                "name": "btop",
                                "target": "btop",
                                "backend": "pacman",
                                "source": "Arch repo",
                                "summary": "System monitor.",
                                "tags": ["terminal", "system"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"MPM_CATALOG": str(catalog_path)}):
                routes = CuratedProvider().search("firefox")

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].provider, "curated")
        self.assertEqual(routes[0].backend, "flatpak")
        self.assertEqual(routes[0].install_target, "org.mozilla.firefox")
        self.assertEqual(routes[0].install_backend, "flatpak")
        self.assertIn("curated", routes[0].badges)

    def test_vendor_index_provider_searches_name_alias_and_route_url(self) -> None:
        provider = VendorIndexProvider(index_path=FIXTURES / "vendor_index.json")

        by_name = provider.search("cursor")
        by_alias = provider.search("cursor editor")
        by_url = provider.search("cursor.rpm")

        self.assertEqual(len(by_name), 3)
        self.assertEqual(len(by_alias), 3)
        self.assertEqual([route.backend for route in by_url], ["distrobox-rpm"])
        self.assertEqual(provider.last_status.state, "ok")
        self.assertIn("read-only", provider.last_status.message)

    def test_vendor_index_provider_maps_appimage_route_metadata(self) -> None:
        provider = VendorIndexProvider(index_path=FIXTURES / "vendor_index.json")

        routes = provider.search("AppImage")
        route = routes[0]

        self.assertEqual(route.route_id, "vendor-index:cursor:appimage-x86_64")
        self.assertEqual(route.provider, "vendor-index")
        self.assertEqual(route.backend, "appimage")
        self.assertEqual(route.install_backend, "appimage")
        self.assertEqual(route.install_target, "https://vendor.example/Cursor.AppImage")
        self.assertFalse(route.requires_host_mutation)
        self.assertFalse(route.requires_container)
        self.assertFalse(route.requires_snapshot)
        self.assertTrue(route.is_official)
        self.assertEqual(route.risk_level, "medium")
        self.assertIn("appimage", route.badges)
        self.assertIn("vendor", route.badges)
        self.assertIn("portable", route.badges)
        self.assertEqual(route.raw["artifact_format"], "AppImage")
        self.assertEqual(route.raw["trust_level"], "vendor-official")
        self.assertTrue(any("updates" in warning.casefold() for warning in route.warnings))
        self.assertTrue(any("sha256" in warning.casefold() for warning in route.warnings))

    def test_vendor_index_provider_maps_vendor_deb_route_metadata(self) -> None:
        provider = VendorIndexProvider(index_path=FIXTURES / "vendor_index.json")

        routes = provider.search("cursor.deb")
        route = routes[0]

        self.assertEqual(route.route_id, "vendor-index:cursor:deb-amd64")
        self.assertEqual(route.backend, "distrobox-deb")
        self.assertEqual(route.install_backend, "distrobox-deb")
        self.assertEqual(route.install_target, "https://vendor.example/cursor.deb")
        self.assertEqual(route.install_app_id, "cursor")
        self.assertTrue(route.requires_container)
        self.assertFalse(route.requires_host_mutation)
        self.assertIn("deb", route.badges)
        self.assertIn("distrobox", route.badges)
        self.assertEqual(route.raw["box"], "mpm-ubuntu-apps")
        self.assertTrue(any("Distrobox" in warning for warning in route.warnings))

    def test_vendor_index_provider_maps_vendor_rpm_route_metadata(self) -> None:
        provider = VendorIndexProvider(index_path=FIXTURES / "vendor_index.json")

        routes = provider.search("cursor.rpm")
        route = routes[0]

        self.assertEqual(route.route_id, "vendor-index:cursor:rpm-x86_64")
        self.assertEqual(route.backend, "distrobox-rpm")
        self.assertEqual(route.install_backend, "distrobox-rpm")
        self.assertEqual(route.install_target, "https://vendor.example/cursor.rpm")
        self.assertEqual(route.raw["box"], "mpm-fedora-apps")
        self.assertIn("rpm", route.badges)
        self.assertTrue(route.requires_container)

    def test_vendor_index_provider_reports_missing_index_as_warning(self) -> None:
        provider = VendorIndexProvider(index_path=FIXTURES / "missing_vendor_index.json")

        routes = provider.search("cursor")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("vendor index not found", provider.last_status.message)

    def test_vendor_index_provider_reports_invalid_index_as_warning(self) -> None:
        provider = VendorIndexProvider(index_path=FIXTURES / "vendor_index_invalid.json")

        routes = provider.search("cursor")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("invalid vendor index", provider.last_status.message)

    def test_load_vendor_index_entries_returns_path_and_entries(self) -> None:
        entries, path, error = load_vendor_index_entries(FIXTURES / "vendor_index.json")

        self.assertIsNone(error)
        self.assertEqual(path, FIXTURES / "vendor_index.json")
        self.assertEqual(entries[0].name, "Cursor")

    def test_bundled_vendor_index_is_valid(self) -> None:
        entries, path, error = load_vendor_index_entries(ROOT / "configs" / "mpm" / "vendor_index.json")

        self.assertIsNone(error)
        self.assertEqual(path, ROOT / "configs" / "mpm" / "vendor_index.json")
        self.assertGreaterEqual(len(entries), 1)

    def test_load_vendor_index_entries_uses_xdg_config_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_home = Path(tmpdir) / "config"
            index_path = config_home / "mpm" / "vendor_index.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text((FIXTURES / "vendor_index.json").read_text(encoding="utf-8"), encoding="utf-8")

            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
                with mock.patch("mpm.catalog_providers.repo_root", return_value=None):
                    entries, path, error = load_vendor_index_entries()

        self.assertIsNone(error)
        self.assertEqual(path, index_path)
        self.assertEqual(entries[0].name, "Cursor")

    def test_flatpak_provider_degrades_when_command_is_missing(self) -> None:
        provider = FlatpakProvider(command="definitely-missing-flatpak")

        routes = provider.search("firefox")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("not found", provider.last_status.message)

    def test_flatpak_provider_maps_command_output_to_routes(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout="Name\tDescription\tApplication\tVersion\tRemotes\n"
                "Firefox\tFast browser\torg.mozilla.firefox\t126.0\tflathub\n",
                stderr="",
            )

        provider = FlatpakProvider(runner=runner)
        with mock.patch("shutil.which", return_value="/usr/bin/flatpak"):
            routes = provider.search("firefox")

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].route_id, "flatpak:flathub:org.mozilla.firefox")
        self.assertEqual(routes[0].backend, "flatpak")
        self.assertFalse(routes[0].requires_host_mutation)
        self.assertEqual(routes[0].install_target, "org.mozilla.firefox")

    def test_pacman_provider_degrades_when_command_is_missing(self) -> None:
        provider = PacmanProvider(command="definitely-missing-pacman")

        with mock.patch("mpm.catalog_providers.detect_host", return_value=fake_host()):
            routes = provider.search("btop")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("not found", provider.last_status.message)

    def test_pacman_provider_maps_command_output_to_routes(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout="extra/btop 1.4.4-1\n    A monitor of resources\n",
                stderr="",
            )

        provider = PacmanProvider(runner=runner)
        with mock.patch("mpm.catalog_providers.detect_host", return_value=fake_host()), mock.patch(
            "shutil.which", return_value="/usr/bin/pacman"
        ):
            routes = provider.search("btop")

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].route_id, "pacman:extra:btop")
        self.assertEqual(routes[0].backend, "pacman")
        self.assertTrue(routes[0].requires_host_mutation)
        self.assertTrue(routes[0].requires_snapshot)
        self.assertEqual(routes[0].install_target, "btop")

    def test_pacman_provider_falls_back_to_passwordless_sudo_when_local_db_is_unreadable(self) -> None:
        calls: list[list[str]] = []

        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            argv = list(args[0])
            calls.append(argv)
            if argv[:2] == ["pacman", "-Ss"]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=1,
                    stdout="",
                    stderr="error: failed to initialize alpm library:\ncould not open database\n",
                )
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="extra/btop 1.4.7-1 [installed]\n    A monitor of resources\n",
                stderr="",
            )

        provider = PacmanProvider(runner=runner)
        with mock.patch("mpm.catalog_providers.detect_host", return_value=fake_host()), mock.patch(
            "shutil.which", return_value="/usr/bin/pacman"
        ):
            routes = provider.search("btop")

        self.assertEqual(calls[0], ["pacman", "-Ss", "btop"])
        self.assertEqual(calls[1], ["sudo", "-n", "pacman", "-Ss", "btop"])
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].install_target, "btop")

    def test_aur_provider_maps_rpc_json_to_routes(self) -> None:
        payload = (FIXTURES / "aur_rpc_search_cursor.json").read_text(encoding="utf-8")
        urls: list[str] = []

        def fetcher(url: str, timeout: float | None) -> str:
            urls.append(url)
            return payload

        provider = AurProvider(fetcher=fetcher)
        with mock.patch("mpm.catalog_providers.detect_host", return_value=fake_host()):
            routes = provider.search("cursor", timeout=1.0)

        self.assertEqual(len(routes), 2)
        self.assertIn("/cursor?", urls[0])
        self.assertEqual(routes[0].route_id, "aur:aur:cursor-bin")
        self.assertEqual(routes[0].backend, "aur")
        self.assertEqual(routes[0].source, "AUR")
        self.assertEqual(routes[0].install_target, "cursor-bin")
        self.assertEqual(routes[0].install_backend, "aur")
        self.assertTrue(routes[0].requires_host_mutation)
        self.assertTrue(routes[0].requires_snapshot)
        self.assertTrue(routes[0].is_community)
        self.assertFalse(routes[0].is_official)
        self.assertEqual(routes[0].risk_level, "medium")
        self.assertIn("aur", routes[0].badges)
        self.assertTrue(any("community" in warning.casefold() for warning in routes[0].warnings))
        self.assertTrue(any("snapshot" in warning.casefold() for warning in routes[0].warnings))
        self.assertEqual(routes[0].raw["votes"], 42)
        self.assertTrue(any("out-of-date" in warning.casefold() for warning in routes[1].warnings))
        self.assertEqual(provider.last_status.state, "ok")
        self.assertEqual(provider.last_status.result_count, 2)
        self.assertIn("read-only", provider.last_status.message)

    def test_aur_provider_degrades_when_rpc_unreachable(self) -> None:
        def fetcher(url: str, timeout: float | None) -> str:
            raise OSError("network unreachable")

        provider = AurProvider(fetcher=fetcher)
        with mock.patch("mpm.catalog_providers.detect_host", return_value=fake_host()):
            routes = provider.search("cursor")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("AUR RPC search failed", provider.last_status.message)

    def test_aur_provider_skips_empty_query_without_network(self) -> None:
        def fetcher(url: str, timeout: float | None) -> str:
            raise AssertionError("empty AUR query should not fetch")

        provider = AurProvider(fetcher=fetcher)
        routes = provider.search("")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "ok")
        self.assertIn("empty query", provider.last_status.message)

    def test_apt_ubuntu_provider_warns_when_box_is_missing(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout="ID | NAME | STATUS | IMAGE\n1 | other-box | running | ubuntu:24.04\n",
                stderr="",
            )

        provider = AptUbuntuProvider(runner=runner)
        with mock.patch("shutil.which", return_value="/usr/bin/distrobox"):
            routes = provider.search("firefox")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("mpm-ubuntu-apps", provider.last_status.message)

    def test_apt_ubuntu_provider_maps_command_output_to_routes(self) -> None:
        calls: list[list[str]] = []

        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            argv = list(args[0])
            calls.append(argv)
            if argv == ["distrobox", "list", "--no-color"]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="ID | NAME | STATUS | IMAGE\n1 | mpm-ubuntu-apps | running | ubuntu:24.04\n",
                    stderr="",
                )
            if argv[-4:] == ["apt-cache", "search", "--names-only", "firefox"]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="firefox - Safe and easy web browser from Mozilla\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="""Package: firefox
Version: 125.0+build3-0ubuntu0.22.04.1
Architecture: amd64
Homepage: https://www.mozilla.org/firefox/
Description-en: Safe and easy web browser from Mozilla
 Firefox delivers safe, easy web browsing.
""",
                stderr="",
            )

        provider = AptUbuntuProvider(runner=runner)
        with mock.patch("shutil.which", return_value="/usr/bin/distrobox"):
            routes = provider.search("firefox")

        self.assertEqual(calls[0], ["distrobox", "list", "--no-color"])
        self.assertEqual(
            calls[1],
            [
                "distrobox",
                "enter",
                "--name",
                "mpm-ubuntu-apps",
                "--",
                "apt-cache",
                "search",
                "--names-only",
                "firefox",
            ],
        )
        self.assertEqual(calls[2][-3:], ["apt-cache", "show", "firefox"])
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].route_id, "apt-ubuntu:ubuntu-apt:firefox")
        self.assertEqual(routes[0].backend, "distrobox-apt")
        self.assertEqual(routes[0].install_backend, "distrobox-apt")
        self.assertEqual(routes[0].install_target, "firefox")
        self.assertTrue(routes[0].requires_container)
        self.assertFalse(routes[0].requires_host_mutation)
        self.assertFalse(routes[0].requires_snapshot)
        self.assertIn("apt", routes[0].badges)
        self.assertIn("mpm-ubuntu-apps", routes[0].badges)
        self.assertEqual(routes[0].raw["box"], "mpm-ubuntu-apps")

    def test_apt_ubuntu_provider_warns_for_snap_transitional_packages(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            argv = list(args[0])
            if argv == ["distrobox", "list", "--no-color"]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="ID | NAME | STATUS | IMAGE\n1 | mpm-ubuntu-apps | running | ubuntu:24.04\n",
                    stderr="",
                )
            if argv[-4:] == ["apt-cache", "search", "--names-only", "chromium"]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="chromium-browser - Transitional package - chromium-browser -> chromium snap\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="""Package: chromium-browser
Version: 1:85.0.4183.83-0ubuntu2
Depends: snapd
Description-en: Transitional package - chromium-browser -> chromium snap
 This is a transitional dummy package.
 Installing this package will install the Chromium snap.
""",
                stderr="",
            )

        provider = AptUbuntuProvider(runner=runner)
        with mock.patch("shutil.which", return_value="/usr/bin/distrobox"):
            routes = provider.search("chromium")

        self.assertEqual(len(routes), 1)
        self.assertTrue(any("transitional" in warning.casefold() for warning in routes[0].warnings))
        self.assertTrue(any("snap" in warning.casefold() for warning in routes[0].warnings))

    def test_dnf_fedora_provider_maps_command_output_to_routes(self) -> None:
        calls: list[list[str]] = []

        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            argv = list(args[0])
            calls.append(argv)
            if argv == ["distrobox", "list", "--no-color"]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="ID | NAME | STATUS | IMAGE\n1 | mpm-fedora-apps | running | fedora:44\n",
                    stderr="",
                )
            if argv[-5:] == ["dnf", "-q", "--cacheonly", "search", "--name"] or argv[-6:] == [
                "dnf",
                "-q",
                "--cacheonly",
                "search",
                "--name",
                "firefox",
            ]:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="Matched fields: name (exact)\n firefox.x86_64: Mozilla Firefox Web browser\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="\n".join(
                    [
                        "Available packages",
                        "Name            : firefox",
                        "Version         : 126.0",
                        "Release         : 1.fc40",
                        "Architecture    : x86_64",
                        "Repository      : updates",
                        "Summary         : Mozilla Firefox Web browser",
                        "URL             : https://www.mozilla.org/firefox/",
                        "License         : MPL-2.0",
                        "Description     : Mozilla Firefox is an open-source web browser.",
                    ]
                ),
                stderr="",
            )

        provider = DnfProvider(runner=runner)
        with mock.patch("shutil.which", return_value="/usr/bin/distrobox"):
            routes = provider.search("firefox")

        self.assertEqual(calls[0], ["distrobox", "list", "--no-color"])
        self.assertEqual(
            calls[1],
            [
                "distrobox",
                "enter",
                "--name",
                "mpm-fedora-apps",
                "--",
                "dnf",
                "-q",
                "--cacheonly",
                "search",
                "--name",
                "firefox",
            ],
        )
        self.assertEqual(calls[2][-5:], ["dnf", "-q", "--cacheonly", "info", "firefox"])
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].route_id, "dnf-fedora:updates:firefox")
        self.assertEqual(routes[0].backend, "distrobox-dnf")
        self.assertEqual(routes[0].install_backend, "distrobox-dnf")
        self.assertTrue(routes[0].requires_container)
        self.assertFalse(routes[0].requires_host_mutation)
        self.assertEqual(routes[0].install_target, "firefox")
        self.assertIn("fedora", routes[0].badges)

    def test_distrobox_provider_warns_on_timeout(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

        provider = AptUbuntuProvider(runner=runner)
        with mock.patch("shutil.which", return_value="/usr/bin/distrobox"):
            routes = provider.search("firefox")

        self.assertEqual(routes, [])
        self.assertEqual(provider.last_status.state, "warning")
        self.assertIn("timed out", provider.last_status.message)


if __name__ == "__main__":
    unittest.main()
