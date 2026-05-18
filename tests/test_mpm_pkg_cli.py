from __future__ import annotations

import hashlib
import json
import subprocess
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MPM_PKG = ROOT / "bin" / "mpm-pkg"


def run_mpm_pkg(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(MPM_PKG), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def run_mpm_pkg_env(env: dict[str, str], *args: str) -> str:
    merged_env = os.environ.copy()
    merged_env.update(env)
    result = subprocess.run(
        [sys.executable, str(MPM_PKG), *args],
        check=True,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    return result.stdout


def run_mpm_pkg_failure(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MPM_PKG), *args],
        check=False,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def create_install_record(
    xdg_data_home: Path,
    *,
    target: str,
    backend: str,
    kind: str = "name",
    source: str = "name",
    app_id: str | None = None,
) -> int:
    db = xdg_data_home / "mpm" / "mpm-pkg" / "installed.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE installs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              target TEXT NOT NULL,
              backend TEXT NOT NULL,
              kind TEXT NOT NULL,
              source TEXT NOT NULL,
              app_id TEXT,
              installed_at INTEGER NOT NULL
            )
            """,
        )
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO installs (target, backend, kind, source, app_id, installed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (target, backend, kind, source, app_id, int(time.time())),
            )
        return int(cursor.lastrowid)
    finally:
        conn.close()


def create_success_uninstall_record(xdg_data_home: Path, install_id: int, *, target: str, backend: str) -> None:
    db = xdg_data_home / "mpm" / "mpm-pkg" / "installed.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uninstalls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              install_id INTEGER,
              target TEXT NOT NULL,
              backend TEXT NOT NULL,
              kind TEXT NOT NULL,
              source TEXT NOT NULL,
              app_id TEXT,
              plan TEXT NOT NULL,
              result TEXT NOT NULL,
              uninstalled_at INTEGER NOT NULL
            )
            """,
        )
        with conn:
            conn.execute(
                """
                INSERT INTO uninstalls
                  (install_id, target, backend, kind, source, app_id, plan, result, uninstalled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (install_id, target, backend, "name", "name", None, "test plan", "success", int(time.time())),
            )
    finally:
        conn.close()


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def write_os_release(path: Path, text: str = "ID=arch\nID_LIKE=arch\n") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def arch_host_env(tmp: Path, fake_bin: Path | None = None) -> dict[str, str]:
    os_release = write_os_release(tmp / "os-release")
    env = {"MPM_HOST_OS_RELEASE": str(os_release)}
    if fake_bin:
        env["PATH"] = str(fake_bin)
    return env


class MalikpkgCliTests(unittest.TestCase):
    def test_detect_deb_routes_to_distrobox_deb(self) -> None:
        output = run_mpm_pkg("detect", "/tmp/vendor.deb")

        self.assertIn("source: file", output)
        self.assertIn("kind: deb", output)
        self.assertIn("backend: distrobox-deb", output)

    def test_detect_appimage_url_routes_to_appimage(self) -> None:
        output = run_mpm_pkg("detect", "https://example.invalid/Cool.AppImage")

        self.assertIn("source: url", output)
        self.assertIn("kind: appimage", output)
        self.assertIn("backend: appimage", output)

    def test_explain_forced_flatpak_mentions_policy_reason(self) -> None:
        output = run_mpm_pkg("explain", "org.mozilla.firefox", "--backend", "flatpak")

        self.assertIn("target: org.mozilla.firefox", output)
        self.assertIn("backend: flatpak", output)
        self.assertIn("Flatpak backend forced", output)

    def test_explain_appimage_url_with_forced_backend(self) -> None:
        output = run_mpm_pkg("explain", "https://vendor.example/Cool.AppImage", "--backend", "appimage")

        self.assertIn("source: url", output)
        self.assertIn("kind: appimage", output)
        self.assertIn("backend: appimage", output)
        self.assertIn("AppImage file", output)

    def test_explain_vendor_deb_url_with_forced_backend(self) -> None:
        output = run_mpm_pkg("explain", "https://vendor.example/cool.deb", "--backend", "distrobox-deb")

        self.assertIn("source: url", output)
        self.assertIn("kind: deb", output)
        self.assertIn("backend: distrobox-deb", output)
        self.assertIn("inside the Ubuntu Distrobox", output)

    def test_distrobox_deb_url_dry_run_does_not_require_downloaded_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = Path(tmpdir) / "bridge.sh"
            write_executable(bridge, "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": tmpdir, "MPM_DISTROBOX_BRIDGE": str(bridge)},
                "install",
                "https://vendor.example/cool.deb",
                "--backend",
                "distrobox-deb",
                "--dry-run",
            )

        self.assertIn("curl -L --fail -o", output)
        self.assertIn("cool.deb", output)
        self.assertIn("backend: distrobox-deb", output)
        self.assertIn(f"{bridge} install-deb", output)
        self.assertLess(
            output.index("warning: vendor artifact has no pinned sha256"),
            output.index("curl -L --fail -o"),
        )

    def test_pacman_dry_run_prints_host_preflight_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                arch_host_env(tmp, fake_bin),
                "install",
                "--dry-run",
                "btop",
                "--backend",
                "pacman",
            )

        self.assertIn("host-preflight:", output)
        self.assertIn("backend: pacman", output)
        self.assertIn("host-mutation: yes", output)
        self.assertIn("package-request: btop", output)
        self.assertIn("expected snapshot description: pre-mpm-pkg-pacman: btop", output)
        self.assertIn("This operation modifies the real host package database.", output)
        snapshot_index = output.index("+ sudo snapper -c root create")
        pacman_index = output.index("+ sudo pacman -S --needed --noconfirm btop")
        self.assertLess(snapshot_index, pacman_index)

    def test_pacman_dry_run_with_no_snapshot_warns_snapshot_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                arch_host_env(tmp, fake_bin),
                "install",
                "--dry-run",
                "btop",
                "--backend",
                "pacman",
                "--no-snapshot",
            )

        self.assertIn("snapshot-status: absent: disabled by explicit --no-snapshot", output)
        self.assertIn("No snapshot will be created", output)
        self.assertIn("+ skip snapper snapshot", output)
        self.assertNotIn("+ sudo snapper -c root create", output)

    def test_pacman_dry_run_honors_snapshot_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")
            config = tmp / "config" / "mpm"
            config.mkdir(parents=True)
            (config / "preferences.json").write_text('{"pacman_snapshots": false}', encoding="utf-8")
            env = arch_host_env(tmp, fake_bin)
            env["XDG_CONFIG_HOME"] = str(tmp / "config")

            output = run_mpm_pkg_env(
                env,
                "install",
                "--dry-run",
                "btop",
                "--backend",
                "pacman",
            )

        self.assertIn("snapshot-status: absent: disabled by pacman_snapshots preference", output)
        self.assertIn("+ skip snapper snapshot", output)

    def test_host_install_requires_yes_after_preflight_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")
            result = run_mpm_pkg_failure(arch_host_env(tmp, fake_bin), "install", "btop", "--backend", "pacman")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("host package install requires --yes", result.stderr)

    def test_host_install_requires_cached_sudo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin = Path(tmpdir) / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "sudo", "#!/bin/sh\nexit 1\n")
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")

            result = run_mpm_pkg_failure(
                arch_host_env(Path(tmpdir), fake_bin),
                "install",
                "btop",
                "--backend",
                "pacman",
                "--yes",
                "--no-snapshot",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an active sudo session", result.stderr)

    def test_host_info_json_reports_portable_and_native_backends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            for name in ("apt", "flatpak", "distrobox", "podman", "gnome-terminal"):
                write_executable(fake_bin / name, "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", 'ID=ubuntu\nID_LIKE="debian"\n')

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                    "XDG_CURRENT_DESKTOP": "GNOME",
                },
                "host-info",
                "--json",
            )

        payload = json.loads(output)
        self.assertEqual(payload["host_family"], "debian")
        self.assertEqual(payload["native_manager"], "apt")
        self.assertEqual(payload["host_backends"], [])
        self.assertEqual(payload["portable_backends"], ["flatpak", "appimage", "distrobox"])
        self.assertEqual(payload["desktop"], "gnome")
        self.assertEqual(payload["terminal"], "gnome-terminal")

    def test_setup_host_check_reports_readiness_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "apt", "#!/bin/sh\nexit 0\n")
            write_executable(fake_bin / "flatpak", "#!/bin/sh\nprintf 'flathub\\n'\n")
            write_executable(fake_bin / "podman", "#!/bin/sh\nexit 0\n")
            write_executable(
                fake_bin / "distrobox",
                "\n".join(
                    [
                        "#!/bin/sh",
                        "printf 'ID           | NAME            | STATUS  | IMAGE\\n'",
                        "printf '123456789abc | mpm-ubuntu-apps | running | ubuntu:24.04\\n'",
                    ]
                )
                + "\n",
            )
            write_executable(fake_bin / "kitty", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", 'ID=ubuntu\nID_LIKE="debian"\nPRETTY_NAME="Ubuntu Test"\n')

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                    "XDG_CURRENT_DESKTOP": "GNOME",
                },
                "setup-host",
                "--check",
            )

        self.assertIn("setup-host-check:", output)
        self.assertIn("- distro: ok - Ubuntu Test (debian)", output)
        self.assertIn("- flatpak: ok -", output)
        self.assertIn("- flathub: ok - remote configured", output)
        self.assertIn("- container:mpm-ubuntu-apps: ok - exists", output)
        self.assertIn("- terminal: ok - kitty", output)

    def test_setup_host_check_json_reports_checks_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "apt", "#!/bin/sh\nexit 0\n")
            write_executable(fake_bin / "ghostty", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", "ID=debian\nID_LIKE=debian\n")

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                    "MPM_TERMINAL": "ghostty --wait",
                },
                "setup-host",
                "--check",
                "--json",
            )

        payload = json.loads(output)
        self.assertEqual(payload["mode"], "check")
        self.assertEqual(payload["host"]["host_family"], "debian")
        self.assertEqual(payload["host"]["terminal"], "ghostty")
        self.assertTrue(any(check["name"] == "flatpak" for check in payload["checks"]))
        self.assertIn("install flatpak: sudo apt install flatpak", payload["actions"])

    def test_setup_host_plan_recommends_missing_portable_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "apt", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", "ID=debian\nID_LIKE=debian\n")

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                },
                "setup-host",
                "--plan",
            )

        self.assertIn("setup-host-plan:", output)
        self.assertIn("install flatpak: sudo apt install flatpak", output)
        self.assertIn("install podman and distrobox: sudo apt install podman distrobox", output)
        self.assertIn("install terminal:", output)

    def test_setup_host_plan_json_uses_plan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "apt", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", "ID=debian\nID_LIKE=debian\n")

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                },
                "setup-host",
                "--plan",
                "--json",
            )

        payload = json.loads(output)
        self.assertEqual(payload["mode"], "plan")
        self.assertIn("install flatpak: sudo apt install flatpak", payload["actions"])

    def test_setup_host_apply_requires_yes(self) -> None:
        result = run_mpm_pkg_failure({}, "setup-host", "--apply")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup-host --apply requires --yes", result.stderr)

    def test_setup_host_apply_runs_only_safe_non_sudo_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            log = tmp / "commands.log"
            write_executable(fake_bin / "apt", "#!/bin/sh\nexit 0\n")
            write_executable(
                fake_bin / "flatpak",
                "\n".join(
                    [
                        "#!/bin/sh",
                        f"printf 'flatpak %s\\n' \"$*\" >> {log}",
                        "if [ \"$1\" = remotes ]; then exit 0; fi",
                        "exit 0",
                    ]
                )
                + "\n",
            )
            write_executable(fake_bin / "podman", "#!/bin/sh\nexit 0\n")
            write_executable(
                fake_bin / "distrobox",
                "\n".join(
                    [
                        "#!/bin/sh",
                        f"printf 'distrobox %s\\n' \"$*\" >> {log}",
                        "if [ \"$1\" = list ]; then printf 'ID | NAME | STATUS | IMAGE\\n'; fi",
                        "exit 0",
                    ]
                )
                + "\n",
            )
            os_release = write_os_release(tmp / "os-release", "ID=debian\nID_LIKE=debian\n")

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                },
                "setup-host",
                "--apply",
                "--yes",
            )

            commands = log.read_text(encoding="utf-8")

        self.assertIn("setup-host-apply:", output)
        self.assertIn("- add flathub: applied", output)
        self.assertIn("- create box mpm-ubuntu-apps: applied", output)
        self.assertIn("manual-actions:", output)
        self.assertIn("install PySide6:", output)
        self.assertIn("flatpak remote-add --if-not-exists flathub", commands)
        self.assertIn("distrobox create --name mpm-ubuntu-apps", commands)
        self.assertNotIn("apt install", commands)
        self.assertNotIn("sudo", commands)

    def test_setup_host_apply_json_reports_results_and_manual_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "apt", "#!/bin/sh\nexit 0\n")
            write_executable(
                fake_bin / "flatpak",
                "\n".join(
                    [
                        "#!/bin/sh",
                        "if [ \"$1\" = remotes ]; then exit 0; fi",
                        "exit 0",
                    ]
                )
                + "\n",
            )
            os_release = write_os_release(tmp / "os-release", "ID=debian\nID_LIKE=debian\n")

            output = run_mpm_pkg_env(
                {
                    "MPM_HOST_OS_RELEASE": str(os_release),
                    "PATH": str(fake_bin),
                },
                "setup-host",
                "--apply",
                "--yes",
                "--json",
            )

        payload = json.loads(output)
        self.assertEqual(payload["mode"], "apply")
        self.assertEqual(payload["results"][0]["id"], "add-flathub")
        self.assertEqual(payload["results"][0]["state"], "applied")
        self.assertIn("install podman and distrobox: sudo apt install podman distrobox", payload["manual_actions"])

    def test_pacman_blocks_on_non_arch_with_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", "ID=debian\nID_LIKE=debian\n")

            result = run_mpm_pkg_failure(
                {"MPM_HOST_OS_RELEASE": str(os_release), "PATH": str(fake_bin)},
                "install",
                "--dry-run",
                "btop",
                "--backend",
                "pacman",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pacman backend is Arch-only", result.stderr)

    def test_aur_blocks_on_non_arch_with_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "yay", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", "ID=fedora\nID_LIKE=fedora\n")

            result = run_mpm_pkg_failure(
                {"MPM_HOST_OS_RELEASE": str(os_release), "PATH": str(fake_bin)},
                "install",
                "--dry-run",
                "coolapp",
                "--backend",
                "aur",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aur backend is Arch-only", result.stderr)

    def test_arch_like_host_allows_pacman_and_aur_when_commands_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")
            write_executable(fake_bin / "paru", "#!/bin/sh\nexit 0\n")
            os_release = write_os_release(tmp / "os-release", "ID=manjaro\nID_LIKE=arch\n")
            env = {"MPM_HOST_OS_RELEASE": str(os_release), "PATH": str(fake_bin)}

            pacman_output = run_mpm_pkg_env(env, "install", "--dry-run", "btop", "--backend", "pacman")
            aur_output = run_mpm_pkg_env(env, "install", "--dry-run", "coolapp", "--backend", "aur")

        self.assertIn("backend: pacman", pacman_output)
        self.assertIn("+ sudo pacman -S --needed --noconfirm btop", pacman_output)
        self.assertIn("backend: aur", aur_output)
        self.assertIn("paru -S --needed --noconfirm coolapp", aur_output)

    def test_aur_paru_dry_run_requires_review_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "paru", "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                arch_host_env(tmp, fake_bin),
                "install",
                "--dry-run",
                "coolapp",
                "--backend",
                "aur",
            )

        self.assertIn("sudo snapper -c root create", output)
        self.assertIn("host-preflight:", output)
        self.assertIn("backend: aur", output)
        self.assertIn("AUR packages are community supplied; review the PKGBUILD", output)
        self.assertIn("paru -S --needed --noconfirm coolapp", output)
        self.assertNotIn("--skipreview", output)

    def test_aur_paru_dry_run_allows_explicit_skip_review_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "paru", "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                arch_host_env(tmp, fake_bin),
                "install",
                "--dry-run",
                "coolapp",
                "--backend",
                "aur",
                "--aur-skip-review",
            )

        self.assertIn("paru -S --needed --noconfirm --skipreview coolapp", output)

    def test_aur_yay_dry_run_does_not_auto_answer_review_prompts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "yay", "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                arch_host_env(tmp, fake_bin),
                "install",
                "--dry-run",
                "coolapp",
                "--backend",
                "aur",
            )

        self.assertIn("yay -S --needed --noconfirm coolapp", output)
        self.assertNotIn("--answerclean", output)
        self.assertNotIn("--answerdiff", output)
        self.assertNotIn("--answeredit", output)

    def test_appimage_url_dry_run_warns_when_sha256_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xdg_data_home = Path(tmpdir) / "xdg"
            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": str(xdg_data_home)},
                "install",
                "https://vendor.example/Cool.AppImage",
                "--backend",
                "appimage",
                "--dry-run",
            )

            self.assertIn("warning: vendor artifact has no pinned sha256", output)
            self.assertFalse((xdg_data_home / "mpm/appimages").exists())
            self.assertFalse((xdg_data_home / "applications").exists())

    def test_appimage_install_verifies_sha256_quotes_exec_and_records_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "Cool App.AppImage"
            source.write_bytes(b"appimage payload")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            xdg_data_home = tmp / "xdg"

            run_mpm_pkg_env(
                {"XDG_DATA_HOME": str(xdg_data_home), "MPM_DISTROBOX_BRIDGE": str(tmp / "missing-bridge")},
                "install",
                str(source),
                "--backend",
                "appimage",
                "--app-id",
                "cool",
                "--icon",
                "cool",
                "--sha256",
                expected,
            )
            desktop = xdg_data_home / "applications" / "mpm-appimage-cool.desktop"
            history = run_mpm_pkg_env({"XDG_DATA_HOME": str(xdg_data_home)}, "history")
            desktop_text = desktop.read_text(encoding="utf-8")

        self.assertIn('Exec="' + str(xdg_data_home / "mpm/appimages/Cool App.AppImage") + '"', desktop_text)
        self.assertIn("Icon=cool", desktop_text)
        self.assertIn('"manifest"', history)
        self.assertIn('"manager": "mpm-appimage"', history)
        self.assertIn('"sha256": "' + expected + '"', history)

    def test_appimage_install_refuses_sha256_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "Cool.AppImage"
            source.write_bytes(b"appimage payload")

            result = run_mpm_pkg_failure(
                {"XDG_DATA_HOME": str(tmp / "xdg"), "MPM_DISTROBOX_BRIDGE": str(tmp / "missing-bridge")},
                "install",
                str(source),
                "--backend",
                "appimage",
                "--sha256",
                "0" * 64,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256 mismatch", result.stderr)

    def test_flatpak_uninstall_dry_run_preserves_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_id = create_install_record(
                Path(tmpdir),
                target="org.mozilla.firefox",
                backend="flatpak",
                app_id="org.mozilla.firefox",
            )

            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": tmpdir},
                "uninstall",
                "--dry-run",
                str(record_id),
            )

        self.assertIn("backend: flatpak", output)
        self.assertIn("flatpak --user uninstall -y org.mozilla.firefox", output)
        self.assertIn("does not pass --delete-data", output)

    def test_flatpak_uninstall_dry_run_reports_registered_app_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "flatpak", "#!/bin/sh\nexit 1\n")
            record_id = create_install_record(
                tmp,
                target="org.mozilla.firefox",
                backend="flatpak",
                app_id="org.mozilla.firefox",
            )

            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": tmpdir, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                "uninstall",
                "--dry-run",
                str(record_id),
            )

        self.assertIn("stale-state: Flatpak record exists, but user Flatpak app is not installed", output)

    def test_appimage_uninstall_dry_run_targets_local_registry_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xdg_data_home = Path(tmpdir)
            record_id = create_install_record(
                xdg_data_home,
                target="/tmp/Cool App.AppImage",
                backend="appimage",
                kind="appimage",
                source="file",
            )

            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": tmpdir},
                "uninstall",
                "--dry-run",
                str(record_id),
            )

        self.assertIn(f"rm -f '{xdg_data_home}/mpm/appimages/Cool App.AppImage'", output)
        self.assertIn("mpm-appimage-cool-app.desktop", output)
        self.assertIn("removes MPM-managed binary copy and launcher only", output)
        self.assertIn("stale-state: AppImage record exists, but the MPM-managed binary and desktop entry are missing", output)

    def test_appimage_uninstall_dry_run_reports_desktop_exec_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xdg_data_home = Path(tmpdir)
            app_dir = xdg_data_home / "mpm" / "appimages"
            apps_dir = xdg_data_home / "applications"
            app_dir.mkdir(parents=True)
            apps_dir.mkdir(parents=True)
            (app_dir / "Cool.AppImage").write_text("appimage", encoding="utf-8")
            (apps_dir / "mpm-appimage-cool.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Cool\nExec=/missing/Cool.AppImage\n",
                encoding="utf-8",
            )
            record_id = create_install_record(
                xdg_data_home,
                target="/tmp/Cool.AppImage",
                backend="appimage",
                kind="appimage",
                source="file",
            )

            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": tmpdir},
                "uninstall",
                "--dry-run",
                str(record_id),
            )

        self.assertIn("stale-state: AppImage desktop entry exists, but Exec target is missing: /missing/Cool.AppImage", output)

    def test_distrobox_uninstall_refuses_unmapped_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_id = create_install_record(
                Path(tmpdir),
                target="/tmp/vendor.deb",
                backend="distrobox-deb",
                kind="deb",
                source="file",
            )
            result = subprocess.run(
                [sys.executable, str(MPM_PKG), "uninstall", "--dry-run", str(record_id)],
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_DATA_HOME": tmpdir},
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot safely uninstall Distrobox record without app_id", result.stderr)

    def test_distrobox_uninstall_refuses_unmapped_exported_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(
                fake_bin / "distrobox",
                """#!/bin/sh
script="$7"
case "$script" in
  *'find "$HOME/.local/share/applications"'*) printf '/usr/share/applications/cool.desktop\n'; exit 0 ;;
  *'cat "$1"'*) printf '[Desktop Entry]\nType=Application\nName=Cool\nExec=cool\n'; exit 0 ;;
  *) exit 0 ;;
esac
""",
            )
            apps_dir = tmp / "applications"
            apps_dir.mkdir()
            (apps_dir / "mpm-ubuntu-apps-cool.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Cool\nExec=distrobox enter mpm-ubuntu-apps -- cool\n",
                encoding="utf-8",
            )
            record_id = create_install_record(
                tmp,
                target="/tmp/cool.deb",
                backend="distrobox-deb",
                kind="deb",
                source="file",
                app_id="cool",
            )

            result = subprocess.run(
                [sys.executable, str(MPM_PKG), "uninstall", "--dry-run", str(record_id)],
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_DATA_HOME": tmpdir, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale-state: Distrobox exported launcher exists, but owning package cannot be mapped", result.stderr)

    def test_distrobox_uninstall_reports_package_exists_but_launcher_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(
                fake_bin / "distrobox",
                """#!/bin/sh
script="$7"
case "$script" in
  *'dpkg -s'*) printf 'cool\n'; exit 0 ;;
  *) exit 0 ;;
esac
""",
            )
            record_id = create_install_record(
                tmp,
                target="/tmp/cool.deb",
                backend="distrobox-deb",
                kind="deb",
                source="file",
                app_id="cool",
            )

            result = subprocess.run(
                [sys.executable, str(MPM_PKG), "uninstall", "--dry-run", str(record_id)],
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_DATA_HOME": tmpdir, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale-state: Distrobox package appears installed but exported launcher is missing", result.stderr)

    def test_host_uninstall_dry_run_creates_snapshot_before_pacman_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 0\n")
            record_id = create_install_record(tmp, target="btop", backend="pacman")

            output = run_mpm_pkg_env(
                {**arch_host_env(tmp, fake_bin), "XDG_DATA_HOME": tmpdir},
                "uninstall",
                "--dry-run",
                str(record_id),
            )

        snapshot_index = output.index("sudo snapper -c root create")
        pacman_index = output.index("sudo pacman -R btop")
        self.assertLess(snapshot_index, pacman_index)
        self.assertIn("expected snapshot description: pre-mpm-pkg-uninstall-pacman: btop", output)
        self.assertIn("rollback is manual only", output)

    def test_host_uninstall_dry_run_reports_pacman_missing_registered_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 1\n")
            record_id = create_install_record(tmp, target="btop", backend="pacman")

            output = run_mpm_pkg_env(
                {**arch_host_env(tmp, fake_bin), "XDG_DATA_HOME": tmpdir},
                "uninstall",
                "--dry-run",
                str(record_id),
            )

        self.assertIn("stale-state: host package record exists, but pacman no longer reports it installed: btop", output)

    def test_uninstall_dry_run_refuses_already_uninstalled_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            record_id = create_install_record(tmp, target="btop", backend="pacman")
            create_success_uninstall_record(tmp, record_id, target="btop", backend="pacman")
            result = subprocess.run(
                [sys.executable, str(MPM_PKG), "uninstall", "--dry-run", str(record_id)],
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_DATA_HOME": tmpdir},
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has already been successfully uninstalled", result.stderr)

    def test_uninstall_dry_run_refuses_already_uninstalled_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            record_id = create_install_record(tmp, target="btop", backend="pacman")
            create_success_uninstall_record(tmp, record_id, target="btop", backend="pacman")
            result = subprocess.run(
                [sys.executable, str(MPM_PKG), "uninstall", "--dry-run", "btop"],
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_DATA_HOME": tmpdir},
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matching install record has already been successfully uninstalled", result.stderr)

    def test_appimage_real_uninstall_marks_record_inactive_and_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xdg_data_home = Path(tmpdir)
            record_id = create_install_record(
                xdg_data_home,
                target="/tmp/Cool.AppImage",
                backend="appimage",
                kind="appimage",
                source="file",
            )

            run_mpm_pkg_env({"XDG_DATA_HOME": tmpdir}, "uninstall", str(record_id))
            installed = run_mpm_pkg_env({"XDG_DATA_HOME": tmpdir}, "list-installed")
            uninstalls = run_mpm_pkg_env({"XDG_DATA_HOME": tmpdir}, "list-uninstalls")

        self.assertIn("No mpm-pkg installs recorded yet.", installed)
        self.assertIn("Cool.AppImage", uninstalls)
        self.assertIn("\tsuccess\t", uninstalls)

    def test_history_lists_installs_uninstalls_and_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xdg_data_home = Path(tmpdir)
            db = xdg_data_home / "mpm" / "mpm-pkg" / "installed.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db)
            now = int(time.time())
            try:
                conn.executescript(
                    """
                    CREATE TABLE installs (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      target TEXT NOT NULL,
                      backend TEXT NOT NULL,
                      kind TEXT NOT NULL,
                      source TEXT NOT NULL,
                      app_id TEXT,
                      installed_at INTEGER NOT NULL
                    );
                    CREATE TABLE uninstalls (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      install_id INTEGER,
                      target TEXT NOT NULL,
                      backend TEXT NOT NULL,
                      kind TEXT NOT NULL,
                      source TEXT NOT NULL,
                      app_id TEXT,
                      plan TEXT NOT NULL,
                      result TEXT NOT NULL,
                      uninstalled_at INTEGER NOT NULL
                    );
                    CREATE TABLE repairs (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      target TEXT NOT NULL,
                      desktop_id TEXT,
                      box TEXT,
                      action TEXT NOT NULL,
                      repaired_at INTEGER NOT NULL
                    );
                    """
                )
                with conn:
                    conn.execute(
                        "INSERT INTO installs VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (1, "org.mozilla.firefox", "flatpak", "name", "name", "org.mozilla.firefox", now),
                    )
                    conn.execute(
                        "INSERT INTO uninstalls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            1,
                            1,
                            "org.mozilla.firefox",
                            "flatpak",
                            "name",
                            "name",
                            "org.mozilla.firefox",
                            "uninstall-plan:\ncommands:\n  - flatpak --user uninstall -y org.mozilla.firefox",
                            "success",
                            now + 1,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO repairs VALUES (?, ?, ?, ?, ?, ?)",
                        (1, "OpenCode", "opencode.desktop", "mpm-ubuntu-apps", "patch exported launcher", now + 2),
                    )
            finally:
                conn.close()

            output = run_mpm_pkg_env({"XDG_DATA_HOME": tmpdir}, "history")

        self.assertIn('"operation": "install"', output)
        self.assertIn('"operation": "uninstall"', output)
        self.assertIn('"operation": "repair"', output)
        self.assertIn('"result": "success"', output)

    def test_repair_desktop_degrades_when_no_refresh_tools_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            result = subprocess.run(
                [sys.executable, str(MPM_PKG), "repair-desktop", "--dry-run"],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PATH": str(fake_bin),
                    "XDG_DATA_HOME": str(tmp / "xdg"),
                    "MPM_DISTROBOX_BRIDGE": str(tmp / "missing-bridge"),
                },
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("warning: update-desktop-database not found", result.stderr)
        self.assertIn("warning: no desktop refresh tool found", result.stderr)


if __name__ == "__main__":
    unittest.main()
