from __future__ import annotations

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

    def test_pacman_dry_run_prints_host_preflight_plan(self) -> None:
        output = run_mpm_pkg("install", "--dry-run", "btop", "--backend", "pacman")

        self.assertIn("host-preflight:", output)
        self.assertIn("backend: pacman", output)
        self.assertIn("host-mutation: yes", output)
        self.assertIn("package-request: btop", output)
        self.assertIn("expected snapshot description: pre-mpm-pkg-pacman: btop", output)
        self.assertIn("This operation modifies the real host package database.", output)
        snapshot_index = output.index("+ sudo snapper -c root create")
        pacman_index = output.index("+ sudo pacman -S --needed --noconfirm btop")
        self.assertLess(snapshot_index, pacman_index)

    def test_aur_paru_dry_run_requires_review_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            write_executable(fake_bin / "paru", "#!/bin/sh\nexit 0\n")

            output = run_mpm_pkg_env(
                {"PATH": str(fake_bin)},
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
                {"PATH": str(fake_bin)},
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
                {"PATH": str(fake_bin)},
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
        self.assertIn("removes MalikOS-managed binary copy and launcher only", output)
        self.assertIn("stale-state: AppImage record exists, but the MalikOS-managed binary and desktop entry are missing", output)

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
            record_id = create_install_record(Path(tmpdir), target="btop", backend="pacman")

            output = run_mpm_pkg_env(
                {"XDG_DATA_HOME": tmpdir},
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
                {"XDG_DATA_HOME": tmpdir, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
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


if __name__ == "__main__":
    unittest.main()
