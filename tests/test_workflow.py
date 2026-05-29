from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mpm.workflow import (  # noqa: E402
    backend_status_from_setup_report_json,
    format_catalog_detail,
    format_discovery_only_backend_message,
    format_history_detail,
    format_preflight_confirmation,
    format_uninstall_confirmation,
    infer_doctor_target,
    is_discovery_only_backend,
    preflight_requires_host_confirmation,
    parse_history_output,
    parse_doctor_summary,
    resolved_preflight_backend,
)


class WorkflowHelperTests(unittest.TestCase):
    def test_infer_doctor_target_prefers_explicit_app_id(self) -> None:
        self.assertEqual(infer_doctor_target("Exporting cursor from mpm-fedora-apps", "cursor.rpm", " cursor "), "cursor")

    def test_infer_doctor_target_uses_latest_distrobox_export(self) -> None:
        output = "\n".join(
            [
                "Exporting first from mpm-ubuntu-apps",
                "Exporting cursor from mpm-fedora-apps",
            ]
        )

        self.assertEqual(infer_doctor_target(output, "/tmp/vendor.rpm", ""), "cursor")

    def test_infer_doctor_target_uses_appimage_desktop_id(self) -> None:
        self.assertEqual(
            infer_doctor_target("installed", "/tmp/Cool App.AppImage", ""),
            "mpm-appimage-cool-app.desktop",
        )

    def test_parse_doctor_summary_extracts_repair_plan(self) -> None:
        summary = parse_doctor_summary(
            "\n".join(
                [
                    "backend: distrobox-export",
                    "box: mpm-ubuntu-apps",
                    "missing-libraries: libasound.so.2",
                    "electron-like: yes",
                    "repair-plan:",
                    "  - install box packages: libasound2t64",
                    "  - patch exported launcher: flags --no-sandbox --disable-gpu",
                ]
            )
        )

        self.assertEqual(summary["backend"], "distrobox-export")
        self.assertEqual(summary["box"], "mpm-ubuntu-apps")
        self.assertEqual(summary["missing_libraries"], "libasound.so.2")
        self.assertEqual(summary["electron_like"], "yes")
        self.assertEqual(
            summary["repair_plan"],
            [
                "install box packages: libasound2t64",
                "patch exported launcher: flags --no-sandbox --disable-gpu",
            ],
        )

    def test_format_preflight_confirmation_includes_policy(self) -> None:
        text = format_preflight_confirmation(
            "org.mozilla.firefox",
            "flatpak",
            "\n".join(
                [
                    "target: org.mozilla.firefox",
                    "source: name",
                    "kind: name",
                    "backend: flatpak",
                    "reason: Flatpak backend forced.",
                ]
            ),
            "mpm-pkg install org.mozilla.firefox --backend flatpak",
        )

        self.assertIn("Backend: flatpak", text)
        self.assertIn("Policy: Flatpak backend forced.", text)
        self.assertNotIn("Host-level backend selected", text)

    def test_format_preflight_confirmation_warns_for_host_backend(self) -> None:
        text = format_preflight_confirmation(
            "btop",
            "",
            "source: name\nkind: name\nbackend: pacman\nreason: host package",
            "mpm-pkg install btop",
        )

        self.assertIn("Backend: pacman", text)
        self.assertIn("Host-level backend selected", text)
        self.assertIn("modifies the real host package database", text)

    def test_auto_preflight_uses_resolved_backend_for_host_confirmation(self) -> None:
        output = "source: name\nkind: name\nbackend: pacman\nreason: host package"

        self.assertEqual(resolved_preflight_backend("", output), "pacman")
        self.assertTrue(preflight_requires_host_confirmation("", output))

    def test_format_preflight_confirmation_warns_for_aur_review(self) -> None:
        text = format_preflight_confirmation(
            "coolapp",
            "aur",
            "\n".join(
                [
                    "host-preflight:",
                    "target: coolapp",
                    "source: name",
                    "kind: name",
                    "backend: aur",
                    "host-mutation: yes",
                    "snapshot-status: planned: Snapper root snapshot will be created before host mutation",
                ]
            ),
            "mpm-pkg install coolapp --backend aur",
        )

        self.assertIn("Backend: aur", text)
        self.assertIn("Snapshot: planned: Snapper root snapshot", text)
        self.assertIn("Review the PKGBUILD", text)

    def test_format_preflight_confirmation_warns_for_distrobox_boundaries(self) -> None:
        text = format_preflight_confirmation(
            "https://vendor.example/cool.deb",
            "distrobox-deb",
            "\n".join(
                [
                    "target: https://vendor.example/cool.deb",
                    "source: url",
                    "kind: deb",
                    "backend: distrobox-deb",
                    "reason: DEB install through Distrobox.",
                ]
            ),
            "mpm-pkg install https://vendor.example/cool.deb --backend distrobox-deb",
        )

        self.assertIn("Distrobox risk:", text)
        self.assertIn("not a strong sandbox", text)
        self.assertIn("HOME, graphical session, D-Bus, and audio", text)

    def test_discovery_only_backend_message_is_explicit(self) -> None:
        self.assertTrue(is_discovery_only_backend("distrobox-apt"))
        self.assertFalse(is_discovery_only_backend("distrobox-deb"))
        self.assertIn("discovery-only", format_discovery_only_backend_message("distrobox-dnf"))
        self.assertIn("distrobox-deb and distrobox-rpm", format_discovery_only_backend_message("distrobox-dnf"))

    def test_backend_status_from_setup_report_json_maps_gui_backends(self) -> None:
        statuses = backend_status_from_setup_report_json(
            """
            {
              "mode": "check",
              "host": {
                "host_family": "debian",
                "host_backends": [],
                "portable_backends": ["flatpak", "appimage", "distrobox"]
              },
              "checks": [
                {"name": "flatpak", "state": "ok", "detail": "/bin/flatpak"},
                {"name": "podman", "state": "ok", "detail": "/bin/podman"},
                {"name": "distrobox", "state": "ok", "detail": "/bin/distrobox"},
                {"name": "aur-helper", "state": "skipped", "detail": "AUR is Arch-only"},
                {"name": "container:mpm-ubuntu-apps", "state": "ok", "detail": "exists"},
                {"name": "container:mpm-fedora-apps", "state": "missing", "detail": "fedora:latest"}
              ],
              "actions": []
            }
            """
        )

        self.assertEqual(statuses["flatpak"]["state"], "ok")
        self.assertEqual(statuses["pacman"]["state"], "missing")
        self.assertEqual(statuses["aur"]["state"], "skipped")
        self.assertEqual(statuses["distrobox-deb"]["state"], "ok")
        self.assertEqual(statuses["distrobox-rpm"]["state"], "warning")
        self.assertEqual(statuses["distrobox-apt"]["state"], "discovery-only")

    def test_format_catalog_detail_keeps_delegation_text(self) -> None:
        text = format_catalog_detail(
            {
                "name": "Firefox",
                "target": "org.mozilla.firefox",
                "backend": "flatpak",
                "source": "Flathub",
                "summary": "Browser",
                "tags": "browser, flatpak",
                "app_id": "",
            }
        )

        self.assertIn("target: org.mozilla.firefox", text)
        self.assertIn("Backend policy and resolver behavior stay in mpm-pkg.", text)

    def test_format_uninstall_confirmation_summarizes_dry_run(self) -> None:
        text = format_uninstall_confirmation(
            "\n".join(
                [
                    "uninstall-plan:",
                    "record-id: 7",
                    "target: org.mozilla.firefox",
                    "backend: flatpak",
                    "kind: name",
                    "source: name",
                    "app-id: org.mozilla.firefox",
                    "data-policy: user data is preserved",
                    "commands:",
                    "  - flatpak --user uninstall -y org.mozilla.firefox",
                ]
            )
        )

        self.assertIn("Record: 7", text)
        self.assertIn("Data policy: user data is preserved", text)
        self.assertIn("flatpak --user uninstall -y org.mozilla.firefox", text)

    def test_format_uninstall_confirmation_warns_for_host_backend(self) -> None:
        text = format_uninstall_confirmation(
            "\n".join(
                [
                    "record-id: 9",
                    "target: btop",
                    "backend: pacman",
                    "data-policy: user data is preserved",
                    "commands:",
                    "  - sudo snapper -c root create --description pre-mpm-pkg-uninstall-pacman: btop",
                    "  - sudo pacman -R btop",
                ]
            )
        )

        self.assertIn("Backend: pacman", text)
        self.assertIn("Host-level backend selected", text)

    def test_parse_history_output_keeps_supported_operations(self) -> None:
        rows = parse_history_output(
            "\n".join(
                [
                    '{"operation":"install","record_id":1,"target":"btop","backend":"pacman","result":"recorded","timestamp":"2026-05-16 10:00:00"}',
                    '{"operation":"repair","record_id":2,"target":"OpenCode","backend":"mpm-ubuntu-apps","result":"recorded","timestamp":"2026-05-16 10:01:00"}',
                    "not json",
                ]
            )
        )

        self.assertEqual([row["operation"] for row in rows], ["install", "repair"])
        self.assertEqual(rows[0]["target"], "btop")

    def test_format_history_detail_is_read_only_delegation_text(self) -> None:
        text = format_history_detail(
            {
                "operation": "uninstall",
                "record_id": "7",
                "target": "org.mozilla.firefox",
                "backend": "flatpak",
                "result": "success",
                "timestamp": "2026-05-16 10:05:00",
                "detail": "uninstall-plan:\ncommands:\n  - flatpak --user uninstall -y org.mozilla.firefox",
            },
            "/tmp/malik-store/logs/operation.log",
        )

        self.assertIn("operation: uninstall", text)
        self.assertIn("operation-log-path: /tmp/malik-store/logs/operation.log", text)
        self.assertIn("flatpak --user uninstall -y org.mozilla.firefox", text)


if __name__ == "__main__":
    unittest.main()
