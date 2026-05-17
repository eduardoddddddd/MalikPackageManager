from __future__ import annotations

import argparse
from datetime import datetime
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .advisor import AdvisorResponse, advise_search_result, format_advisor_response
from .catalog import load_catalog_entries
from .catalog_providers import default_catalog_providers
from .search import AppGroup, CatalogRoute, SearchResultSet, search_all
from .workflow import (
    format_catalog_detail,
    format_doctor_summary,
    format_history_detail,
    format_preflight_confirmation,
    format_uninstall_confirmation,
    infer_doctor_target,
    parse_history_output,
    parse_doctor_summary,
)


VERSION = "mpm 0.14-mvp"
BACKENDS = (
    ("Auto", ""),
    ("pacman", "pacman"),
    ("flatpak", "flatpak"),
    ("aur", "aur"),
    ("appimage", "appimage"),
    ("distrobox-deb", "distrobox-deb"),
    ("distrobox-rpm", "distrobox-rpm"),
    ("distrobox-apt", "distrobox-apt"),
    ("distrobox-dnf", "distrobox-dnf"),
)


def repo_root() -> Path | None:
    current = Path(__file__).resolve()
    for parent in [current.parent, *current.parents]:
        if (parent / "bin/mpm-pkg").exists():
            return parent
    return None


def find_mpm_pkg() -> str | None:
    override = os.environ.get("MPM_PKG_BIN") or os.environ.get("MPM_MPM_PKG")
    if override:
        return override

    path_match = shutil.which("mpm-pkg")
    if path_match:
        return path_match

    root = repo_root()
    candidates = []
    if root:
        candidates.append(root / "bin/mpm-pkg")
    candidates.extend(
        [
            Path.home() / ".local/bin/mpm-pkg",
            Path("/usr/bin/mpm-pkg"),
        ]
    )
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def operation_log_dir() -> Path:
    return xdg_data_home() / "mpm" / "logs"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return slug or "operation"


def drop_target_from_mime_data(mime_data) -> str | None:
    if mime_data.hasUrls():
        for url in mime_data.urls():
            if url.isLocalFile():
                return url.toLocalFile()
            if url.scheme() in {"http", "https"}:
                return url.toString()

    text = mime_data.text().strip()
    if not text:
        return None
    return text.splitlines()[0].strip()


class TargetLineEdit(QLineEdit):
    def __init__(self, on_drop: Callable[[str], None]) -> None:
        super().__init__()
        self.on_drop = on_drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if drop_target_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        target = drop_target_from_mime_data(event.mimeData())
        if target:
            self.on_drop(target)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class MPMWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MPM")
        self.resize(1040, 720)

        self.mpm_pkg_path = find_mpm_pkg()
        self.process: QProcess | None = None
        self.stdout_chunks: list[str] = []
        self.stderr_chunks: list[str] = []
        self.on_success: Callable[[str], None] | None = None
        self.command_buttons: list[QPushButton] = []
        self.pending_doctor_target: str | None = None
        self.current_command_text = ""
        self.current_operation_label = ""
        self.current_started_at: datetime | None = None
        self.last_install_target = ""
        self.last_install_app_id = ""
        self.catalog_entries, self.catalog_path, self.catalog_error = load_catalog_entries()
        self.catalog_providers = default_catalog_providers()
        self.catalog_search_result: SearchResultSet | None = None
        self.catalog_group_rows: list[AppGroup] = []
        self.catalog_route_rows: list[CatalogRoute] = []
        self.catalog_route_by_id: dict[str, CatalogRoute] = {}
        self.catalog_advisor_response: AdvisorResponse | None = None

        self.setAcceptDrops(True)
        self.catalog_search_edit = QLineEdit()
        self.catalog_search_edit.setPlaceholderText("Search all software")
        self.catalog_search_edit.returnPressed.connect(self.run_catalog_search)
        self.catalog_search_edit.textChanged.connect(self.render_catalog_results)
        self.catalog_source_checks: dict[str, QCheckBox] = {}
        for source_id, label in [
            ("all", "All"),
            ("curated", "MalikOS"),
            ("vendor", "Vendor"),
            ("flatpak", "Flatpak"),
            ("pacman", "Arch"),
            ("aur", "AUR"),
            ("deb", "DEB"),
            ("debian", "Debian"),
            ("ubuntu", "Ubuntu"),
            ("fedora", "Fedora"),
            ("rpm", "RPM"),
            ("appimage", "AppImage"),
        ]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(
                source_id
                in {"all", "curated", "vendor", "flatpak", "pacman", "aur", "deb", "debian", "ubuntu", "fedora", "rpm", "appimage"}
            )
            checkbox.stateChanged.connect(self.render_catalog_results)
            self.catalog_source_checks[source_id] = checkbox
        self.catalog_table = QTableWidget(0, 4)
        self.catalog_table.setHorizontalHeaderLabels(["App", "Recommended", "Routes", "Summary"])
        self.catalog_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.catalog_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.catalog_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.catalog_table.itemDoubleClicked.connect(self.use_catalog_selection)
        self.catalog_table.itemSelectionChanged.connect(self.update_catalog_routes)
        self.catalog_route_table = QTableWidget(0, 6)
        self.catalog_route_table.setHorizontalHeaderLabels(["Route", "Backend", "Target", "Box", "Badges", "Warnings"])
        self.catalog_route_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.catalog_route_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.catalog_route_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.catalog_route_table.itemDoubleClicked.connect(self.use_catalog_selection)
        self.catalog_route_table.itemSelectionChanged.connect(self.update_catalog_detail)
        self.catalog_detail = QPlainTextEdit()
        self.catalog_detail.setReadOnly(True)
        self.catalog_detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.catalog_status = QLabel()

        self.target_edit = TargetLineEdit(self.apply_dropped_target)
        self.target_edit.setPlaceholderText("Package name, URL, .deb, .rpm, or .AppImage")
        self.backend_combo = QComboBox()
        for label, backend in BACKENDS:
            self.backend_combo.addItem(label, backend)
        self.app_id_edit = QLineEdit()
        self.app_id_edit.setPlaceholderText("Optional app id")
        self.auto_doctor_check = QCheckBox("Doctor after install")
        self.auto_doctor_check.setChecked(True)
        self.doctor_target_edit = QLineEdit()
        self.doctor_target_edit.setPlaceholderText("Installed app name or desktop id")

        self.installed_table = QTableWidget(0, 7)
        self.installed_table.setHorizontalHeaderLabels(
            ["Id", "Target", "Backend", "Kind", "Source", "App ID", "Installed at"]
        )
        self.installed_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.installed_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.installed_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.installed_table.itemSelectionChanged.connect(self.use_selected_install)

        self.installed_status = QLabel("No install list loaded.")
        self.doctor_summary = QPlainTextEdit()
        self.doctor_summary.setReadOnly(True)
        self.doctor_summary.setMaximumHeight(120)
        self.doctor_summary.setPlainText(format_doctor_summary({}))

        self.history_rows: list[dict[str, str]] = []
        self.filtered_history_rows: list[dict[str, str]] = []
        self.history_filter_combo = QComboBox()
        self.history_filter_combo.addItem("All", "")
        self.history_filter_combo.addItem("Install", "install")
        self.history_filter_combo.addItem("Uninstall", "uninstall")
        self.history_filter_combo.addItem("Repair", "repair")
        self.history_filter_combo.currentIndexChanged.connect(self.populate_history_table)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(["Operation", "Id", "Target", "Backend", "Result", "Timestamp"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.itemSelectionChanged.connect(self.update_history_detail)
        self.history_detail = QPlainTextEdit()
        self.history_detail.setReadOnly(True)
        self.history_detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.history_detail.setPlainText(format_history_detail(None))
        self.history_status = QLabel("No history loaded.")
        self.history_log_path_label = QLabel(str(operation_log_dir()))
        self.history_log_path_label.setWordWrap(True)

        self.operation_state_label = QLabel("idle")
        self.operation_command_label = self.make_operation_text("none", maximum_height=58)
        self.operation_exit_label = QLabel("none")
        self.operation_log_path_label = self.make_operation_text("No operation log saved yet.", maximum_height=58)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(self.build_tabs(), stretch=4)
        layout.addWidget(self.build_log_panel(), stretch=3)
        self.setCentralWidget(root)
        self.run_catalog_search(include_live=False)

        if self.mpm_pkg_path:
            self.statusBar().showMessage(f"Using {self.mpm_pkg_path}")
        else:
            self.statusBar().showMessage("mpm-pkg not found")
            self.append_log("mpm-pkg was not found. Install MVP 0.4.1 before using MPM.\n")
            self.set_command_buttons_enabled(False)

    def build_tabs(self) -> QTabWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_catalog_tab(), "Catalog")
        self.tabs.addTab(self.build_install_tab(), "Install")
        self.tabs.addTab(self.build_installed_tab(), "Installed")
        self.tabs.addTab(self.build_history_tab(), "History")
        return self.tabs

    def build_catalog_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        search_row = QHBoxLayout()
        search_row.addWidget(self.catalog_search_edit, stretch=1)
        search_button = self.make_button("Search", QStyle.StandardPixmap.SP_FileDialogContentsView)
        search_button.clicked.connect(self.run_catalog_search)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Sources"))
        for checkbox in self.catalog_source_checks.values():
            source_row.addWidget(checkbox)
        source_row.addStretch(1)
        layout.addLayout(source_row)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        routes_title = QLabel("Routes")
        routes_title.setStyleSheet("font-weight: 600;")
        detail_title = QLabel("Route detail")
        detail_title.setStyleSheet("font-weight: 600;")
        use_button = self.make_button("Use route", QStyle.StandardPixmap.SP_ArrowForward)
        use_button.clicked.connect(self.use_catalog_selection)
        explain_button = self.make_button("Explain route", QStyle.StandardPixmap.SP_MessageBoxQuestion)
        explain_button.clicked.connect(self.explain_catalog_selection)
        advisor_button = self.make_button("Ask advisor", QStyle.StandardPixmap.SP_DialogHelpButton)
        advisor_button.clicked.connect(self.ask_catalog_advisor)
        install_button = self.make_button("Install route", QStyle.StandardPixmap.SP_DialogApplyButton)
        install_button.clicked.connect(self.install_catalog_selection)
        detail_actions = QHBoxLayout()
        detail_actions.addWidget(use_button)
        detail_actions.addWidget(explain_button)
        detail_actions.addWidget(advisor_button)
        detail_actions.addStretch(1)
        detail_actions.addWidget(install_button)
        detail_layout.addWidget(routes_title)
        detail_layout.addWidget(self.catalog_route_table, stretch=1)
        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.catalog_detail, stretch=1)
        detail_layout.addLayout(detail_actions)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.catalog_table)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.catalog_status)
        return tab

    def build_install_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_box = QGroupBox("Target")
        form = QFormLayout(form_box)

        target_row = QHBoxLayout()
        target_row.addWidget(self.target_edit, stretch=1)
        browse_button = self.make_button("Browse", QStyle.StandardPixmap.SP_DirOpenIcon)
        browse_button.clicked.connect(self.browse_target)
        target_row.addWidget(browse_button)
        form.addRow("Target", target_row)
        form.addRow("Backend", self.backend_combo)
        form.addRow("App ID", self.app_id_edit)
        form.addRow("", self.auto_doctor_check)

        action_row = QHBoxLayout()
        detect_button = self.make_button("Detect", QStyle.StandardPixmap.SP_FileDialogInfoView)
        detect_button.clicked.connect(self.detect_target)
        explain_button = self.make_button("Explain", QStyle.StandardPixmap.SP_MessageBoxQuestion)
        explain_button.clicked.connect(self.explain_target)
        install_button = self.make_button("Install", QStyle.StandardPixmap.SP_DialogApplyButton)
        install_button.clicked.connect(self.install_target)
        action_row.addWidget(detect_button)
        action_row.addWidget(explain_button)
        action_row.addStretch(1)
        action_row.addWidget(install_button)

        layout.addWidget(form_box)
        layout.addLayout(action_row)
        layout.addStretch(1)
        return tab

    def build_installed_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        refresh_row = QHBoxLayout()
        refresh_button = self.make_button("Refresh", QStyle.StandardPixmap.SP_BrowserReload)
        refresh_button.clicked.connect(self.refresh_installed)
        self.uninstall_button = self.make_button("Uninstall", QStyle.StandardPixmap.SP_TrashIcon)
        self.uninstall_button.clicked.connect(self.uninstall_selected_install)
        refresh_row.addWidget(refresh_button)
        refresh_row.addWidget(self.uninstall_button)
        refresh_row.addWidget(self.installed_status, stretch=1)

        doctor_box = QGroupBox("Doctor")
        doctor_layout = QFormLayout(doctor_box)
        doctor_layout.addRow("App", self.doctor_target_edit)
        doctor_layout.addRow("Summary", self.doctor_summary)

        doctor_actions = QHBoxLayout()
        doctor_button = self.make_button("Doctor", QStyle.StandardPixmap.SP_FileDialogContentsView)
        doctor_button.clicked.connect(self.doctor_app)
        repair_button = self.make_button("Repair", QStyle.StandardPixmap.SP_DialogApplyButton)
        repair_button.clicked.connect(self.repair_app)
        doctor_actions.addWidget(doctor_button)
        doctor_actions.addStretch(1)
        doctor_actions.addWidget(repair_button)
        doctor_layout.addRow("", doctor_actions)

        layout.addLayout(refresh_row)
        layout.addWidget(self.installed_table, stretch=1)
        layout.addWidget(doctor_box)
        return tab

    def build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls = QHBoxLayout()
        refresh_button = self.make_button("Refresh", QStyle.StandardPixmap.SP_BrowserReload)
        refresh_button.clicked.connect(self.refresh_history)
        controls.addWidget(refresh_button)
        controls.addWidget(QLabel("Filter"))
        controls.addWidget(self.history_filter_combo)
        controls.addWidget(self.history_status, stretch=1)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_title = QLabel("History detail")
        detail_title.setStyleSheet("font-weight: 600;")
        log_label = QLabel("Store operation logs")
        log_label.setStyleSheet("font-weight: 600;")
        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.history_detail, stretch=1)
        detail_layout.addWidget(log_label)
        detail_layout.addWidget(self.history_log_path_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.history_table)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addLayout(controls)
        layout.addWidget(splitter, stretch=1)
        return tab

    def build_log_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        state_box = QGroupBox("Operation")
        state_grid = QGridLayout(state_box)
        state_grid.setColumnStretch(1, 1)
        state_grid.addWidget(QLabel("State"), 0, 0)
        state_grid.addWidget(self.operation_state_label, 0, 1)
        state_grid.addWidget(QLabel("Exit code"), 0, 2)
        state_grid.addWidget(self.operation_exit_label, 0, 3)
        state_grid.addWidget(QLabel("Command"), 1, 0, Qt.AlignmentFlag.AlignTop)
        state_grid.addWidget(self.operation_command_label, 1, 1, 1, 3)
        state_grid.addWidget(QLabel("Log file"), 2, 0, Qt.AlignmentFlag.AlignTop)
        state_grid.addWidget(self.operation_log_path_label, 2, 1, 1, 3)

        header = QHBoxLayout()
        title = QLabel("Operation log")
        clear_button = self.make_button("Clear", QStyle.StandardPixmap.SP_DialogResetButton)
        clear_button.clicked.connect(self.log.clear)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(clear_button)
        layout.addWidget(state_box)
        layout.addLayout(header)
        layout.addWidget(self.log)
        return panel

    def make_operation_text(self, text: str, *, maximum_height: int) -> QPlainTextEdit:
        field = QPlainTextEdit()
        field.setPlainText(text)
        field.setReadOnly(True)
        field.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        field.setMinimumHeight(42)
        field.setMaximumHeight(maximum_height)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return field

    def make_button(self, text: str, icon: QStyle.StandardPixmap) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(self.style().standardIcon(icon))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if text != "Clear":
            self.command_buttons.append(button)
        return button

    def set_command_buttons_enabled(self, enabled: bool) -> None:
        for button in self.command_buttons:
            button.setEnabled(enabled)

    def checked_catalog_sources(self) -> list[str]:
        if self.catalog_source_checks.get("all") and self.catalog_source_checks["all"].isChecked():
            return []
        return [
            source_id
            for source_id, checkbox in self.catalog_source_checks.items()
            if source_id != "all" and checkbox.isChecked()
        ]

    def run_catalog_search(self, *_args, include_live: bool = True) -> None:
        query = self.catalog_search_edit.text().strip()
        enabled_sources = self.checked_catalog_sources()
        if not include_live or not query:
            enabled_sources = ["curated"]
        self.catalog_status.setText("Searching software routes...")
        QApplication.processEvents()
        self.catalog_search_result = search_all(
            query,
            self.catalog_providers,
            enabled_sources=enabled_sources,
            limit_per_source=8,
            timeout_per_source=3.0,
        )
        self.catalog_advisor_response = None
        self.render_catalog_results()

    def route_matches_query(self, route: CatalogRoute, terms: list[str]) -> bool:
        haystack = " ".join(
            [
                route.display_name,
                route.package_name,
                route.app_id,
                route.install_target,
                route.install_backend,
                route.source,
                route.summary,
                " ".join(route.badges),
            ]
        ).lower()
        return all(term in haystack for term in terms)

    def route_box(self, route: CatalogRoute) -> str:
        return str(route.raw.get("box", "")).strip()

    def format_route_badges(self, route: CatalogRoute, *, recommended: bool = False) -> str:
        label_map = {
            "apt": "APT",
            "arch": "Arch",
            "aur": "AUR",
            "community": "Community",
            "container": "Container",
            "curated": "MalikOS",
            "deb": "DEB",
            "distrobox": "Distrobox",
            "dnf": "DNF",
            "fedora": "Fedora",
            "flatpak": "Flatpak",
            "flathub": "Flathub",
            "host": "Host",
            "official": "Official",
            "portable": "Portable",
            "rpm": "RPM",
            "sandbox": "Sandbox",
            "snapshot": "Snapshot",
            "ubuntu": "Ubuntu",
            "debian": "Debian",
            "vendor": "Vendor",
            "appimage": "AppImage",
            "unknown": "Unknown",
        }
        box = self.route_box(route)
        badges: list[str] = ["Recommended"] if recommended else []
        for badge in route.badges:
            if badge == box:
                continue
            key = badge.strip().casefold()
            badges.append(label_map.get(key, badge.strip()))
        return ", ".join(dict.fromkeys(item for item in badges if item)) or "none"

    def format_provider_statuses(self) -> tuple[str, str]:
        if not self.catalog_search_result:
            return "", ""
        short_parts: list[str] = []
        detail_parts: list[str] = []
        for status in self.catalog_search_result.provider_statuses:
            short_parts.append(f"{status.provider} {status.state} {status.result_count} ({status.duration_ms}ms)")
            detail = f"{status.provider}: {status.state}, {status.result_count} result(s), {status.duration_ms}ms"
            if status.message:
                detail = f"{detail}: {status.message}"
            detail_parts.append(detail)
        return "; ".join(short_parts), "\n".join(detail_parts)

    def render_catalog_results(self, *_args) -> None:
        if self.catalog_search_result is None:
            return
        query = self.catalog_search_edit.text().strip()
        terms = [term for term in query.lower().split() if term]
        route_by_id = {route.route_id: route for route in self.catalog_search_result.routes}
        rows: list[AppGroup] = []
        route_count = 0
        for group in self.catalog_search_result.groups:
            group_routes = [route_by_id[route_id] for route_id in group.routes if route_id in route_by_id]
            if terms and not any(self.route_matches_query(route, terms) for route in group_routes):
                continue
            rows.append(group)
            route_count += len(group_routes)

        self.catalog_route_by_id = route_by_id
        self.catalog_group_rows = rows
        self.catalog_table.setRowCount(len(rows))
        for row_index, group in enumerate(rows):
            recommended = route_by_id.get(group.recommended_route_id)
            recommended_text = "none"
            if recommended:
                recommended_text = f"{recommended.install_backend or recommended.backend or 'auto'} / {recommended.source}"
            values = [
                group.display_name,
                recommended_text,
                str(len(group.routes)),
                group.summary,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.catalog_table.setItem(row_index, column, item)

        provider_text, provider_detail = self.format_provider_statuses()
        if self.catalog_error and not self.catalog_entries:
            self.catalog_status.setText(f"Catalog unavailable: {self.catalog_error}")
        elif not rows and query:
            self.catalog_status.setText(f'No routes found for "{query}". Try All sources or another name. {provider_text}')
        elif not rows:
            self.catalog_status.setText("No catalog entries loaded.")
        else:
            self.catalog_status.setText(f"{len(rows)} app group(s), {route_count} route(s). {provider_text}")
        self.catalog_status.setToolTip(provider_detail)

        if rows and self.catalog_table.currentRow() < 0:
            self.catalog_table.setCurrentCell(0, 0)
        else:
            self.update_catalog_routes()

    def update_catalog_routes(self) -> None:
        row = self.catalog_table.currentRow()
        group = self.catalog_group_rows[row] if 0 <= row < len(self.catalog_group_rows) else None
        routes = [self.catalog_route_by_id[route_id] for route_id in group.routes if route_id in self.catalog_route_by_id] if group else []
        self.catalog_route_rows = routes
        self.catalog_route_table.setRowCount(len(routes))
        for row_index, route in enumerate(routes):
            recommended = bool(group and route.route_id == group.recommended_route_id)
            warnings_text = f"{len(route.warnings)} warning(s)" if route.warnings else ""
            values = [
                route.display_name or route.package_name,
                route.install_backend or route.backend or "auto",
                route.install_target,
                self.route_box(route),
                self.format_route_badges(route, recommended=recommended),
                warnings_text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 2 and route.install_target:
                    item.setToolTip(route.install_target)
                elif column == 4:
                    item.setToolTip(self.format_route_badges(route, recommended=recommended))
                elif column == 5 and route.warnings:
                    item.setToolTip("\n".join(route.warnings))
                self.catalog_route_table.setItem(row_index, column, item)
        if routes:
            self.catalog_route_table.setCurrentCell(0, 0)
            self.update_catalog_detail()
        else:
            self.catalog_detail.setPlainText("Select an app group to see install routes.")

    def update_catalog_detail(self) -> None:
        route = self.selected_catalog_route_entry(show_warning=False)
        self.catalog_detail.setPlainText(self.format_catalog_route_detail(route) if route else "Select a route.")

    def ask_catalog_advisor(self) -> None:
        if not self.catalog_search_result:
            QMessageBox.warning(self, "Advisor unavailable", "Run a catalog search before asking the advisor.")
            return
        response = advise_search_result(self.catalog_search_result)
        self.catalog_advisor_response = response
        self.catalog_detail.setPlainText(format_advisor_response(response))
        self.catalog_status.setText(f"Advisor: {response.state}. Routes remain selectable.")

    def selected_catalog_route_entry(self, *, show_warning: bool = True) -> CatalogRoute | None:
        row = self.catalog_route_table.currentRow()
        if 0 <= row < len(self.catalog_route_rows):
            return self.catalog_route_rows[row]
        if show_warning:
            QMessageBox.warning(self, "Missing selection", "Select an install route.")
        return None

    def format_catalog_route_detail(self, route: CatalogRoute | None) -> str:
        if not route:
            return "Select a route."
        warnings = "\n".join(f"- {warning}" for warning in route.warnings) if route.warnings else "- none"
        badges = self.format_route_badges(route)
        box = self.route_box(route) or "none"
        artifact_format = str(route.raw.get("artifact_format", "") or route.raw.get("kind", "") or "none")
        artifact_url = str(route.raw.get("artifact_url", "") or route.raw.get("url", "") or "none")
        trust = str(route.raw.get("trust_level", "") or route.raw.get("trust", "") or "none")
        updates = str(route.raw.get("update_policy", "") or "none")
        uninstall = str(route.raw.get("uninstall_policy", "") or "none")
        checksum = str(route.raw.get("sha256", "") or route.raw.get("checksum", "") or "none")
        signature = str(route.raw.get("signature_url", "") or "none")
        return "\n".join(
            [
                f"Name: {route.display_name}",
                f"Source: {route.source}",
                f"Backend: {route.install_backend or route.backend or 'auto'}",
                f"Target: {route.install_target}",
                f"Box: {box}",
                f"App ID: {route.install_app_id or route.app_id or 'none'}",
                f"Version: {route.version or 'none'}",
                f"Publisher: {route.publisher or 'none'}",
                f"Homepage: {route.homepage or 'none'}",
                f"License: {route.license or 'none'}",
                f"Artifact: {artifact_format}",
                f"Artifact URL: {artifact_url}",
                f"Trust: {trust}",
                f"Updates: {updates}",
                f"Uninstall: {uninstall}",
                f"Checksum: {checksum}",
                f"Signature: {signature}",
                f"Risk: {route.risk_level}",
                f"Host mutation: {'yes' if route.requires_host_mutation else 'no'}",
                f"Container: {'yes' if route.requires_container else 'no'}",
                f"Snapshot required: {'yes' if route.requires_snapshot else 'no'}",
                f"Community: {'yes' if route.is_community else 'no'}",
                f"Badges: {badges}",
                "",
                "Summary:",
                route.summary or "none",
                "",
                "Warnings:",
                warnings,
            ]
        )

    def apply_catalog_route(self, route: CatalogRoute, *, switch_to_install: bool = False) -> None:
        backend = route.install_backend or route.backend
        self.target_edit.setText(route.install_target)
        self.app_id_edit.setText(route.install_app_id or route.app_id)
        index = self.backend_combo.findData(backend)
        self.backend_combo.setCurrentIndex(index if index >= 0 else 0)
        self.append_log(f"\nCatalog route: {route.display_name or route.install_target} [{backend or 'auto'}]\n")
        if switch_to_install and hasattr(self, "tabs"):
            self.tabs.setCurrentIndex(1)

    def use_catalog_selection(self, *_args) -> None:
        route = self.selected_catalog_route_entry()
        if route:
            self.apply_catalog_route(route, switch_to_install=True)

    def explain_catalog_selection(self) -> None:
        route = self.selected_catalog_route_entry()
        if route:
            self.apply_catalog_route(route)
            self.explain_target()

    def install_catalog_selection(self) -> None:
        route = self.selected_catalog_route_entry()
        if route:
            backend = route.install_backend or route.backend
            if backend in {"distrobox-apt", "distrobox-dnf"}:
                QMessageBox.information(
                    self,
                    "Discovery only",
                    f"{backend} routes are searchable in 0.14, but install support is not implemented yet.",
                )
                self.append_log(
                    f"\nCatalog route skipped: {backend} is discovery-only in 0.14.\n"
                )
                return
            self.apply_catalog_route(route)
            self.install_target()

    def command_running(self) -> bool:
        return bool(self.process and self.process.state() != QProcess.ProcessState.NotRunning)

    def dragEnterEvent(self, event) -> None:
        if drop_target_from_mime_data(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        target = drop_target_from_mime_data(event.mimeData())
        if target:
            self.apply_dropped_target(target)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def apply_dropped_target(self, target: str, *, run_detect: bool = True) -> None:
        self.target_edit.setText(target)
        self.append_log(f"\nDropped target: {target}\n")
        if run_detect and self.mpm_pkg_path and not self.command_running():
            self.run_mpm_pkg(["detect", target], "detect")

    def browse_target(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select package",
            str(Path.home()),
            "Packages (*.deb *.rpm *.AppImage);;All files (*)",
        )
        if filename:
            self.target_edit.setText(filename)

    def target_text(self) -> str | None:
        target = self.target_edit.text().strip()
        if not target:
            QMessageBox.warning(self, "Missing target", "Enter a package name, URL, or file path.")
            return None
        return target

    def selected_backend(self) -> str:
        return str(self.backend_combo.currentData() or "")

    def explain_args(self, target: str, backend: str | None = None) -> list[str]:
        args = ["explain", target]
        backend = self.selected_backend() if backend is None else backend
        if backend:
            args.extend(["--backend", backend])
        return args

    def install_args(self, target: str, backend: str, app_id: str) -> list[str]:
        args = ["install", target]
        if backend:
            args.extend(["--backend", backend])
        if app_id:
            args.extend(["--app-id", app_id])
        return args

    def selected_install_record_id(self) -> str | None:
        row = self.installed_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Missing selection", "Select an installed record.")
            return None
        item = self.installed_table.item(row, 0)
        record_id = item.text().strip() if item else ""
        if not record_id:
            QMessageBox.warning(self, "Missing selection", "Selected row has no install record id.")
            return None
        return record_id

    def detect_target(self) -> None:
        target = self.target_text()
        if target:
            self.run_mpm_pkg(["detect", target], "detect")

    def explain_target(self) -> None:
        target = self.target_text()
        if target:
            self.run_mpm_pkg(self.explain_args(target), "explain")

    def install_target(self) -> None:
        target = self.target_text()
        if not target:
            return
        backend = self.selected_backend()
        app_id = self.app_id_edit.text().strip()
        args = self.install_args(target, backend, app_id)
        self.last_install_target = target
        self.last_install_app_id = app_id
        self.run_mpm_pkg(
            self.explain_args(target, backend),
            "install-preflight",
            lambda output: self.confirm_install_after_preflight(target, backend, app_id, args, output),
        )

    def confirm_install_after_preflight(
        self,
        target: str,
        backend: str,
        app_id: str,
        install_args: list[str],
        explain_output: str,
    ) -> None:
        if not self.mpm_pkg_path:
            return

        command_text = shlex.join([self.mpm_pkg_path, *install_args])
        message = format_preflight_confirmation(target, backend, explain_output, command_text)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Confirm install")
        dialog.setText("Review the MPM install preflight.")
        dialog.setInformativeText(message)
        dialog.setDetailedText(explain_output)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Install")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")

        if dialog.exec() == QMessageBox.StandardButton.Yes:
            self.last_install_target = target
            self.last_install_app_id = app_id
            self.run_mpm_pkg(install_args, "install", self.after_install)
            return

        self.append_log("\nInstall cancelled after preflight.\n")
        self.set_operation_state("idle", command="Install cancelled after preflight", exit_code="none")
        self.statusBar().showMessage("Install cancelled")

    def refresh_installed(self) -> None:
        self.run_mpm_pkg(["list-installed"], "list-installed", self.populate_installed_table)

    def refresh_history(self) -> None:
        self.run_mpm_pkg(["history"], "history", self.populate_history_table)

    def refresh_installed_from_output(self, _output: str) -> None:
        self.refresh_installed()

    def after_install(self, output: str) -> None:
        doctor_target = infer_doctor_target(
            output,
            getattr(self, "last_install_target", ""),
            getattr(self, "last_install_app_id", ""),
        )
        if self.auto_doctor_check.isChecked() and doctor_target:
            self.pending_doctor_target = doctor_target
            self.doctor_target_edit.setText(doctor_target)
            self.append_log(f"\nDoctor target: {doctor_target}\n")
        elif self.auto_doctor_check.isChecked():
            self.append_log("\nDoctor target could not be inferred from this install.\n")
        self.run_mpm_pkg(["list-installed"], "list-installed", self.after_install_list_installed)

    def after_install_list_installed(self, output: str) -> None:
        self.populate_installed_table(output)
        doctor_target = self.pending_doctor_target
        self.pending_doctor_target = None
        if doctor_target:
            self.run_mpm_pkg(["doctor", doctor_target], "doctor", self.after_doctor)

    def use_selected_install(self) -> None:
        row = self.installed_table.currentRow()
        if row < 0:
            return
        app_id_item = self.installed_table.item(row, 5)
        target_item = self.installed_table.item(row, 1)
        app_id = app_id_item.text().strip() if app_id_item else ""
        target = target_item.text().strip() if target_item else ""
        self.doctor_target_edit.setText(app_id or target)

    def doctor_app(self) -> None:
        target = self.doctor_target_edit.text().strip()
        if not target:
            QMessageBox.warning(self, "Missing app", "Enter an installed app name or desktop id.")
            return
        self.run_mpm_pkg(["doctor", target], "doctor", self.after_doctor)

    def after_doctor(self, output: str) -> None:
        summary = parse_doctor_summary(output)
        self.doctor_summary.setPlainText(format_doctor_summary(summary))

    def repair_app(self) -> None:
        target = self.doctor_target_edit.text().strip()
        if not target:
            QMessageBox.warning(self, "Missing app", "Enter an installed app name or desktop id.")
            return
        reply = QMessageBox.question(
            self,
            "Repair dry-run",
            f"Run mpm-pkg repair-app --dry-run for {target}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.run_mpm_pkg(
                ["repair-app", target, "--dry-run"],
                "repair dry-run",
                lambda output: self.confirm_repair_after_dry_run(target, output),
            )

    def confirm_repair_after_dry_run(self, target: str, dry_run_output: str) -> None:
        self.after_doctor(dry_run_output)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Confirm repair")
        dialog.setText(f"Run real repair for {target}?")
        dialog.setInformativeText("Review the dry-run plan and log before continuing.")
        dialog.setDetailedText(dry_run_output)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Repair")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")

        if dialog.exec() == QMessageBox.StandardButton.Yes:
            self.run_mpm_pkg(["repair-app", target], "repair-app", self.refresh_installed_from_output)
            return

        self.append_log("\nRepair cancelled after dry-run.\n")
        self.set_operation_state("idle", command="Repair cancelled after dry-run", exit_code="none")
        self.statusBar().showMessage("Repair cancelled")

    def uninstall_selected_install(self) -> None:
        record_id = self.selected_install_record_id()
        if not record_id:
            return
        self.run_mpm_pkg(
            ["uninstall", "--dry-run", record_id],
            "uninstall-preflight",
            lambda output: self.confirm_uninstall_after_dry_run(record_id, output),
        )

    def confirm_uninstall_after_dry_run(self, record_id: str, dry_run_output: str) -> None:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Confirm uninstall")
        dialog.setText("Review the MPM uninstall preflight.")
        dialog.setInformativeText(format_uninstall_confirmation(dry_run_output))
        dialog.setDetailedText(dry_run_output)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Uninstall")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")

        if dialog.exec() == QMessageBox.StandardButton.Yes:
            self.run_mpm_pkg(["uninstall", record_id, "--yes"], "uninstall", self.refresh_installed_from_output)
            return

        self.append_log("\nUninstall cancelled after dry-run.\n")
        self.set_operation_state("idle", command="Uninstall cancelled after dry-run", exit_code="none")
        self.statusBar().showMessage("Uninstall cancelled")

    def run_mpm_pkg(
        self,
        args: list[str],
        label: str,
        on_success: Callable[[str], None] | None = None,
    ) -> None:
        if not self.mpm_pkg_path:
            QMessageBox.critical(self, "mpm-pkg missing", "mpm-pkg is not available.")
            return
        if self.command_running():
            QMessageBox.information(self, "Command running", "Wait for the current operation to finish.")
            return

        command_text = shlex.join([self.mpm_pkg_path, *args])
        started_at = datetime.now()
        self.current_started_at = started_at
        self.current_command_text = command_text
        self.current_operation_label = label
        self.append_log(f"\n== {started_at.isoformat(timespec='seconds')} {label} ==\n$ {command_text}\n")
        self.statusBar().showMessage(f"Running {label}")
        self.set_operation_state("running", command=command_text, exit_code="running")
        self.set_command_buttons_enabled(False)
        self.stdout_chunks = []
        self.stderr_chunks = []
        self.on_success = on_success

        process = QProcess(self)
        process.setProgram(self.mpm_pkg_path)
        process.setArguments(args)
        process.setProcessEnvironment(self.process_environment())
        process.readyReadStandardOutput.connect(self.read_stdout)
        process.readyReadStandardError.connect(self.read_stderr)
        process.finished.connect(self.process_finished)
        self.process = process
        process.start()
        process.closeWriteChannel()
        if not process.waitForStarted(3000):
            error_text = f"Failed to start mpm-pkg: {process.errorString()}\n"
            self.stderr_chunks.append(error_text)
            self.append_log(error_text)
            log_file = self.write_operation_log(-1, "failed-to-start")
            if log_file:
                self.append_log(f"Log saved: {log_file}\n")
            self.statusBar().showMessage("Command failed to start")
            self.set_operation_state("failure", command=command_text, exit_code="-1", log_file=log_file)
            self.set_command_buttons_enabled(True)
            self.process = None

    def process_environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        path_entries = [str(Path.home() / ".local/bin")]
        root = repo_root()
        if root:
            path_entries.append(str(root / "bin"))
        current_path = env.value("PATH", "")
        if current_path:
            path_entries.append(current_path)
        env.insert("PATH", os.pathsep.join(path_entries))
        return env

    def read_stdout(self) -> None:
        if not self.process:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        self.stdout_chunks.append(text)
        self.append_log(text)

    def read_stderr(self) -> None:
        if not self.process:
            return
        text = bytes(self.process.readAllStandardError()).decode(errors="replace")
        self.stderr_chunks.append(text)
        self.append_log(text)

    def process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        ok = exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        self.append_log(f"\n[{exit_code}] {'done' if ok else 'failed'}\n")
        exit_status_text = "normal" if exit_status == QProcess.ExitStatus.NormalExit else "crashed"
        log_file = self.write_operation_log(exit_code, exit_status_text)
        if log_file:
            self.append_log(f"Log saved: {log_file}\n")
        self.statusBar().showMessage("Ready" if ok else f"Command failed: {exit_code}")
        self.set_operation_state(
            "success" if ok else "failure",
            command=self.current_command_text,
            exit_code=str(exit_code),
            log_file=log_file,
        )
        callback = self.on_success if ok else None
        output = "".join(self.stdout_chunks)
        if self.process:
            self.process.deleteLater()
        self.process = None
        self.on_success = None
        self.set_command_buttons_enabled(True)
        if callback:
            callback(output)

    def set_operation_state(
        self,
        state: str,
        *,
        command: str | None = None,
        exit_code: str | None = None,
        log_file: Path | None = None,
    ) -> None:
        self.operation_state_label.setText(state)
        if command is not None:
            self.operation_command_label.setPlainText(command or "none")
        if exit_code is not None:
            self.operation_exit_label.setText(exit_code)
        if log_file is not None:
            self.operation_log_path_label.setPlainText(str(log_file))

    def write_operation_log(self, exit_code: int, exit_status: str) -> Path | None:
        try:
            log_dir = operation_log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            started_at = self.current_started_at or datetime.now()
            filename = f"{started_at.strftime('%Y%m%d-%H%M%S-%f')}-{slugify(self.current_operation_label)}.log"
            path = log_dir / filename
            text = "\n".join(
                [
                    f"timestamp: {started_at.isoformat(timespec='seconds')}",
                    f"command: {self.current_command_text}",
                    f"operation: {self.current_operation_label}",
                    f"exit-code: {exit_code}",
                    f"exit-status: {exit_status}",
                    "",
                    "--- stdout ---",
                    "".join(self.stdout_chunks),
                    "",
                    "--- stderr ---",
                    "".join(self.stderr_chunks),
                ]
            )
            path.write_text(text, encoding="utf-8")
            return path
        except OSError as exc:
            self.append_log(f"Could not write operation log: {exc}\n")
            return None

    def append_log(self, text: str) -> None:
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def populate_installed_table(self, output: str) -> None:
        self.installed_table.setRowCount(0)
        rows = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) == 7 and parts[0].isdigit():
                rows.append(parts)

        if not rows:
            self.installed_status.setText(output.strip() or "No installs recorded.")
            return

        self.installed_table.setRowCount(len(rows))
        for row_index, parts in enumerate(rows):
            for column, value in enumerate(parts):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.installed_table.setItem(row_index, column, item)
        self.installed_status.setText(f"{len(rows)} recorded install(s).")

    def populate_history_table(self, output: str | None = None) -> None:
        if isinstance(output, str):
            self.history_rows = parse_history_output(output)

        selected_operation = str(self.history_filter_combo.currentData() or "")
        rows = [
            row
            for row in self.history_rows
            if not selected_operation or row.get("operation") == selected_operation
        ]
        self.filtered_history_rows = rows
        self.history_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("operation", ""),
                row.get("record_id", ""),
                row.get("target", ""),
                row.get("backend", ""),
                row.get("result", ""),
                row.get("timestamp", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.history_table.setItem(row_index, column, item)

        if rows:
            self.history_status.setText(f"{len(rows)} history record(s).")
            if self.history_table.currentRow() < 0:
                self.history_table.setCurrentCell(0, 0)
            else:
                self.update_history_detail()
        else:
            self.history_status.setText("No history records for this filter.")
            self.update_history_detail()

    def update_history_detail(self) -> None:
        row = self.history_table.currentRow()
        entry = self.filtered_history_rows[row] if 0 <= row < len(self.filtered_history_rows) else None
        self.history_detail.setPlainText(format_history_detail(entry, str(operation_log_dir())))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mpm")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--self-test", action="store_true", help="create the Qt window and exit")
    parser.add_argument("--self-test-drop-target", help="set a target through the drop handler and exit")
    parser.add_argument("--self-test-infer-doctor", action="store_true", help="exercise install-output doctor inference")
    parser.add_argument("--self-test-catalog", action="store_true", help="load catalog and print entry count")
    parser.add_argument("--self-test-catalog-validate", action="store_true", help="strictly validate catalog and print entry count")
    parser.add_argument("--self-test-catalog-detail", action="store_true", help="format the Firefox catalog detail and exit")
    parser.add_argument("--self-test-doctor-summary", action="store_true", help="parse a sample doctor result and exit")
    parser.add_argument("--self-test-preflight-summary", action="store_true", help="format a sample install preflight and exit")
    parser.add_argument("--self-test-uninstall-preflight", action="store_true", help="format a sample uninstall preflight and exit")
    parser.add_argument("--self-test-uninstall-control", action="store_true", help="verify the Installed tab exposes uninstall")
    parser.add_argument("--self-test-history-control", action="store_true", help="verify the History tab opens read-only")
    parser.add_argument("--self-test-history-format", action="store_true", help="parse and format sample mpm-pkg history output")
    parser.add_argument("--self-test-universal-search", metavar="QUERY", help="run federated catalog search and exit")
    parser.add_argument("--self-test-llm-advisor", metavar="QUERY", help="run optional advisor over federated search and exit")
    parser.add_argument("--self-test-log-dir", action="store_true", help="print and create the operation log directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or []))
    if args.version:
        print(VERSION)
        return 0
    if args.self_test_infer_doctor:
        print(infer_doctor_target("==> Exporting cursor from mpm-fedora-apps", "/tmp/vendor.rpm", "") or "")
        return 0
    if args.self_test_catalog or args.self_test_catalog_validate:
        entries, path, error = load_catalog_entries()
        if error and not entries:
            print(error, file=sys.stderr)
            return 1
        print(f"{len(entries)} {path}")
        return 0
    if args.self_test_catalog_detail:
        entries, _path, error = load_catalog_entries()
        if error and not entries:
            print(error, file=sys.stderr)
            return 1
        entry = next((item for item in entries if item.get("target") == "org.mozilla.firefox"), entries[0] if entries else None)
        print(format_catalog_detail(entry))
        return 0
    if args.self_test_doctor_summary:
        sample = "\n".join(
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
        print(format_doctor_summary(parse_doctor_summary(sample)))
        return 0
    if args.self_test_preflight_summary:
        explain_output = "\n".join(
            [
                "target: org.mozilla.firefox",
                "source: name",
                "kind: name",
                "backend: flatpak",
                "reason: Flatpak backend forced: install through user Flathub/Flatpak for isolated GUI apps.",
            ]
        )
        print(
            format_preflight_confirmation(
                "org.mozilla.firefox",
                "flatpak",
                explain_output,
                "mpm-pkg install org.mozilla.firefox --backend flatpak",
            )
        )
        return 0
    if args.self_test_uninstall_preflight:
        dry_run_output = "\n".join(
            [
                "uninstall-plan:",
                "record-id: 1",
                "target: org.mozilla.firefox",
                "backend: flatpak",
                "kind: name",
                "source: name",
                "app-id: org.mozilla.firefox",
                "data-policy: user data is preserved; package-managed files only",
                "commands:",
                "  - flatpak --user uninstall -y org.mozilla.firefox",
            ]
        )
        print(format_uninstall_confirmation(dry_run_output))
        return 0
    if args.self_test_history_format:
        sample = "\n".join(
            [
                '{"operation":"install","record_id":1,"install_id":1,"target":"org.mozilla.firefox","backend":"flatpak","result":"recorded","timestamp":"2026-05-16 10:00:00","app_id":"org.mozilla.firefox"}',
                '{"operation":"uninstall","record_id":2,"install_id":1,"target":"org.mozilla.firefox","backend":"flatpak","result":"success","timestamp":"2026-05-16 10:05:00","detail":"uninstall-plan:\\ncommands:\\n  - flatpak --user uninstall -y org.mozilla.firefox"}',
                '{"operation":"repair","record_id":3,"target":"OpenCode","backend":"mpm-ubuntu-apps","result":"recorded","timestamp":"2026-05-16 10:10:00","detail":"patch exported launcher"}',
            ]
        )
        rows = parse_history_output(sample)
        print(format_history_detail(rows[1], str(operation_log_dir())))
        return 0
    if args.self_test_universal_search:
        provider_list = default_catalog_providers()
        result = search_all(args.self_test_universal_search, provider_list, limit_per_source=8)
        providers = {provider.provider_id: provider for provider in provider_list if hasattr(provider, "provider_id")}
        for status in result.provider_statuses:
            aliases = ",".join(getattr(providers.get(status.provider), "source_aliases", []))
            print(
                f"provider: {status.provider}\tstate: {status.state}\t"
                f"count: {status.result_count}\taliases: {aliases}\tmessage: {status.message}"
            )
        for route in result.routes:
            box = str(route.raw.get("box", ""))
            distro = str(route.raw.get("distro_family", ""))
            package_manager = str(route.raw.get("package_manager", ""))
            artifact_format = str(route.raw.get("artifact_format", ""))
            trust = str(route.raw.get("trust_level", "") or route.raw.get("trust", ""))
            update_policy = str(route.raw.get("update_policy", ""))
            uninstall_policy = str(route.raw.get("uninstall_policy", ""))
            print(
                f"route: {route.route_id}\tbackend: {route.backend}\tinstall-backend: {route.install_backend}\tsource: {route.source}\t"
                f"target: {route.install_target}\tbox: {box}\t"
                f"distro: {distro}\tpm: {package_manager}\t"
                f"artifact: {artifact_format}\ttrust: {trust}\t"
                f"updates: {update_policy}\tuninstall: {uninstall_policy}\t"
                f"host: {'yes' if route.requires_host_mutation else 'no'}\t"
                f"container: {'yes' if route.requires_container else 'no'}\t"
                f"snapshot: {'yes' if route.requires_snapshot else 'no'}\t"
                f"community: {'yes' if route.is_community else 'no'}\t"
                f"badges: {','.join(route.badges)}\t"
                f"warnings: {' | '.join(route.warnings)}"
            )
        for group in result.groups:
            print(
                f"group: {group.display_name}\trecommended: {group.recommended_route_id}\t"
                f"routes: {len(group.routes)}\tconfidence: {group.confidence:.2f}\t"
                f"reason: {group.recommendation_reason}"
            )
        return 0
    if args.self_test_llm_advisor:
        provider_list = default_catalog_providers()
        result = search_all(args.self_test_llm_advisor, provider_list, limit_per_source=8)
        print(format_advisor_response(advise_search_result(result)))
        return 0
    if args.self_test_log_dir:
        path = operation_log_dir()
        path.mkdir(parents=True, exist_ok=True)
        print(path)
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MPMWindow()
    if args.self_test_drop_target:
        window.apply_dropped_target(args.self_test_drop_target, run_detect=False)
        print(window.target_edit.text())
        return 0
    if args.self_test:
        window.show()
        app.processEvents()
        return 0
    if args.self_test_uninstall_control:
        print(window.uninstall_button.text())
        return 0
    if args.self_test_history_control:
        labels = [window.tabs.tabText(index) for index in range(window.tabs.count())]
        print("History" if "History" in labels and window.history_detail.isReadOnly() else "missing")
        return 0

    window.show()
    return int(app.exec())
