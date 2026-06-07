from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit,
    QLabel, QMessageBox, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut

_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
_POLL_INTERVAL_MS = 1500           # fallback poll for missed watcher events


def _mono_font() -> QFont:
    f = QFont('Monospace')
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(10)
    return f


# ── Reload banner ─────────────────────────────────────────────────────────────

class _ReloadBar(QFrame):
    def __init__(self, on_reload, on_dismiss, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            'QFrame { background: rgba(124,58,237,0.3);'
            ' border-bottom: 1px solid rgba(124,58,237,0.6); }'
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(8)

        lbl = QLabel('File changed on disk.')
        lbl.setStyleSheet(
            'color: rgba(255,255,255,0.85); font-size: 11px;'
            ' background: transparent; border: none;'
        )

        reload_btn = QPushButton('Reload')
        reload_btn.setFixedHeight(20)
        reload_btn.setStyleSheet(
            'QPushButton { background: rgba(124,58,237,0.7);'
            ' border: 1px solid rgba(167,139,250,0.6);'
            ' border-radius: 4px; color: white; padding: 0 8px; font-size: 11px; }'
            'QPushButton:hover { background: rgba(124,58,237,0.9); }'
        )
        reload_btn.clicked.connect(on_reload)

        dismiss_btn = QPushButton('✕')
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.setFlat(True)
        dismiss_btn.setStyleSheet(
            'QPushButton { color: rgba(255,255,255,0.5); font-size: 11px; border: none; }'
        )
        dismiss_btn.clicked.connect(on_dismiss)

        layout.addWidget(lbl)
        layout.addStretch()
        layout.addWidget(reload_btn)
        layout.addWidget(dismiss_btn)


# ── Per-file editor container ─────────────────────────────────────────────────

class _EditorContainer(QWidget):
    def __init__(self, editor: '_FileEditor', parent=None):
        super().__init__(parent)
        self.editor = editor
        self._bar: _ReloadBar | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(editor, 1)

    def show_reload_bar(self, on_reload):
        if self._bar is not None:
            return
        self._bar = _ReloadBar(on_reload, self._dismiss_bar, self)
        self.layout().insertWidget(0, self._bar)

    def dismiss_bar(self):
        self._dismiss_bar()

    def _dismiss_bar(self):
        if self._bar is not None:
            self._bar.setParent(None)
            self._bar = None


class _FileEditor(QPlainTextEdit):
    def __init__(self, path: str, content: str, parent=None):
        super().__init__(parent)
        self.file_path = path
        self.setFont(_mono_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(32)
        self.setPlainText(content)
        self.document().setModified(False)


# ── Main panel ────────────────────────────────────────────────────────────────

class FileEditorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # mtime tracking: path → float (mtime at last-seen state)
        self._mtimes: dict[str, float] = {}

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_watcher_change)

        # Polling fallback: catches any events inotify drops
        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_INTERVAL_MS)
        self._poll.timeout.connect(self._poll_mtimes)
        self._poll.start()

        self._setup_ui()

    # ── UI ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel('Open a file from the tree to start editing.')
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            'color: rgba(255,255,255,0.28); font-size: 13px;'
        )

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setVisible(False)
        self._tabs.tabCloseRequested.connect(self._close_tab)

        layout.addWidget(self._placeholder)
        layout.addWidget(self._tabs, 1)

    # ── Public API ───────────────────────────────────────────────────────

    def open_file(self, path: str):
        idx = self._find_tab(path)
        if idx >= 0:
            self._tabs.setCurrentIndex(idx)
            self._show_tabs()
            return

        p = Path(path)
        try:
            if p.stat().st_size > _MAX_FILE_SIZE:
                QMessageBox.warning(
                    self, 'File Too Large',
                    f'{p.name} is {p.stat().st_size // 1024 // 1024} MB — too large.'
                )
                return
            content = p.read_text(encoding='utf-8', errors='replace')
            self._mtimes[path] = p.stat().st_mtime
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot Open File', str(exc))
            return

        editor = _FileEditor(path, content, self)
        editor.document().modificationChanged.connect(
            lambda mod, fp=path: self._mark_modified(fp, mod)
        )
        save_sc = QShortcut(QKeySequence.StandardKey.Save, editor)
        save_sc.activated.connect(lambda fp=path: self.save_file(fp))

        container = _EditorContainer(editor, self)
        idx = self._tabs.addTab(container, p.name)
        self._tabs.setTabToolTip(idx, path)
        self._tabs.setCurrentIndex(idx)
        self._show_tabs()

        self._watcher.addPath(path)

    def save_current(self):
        c = self._tabs.currentWidget()
        if isinstance(c, _EditorContainer):
            self.save_file(c.editor.file_path)

    def save_file(self, path: str):
        idx = self._find_tab(path)
        if idx < 0:
            return
        container = self._tabs.widget(idx)
        if not isinstance(container, _EditorContainer):
            return
        try:
            Path(path).write_text(container.editor.toPlainText(), encoding='utf-8')
            container.editor.document().setModified(False)
            container.dismiss_bar()
            self._mtimes[path] = Path(path).stat().st_mtime
        except Exception as exc:
            QMessageBox.warning(self, 'Save Failed', str(exc))

    # ── Change detection ─────────────────────────────────────────────────

    def _on_watcher_change(self, path: str):
        # Immediately re-add: inotify removes the path after firing
        self._watcher.addPath(path)
        self._apply_external_change(path)

    def _poll_mtimes(self):
        """Fallback: detect any changes the watcher missed."""
        for i in range(self._tabs.count()):
            container = self._tabs.widget(i)
            if not isinstance(container, _EditorContainer):
                continue
            path = container.editor.file_path
            try:
                mtime = Path(path).stat().st_mtime
            except Exception:
                continue
            known = self._mtimes.get(path, 0.0)
            if mtime > known:
                self._apply_external_change(path)

    def _apply_external_change(self, path: str):
        idx = self._find_tab(path)
        if idx < 0:
            return
        container = self._tabs.widget(idx)
        if not isinstance(container, _EditorContainer):
            return

        p = Path(path)
        if not p.exists():
            self._tabs.setTabText(idx, f'⚠ {p.name}')
            return

        # Update mtime so polling doesn't double-fire
        try:
            self._mtimes[path] = p.stat().st_mtime
        except Exception:
            pass

        if not container.editor.document().isModified():
            self._reload_into(container.editor, path)
            self._tabs.setTabText(idx, p.name)
            container.dismiss_bar()
        else:
            container.show_reload_bar(
                on_reload=lambda fp=path, c=container: self._reload_from_disk(fp, c)
            )
            self._tabs.setTabText(idx, f'⚠ {p.name}')

    def _reload_into(self, editor: _FileEditor, path: str):
        try:
            content = Path(path).read_text(encoding='utf-8', errors='replace')
        except Exception:
            return
        pos = editor.textCursor().position()
        editor.setPlainText(content)
        editor.document().setModified(False)
        cursor = editor.textCursor()
        cursor.setPosition(min(pos, len(content)))
        editor.setTextCursor(cursor)

    def _reload_from_disk(self, path: str, container: _EditorContainer):
        self._reload_into(container.editor, path)
        container.dismiss_bar()
        idx = self._find_tab(path)
        if idx >= 0:
            self._tabs.setTabText(idx, Path(path).name)

    # ── Tab helpers ───────────────────────────────────────────────────────

    def _find_tab(self, path: str) -> int:
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, _EditorContainer) and w.editor.file_path == path:
                return i
        return -1

    def _mark_modified(self, path: str, modified: bool):
        idx = self._find_tab(path)
        if idx < 0:
            return
        name = Path(path).name
        self._tabs.setTabText(idx, f'● {name}' if modified else name)

    def _close_tab(self, idx: int):
        container = self._tabs.widget(idx)
        if isinstance(container, _EditorContainer):
            editor = container.editor
            if editor.document().isModified():
                ret = QMessageBox.question(
                    self, 'Unsaved Changes',
                    f'Save {Path(editor.file_path).name} before closing?',
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                if ret == QMessageBox.StandardButton.Save:
                    self.save_file(editor.file_path)
                elif ret == QMessageBox.StandardButton.Cancel:
                    return
            self._watcher.removePath(editor.file_path)
            self._mtimes.pop(editor.file_path, None)
        self._tabs.removeTab(idx)
        if self._tabs.count() == 0:
            self._tabs.setVisible(False)
            self._placeholder.setVisible(True)

    def _show_tabs(self):
        self._placeholder.setVisible(False)
        self._tabs.setVisible(True)
