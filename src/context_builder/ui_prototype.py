"""PROTOTYPE — throwaway UI layout exploration for Context Builder.

Question: Which information hierarchy gives the file tree substantially more
vertical working space while keeping the project identity, preview, user prompt,
and LLM task easy to reach?

Three variants reuse the existing MainWindow widgets and behavior. Run with:

    uv run python -m context_builder.ui_prototype --variant A

Use the floating switcher or the left/right arrow keys while focus is outside an
editor or item view. This module is intentionally not production architecture.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .ui import MainWindow


PROTOTYPE_VARIANTS = {
    "A": "Workspace focus",
    "B": "Prompt rail",
    "C": "Tree first",
}


class PrototypeMainWindow(MainWindow):
    """Recompose the production widgets into switchable throwaway layouts."""

    def __init__(
        self,
        default_paths: list[str] | None = None,
        verbose: bool = False,
        session_path: str | None = None,
        initial_variant: str = "A",
    ) -> None:
        self._prototype_ready = False
        self._prototype_variant = initial_variant if initial_variant in PROTOTYPE_VARIANTS else "A"
        super().__init__(
            default_paths=default_paths,
            verbose=verbose,
            session_path=session_path,
        )
        self.setWindowTitle("Context Builder — UI Prototype")
        self._capture_production_surfaces()
        self._build_compact_project_header()
        self._build_prototype_host()
        self._build_variant_switcher()
        self._apply_prototype_styles()
        self._prototype_ready = True
        self._update_input_summary()
        self._update_loaded_stats()
        self.set_prototype_variant(self._prototype_variant)

    def _capture_production_surfaces(self) -> None:
        central = self.centralWidget()
        if central is None or central.layout() is None:
            raise RuntimeError("The production UI did not create a central layout.")

        self._prototype_root_layout = central.layout()
        self._prototype_header = self._prototype_root_layout.itemAt(0).widget()
        if self._prototype_header is None:
            raise RuntimeError("The production header could not be found.")

        original_splitter = next(
            (
                self._prototype_root_layout.itemAt(index).widget()
                for index in range(self._prototype_root_layout.count())
                if isinstance(self._prototype_root_layout.itemAt(index).widget(), QSplitter)
            ),
            None,
        )
        if not isinstance(original_splitter, QSplitter) or original_splitter.count() < 3:
            raise RuntimeError("The production workspace splitter could not be found.")

        self._prototype_tree_panel = original_splitter.widget(0)
        self._prototype_preview_panel = original_splitter.widget(1)
        self._prototype_task_panel = original_splitter.widget(2)
        self._prototype_prompt_panel = self._direct_child_of_central(self.user_prompt_edit)
        self._prototype_footer = self._direct_child_of_central(self.token_count_label)

        for panel in self._prototype_panels():
            panel.setParent(central)

        self._prototype_root_layout.removeWidget(original_splitter)
        self._prototype_root_layout.removeWidget(self._prototype_prompt_panel)
        original_splitter.deleteLater()

    def _direct_child_of_central(self, widget: QWidget) -> QWidget:
        central = self.centralWidget()
        current = widget
        while current.parentWidget() is not None and current.parentWidget() is not central:
            current = current.parentWidget()
        if current.parentWidget() is not central:
            raise RuntimeError(f"Could not locate the top-level panel for {widget.objectName()!r}.")
        return current

    def _prototype_panels(self) -> tuple[QWidget, QWidget, QWidget, QWidget]:
        return (
            self._prototype_tree_panel,
            self._prototype_preview_panel,
            self._prototype_task_panel,
            self._prototype_prompt_panel,
        )

    def _build_compact_project_header(self) -> None:
        header_layout = self._prototype_header.layout()
        if header_layout is None:
            raise RuntimeError("The production header has no layout.")

        keep_widgets = {
            self.input_summary_label,
            self.loaded_stats_label,
            self.settings_button,
            self.reset_button,
            self.sessions_button,
        }
        self._clear_layout(header_layout, keep_widgets=keep_widgets)

        self.prototype_project_name_label = QLabel("No project loaded")
        self.prototype_project_name_label.setObjectName("prototypeProjectName")
        self.prototype_project_path_label = QLabel("Drop a file or folder to detect a project root.")
        self.prototype_project_path_label.setObjectName("prototypeProjectPath")
        self.prototype_project_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        project_stack = QVBoxLayout()
        project_stack.setSpacing(1)
        project_stack.addWidget(self.prototype_project_name_label)
        project_stack.addWidget(self.prototype_project_path_label)
        project_stack.addWidget(self.input_summary_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self.settings_button)
        action_row.addWidget(self.reset_button)
        action_row.addWidget(self.sessions_button)

        right_stack = QVBoxLayout()
        right_stack.setSpacing(6)
        right_stack.addWidget(self.loaded_stats_label, alignment=Qt.AlignRight)
        right_stack.addLayout(action_row)

        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(16)
        header_layout.addLayout(project_stack, 3)
        header_layout.addStretch(1)
        header_layout.addLayout(right_stack, 2)

    def _clear_layout(self, layout: QLayout, *, keep_widgets: set[QWidget]) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            child_widget = item.widget()
            if child_layout is not None:
                self._clear_layout(child_layout, keep_widgets=keep_widgets)
                child_layout.deleteLater()
            elif child_widget is not None:
                if child_widget in keep_widgets:
                    child_widget.show()
                else:
                    child_widget.hide()

    def _build_prototype_host(self) -> None:
        central = self.centralWidget()
        self.prototype_host = QWidget(central)
        self.prototype_host.setObjectName("prototypeHost")
        self.prototype_host_layout = QVBoxLayout(self.prototype_host)
        self.prototype_host_layout.setContentsMargins(0, 0, 0, 0)
        self.prototype_host_layout.setSpacing(0)

        footer_index = self._prototype_root_layout.indexOf(self._prototype_footer)
        if footer_index < 0:
            footer_index = self._prototype_root_layout.count()
        self._prototype_root_layout.insertWidget(footer_index, self.prototype_host, 1)

    def _build_variant_switcher(self) -> None:
        central = self.centralWidget()
        self.prototype_switcher = QFrame(central)
        self.prototype_switcher.setObjectName("prototypeSwitcher")
        switcher_layout = QHBoxLayout(self.prototype_switcher)
        switcher_layout.setContentsMargins(8, 6, 8, 6)
        switcher_layout.setSpacing(8)

        self.prototype_previous_button = QPushButton("←")
        self.prototype_previous_button.setObjectName("prototypeSwitcherButton")
        self.prototype_previous_button.setToolTip("Previous prototype variant")
        self.prototype_previous_button.setFixedWidth(38)
        self.prototype_variant_label = QLabel()
        self.prototype_variant_label.setObjectName("prototypeVariantLabel")
        self.prototype_variant_label.setAlignment(Qt.AlignCenter)
        self.prototype_next_button = QPushButton("→")
        self.prototype_next_button.setObjectName("prototypeSwitcherButton")
        self.prototype_next_button.setToolTip("Next prototype variant")
        self.prototype_next_button.setFixedWidth(38)

        switcher_layout.addWidget(self.prototype_previous_button)
        switcher_layout.addWidget(self.prototype_variant_label)
        switcher_layout.addWidget(self.prototype_next_button)
        self.prototype_previous_button.clicked.connect(lambda: self.cycle_prototype_variant(-1))
        self.prototype_next_button.clicked.connect(lambda: self.cycle_prototype_variant(1))
        self.prototype_switcher.adjustSize()
        self.prototype_switcher.raise_()

    def _apply_prototype_styles(self) -> None:
        self.setStyleSheet(
            self.styleSheet()
            + """
            QLabel#prototypeProjectName {
                color: #f8fafc;
                font-size: 21px;
                font-weight: 800;
            }
            QLabel#prototypeProjectPath {
                color: #7dd3fc;
                font-family: monospace;
                font-size: 9pt;
            }
            QWidget#prototypeHost {
                background: transparent;
            }
            QFrame#prototypeSwitcher {
                background: #020617;
                border: 1px solid rgba(125, 211, 252, 0.55);
                border-radius: 18px;
            }
            QLabel#prototypeVariantLabel {
                color: #f8fafc;
                font-weight: 700;
                min-width: 190px;
            }
            QPushButton#prototypeSwitcherButton {
                background: #0f172a;
                border: 1px solid rgba(148, 163, 184, 0.28);
                border-radius: 12px;
                padding: 5px 9px;
                font-size: 15px;
                font-weight: 800;
            }
            QPushButton#prototypeSwitcherButton:hover {
                background: #0ea5e9;
            }
            """
        )

    def set_prototype_variant(self, variant: str) -> None:
        normalized = variant.upper()
        if normalized not in PROTOTYPE_VARIANTS:
            normalized = "A"
        self._prototype_variant = normalized
        self._detach_panels_from_previous_variant()

        if normalized == "A":
            root_widget = self._build_variant_a()
        elif normalized == "B":
            root_widget = self._build_variant_b()
        else:
            root_widget = self._build_variant_c()

        self.prototype_host_layout.addWidget(root_widget, 1)
        root_widget.show()
        for panel in self._prototype_panels():
            panel.show()
        self.prototype_variant_label.setText(
            f"{normalized} — {PROTOTYPE_VARIANTS[normalized]}"
        )
        self.status_label.setText(
            f"Prototype {normalized}: {PROTOTYPE_VARIANTS[normalized]}."
        )
        self.statusBar().showMessage(
            f"UI prototype {normalized}: {PROTOTYPE_VARIANTS[normalized]}"
        )
        QTimer.singleShot(0, self._position_variant_switcher)

    def _detach_panels_from_previous_variant(self) -> None:
        for panel in self._prototype_panels():
            panel.setParent(self.prototype_host)

        while self.prototype_host_layout.count():
            item = self.prototype_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in self._prototype_panels():
                widget.deleteLater()

    def _configured_splitter(self, orientation: Qt.Orientation) -> QSplitter:
        splitter = QSplitter(orientation)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)
        return splitter

    def _build_variant_a(self) -> QWidget:
        """Tree and preview dominate; prompt and task share a narrow right column."""
        main_splitter = self._configured_splitter(Qt.Horizontal)
        prompt_stack = self._configured_splitter(Qt.Vertical)
        prompt_stack.addWidget(self._prototype_prompt_panel)
        prompt_stack.addWidget(self._prototype_task_panel)
        prompt_stack.setStretchFactor(0, 2)
        prompt_stack.setStretchFactor(1, 3)
        prompt_stack.setSizes([300, 460])

        main_splitter.addWidget(self._prototype_tree_panel)
        main_splitter.addWidget(self._prototype_preview_panel)
        main_splitter.addWidget(prompt_stack)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 5)
        main_splitter.setStretchFactor(2, 3)
        main_splitter.setSizes([520, 650, 380])
        return main_splitter

    def _build_variant_b(self) -> QWidget:
        """A compact prompt rail comes first, followed by tree and wide preview."""
        main_splitter = self._configured_splitter(Qt.Horizontal)
        prompt_rail = self._configured_splitter(Qt.Vertical)
        prompt_rail.addWidget(self._prototype_prompt_panel)
        prompt_rail.addWidget(self._prototype_task_panel)
        prompt_rail.setStretchFactor(0, 2)
        prompt_rail.setStretchFactor(1, 3)
        prompt_rail.setSizes([310, 450])

        main_splitter.addWidget(prompt_rail)
        main_splitter.addWidget(self._prototype_tree_panel)
        main_splitter.addWidget(self._prototype_preview_panel)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setStretchFactor(2, 5)
        main_splitter.setSizes([350, 500, 650])
        return main_splitter

    def _build_variant_c(self) -> QWidget:
        """The tree owns the left half; preview and prompt controls stack on the right."""
        main_splitter = self._configured_splitter(Qt.Horizontal)
        right_splitter = self._configured_splitter(Qt.Vertical)
        prompt_tabs = QTabWidget()
        prompt_tabs.setObjectName("prototypePromptTabs")
        prompt_tabs.addTab(self._prototype_prompt_panel, "User Prompt")
        prompt_tabs.addTab(self._prototype_task_panel, "LLM Task")

        right_splitter.addWidget(self._prototype_preview_panel)
        right_splitter.addWidget(prompt_tabs)
        right_splitter.setStretchFactor(0, 5)
        right_splitter.setStretchFactor(1, 3)
        right_splitter.setSizes([560, 330])

        main_splitter.addWidget(self._prototype_tree_panel)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 6)
        main_splitter.setStretchFactor(1, 5)
        main_splitter.setSizes([760, 680])
        return main_splitter

    def cycle_prototype_variant(self, step: int) -> None:
        variants = list(PROTOTYPE_VARIANTS)
        current_index = variants.index(self._prototype_variant)
        next_variant = variants[(current_index + step) % len(variants)]
        self.set_prototype_variant(next_variant)

    def _project_identity_path(self) -> Path | None:
        if self.workspace is not None:
            return Path(self.workspace.project_root)
        if not self.input_paths:
            return None
        candidate = Path(self.input_paths[0]).expanduser()
        return candidate if candidate.is_dir() else candidate.parent

    def _update_project_identity(self) -> None:
        if not hasattr(self, "prototype_project_name_label"):
            return
        root = self._project_identity_path()
        if root is None:
            self.prototype_project_name_label.setText("No project loaded")
            self.prototype_project_path_label.setText(
                "Drop a file or folder to detect a project root."
            )
            self.prototype_project_path_label.setToolTip("")
            return

        try:
            root = root.resolve()
        except OSError:
            pass
        name = root.name or root.as_posix()
        full_path = root.as_posix()
        self.prototype_project_name_label.setText(name)
        self.prototype_project_path_label.setText(full_path)
        self.prototype_project_path_label.setToolTip(full_path)

    def _update_input_summary(self) -> None:
        super()._update_input_summary()
        if not self._prototype_ready:
            return
        count = len(self.input_paths)
        if count == 0:
            self.input_summary_label.setText("No inputs loaded.")
        elif count == 1:
            self.input_summary_label.setText("1 input loaded")
        else:
            self.input_summary_label.setText(f"{count} inputs loaded")
        self._update_project_identity()

    def _update_loaded_stats(self) -> None:
        super()._update_loaded_stats()
        if not self._prototype_ready:
            return
        self._update_project_identity()
        if self.workspace is None or self.current_result is None:
            self.loaded_stats_label.setText("No bundle yet")
            return

        bundle = self.current_result.bundle
        file_count = len(bundle["files"])
        dependency_count = sum(
            len(item["includes"]) for item in bundle["dependency_graph"]
        )
        self.loaded_stats_label.setText(
            f"<b>{file_count:,}</b> files &nbsp; <b>{dependency_count:,}</b> links"
        )

    def on_build_finished(self, result) -> None:
        super().on_build_finished(result)
        if self._prototype_ready:
            self._update_project_identity()
            self._update_loaded_stats()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if self._prototype_ready and event.type() == QEvent.Type.KeyPress:
            key_event = event if isinstance(event, QKeyEvent) else None
            if key_event is not None and key_event.key() in {Qt.Key_Left, Qt.Key_Right}:
                focus = QApplication.focusWidget()
                blocks_variant_shortcut = isinstance(
                    focus,
                    (
                        QLineEdit,
                        QPlainTextEdit,
                        QAbstractItemView,
                        QComboBox,
                        QSpinBox,
                    ),
                )
                if not blocks_variant_shortcut:
                    self.cycle_prototype_variant(
                        -1 if key_event.key() == Qt.Key_Left else 1
                    )
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._prototype_ready:
            QTimer.singleShot(0, self._position_variant_switcher)

    def _position_variant_switcher(self) -> None:
        if not hasattr(self, "prototype_switcher"):
            return
        self.prototype_switcher.adjustSize()
        central = self.centralWidget()
        if central is None:
            return
        switcher_size = self.prototype_switcher.sizeHint()
        x = max(8, (central.width() - switcher_size.width()) // 2)
        footer_top = self._prototype_footer.geometry().top()
        y = max(8, footer_top - switcher_size.height() - 10)
        self.prototype_switcher.resize(switcher_size)
        self.prototype_switcher.move(x, y)
        self.prototype_switcher.raise_()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Throwaway Context Builder UI layout prototype"
    )
    parser.add_argument("paths", nargs="*", help="Files or folders to load on startup")
    parser.add_argument(
        "--variant",
        choices=tuple(PROTOTYPE_VARIANTS),
        default="A",
        help="Initial prototype variant",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--session", help="Context session JSON file to load on startup")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(["context-builder-ui-prototype"])
    app.setApplicationName("context-builder-ui-prototype")
    app.setApplicationDisplayName("Context Builder UI Prototype")
    app.setDesktopFileName("context-builder")
    window = PrototypeMainWindow(
        default_paths=args.paths,
        verbose=args.verbose,
        session_path=args.session,
        initial_variant=args.variant,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
