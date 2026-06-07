import os
import shutil

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QTabWidget, QFileDialog, QMenu,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QDesktopServices, QKeySequence,
    QLinearGradient, QPainter,
)
from PyQt6.QtCore import QUrl

from ..session_tracker import SessionTracker
from .file_tree_panel import FileTreePanel
from .file_editor_panel import FileEditorPanel
from .session_log_panel import SessionLogPanel
from .preferences_panel import PreferencesPanel
from .terminal_panel import TerminalPanel
from .git_changes_panel import GitChangesPanel
from .. import opencode_config as cfg

_SETTINGS_APP = 'OpenCodeEditor'
_SETTINGS_ORG = 'OpenCodeEditor'

_THEME_QSS = """
    QWidget {
        color: white;
        background: transparent;
    }

    QTreeView, QListView, QTreeWidget, QListWidget {
        background: rgba(255, 255, 255, 0.05);
        alternate-background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-radius: 8px;
        outline: none;
        selection-background-color: rgba(29, 78, 216, 0.55);
        selection-color: white;
    }
    QTreeView::item, QListView::item, QTreeWidget::item, QListWidget::item { padding: 3px 6px; }
    QTreeView::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {
        background: rgba(255, 255, 255, 0.07);
    }
    QTreeView::item:selected, QListWidget::item:selected, QTreeWidget::item:selected,
    QTreeView::item:selected:!active, QListWidget::item:selected:!active,
    QTreeWidget::item:selected:!active {
        background: rgba(29, 78, 216, 0.55);
        color: white;
    }

    QHeaderView { background: transparent; border: none; }
    QHeaderView::section {
        background: rgba(255, 255, 255, 0.06);
        color: rgba(255, 255, 255, 0.5);
        border: none;
        border-bottom: 1px solid rgba(255, 255, 255, 0.09);
        border-right: 1px solid rgba(255, 255, 255, 0.05);
        padding: 4px 8px;
        font-size: 11px;
    }
    QHeaderView::section:last-child { border-right: none; }

    QPushButton {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 6px;
        color: white;
        padding: 4px 10px;
    }
    QPushButton:hover {
        background: rgba(255, 255, 255, 0.15);
        border-color: rgba(255, 255, 255, 0.22);
    }
    QPushButton:pressed { background: rgba(255, 255, 255, 0.04); }
    QPushButton:checked {
        background: rgba(29, 78, 216, 0.6);
        border-color: rgba(80, 120, 240, 0.9);
    }
    QPushButton:disabled {
        color: rgba(255, 255, 255, 0.25);
        background: rgba(255, 255, 255, 0.03);
        border-color: rgba(255, 255, 255, 0.05);
    }
    QPushButton:flat {
        background: transparent; border: none; padding: 4px 8px;
    }
    QPushButton:flat:hover {
        background: rgba(255, 255, 255, 0.1); border-radius: 4px;
    }

    QPlainTextEdit, QTextEdit {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-radius: 6px;
        color: rgba(255, 255, 255, 0.9);
        selection-background-color: rgba(29, 78, 216, 0.55);
        padding: 4px;
    }

    QLineEdit {
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 5px;
        color: white;
        padding: 3px 7px;
        selection-background-color: rgba(29, 78, 216, 0.55);
    }
    QLineEdit:focus { border-color: rgba(80, 120, 240, 0.8); }

    QTabWidget::pane {
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.02);
    }
    QTabBar::tab {
        background: rgba(255, 255, 255, 0.06);
        color: rgba(255, 255, 255, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 5px 14px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background: rgba(29, 78, 216, 0.55);
        color: white;
        border-color: rgba(80, 120, 240, 0.9);
    }
    QTabBar::tab:hover:!selected {
        background: rgba(255, 255, 255, 0.1); color: white;
    }

    QSlider::groove:horizontal {
        height: 4px;
        background: rgba(255, 255, 255, 0.15);
        border-radius: 2px;
    }
    QSlider::sub-page:horizontal {
        background: #1d4ed8;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: white;
        border: none;
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border-radius: 6px;
    }

    QScrollBar:vertical {
        background: transparent; width: 6px; margin: 2px 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 3px; min-height: 24px;
    }
    QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.35); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

    QScrollBar:horizontal {
        background: transparent; height: 6px; margin: 0 2px;
    }
    QScrollBar::handle:horizontal {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 3px; min-width: 24px;
    }
    QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 0.35); }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

    QSplitter::handle { background: rgba(255, 255, 255, 0.06); }
    QSplitter::handle:horizontal { width: 1px; }
    QSplitter::handle:vertical   { height: 1px; }
"""

_OPENCODE_CMD = ['opencode']


class OpenCodeEditorContent(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings(_SETTINGS_APP, _SETTINGS_ORG)
        self._tracker = SessionTracker(self)
        self._setup_actions()
        self._setup_ui()
        self._restore_state()
        self._tracker.start()
        QTimer.singleShot(300, self._launch_opencode)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor('#0f0c29'))
        gradient.setColorAt(0.5, QColor('#302b63'))
        gradient.setColorAt(1.0, QColor('#24243e'))
        painter.fillRect(self.rect(), QBrush(gradient))

    # ── Public ──────────────────────────────────────────────────────────

    def menus(self, parent=None) -> list[QMenu]:
        menu = QMenu('&OpenCode', parent)
        menu.addAction(self._launch_action)
        menu.addAction(self._stop_action)
        menu.addSeparator()
        menu.addAction(self._save_action)
        menu.addSeparator()
        menu.addAction(self._set_dir_action)
        menu.addAction(self._refresh_action)
        menu.addSeparator()
        menu.addAction(self._open_config_action)
        return [menu]

    def cleanup(self):
        self._terminal.stop()
        self._tracker.stop()
        self._save_state()

    # ── Setup ────────────────────────────────────────────────────────────

    def _setup_actions(self):
        self._launch_action = QAction('▶  Launch OpenCode', self)
        self._launch_action.setShortcut(QKeySequence('Ctrl+Shift+O'))
        self._launch_action.triggered.connect(self._launch_opencode)

        self._stop_action = QAction('■  Stop OpenCode', self)
        self._stop_action.setEnabled(False)
        self._stop_action.triggered.connect(self._stop_opencode)

        self._save_action = QAction('&Save File', self)
        self._save_action.setShortcut(QKeySequence.StandardKey.Save)
        self._save_action.triggered.connect(self._save_current_file)

        self._set_dir_action = QAction('Set &Working Directory…', self)
        self._set_dir_action.triggered.connect(self._set_working_dir)

        self._refresh_action = QAction('&Refresh Session Log', self)
        self._refresh_action.triggered.connect(self._tracker.poll_now)

        self._open_config_action = QAction('Open &Config Folder', self)
        self._open_config_action.triggered.connect(self._open_config_folder)

    def _setup_ui(self):
        self.setStyleSheet(_THEME_QSS)

        # ── Left panel: file tree + git changes ──────────────────────
        self._file_tree = FileTreePanel(parent=self)
        self._file_tree.working_dir_changed.connect(self._on_dir_changed)
        self._file_tree.file_open_requested.connect(self._open_file)

        self._git_changes = GitChangesPanel(self)
        self._git_changes.file_open_requested.connect(self._open_file)

        left_tabs = QTabWidget()
        left_tabs.addTab(self._file_tree, 'Files')
        left_tabs.addTab(self._git_changes, 'Changes')
        self._left_tabs = left_tabs

        # ── Center: vertical splitter (editor top / terminal bottom) ─
        self._file_editor = FileEditorPanel(self)
        self._terminal = TerminalPanel(self)
        self._terminal.process_exited.connect(self._on_process_exited)

        center_split = QSplitter(Qt.Orientation.Vertical)
        center_split.addWidget(self._file_editor)
        center_split.addWidget(self._terminal)
        center_split.setStretchFactor(0, 3)
        center_split.setStretchFactor(1, 2)
        self._center_split = center_split

        # ── Right panel: session log + preferences ────────────────────
        self._session_log = SessionLogPanel(self._tracker, self)
        self._prefs = PreferencesPanel(working_dir='', parent=self)

        right_tabs = QTabWidget()
        right_tabs.addTab(self._session_log, 'Session Log')
        right_tabs.addTab(self._prefs, 'Preferences')
        self._right_tabs = right_tabs

        # ── Main horizontal splitter ──────────────────────────────────
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.addWidget(left_tabs)
        main_split.addWidget(center_split)
        main_split.addWidget(right_tabs)
        self._main_split = main_split

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(main_split)

    # ── State ────────────────────────────────────────────────────────────

    def _restore_state(self):
        saved_dir = self._settings.value('working_dir', '')
        path = saved_dir if saved_dir and os.path.isdir(saved_dir) else os.getcwd()
        self._file_tree.set_root(path)
        self._prefs.set_working_dir(path)
        self._git_changes.set_working_dir(path)

        main_sizes = self._settings.value('main_split')
        if main_sizes:
            iv = [int(s) for s in main_sizes]
            total = max(sum(iv), 900)
            if len(iv) == 3 and min(iv[1], iv[2]) >= 100:
                self._main_split.setSizes(iv)
            else:
                self._main_split.setSizes([200, total * 3 // 5, total * 2 // 5])
        else:
            self._main_split.setSizes([200, 700, 300])

        center_sizes = self._settings.value('center_split')
        if center_sizes:
            iv = [int(s) for s in center_sizes]
            if len(iv) == 2 and min(iv) >= 80:
                self._center_split.setSizes(iv)
        else:
            self._center_split.setSizes([420, 220])

    def _save_state(self):
        self._settings.setValue('working_dir', self._file_tree.current_root())
        self._settings.setValue('main_split', self._main_split.sizes())
        self._settings.setValue('center_split', self._center_split.sizes())

    # ── Slots ────────────────────────────────────────────────────────────

    def _open_file(self, path: str):
        self._file_editor.open_file(path)

    def _save_current_file(self):
        self._file_editor.save_current()

    def _on_dir_changed(self, path: str):
        self._tracker.set_working_dir(path)
        self._prefs.set_working_dir(path)
        self._git_changes.set_working_dir(path)
        self._settings.setValue('working_dir', path)

    def _set_working_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select Working Directory', self._file_tree.current_root()
        )
        if path:
            self._file_tree.set_root(path)

    def _open_config_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(cfg.config_dir())))

    def _launch_opencode(self):
        if not shutil.which('opencode'):
            QMessageBox.warning(
                self, 'OpenCode Not Found',
                'opencode is not in PATH.\n\nInstall it with: npm install -g opencode-ai'
            )
            return
        if self._terminal.is_running():
            self._terminal.setFocus()
            return
        self._terminal.start(_OPENCODE_CMD, self._file_tree.current_root())
        self._launch_action.setEnabled(False)
        self._stop_action.setEnabled(True)
        # Ensure terminal is visible — give it a reasonable height if collapsed
        sizes = self._center_split.sizes()
        if sizes[1] < 100:
            total = sum(sizes) or 600
            self._center_split.setSizes([total * 3 // 5, total * 2 // 5])

    def _stop_opencode(self):
        self._terminal.stop()
        self._launch_action.setEnabled(True)
        self._stop_action.setEnabled(False)

    def _on_process_exited(self):
        self._launch_action.setEnabled(True)
        self._stop_action.setEnabled(False)
