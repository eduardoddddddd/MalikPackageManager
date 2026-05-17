from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mpm.search import (  # noqa: E402
    AppGroup,
    CatalogRoute,
    ProviderStatus,
    SearchResultSet,
    group_key,
    group_routes,
    local_quality_score,
    local_recommendation_score,
    make_route_id,
    normalize_token,
    search_all,
)


class SearchDataModelTests(unittest.TestCase):
    def test_normalize_token_is_case_accent_and_punctuation_insensitive(self) -> None:
        self.assertEqual(normalize_token("  Café-Déjà Vu!! "), "cafedejavu")
        self.assertEqual(normalize_token("org.mozilla.Firefox"), "orgmozillafirefox")

    def test_make_route_id_is_deterministic_and_preserves_app_id_shape(self) -> None:
        self.assertEqual(
            make_route_id("Flatpak", "Flathub", "org.mozilla.Firefox"),
            "flatpak:flathub:org.mozilla.firefox",
        )
        self.assertEqual(make_route_id("Pacman", "Arch repo", "btop"), "pacman:arch-repo:btop")

    def test_catalog_route_fills_install_defaults_and_policy_flags(self) -> None:
        route = CatalogRoute(
            provider="pacman",
            backend="pacman",
            source="extra",
            display_name="btop",
            package_name="btop",
            is_official=True,
        )

        self.assertEqual(route.route_id, "pacman:extra:btop")
        self.assertEqual(route.install_target, "btop")
        self.assertEqual(route.install_backend, "pacman")
        self.assertTrue(route.requires_host_mutation)
        self.assertTrue(route.requires_snapshot)
        self.assertFalse(route.requires_container)

    def test_curated_catalog_entry_converts_to_route(self) -> None:
        route = CatalogRoute.from_catalog_entry(
            {
                "name": "Firefox",
                "target": "org.mozilla.firefox",
                "backend": "flatpak",
                "source": "Flathub",
                "summary": "Web browser installed as a user Flatpak.",
                "tags": "browser, web, flatpak, tested",
                "app_id": "org.mozilla.firefox",
            }
        )

        self.assertEqual(route.provider, "curated")
        self.assertEqual(route.route_id, "curated:flathub:org.mozilla.firefox")
        self.assertEqual(route.display_name, "Firefox")
        self.assertEqual(route.install_target, "org.mozilla.firefox")
        self.assertEqual(route.install_backend, "flatpak")
        self.assertEqual(route.install_app_id, "org.mozilla.firefox")
        self.assertIn("curated", route.badges)
        self.assertIn("flatpak", route.badges)
        self.assertFalse(route.requires_host_mutation)

    def test_curated_catalog_entry_preserves_auto_backend(self) -> None:
        route = CatalogRoute.from_catalog_entry(
            {
                "name": "Local file",
                "target": "/tmp/app.deb",
                "backend": "",
                "source": "Local",
                "summary": "Auto-detected installer route.",
                "tags": "local",
                "app_id": "",
            }
        )

        self.assertEqual(route.provider, "curated")
        self.assertEqual(route.backend, "")
        self.assertEqual(route.install_backend, "")
        self.assertEqual(route.install_target, "/tmp/app.deb")

    def test_group_key_prefers_alias_or_display_name(self) -> None:
        route = CatalogRoute(
            provider="flatpak",
            backend="flatpak",
            source="Flathub",
            display_name="Firefox",
            package_name="org.mozilla.firefox",
            app_id="org.mozilla.firefox",
            aliases=["Mozilla Firefox"],
        )

        self.assertEqual(group_key(route), "mozillafirefox")

    def test_group_routes_merges_duplicate_names_and_recommends_flatpak(self) -> None:
        pacman = CatalogRoute(
            provider="pacman",
            backend="pacman",
            source="extra",
            display_name="Firefox",
            package_name="firefox",
            summary="Fast, Private & Safe Web Browser",
            is_official=True,
            badges=["arch", "host", "snapshot"],
        )
        flatpak = CatalogRoute(
            provider="flatpak",
            backend="flatpak",
            source="Flathub",
            display_name="Firefox",
            package_name="org.mozilla.firefox",
            app_id="org.mozilla.firefox",
            summary="Web browser",
            is_official=True,
            badges=["flathub", "sandbox"],
        )

        groups = group_routes([pacman, flatpak], query="firefox")

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertIsInstance(group, AppGroup)
        self.assertEqual(group.group_id, "firefox")
        self.assertEqual(group.recommended_route_id, flatpak.route_id)
        self.assertEqual(group.routes, [flatpak.route_id, pacman.route_id])
        self.assertIn("org.mozilla.firefox", group.aliases)
        self.assertGreaterEqual(group.confidence, 0.8)

    def test_group_routes_is_deterministically_sorted_by_best_score(self) -> None:
        btop = CatalogRoute(
            provider="pacman",
            backend="pacman",
            source="extra",
            display_name="btop",
            package_name="btop",
            is_official=True,
        )
        firefox = CatalogRoute(
            provider="flatpak",
            backend="flatpak",
            source="Flathub",
            display_name="Firefox",
            package_name="org.mozilla.firefox",
            is_official=True,
            badges=["flathub", "sandbox"],
        )

        groups = group_routes([btop, firefox], query="firefox")

        self.assertEqual([group.group_id for group in groups], ["firefox", "btop"])

    def test_local_scoring_penalizes_community_host_routes(self) -> None:
        aur = CatalogRoute(
            provider="aur",
            backend="aur",
            source="AUR",
            display_name="Cursor",
            package_name="cursor-bin",
            is_community=True,
            warnings=["Community PKGBUILD should be reviewed."],
        )
        rpm_box = CatalogRoute(
            provider="rpm",
            backend="distrobox-rpm",
            source="Vendor RPM",
            display_name="Cursor",
            package_name="cursor",
            is_official=True,
            requires_container=True,
        )

        self.assertLess(local_quality_score(aur), local_quality_score(rpm_box))
        self.assertLess(local_recommendation_score(aur, "cursor"), local_recommendation_score(rpm_box, "cursor"))

    def test_local_scoring_prefers_official_vendor_container_route_over_aur(self) -> None:
        aur = CatalogRoute(
            provider="aur",
            backend="aur",
            source="AUR",
            display_name="Cursor",
            package_name="cursor-bin",
            is_community=True,
            warnings=["AUR is community-sourced; review the PKGBUILD before installing."],
        )
        vendor_rpm = CatalogRoute(
            provider="vendor-index",
            backend="distrobox-rpm",
            source="Cursor vendor RPM",
            display_name="Cursor",
            package_name="cursor",
            install_target="https://vendor.example/cursor.rpm",
            is_official=True,
            requires_container=True,
            badges=["vendor", "rpm", "distrobox", "container"],
            warnings=["Vendor DEB/RPM route installs inside Distrobox, not on the Arch host."],
        )

        groups = group_routes([aur, vendor_rpm], query="cursor")

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].recommended_route_id, vendor_rpm.route_id)
        self.assertLess(local_recommendation_score(aur, "cursor"), local_recommendation_score(vendor_rpm, "cursor"))

    def test_search_result_set_carries_routes_groups_and_provider_statuses(self) -> None:
        route = CatalogRoute(provider="curated", backend="flatpak", source="Flathub", display_name="Firefox")
        groups = group_routes([route], query="firefox")
        status = ProviderStatus(provider="curated", state="ok", duration_ms=7, result_count=1)
        result = SearchResultSet(query="firefox", routes=[route], groups=groups, provider_statuses=[status], duration_ms=9)

        self.assertEqual(result.query, "firefox")
        self.assertEqual(result.routes, [route])
        self.assertEqual(result.groups, groups)
        self.assertEqual(result.provider_statuses[0].provider, "curated")
        self.assertEqual(result.provider_statuses[0].result_count, 1)

    def test_search_all_collects_provider_routes_and_groups(self) -> None:
        class Provider:
            provider_id = "flatpak"
            display_name = "Flatpak"
            last_status = ProviderStatus(provider="flatpak", state="idle")

            def is_available(self) -> bool:
                return True

            def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
                route = CatalogRoute(
                    provider="flatpak",
                    backend="flatpak",
                    source="Flathub",
                    display_name="Firefox",
                    package_name="org.mozilla.firefox",
                    is_official=True,
                    badges=["flathub", "sandbox"],
                )
                self.last_status = ProviderStatus(provider="flatpak", state="ok", result_count=1)
                return [route]

        result = search_all("firefox", [Provider()])

        self.assertEqual(len(result.routes), 1)
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].display_name, "Firefox")
        self.assertEqual(result.provider_statuses[0].provider, "flatpak")
        self.assertEqual(result.provider_statuses[0].state, "ok")

    def test_search_all_keeps_working_when_provider_fails(self) -> None:
        class FailingProvider:
            provider_id = "broken"
            display_name = "Broken"
            last_status = ProviderStatus(provider="broken", state="idle")

            def is_available(self) -> bool:
                return True

            def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
                raise RuntimeError("boom")

        result = search_all("firefox", [FailingProvider()])

        self.assertEqual(result.routes, [])
        self.assertEqual(result.groups, [])
        self.assertEqual(result.provider_statuses[0].provider, "broken")
        self.assertEqual(result.provider_statuses[0].state, "warning")
        self.assertIn("boom", result.provider_statuses[0].message)

    def test_search_all_can_filter_enabled_sources(self) -> None:
        class Provider:
            def __init__(self, provider_id: str) -> None:
                self.provider_id = provider_id
                self.display_name = provider_id
                self.last_status = ProviderStatus(provider=provider_id, state="idle")

            def is_available(self) -> bool:
                return True

            def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
                self.last_status = ProviderStatus(provider=self.provider_id, state="ok", result_count=1)
                return [
                    CatalogRoute(
                        provider=self.provider_id,
                        backend=self.provider_id,
                        source=self.provider_id,
                        display_name=self.provider_id,
                    )
                ]

        result = search_all("anything", [Provider("flatpak"), Provider("pacman")], enabled_sources=["pacman"])

        self.assertEqual([route.provider for route in result.routes], ["pacman"])
        self.assertEqual([status.provider for status in result.provider_statuses], ["pacman"])

    def test_search_all_can_filter_provider_aliases(self) -> None:
        class Provider:
            provider_id = "apt-ubuntu"
            display_name = "Ubuntu apt"
            source_aliases = ("ubuntu", "apt", "deb")
            last_status = ProviderStatus(provider="apt-ubuntu", state="idle")

            def is_available(self) -> bool:
                return True

            def search(self, query: str, limit: int = 20, timeout: float | None = None) -> list[CatalogRoute]:
                self.last_status = ProviderStatus(provider="apt-ubuntu", state="ok", result_count=1)
                return [
                    CatalogRoute(
                        provider="apt-ubuntu",
                        backend="distrobox-apt",
                        source="Ubuntu apt",
                        display_name="firefox",
                        package_name="firefox",
                    )
                ]

        result = search_all("firefox", [Provider()], enabled_sources=["ubuntu"])

        self.assertEqual([route.provider for route in result.routes], ["apt-ubuntu"])
        self.assertEqual(result.provider_statuses[0].provider, "apt-ubuntu")


if __name__ == "__main__":
    unittest.main()
