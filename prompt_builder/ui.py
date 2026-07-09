from __future__ import annotations

import logging
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QAction, QFontDatabase, QIcon, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QFrame,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core import (
    BuildRequest,
    BuildResult,
    BuildSettings,
    BuildError,
    DEFAULT_LARGE_FILE_THRESHOLD,
    DEFAULT_MAX_DEPENDENCY_DEPTH,
    DEFAULT_TRUNCATION_SIZE,
    PromptFields,
    PromptTemplateMode,
    LLM_TASK_TEMPLATES,
    TreeNode,
    build_prompt_bundle,
    serialize_bundle,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionState:
    input_paths: list[str]
    prompt: dict
    settings: dict
    file_overrides: dict[str, str]


class BuildWorker(QObject):
    progress = Signal(str, int, int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, request: BuildRequest) -> None:
        super().__init__()
        self._request = request
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        logger.info("Starting background build for %d input path(s)", len(self._request.input_paths))
        try:
            result = build_prompt_bundle(
                self._request,
                progress=lambda message, current, total: self.progress.emit(message, current, total),
                should_cancel=lambda: self._cancelled,
            )
            if self._cancelled:
                logger.info("Background build cancelled")
                self.cancelled.emit()
                return
            logger.info("Background build finished successfully")
            self.finished.emit(result)
        except BuildError as exc:
            if "cancelled" in str(exc).lower():
                logger.info("Background build cancelled")
                self.cancelled.emit()
            else:
                logger.exception("Background build failed")
                self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive Qt boundary
            logger.exception("Unexpected background build failure")
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, default_paths: list[str] | None = None, verbose: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Prompt Builder")
        self.resize(1500, 950)
        self.setAcceptDrops(True)
        self.verbose = verbose

        self.input_paths: list[str] = list(dict.fromkeys(default_paths or []))
        self.file_overrides: dict[str, str] = {}
        self.workspace = None
        self.current_result: BuildResult | None = None
        self.selected_file_id: str | None = None
        self._worker_thread: QThread | None = None
        self._worker: BuildWorker | None = None
        self._pending_rebuild = False
        self._refreshing_tree = False
        self._refreshing_table = False
        self._file_icon_cache: dict[str, QIcon] = {}
        self._material_icon_dir = Path(__file__).resolve().parent / "icons" / "material-icon-theme" / "icons"

        self._build_menu_bar()
        self._build_ui()
        self._sync_settings_controls()
        if self.input_paths:
            self._log("Loaded %d startup path(s)", len(self.input_paths))
            self.request_rebuild()

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        self.add_file_action = QAction("Add File...", self)
        self.add_folder_action = QAction("Add Folder...", self)
        self.refresh_action = QAction("Refresh", self)
        self.copy_action = QAction("Copy JSON", self)
        self.save_session_action = QAction("Save Session", self)
        self.load_session_action = QAction("Load Session", self)
        self.export_action = QAction("Export JSON...", self)
        self.reset_action = QAction("Reset", self)
        self.settings_action = QAction("Settings", self)

        self.save_session_action.setShortcut(QKeySequence.StandardKey.Save)
        self.load_session_action.setShortcut(QKeySequence("Ctrl+L"))

        for action in [
            self.add_file_action,
            self.add_folder_action,
            self.refresh_action,
            self.copy_action,
            self.save_session_action,
            self.load_session_action,
            self.export_action,
        ]:
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.settings_action)
        file_menu.addAction(self.reset_action)

    def _log(self, message: str, *args: object) -> None:
        if self.verbose:
            logger.info(message, *args)

    def _apply_default_settings(self) -> None:
        self.max_depth_spin.setValue(DEFAULT_MAX_DEPENDENCY_DEPTH if DEFAULT_MAX_DEPENDENCY_DEPTH is not None else 0)
        self.large_file_spin.setValue(DEFAULT_LARGE_FILE_THRESHOLD)
        self.truncation_spin.setValue(DEFAULT_TRUNCATION_SIZE)
        self.project_root_edit.clear()
        self.import_roots_edit.clear()
        self.include_hidden_check.setChecked(False)
        self.include_unchecked_folder_check.setChecked(False)
        self.show_skipped_dependencies_check.setChecked(False)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #0f172a;
            }
            QWidget#rootCanvas {
                background: #0f172a;
                color: #e2e8f0;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QLabel, QGroupBox, QStatusBar {
                color: #e2e8f0;
            }
            QMenuBar {
                background: #0f172a;
                color: #e2e8f0;
                padding: 4px;
            }
            QMenuBar::item:selected {
                background: #1e293b;
                border-radius: 6px;
            }
            QMenu {
                background: #111827;
                color: #e5e7eb;
                border: 1px solid rgba(148, 163, 184, 0.22);
            }
            QMenu::item:selected {
                background: #0ea5e9;
            }
            QFrame#heroCard, QFrame#card {
                background: rgba(15, 23, 42, 0.88);
                border: 1px solid rgba(148, 163, 184, 0.18);
                border-radius: 18px;
            }
            QLabel#titleLabel {
                font-size: 24px;
                font-weight: 700;
                color: #f8fafc;
            }
            QLabel#subtitleLabel, QLabel#inputSummaryLabel, QLabel#hintLabel {
                color: #94a3b8;
            }
            QLabel#sectionLabel {
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.04em;
                color: #cbd5e1;
                text-transform: uppercase;
            }
            QLabel#resolvedPrompt {
                padding: 12px;
                background: rgba(30, 41, 59, 0.92);
                border-radius: 12px;
                border: 1px solid rgba(148, 163, 184, 0.14);
                color: #cbd5e1;
            }
            QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QTreeWidget, QTableWidget {
                background: #111827;
                color: #e5e7eb;
                border: 1px solid rgba(148, 163, 184, 0.22);
                border-radius: 10px;
                padding: 8px;
                selection-background-color: #0ea5e9;
            }
            QComboBox QAbstractItemView {
                background: #111827;
                color: #f8fafc;
                border: 1px solid rgba(148, 163, 184, 0.22);
                selection-background-color: #0ea5e9;
                selection-color: white;
            }
            QStatusBar {
                background: #0f172a;
            }
            QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton {
                background: #1f2937;
                color: #e5e7eb;
                border: 1px solid rgba(148, 163, 184, 0.2);
                border-radius: 10px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background: #334155;
            }
            QPushButton:pressed {
                background: #0f172a;
            }
            QPushButton#primaryAction {
                background: #0ea5e9;
                color: white;
                border: none;
                font-weight: 700;
            }
            QPushButton#primaryAction:hover {
                background: #0284c7;
            }
            QLabel#overviewSummary {
                padding: 16px;
                background: rgba(30, 41, 59, 0.92);
                border: 1px solid rgba(148, 163, 184, 0.14);
                border-radius: 14px;
                color: #e2e8f0;
                line-height: 1.4;
                font-size: 11pt;
            }
            QTreeWidget::item, QTableWidget::item {
                padding: 6px;
            }
            QHeaderView::section {
                background: #1e293b;
                color: #cbd5e1;
                padding: 8px;
                border: none;
            }
            QTabWidget::pane {
                border: 1px solid rgba(148, 163, 184, 0.18);
                border-radius: 12px;
                top: -1px;
                background: rgba(15, 23, 42, 0.88);
            }
            QTabBar::tab {
                background: #1e293b;
                color: #cbd5e1;
                padding: 8px 14px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background: #0f172a;
                color: white;
            }
            QProgressBar {
                background: #1e293b;
                border: 1px solid rgba(148, 163, 184, 0.18);
                border-radius: 8px;
                text-align: center;
                color: #e2e8f0;
            }
            QProgressBar::chunk {
                background: #0ea5e9;
                border-radius: 8px;
            }
            """
        )

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("rootCanvas")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("heroCard")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(14)

        title_stack = QVBoxLayout()
        title = QLabel("Prompt Builder")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Build a lean, repo-aware prompt bundle from files or folders.")
        subtitle.setObjectName("subtitleLabel")
        self.input_summary_label = QLabel("No inputs loaded yet.")
        self.input_summary_label.setObjectName("inputSummaryLabel")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        title_stack.addWidget(self.input_summary_label)

        button_row = QHBoxLayout()
        self.settings_button = QPushButton("Settings")
        self.reset_button = QPushButton("Reset")
        self.copy_button = QPushButton("Copy JSON")
        for button in [
            self.settings_button,
            self.reset_button,
            self.copy_button,
        ]:
            button_row.addWidget(button)
        button_row.addStretch(1)
        self.copy_button.setObjectName("primaryAction")
        header_layout.addLayout(title_stack, 2)
        header_layout.addLayout(button_row, 1)

        self.settings_panel = QFrame()
        self.settings_panel.setObjectName("card")
        self.settings_panel.setVisible(False)
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(18, 18, 18, 18)
        settings_layout.setSpacing(12)
        settings_header = QHBoxLayout()
        settings_title = QLabel("Settings")
        settings_title.setObjectName("sectionLabel")
        self.reset_settings_button = QPushButton("Reset Defaults")
        self.reset_settings_button.clicked.connect(self._reset_settings_defaults)
        settings_header.addWidget(settings_title)
        settings_header.addStretch(1)
        settings_header.addWidget(self.reset_settings_button)
        settings_layout.addLayout(settings_header)

        form = QFormLayout()
        self.project_root_edit = QLineEdit()
        self.import_roots_edit = QLineEdit()
        self.max_depth_spin = QSpinBox()
        self.max_depth_spin.setRange(0, 99)
        self.max_depth_spin.setToolTip("Use 0 for unlimited depth.")
        self.large_file_spin = QSpinBox()
        self.large_file_spin.setRange(0, 50_000_000)
        self.truncation_spin = QSpinBox()
        self.truncation_spin.setRange(0, 50_000_000)
        self.include_hidden_check = QPushButton("Include hidden files")
        self.include_hidden_check.setCheckable(True)
        self.include_unchecked_folder_check = QPushButton("Keep unchecked folder files in JSON")
        self.include_unchecked_folder_check.setCheckable(True)
        self.show_skipped_dependencies_check = QPushButton("Show skipped dependencies")
        self.show_skipped_dependencies_check.setCheckable(True)
        form.addRow("Project root override", self.project_root_edit)
        form.addRow("Import root overrides", self.import_roots_edit)
        form.addRow("Max dependency depth", self.max_depth_spin)
        form.addRow("Large file threshold", self.large_file_spin)
        form.addRow("Truncation size", self.truncation_spin)
        form.addRow(self.include_hidden_check)
        form.addRow(self.include_unchecked_folder_check)
        form.addRow(self.show_skipped_dependencies_check)
        settings_layout.addLayout(form)

        root_layout.addWidget(header)
        root_layout.addWidget(self.settings_panel)

        splitter = QSplitter(Qt.Horizontal)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        self.views = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Context tree", "Type", "Size"])
        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragEnabled(True)
        self.tree.installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_context_menu)

        flat_container = QWidget()
        flat_layout = QVBoxLayout(flat_container)
        flat_layout.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search files")
        self.search_edit.textChanged.connect(self.refresh_flat_table)
        self.flat_table = QTableWidget(0, 6)
        self.flat_table.setHorizontalHeaderLabels(["File", "Type", "Mode", "Size", "Included", "Context"])
        self.flat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.flat_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.flat_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.flat_table.horizontalHeader().setStretchLastSection(True)
        self.flat_table.setColumnWidth(0, 560)
        self.flat_table.setColumnWidth(1, 160)
        self.flat_table.setColumnWidth(2, 110)
        self.flat_table.setColumnWidth(4, 90)
        self.flat_table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.flat_table.itemChanged.connect(self.on_table_item_changed)
        self.flat_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.flat_table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.flat_table.installEventFilter(self)
        flat_layout.addWidget(self.search_edit)
        flat_layout.addWidget(self.flat_table, 1)

        self.views.addTab(self.tree, "Tree")
        self.views.addTab(flat_container, "Flat")
        left_layout.addWidget(self.views, 1)

        self.preview_tabs = QTabWidget()
        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        self.detail_label = QLabel("Select a file to inspect it here.")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        preview_layout.addWidget(self.detail_label)
        preview_layout.addWidget(self.preview, 1)
        self.preview_tabs.addTab(preview_page, "Preview")

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        self.bundle_summary = QLabel("Bundle summary will appear here after a scan.")
        self.bundle_summary.setObjectName("overviewSummary")
        self.bundle_summary.setWordWrap(True)
        self.bundle_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        overview_layout.addWidget(self.bundle_summary, 1)
        self.preview_tabs.addTab(overview_page, "Overview")

        task_card = QFrame()
        task_card.setObjectName("card")
        task_layout = QVBoxLayout(task_card)
        task_layout.setContentsMargins(18, 18, 18, 18)
        task_layout.setSpacing(12)
        task_heading = QLabel("LLM Task")
        task_heading.setObjectName("sectionLabel")
        self.system_template_combo = QComboBox()
        for template_id in list(LLM_TASK_TEMPLATES.keys()) + ["custom"]:
            self.system_template_combo.addItem(template_id.replace("_", " ").title(), template_id)
        self.system_template_combo.currentIndexChanged.connect(self._on_system_template_changed)
        self.custom_system_prompt = QPlainTextEdit()
        self.custom_system_prompt.setPlaceholderText("Write a custom LLM task here.")
        self.custom_system_prompt.setMinimumHeight(130)
        self.custom_system_prompt.textChanged.connect(self._on_prompt_fields_changed)
        resolved_label = QLabel("Resolved LLM Task")
        resolved_label.setObjectName("sectionLabel")
        self.system_preview = QLabel()
        self.system_preview.setWordWrap(True)
        self.system_preview.setObjectName("resolvedPrompt")
        task_layout.addWidget(task_heading)
        task_layout.addWidget(self.system_template_combo)
        task_layout.addWidget(self.custom_system_prompt, 2)
        task_layout.addWidget(resolved_label)
        task_layout.addWidget(self.system_preview, 1)
        task_layout.addStretch(1)

        splitter.addWidget(left_container)
        splitter.addWidget(self.preview_tabs)
        splitter.addWidget(task_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([420, 560, 360])
        root_layout.addWidget(splitter, 1)

        prompt_card = QFrame()
        prompt_card.setObjectName("card")
        prompt_layout = QVBoxLayout(prompt_card)
        prompt_layout.setContentsMargins(18, 18, 18, 18)
        prompt_layout.setSpacing(12)
        prompt_heading = QLabel("User Prompt")
        prompt_heading.setObjectName("sectionLabel")
        self.user_prompt_edit = QPlainTextEdit()
        self.user_prompt_edit.setPlaceholderText("Describe the task you want the LLM to perform. This is placed at the bottom like a traditional chat prompt.")
        self.user_prompt_edit.setMinimumHeight(120)
        self.user_prompt_edit.textChanged.connect(self._on_prompt_fields_changed)
        self.disk_note = QLabel("Files are read from disk, so save files before importing or dragging them in.")
        self.disk_note.setObjectName("hintLabel")
        prompt_layout.addWidget(prompt_heading)
        prompt_layout.addWidget(self.user_prompt_edit)
        prompt_layout.addWidget(self.disk_note)
        root_layout.addWidget(prompt_card)

        footer = QHBoxLayout()
        self.status_label = QLabel("Ready.")
        self.token_count_label = QLabel("Estimated JSON tokens: 0")
        self.token_count_label.setObjectName("hintLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_build)
        footer.addWidget(self.status_label, 3)
        footer.addWidget(self.token_count_label, 2)
        footer.addWidget(self.progress_bar, 2)
        footer.addWidget(self.cancel_button)
        root_layout.addLayout(footer)

        self.add_file_action.triggered.connect(lambda: self.add_files())
        self.add_folder_action.triggered.connect(lambda: self.add_folder())
        self.refresh_action.triggered.connect(lambda: self.request_rebuild())
        self.copy_action.triggered.connect(lambda: self.copy_json())
        self.save_session_action.triggered.connect(lambda: self.save_session())
        self.load_session_action.triggered.connect(lambda: self.load_session())
        self.export_action.triggered.connect(lambda: self.export_json())
        self.reset_action.triggered.connect(lambda: self.reset_session())
        self.settings_action.triggered.connect(lambda: self.toggle_settings_panel())
        self.settings_button.clicked.connect(self.toggle_settings_panel)
        self.reset_button.clicked.connect(self.reset_session)
        self.copy_button.clicked.connect(self.copy_json)
        self.show_skipped_dependencies_check.clicked.connect(self._on_show_skipped_dependencies_changed)

        self._apply_default_settings()
        self._apply_styles()
        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("Ready")

    def _sync_settings_controls(self) -> None:
        self._set_system_template_preview()
        self._update_input_summary()
        self._update_token_count()

    def _update_input_summary(self) -> None:
        count = len(self.input_paths)
        if count == 0:
            self.input_summary_label.setText("No inputs loaded yet.")
        elif count == 1:
            self.input_summary_label.setText(f"1 input loaded: {self.input_paths[0]}")
        else:
            self.input_summary_label.setText(f"{count} inputs loaded.")

    def toggle_settings_panel(self) -> None:
        self.settings_panel.setVisible(not self.settings_panel.isVisible())
        self.settings_button.setText("Hide Settings" if self.settings_panel.isVisible() else "Settings")
        self.settings_action.setText("Hide Settings" if self.settings_panel.isVisible() else "Settings")
        self._log("Settings panel %s", "opened" if self.settings_panel.isVisible() else "hidden")

    def _on_show_skipped_dependencies_changed(self) -> None:
        self.refresh_tree()

    def _reset_settings_defaults(self) -> None:
        self._apply_default_settings()
        self._log("Reset settings to defaults")

    def _set_system_template_preview(self) -> None:
        template_id = self.system_template_combo.currentData()
        if template_id == "custom":
            self.custom_system_prompt.setEnabled(True)
            preview = self.custom_system_prompt.toPlainText().strip() or "Custom LLM task mode."
        else:
            self.custom_system_prompt.setEnabled(False)
            preview = LLM_TASK_TEMPLATES.get(template_id, LLM_TASK_TEMPLATES["code_editing"])
        self.system_preview.setText(preview)

    def _on_system_template_changed(self, *_: object) -> None:
        self._on_prompt_fields_changed()

    def _on_prompt_fields_changed(self) -> None:
        self._set_system_template_preview()
        if self.workspace is None:
            self._update_token_count()
            return
        self._sync_current_bundle()
        if self.current_result is not None:
            self._show_bundle_summary(self.current_result)

    def current_prompt_fields(self) -> PromptFields:
        template_id = str(self.system_template_combo.currentData())
        mode = "custom" if template_id == "custom" else "template"
        return PromptFields(
            llm_task=PromptTemplateMode(
                mode=mode,
                template_id=template_id if template_id != "custom" else "code_editing",
                custom_text=self.custom_system_prompt.toPlainText(),
            ),
            user_prompt=self.user_prompt_edit.toPlainText(),
        )

    def current_settings(self) -> BuildSettings:
        depth = self.max_depth_spin.value()
        return BuildSettings(
            max_dependency_depth=None if depth == 0 else depth,
            large_file_threshold=self.large_file_spin.value(),
            truncation_size=self.truncation_spin.value(),
            project_root_override=self.project_root_edit.text().strip(),
            import_root_overrides=[part.strip() for part in self.import_roots_edit.text().split(",") if part.strip()],
            include_unchecked_folder_files=self.include_unchecked_folder_check.isChecked(),
            include_hidden=self.include_hidden_check.isChecked(),
        )

    def current_request(self) -> BuildRequest:
        return BuildRequest(
            input_paths=list(self.input_paths),
            prompt=self.current_prompt_fields(),
            settings=self.current_settings(),
            file_overrides=dict(self.file_overrides),
        )

    def reset_session(self) -> None:
        if self._worker is not None:
            self._pending_rebuild = False
            self.cancel_build()
        self.input_paths.clear()
        self.file_overrides.clear()
        self.workspace = None
        self.current_result = None
        self.selected_file_id = None
        self.user_prompt_edit.clear()
        self.custom_system_prompt.clear()
        default_template_index = self.system_template_combo.findData("code_editing")
        if default_template_index >= 0:
            self.system_template_combo.setCurrentIndex(default_template_index)
        self._apply_default_settings()
        self.tree.clear()
        self.flat_table.setRowCount(0)
        self.preview.clear()
        self.detail_label.setText("Add a file or folder to begin.")
        self.bundle_summary.clear()
        self._update_input_summary()
        self._update_token_count(0, 0)
        self.status_label.setText("Ready.")
        self.statusBar().showMessage("Reset complete")

    def request_rebuild(self) -> None:
        if not self.input_paths:
            self.workspace = None
            self.current_result = None
            self.tree.clear()
            self.flat_table.setRowCount(0)
            self.preview.clear()
            self.detail_label.setText("Add a file or folder to begin.")
            self.bundle_summary.clear()
            self._update_token_count()
            self.status_label.setText("No input paths.")
            self.statusBar().showMessage("No input paths")
            return
        if self._worker_thread is not None:
            self._pending_rebuild = True
            self._log("Rebuild requested while scan is active; cancelling current scan first")
            self.cancel_build()
            return
        self._log("Starting rebuild for %d input path(s)", len(self.input_paths))
        self.start_rebuild()

    def start_rebuild(self) -> None:
        request = self.current_request()
        self._worker_thread = QThread(self)
        self._worker = BuildWorker(request)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.on_build_progress)
        self._worker.finished.connect(self.on_build_finished)
        self._worker.failed.connect(self.on_build_failed)
        self._worker.cancelled.connect(self.on_build_cancelled)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker.cancelled.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Scanning...")
        self.statusBar().showMessage("Scanning project...")
        self._log(
            "Scan settings: depth=%s, large_file_threshold=%s, truncation_size=%s, project_root_override=%r, import_root_overrides=%r",
            self.current_settings().max_dependency_depth,
            self.current_settings().large_file_threshold,
            self.current_settings().truncation_size,
            self.current_settings().project_root_override,
            self.current_settings().import_root_overrides,
        )
        self._set_controls_enabled(False)
        self._worker_thread.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for action in [
            self.add_file_action,
            self.add_folder_action,
            self.refresh_action,
            self.copy_action,
            self.save_session_action,
            self.load_session_action,
            self.export_action,
            self.reset_action,
            self.settings_action,
        ]:
            action.setEnabled(enabled)
        for widget in [
            self.settings_button,
            self.reset_button,
            self.copy_button,
            self.reset_settings_button,
            self.project_root_edit,
            self.import_roots_edit,
            self.max_depth_spin,
            self.large_file_spin,
            self.truncation_spin,
            self.include_hidden_check,
            self.include_unchecked_folder_check,
            self.show_skipped_dependencies_check,
            self.user_prompt_edit,
            self.system_template_combo,
            self.custom_system_prompt,
            self.search_edit,
            self.tree,
            self.flat_table,
        ]:
            widget.setEnabled(enabled)

    def _cleanup_worker(self) -> None:
        self._worker = None
        self._worker_thread = None
        self._set_controls_enabled(True)
        self.progress_bar.setVisible(False)
        if self._pending_rebuild:
            self._pending_rebuild = False
            self.start_rebuild()

    def cancel_build(self) -> None:
        if self._worker is not None:
            self._log("Cancelling active scan")
            self._worker.cancel()
            self.status_label.setText("Cancelling...")
            self.statusBar().showMessage("Cancelling scan...")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if watched in {self.tree, self.flat_table} and event.type() == QEvent.Type.KeyPress:
            key_event = event if isinstance(event, QKeyEvent) else None
            if key_event is not None and key_event.key() == Qt.Key_Delete:
                self.remove_selected()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def on_build_progress(self, message: str, current: int, total: int) -> None:
        self._log("%s (%d/%d)", message, current, total)
        self.status_label.setText(message)
        self.statusBar().showMessage(message)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)

    def on_build_finished(self, result: BuildResult) -> None:
        self._log("Scan complete: %d tracked file(s), %d dependency edge(s)", len(result.bundle["files"]), len(result.bundle["dependency_graph"]))
        self.workspace = result.workspace
        self.current_result = result
        self._sync_current_bundle()
        self._refresh_all_views()
        self._show_bundle_summary(result)
        self.status_label.setText("Scan complete.")
        self.statusBar().showMessage("Scan complete")

    def on_build_failed(self, message: str) -> None:
        self._log("Scan failed: %s", message)
        QMessageBox.warning(self, "Build failed", message)
        self.status_label.setText("Build failed.")
        self.statusBar().showMessage(f"Build failed: {message}")

    def on_build_cancelled(self) -> None:
        self._log("Scan cancelled")
        self.status_label.setText("Cancelled.")
        self.statusBar().showMessage("Scan cancelled")

    def _show_bundle_summary(self, result: BuildResult) -> None:
        bundle = result.bundle
        file_count = len(bundle["files"])
        graph_groups = len(bundle["dependency_graph"])
        linked_files = sum(len(item["includes"]) for item in bundle["dependency_graph"])
        json_bytes = len(result.json_text.encode("utf-8"))
        json_chars = len(result.json_text)
        estimated_tokens = self._estimate_tokens(result.json_text)
        self._update_token_count(estimated_tokens, json_bytes)
        self.bundle_summary.setText(
            f"""
            <h2 style="margin: 0 0 12px 0;">Bundle overview</h2>
            <table cellspacing="0" cellpadding="6">
              <tr><td><b>Files</b></td><td>{file_count:,}</td></tr>
              <tr><td><b>Dependency groups</b></td><td>{graph_groups:,}</td></tr>
              <tr><td><b>Linked files</b></td><td>{linked_files:,}</td></tr>
              <tr><td><b>JSON characters</b></td><td>{json_chars:,}</td></tr>
              <tr><td><b>JSON bytes</b></td><td>{json_bytes:,}</td></tr>
              <tr><td><b>Estimated JSON tokens</b></td><td>{estimated_tokens:,}</td></tr>
              <tr><td><b>System prompt characters</b></td><td>{len(bundle["system_prompt"]):,}</td></tr>
              <tr><td><b>LLM task characters</b></td><td>{len(bundle["llm_task"]):,}</td></tr>
              <tr><td><b>User prompt characters</b></td><td>{len(bundle["user_prompt"]):,}</td></tr>
            </table>
            """
        )

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)

    def _update_token_count(self, estimated_tokens: int | None = None, json_bytes: int | None = None) -> None:
        if estimated_tokens is None:
            if self.current_result is None:
                estimated_tokens = 0
                json_bytes = 0 if json_bytes is None else json_bytes
            else:
                estimated_tokens = self._estimate_tokens(self.current_result.json_text)
                json_bytes = len(self.current_result.json_text.encode("utf-8"))
        elif json_bytes is None:
            json_bytes = len(self.current_result.json_text.encode("utf-8")) if self.current_result else 0
        self.token_count_label.setText(f"Estimated JSON tokens: {estimated_tokens:,}")
        self.token_count_label.setToolTip(
            f"Approximate token count from serialized JSON size ({json_bytes:,} bytes)."
        )

    def _refresh_all_views(self) -> None:
        self._sync_current_bundle()
        self.refresh_tree()
        self.refresh_flat_table()
        if self.current_result is not None:
            self._show_bundle_summary(self.current_result)
        if self.selected_file_id and self.workspace and self.selected_file_id in self.workspace.files:
            self.show_record(self.selected_file_id)

    def _sync_current_bundle(self) -> None:
        if self.workspace is None:
            self.current_result = None
            return
        try:
            bundle = self.workspace.to_bundle(self.current_prompt_fields())
            self.current_result = BuildResult(
                workspace=self.workspace,
                bundle=bundle,
                json_text=serialize_bundle(bundle),
            )
            self._update_token_count()
        except BuildError:
            return

    def refresh_tree(self) -> None:
        if self.workspace is None:
            self.tree.clear()
            return
        self._log("Refreshing tree with %d top-level node(s)", len(self.workspace.tree_roots))
        self._refreshing_tree = True
        try:
            self.tree.clear()
            for node in self.workspace.tree_roots:
                item = self._build_tree_item(node)
                if item is None:
                    continue
                self.tree.addTopLevelItem(item)
                item.setExpanded(True)
            self.tree.resizeColumnToContents(0)
        finally:
            self._refreshing_tree = False

    def _should_show_tree_node(self, node: TreeNode) -> bool:
        if node.kind == "skipped" and not self.show_skipped_dependencies_check.isChecked():
            return False
        if node.file_id:
            return True
        return any(self._should_show_tree_node(child) for child in node.children) if node.children else True

    def _build_tree_item(self, node: TreeNode) -> QTreeWidgetItem | None:
        if not self._should_show_tree_node(node):
            return None
        item = QTreeWidgetItem([node.label, node.kind, ""])
        record = None
        if node.file_id:
            item.setData(0, Qt.UserRole, node.file_id)
            if self.workspace and node.file_id in self.workspace.files:
                record = self.workspace.files[node.file_id]
                item.setCheckState(0, Qt.Checked if record.included else Qt.Unchecked)
                item.setText(1, record.context_type)
                item.setText(2, self._format_size(record.size_bytes))
                self._style_item(item, record)
        else:
            item.setData(0, Qt.UserRole, None)
        for child in node.children:
            child_item = self._build_tree_item(child)
            if child_item is not None:
                item.addChild(child_item)
        if node.kind == "folder":
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        elif node.kind == "skipped":
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
        elif record is not None:
            item.setIcon(0, self._icon_for_record(record))
        else:
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        return item

    def _icon_from_path(self, icon_path: Path) -> QIcon | None:
        cache_key = str(icon_path)
        if cache_key in self._file_icon_cache:
            return self._file_icon_cache[cache_key]

        if not icon_path.exists():
            return None

        icon = QIcon(str(icon_path))
        if icon.isNull():
            return None

        self._file_icon_cache[cache_key] = icon
        return icon

    def _material_icon_stems_for_filename(self, filename: str) -> list[str]:
        normalized = filename.lower()
        extension = Path(normalized).suffix.lower().lstrip(".")
        stems: list[str] = []

        file_name_map = {
            ".dockerignore": ["docker"],
            ".env": ["tune", "settings"],
            ".gitignore": ["git"],
            ".prettierrc": ["prettier"],
            ".python-version": ["python"],
            "docker-compose.yaml": ["docker"],
            "docker-compose.yml": ["docker"],
            "dockerfile": ["docker"],
            "makefile": ["makefile"],
            "pyproject.toml": ["python"],
            "readme": ["readme", "markdown"],
            "readme.md": ["readme", "markdown"],
            "requirements.txt": ["python"],
        }
        extension_map = {
            "bat": ["console"],
            "c": ["c"],
            "cc": ["cpp"],
            "cfg": ["settings"],
            "conf": ["settings"],
            "cpp": ["cpp"],
            "cs": ["c-sharp", "csharp"],
            "css": ["css"],
            "csv": ["table"],
            "cxx": ["cpp"],
            "dockerfile": ["docker"],
            "env": ["tune", "settings"],
            "gitignore": ["git"],
            "go": ["go"],
            "h": ["h", "c"],
            "hpp": ["hpp", "cpp"],
            "html": ["html"],
            "ini": ["settings"],
            "ipynb": ["jupyter"],
            "java": ["java"],
            "js": ["javascript"],
            "json": ["json"],
            "jsx": ["react", "javascript"],
            "md": ["markdown"],
            "mdx": ["markdown"],
            "py": ["python"],
            "pyi": ["python"],
            "qml": ["qt"],
            "rs": ["rust"],
            "rst": ["document"],
            "sh": ["console"],
            "sql": ["database"],
            "svg": ["svg"],
            "toml": ["settings", "toml"],
            "ts": ["typescript"],
            "tsx": ["react_ts", "react", "typescript"],
            "txt": ["document"],
            "ui": ["qt"],
            "xml": ["xml"],
            "yaml": ["yaml"],
            "yml": ["yaml"],
        }

        stems.extend(file_name_map.get(normalized, []))

        if normalized.startswith(".env."):
            stems.extend(["tune", "settings"])
        if normalized.startswith("docker-compose."):
            stems.append("docker")

        if extension:
            stems.extend(extension_map.get(extension, []))
            stems.append(extension)

        stems.extend(["file", "default_file"])
        return list(dict.fromkeys(stems))

    def _icon_from_material_icons(self, filename: str) -> QIcon | None:
        if not self._material_icon_dir.exists():
            self._log("Material icon directory not found: %s", self._material_icon_dir)
            return None

        for stem in self._material_icon_stems_for_filename(filename):
            for image_format in ["svg", "png"]:
                icon = self._icon_from_path(self._material_icon_dir / f"{stem}.{image_format}")
                if icon is not None:
                    return icon
        return None

    def _icon_for_record(self, record) -> QIcon:
        icon = self._icon_from_material_icons(record.filename)
        if icon is not None:
            return icon

        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _style_item(self, item: QTreeWidgetItem, record) -> None:
        if record.is_dependency:
            from PySide6.QtGui import QBrush, QColor

            for col in range(3):
                item.setForeground(col, QBrush(QColor("gray")))
        if record.source_kind == "direct_file":
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)

    def refresh_flat_table(self) -> None:
        if self.workspace is None:
            self.flat_table.setRowCount(0)
            return
        self._log("Refreshing flat list with %d file record(s)", len(self.workspace.files))
        self._refreshing_table = True
        try:
            query = self.search_edit.text().strip().lower()
            records = sorted(self.workspace.files.values(), key=lambda record: (record.repo_relative_path, record.id))
            if query:
                records = [
                    record
                    for record in records
                    if query in record.repo_relative_path.lower()
                    or query in record.filename.lower()
                    or query in record.context_type.lower()
                ]
            self.flat_table.setRowCount(len(records))
            for row, record in enumerate(records):
                self._set_table_row(row, record)
        finally:
            self._refreshing_table = False

    def _set_table_row(self, row: int, record) -> None:
        items = [
            QTableWidgetItem(record.repo_relative_path),
            QTableWidgetItem(record.context_type),
            QTableWidgetItem(record.inclusion_mode),
            QTableWidgetItem(self._format_size(record.size_bytes)),
            QTableWidgetItem(),
            QTableWidgetItem(record.source_kind),
        ]
        items[0].setIcon(self._icon_for_record(record))
        items[4].setCheckState(Qt.Checked if record.included else Qt.Unchecked)
        for col, item in enumerate(items):
            item.setData(Qt.UserRole, record.id)
            if col == 4:
                item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if record.is_dependency:
                item.setForeground(Qt.gray)
            self.flat_table.setItem(row, col, item)

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KiB"
        return f"{size_bytes / (1024 * 1024):.1f} MiB"

    def on_tree_selection_changed(self) -> None:
        if self._refreshing_tree:
            return
        item = self.tree.currentItem()
        if item is None:
            return
        file_id = item.data(0, Qt.UserRole)
        if isinstance(file_id, str):
            self.selected_file_id = file_id
            self.show_record(file_id)

    def on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._refreshing_tree or column != 0:
            return
        file_id = item.data(0, Qt.UserRole)
        if not isinstance(file_id, str) or self.workspace is None or file_id not in self.workspace.files:
            return
        record = self.workspace.files[file_id]
        new_mode = "full" if item.checkState(0) == Qt.Checked else "excluded"
        self.file_overrides[file_id] = new_mode
        record.inclusion_mode = new_mode
        record.included = new_mode != "excluded"
        self._refresh_all_views()

    def on_table_selection_changed(self) -> None:
        if self._refreshing_table:
            return
        items = self.flat_table.selectedItems()
        if not items:
            return
        file_id = items[0].data(Qt.UserRole)
        if isinstance(file_id, str):
            self.selected_file_id = file_id
            self.show_record(file_id)

    def on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing_table or item.column() != 4:
            return
        file_id = item.data(Qt.UserRole)
        if not isinstance(file_id, str):
            return
        self.selected_file_id = file_id
        self.flat_table.selectRow(item.row())
        if item.checkState() == Qt.Checked:
            self._set_file_mode(file_id, "full")
        else:
            self._set_file_mode(file_id, "excluded")

    def _show_tree_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        file_id = item.data(0, Qt.UserRole)
        if not isinstance(file_id, str):
            return
        self._show_file_context_menu(file_id, self.tree.viewport().mapToGlobal(position))

    def _show_table_context_menu(self, position) -> None:
        row = self.flat_table.rowAt(position.y())
        if row < 0:
            return
        self.flat_table.selectRow(row)
        item = self.flat_table.item(row, 0)
        file_id = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(file_id, str):
            return
        self._show_file_context_menu(file_id, self.flat_table.viewport().mapToGlobal(position))

    def _show_file_context_menu(self, file_id: str, global_position) -> None:
        self.selected_file_id = file_id
        menu = QMenu(self)
        include_full_action = menu.addAction("Include full")
        include_truncated_action = menu.addAction("Include truncated")
        exclude_action = menu.addAction("Exclude")
        menu.addSeparator()
        remove_action = menu.addAction("Remove selected")
        chosen_action = menu.exec(global_position)
        if chosen_action == include_full_action:
            self.include_full_selected()
        elif chosen_action == include_truncated_action:
            self.include_truncated_selected()
        elif chosen_action == exclude_action:
            self.exclude_selected()
        elif chosen_action == remove_action:
            self.remove_selected()

    def show_record(self, file_id: str) -> None:
        if self.workspace is None or file_id not in self.workspace.files:
            return
        record = self.workspace.files[file_id]
        self.selected_file_id = file_id
        preview_text = record.content or ""
        if not record.included:
            preview_text = preview_text or "[excluded from prompt]"
        elif record.inclusion_mode == "truncated":
            preview_text = preview_text[: min(len(preview_text), self.truncation_spin.value())]
        self.preview.setPlainText(preview_text)
        detail_lines = [
            f"File: {record.repo_relative_path}",
            f"Type: {record.context_type}",
            f"Included: {'yes' if record.included else 'no'}",
            f"Mode: {record.inclusion_mode}",
            f"Links: {len(record.dependency_target_ids)}",
        ]
        if record.truncation is not None:
            detail_lines.append(f"Truncation: {json.dumps(record.truncation)}")
        self.detail_label.setText("\n".join(detail_lines))

    def _selected_file_ids(self) -> list[str]:
        ids: list[str] = []
        if self.views.currentWidget() == self.tree:
            item = self.tree.currentItem()
            if item is not None:
                file_id = item.data(0, Qt.UserRole)
                if isinstance(file_id, str):
                    ids.append(file_id)
        else:
            items = self.flat_table.selectedItems()
            if items:
                file_id = items[0].data(Qt.UserRole)
                if isinstance(file_id, str):
                    ids.append(file_id)
        return ids

    def _set_file_mode(self, file_id: str, mode: str) -> None:
        if self.workspace is None or file_id not in self.workspace.files:
            return
        self.file_overrides[file_id] = mode
        record = self.workspace.files[file_id]
        record.inclusion_mode = mode
        record.included = mode != "excluded"
        self._refresh_all_views()

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files")
        if not paths:
            return
        self._log("Adding %d file(s)", len(paths))
        self._extend_input_paths(paths)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if not folder:
            return
        self._log("Adding folder %s", folder)
        self._extend_input_paths([folder])

    def _extend_input_paths(self, paths: list[str]) -> None:
        normalized = [str(Path(path).expanduser().resolve()) for path in paths]
        for path in normalized:
            if path not in self.input_paths:
                self.input_paths.append(path)
                self._log("Queued input path: %s", path)
        self._update_input_summary()
        self.status_label.setText(f"{len(self.input_paths)} input paths.")
        self.request_rebuild()

    def remove_selected(self) -> None:
        selected_ids = self._selected_file_ids()
        if not selected_ids or self.workspace is None:
            return

        removed_input_path = False
        removed_any = False
        normalized_inputs = {
            str(Path(path).expanduser().resolve()): path for path in self.input_paths
        }

        for file_id in selected_ids:
            record = self.workspace.files.get(file_id)
            if record is None:
                continue

            removed_any = True
            record_path = str(Path(record.absolute_path).expanduser().resolve())
            if record_path in normalized_inputs:
                self.input_paths.remove(normalized_inputs[record_path])
                self.file_overrides.pop(file_id, None)
                removed_input_path = True
            else:
                self.file_overrides[file_id] = "excluded"
                record.included = False
                record.inclusion_mode = "excluded"

        if not removed_any:
            return

        self.selected_file_id = None
        self.preview.clear()
        self.detail_label.setText("Select a file to inspect it here.")
        self._update_input_summary()

        if removed_input_path:
            self.request_rebuild()
        else:
            self._sync_current_bundle()
            self._refresh_all_views()

    def include_full_selected(self) -> None:
        for file_id in self._selected_file_ids():
            self._set_file_mode(file_id, "full")

    def include_truncated_selected(self) -> None:
        for file_id in self._selected_file_ids():
            self._set_file_mode(file_id, "truncated")

    def exclude_selected(self) -> None:
        for file_id in self._selected_file_ids():
            self._set_file_mode(file_id, "excluded")

    def copy_json(self) -> None:
        bundle = self._build_current_bundle()
        if bundle is None:
            return
        text = serialize_bundle(bundle)
        QApplication.clipboard().setText(text)
        self._log("Copied JSON bundle to clipboard (%d bytes)", len(text.encode("utf-8")))
        self.status_label.setText("JSON copied to clipboard.")
        self.statusBar().showMessage("Prompt bundle copied to clipboard")

    def export_json(self) -> None:
        bundle = self._build_current_bundle()
        if bundle is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", filter="JSON Files (*.json)")
        if not path:
            return
        Path(path).write_text(serialize_bundle(bundle), encoding="utf-8")
        self._log("Exported JSON bundle to %s", path)
        self.status_label.setText(f"Exported to {path}.")

    def _build_current_bundle(self) -> dict | None:
        if self.workspace is None:
            QMessageBox.information(self, "No bundle", "Add at least one file or folder first.")
            return None
        try:
            bundle = self.workspace.to_bundle(self.current_prompt_fields())
            return bundle
        except BuildError as exc:
            QMessageBox.warning(self, "Invalid bundle", str(exc))
            return None

    def save_session(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Session", filter="Prompt Session (*.json)")
        if not path:
            return
        state = SessionState(
            input_paths=list(self.input_paths),
            prompt={
                "llm_task": {
                    "mode": "custom" if self.system_template_combo.currentData() == "custom" else "template",
                    "template_id": self.system_template_combo.currentData(),
                    "custom_text": self.custom_system_prompt.toPlainText(),
                },
                "user_prompt": self.user_prompt_edit.toPlainText(),
            },
            settings={
                **asdict(self.current_settings()),
                "show_skipped_dependencies": self.show_skipped_dependencies_check.isChecked(),
            },
            file_overrides=dict(self.file_overrides),
        )
        Path(path).write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
        self.status_label.setText(f"Session saved to {path}.")

    def load_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", filter="Prompt Session (*.json)")
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.input_paths = list(payload.get("input_paths", []))
        prompt = payload.get("prompt", {})
        llm_task = prompt.get("llm_task", prompt.get("system", {}))
        template_id = llm_task.get("template_id", "code_editing")
        index = self.system_template_combo.findData(template_id)
        if index < 0:
            index = self.system_template_combo.findData("custom")
        self.system_template_combo.setCurrentIndex(index)
        self.custom_system_prompt.setPlainText(llm_task.get("custom_text", ""))
        self.user_prompt_edit.setPlainText(prompt.get("user_prompt", ""))
        settings = payload.get("settings", {})
        self.project_root_edit.setText(settings.get("project_root_override", ""))
        self.import_roots_edit.setText(", ".join(settings.get("import_root_overrides", [])))
        self.max_depth_spin.setValue(0 if settings.get("max_dependency_depth") is None else int(settings.get("max_dependency_depth", 5)))
        self.large_file_spin.setValue(int(settings.get("large_file_threshold", 256 * 1024)))
        self.truncation_spin.setValue(int(settings.get("truncation_size", 40 * 1024)))
        self.include_hidden_check.setChecked(bool(settings.get("include_hidden", False)))
        self.include_unchecked_folder_check.setChecked(bool(settings.get("include_unchecked_folder_files", False)))
        self.show_skipped_dependencies_check.setChecked(bool(settings.get("show_skipped_dependencies", False)))
        self.file_overrides = dict(payload.get("file_overrides", {}))
        self._update_input_summary()
        self.status_label.setText(f"Loaded session from {path}.")
        self.request_rebuild()

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        paths = self._paths_from_mime_data(event.mimeData())
        if paths:
            self._log("Dropped %d path(s) into the app", len(paths))
            self._extend_input_paths(paths)
            event.acceptProposedAction()

    def _paths_from_mime_data(self, mime_data) -> list[str]:
        paths: list[str] = []
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    paths.append(url.toLocalFile())
        if not paths and mime_data.hasText():
            raw_text = mime_data.text().strip()
            for line in raw_text.splitlines():
                candidate = line.strip().strip('"')
                if not candidate:
                    continue
                if candidate.startswith("file://"):
                    url = QUrl(candidate)
                    if url.isLocalFile():
                        paths.append(url.toLocalFile())
                    continue
                paths.append(candidate)
        return paths


def launch_app(default_paths: list[str] | None = None, verbose: bool = False) -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(default_paths=default_paths, verbose=verbose)
    window.show()
    return app.exec()
