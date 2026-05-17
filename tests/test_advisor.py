from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mpm.advisor import (  # noqa: E402
    POLICY_VERSION,
    advise_search_result,
    advisor_cache_key,
    build_advisor_input,
    format_advisor_response,
    route_policy_labels,
    route_policy_warnings,
)
from mpm.search import CatalogRoute, SearchResultSet, group_routes  # noqa: E402


def result_for_routes(*routes: CatalogRoute, query: str = "cursor") -> SearchResultSet:
    route_list = list(routes)
    return SearchResultSet(query=query, routes=route_list, groups=group_routes(route_list, query=query))


class AdvisorTests(unittest.TestCase):
    def test_build_advisor_input_uses_discovered_routes_only(self) -> None:
        vendor = CatalogRoute(
            provider="vendor-index",
            backend="distrobox-rpm",
            source="Cursor vendor RPM",
            display_name="Cursor",
            package_name="cursor",
            install_target="https://vendor.example/cursor.rpm",
            is_official=True,
            requires_container=True,
        )
        aur = CatalogRoute(
            provider="aur",
            backend="aur",
            source="AUR",
            display_name="Cursor",
            package_name="cursor-bin",
            is_community=True,
        )

        payload = build_advisor_input(result_for_routes(vendor, aur))

        self.assertEqual(payload["task"], "rank_install_routes")
        self.assertEqual(payload["policy_version"], POLICY_VERSION)
        self.assertEqual([route["route_id"] for route in payload["routes"]], [vendor.route_id, aur.route_id])
        self.assertEqual(payload["groups"][0]["recommended_route_id"], vendor.route_id)
        self.assertIn("Show every viable route", payload["system_context"]["principles"])

    def test_advisor_default_is_local_only_and_preserves_alternatives(self) -> None:
        flatpak = CatalogRoute(
            provider="flatpak",
            backend="flatpak",
            source="Flathub",
            display_name="Firefox",
            package_name="org.mozilla.firefox",
            app_id="org.mozilla.firefox",
            is_official=True,
            badges=["flathub", "sandbox"],
        )
        pacman = CatalogRoute(
            provider="pacman",
            backend="pacman",
            source="extra",
            display_name="Firefox",
            package_name="firefox",
            is_official=True,
        )

        response = advise_search_result(result_for_routes(pacman, flatpak, query="firefox"), env={})

        self.assertEqual(response.provider, "none")
        self.assertEqual(response.state, "local-only")
        self.assertEqual(response.recommended_route_id, flatpak.route_id)
        self.assertIn(pacman.route_id, response.labels)
        self.assertIn("Las rutas alternativas siguen visibles", response.why)

    def test_unknown_provider_falls_back_without_blocking(self) -> None:
        route = CatalogRoute(provider="flatpak", backend="flatpak", source="Flathub", display_name="Firefox")

        response = advise_search_result(result_for_routes(route, query="firefox"), env={"MPM_LLM_PROVIDER": "anthropic"})

        self.assertEqual(response.provider, "anthropic")
        self.assertEqual(response.state, "warning")
        self.assertIn("falling back to local policy", response.message)
        self.assertEqual(response.recommended_route_id, route.route_id)

    def test_route_policy_labels_expose_safety_shape(self) -> None:
        route = CatalogRoute(
            provider="aur",
            backend="aur",
            source="AUR",
            display_name="Cool App",
            package_name="coolapp-bin",
            is_community=True,
        )

        labels = route_policy_labels(route, recommended=True)

        self.assertIn("recommended", labels)
        self.assertIn("community", labels)
        self.assertIn("host", labels)
        self.assertIn("snapshot", labels)

    def test_route_policy_warnings_add_host_and_community_notes(self) -> None:
        route = CatalogRoute(
            provider="aur",
            backend="aur",
            source="AUR",
            display_name="Cool App",
            package_name="coolapp-bin",
            is_community=True,
            warnings=["AUR is community-sourced; review the PKGBUILD before installing."],
        )

        warnings = route_policy_warnings(route)
        text = "\n".join(warning.text for warning in warnings)

        self.assertIn("muta el host Arch", text)
        self.assertIn("Ruta comunitaria", text)
        self.assertEqual(len({warning.text for warning in warnings}), len(warnings))

    def test_cache_key_is_stable_and_changes_with_routes(self) -> None:
        route = CatalogRoute(provider="flatpak", backend="flatpak", source="Flathub", display_name="Firefox")
        payload = build_advisor_input(result_for_routes(route, query="firefox"))

        key_a = advisor_cache_key(payload, provider="none", model="local-policy")
        key_b = advisor_cache_key(payload, provider="none", model="local-policy")
        key_c = advisor_cache_key({**payload, "query": "cursor"}, provider="none", model="local-policy")

        self.assertEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)

    def test_format_advisor_response_is_human_readable(self) -> None:
        route = CatalogRoute(provider="flatpak", backend="flatpak", source="Flathub", display_name="Firefox")
        response = advise_search_result(result_for_routes(route, query="firefox"), env={})

        text = format_advisor_response(response)

        self.assertIn("Advisor: none", text)
        self.assertIn("Recommended route:", text)
        self.assertIn(route.route_id, text)


if __name__ == "__main__":
    unittest.main()
