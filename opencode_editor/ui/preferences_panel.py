import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QPushButton, QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QFont

from .. import opencode_config as cfg

# Project-level: relative to working dir
_PROJECT_MEMORY_CANDIDATES = [
    'AGENTS.md',
    '.github/instructions/memory.instruction.md',
]
# Global: absolute paths OpenCode always reads
_GLOBAL_MEMORY_CANDIDATES = [
    cfg.config_dir() / 'AGENTS.md',
]
_MEMORY_FRONTMATTER = "---\napplyTo: '**'\n---\n\n"
_POLL_MS = 1500


def _make_editor(placeholder: str = '') -> QPlainTextEdit:
    ed = QPlainTextEdit()
    ed.setPlaceholderText(placeholder)
    font = QFont('Monospace')
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    ed.setFont(font)
    return ed


def _info_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        'color: rgba(100,140,255,0.85); font-size: 11px;'
        ' background: rgba(29,78,216,0.08);'
        ' border: 1px solid rgba(29,78,216,0.25);'
        ' border-radius: 4px; padding: 4px 8px;'
    )
    return lbl


def _status_label() -> QLabel:
    lbl = QLabel()
    lbl.setStyleSheet('color: rgba(100,140,255,0.9); font-size: 11px;')
    return lbl


class _EditorTab(QWidget):
    def __init__(self, read_fn, write_fn, placeholder='', info='', parent=None):
        super().__init__(parent)
        self._read_fn = read_fn
        self._write_fn = write_fn

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        if info:
            layout.addWidget(_info_label(info))

        self._editor = _make_editor(placeholder)

        bar = QHBoxLayout()
        self._status = _status_label()
        save_btn = QPushButton('Save')
        save_btn.setFixedWidth(72)
        reload_btn = QPushButton('Reload')
        reload_btn.setFixedWidth(72)
        bar.addWidget(self._status, 1)
        bar.addWidget(reload_btn)
        bar.addWidget(save_btn)

        layout.addWidget(self._editor, 1)
        layout.addLayout(bar)

        save_btn.clicked.connect(self._save)
        reload_btn.clicked.connect(self._load)
        self._load()

    def _load(self):
        self._editor.setPlainText(self._read_fn())
        self._status.setText('')

    def _save(self):
        try:
            self._write_fn(self._editor.toPlainText())
            self._status.setText('Saved.')
        except Exception as exc:
            self._status.setText(f'Error: {exc}')


class _MemoryTab(QWidget):
    """
    Watches all files OpenCode may write memories to in the working directory:
      - AGENTS.md  (project-level instructions / preferences)
      - .github/instructions/memory.instruction.md  (structured memory)
    Shows whichever file exists; auto-reloads when OpenCode writes to either.
    """

    def __init__(self, working_dir: str = '', parent=None):
        super().__init__(parent)
        self._working_dir = ''
        self._mtimes: dict[str, float] = {}
        self._active_path = ''      # which file is currently displayed

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._info = _info_label('')
        layout.addWidget(self._info)

        self._editor = _make_editor(
            'No memories yet.\n'
            'OpenCode will create AGENTS.md or .github/instructions/memory.instruction.md\n'
            'the first time you ask it to remember something.'
        )

        bar = QHBoxLayout()
        self._status = _status_label()
        save_btn = QPushButton('Save')
        save_btn.setFixedWidth(72)
        reload_btn = QPushButton('Reload')
        reload_btn.setFixedWidth(72)
        bar.addWidget(self._status, 1)
        bar.addWidget(reload_btn)
        bar.addWidget(save_btn)

        layout.addWidget(self._editor, 1)
        layout.addLayout(bar)

        save_btn.clicked.connect(self._save)
        reload_btn.clicked.connect(self._load)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._poll_mtimes)
        self._poll.start()

        if working_dir:
            self.set_working_dir(working_dir)

    # ── Public ──────────────────────────────────────────────────────────

    def set_working_dir(self, path: str):
        for watched in list(self._watcher.files()):
            self._watcher.removePath(watched)
        self._mtimes.clear()
        self._working_dir = path
        self._load()

    # ── Internal ─────────────────────────────────────────────────────────

    def _candidate_paths(self) -> list[Path]:
        """All paths to watch: project-relative ones + global config ones."""
        paths = list(_GLOBAL_MEMORY_CANDIDATES)
        if self._working_dir:
            for rel in _PROJECT_MEMORY_CANDIDATES:
                paths.append(Path(self._working_dir) / rel)
        return paths

    def _most_recent(self) -> Path | None:
        """Return the candidate that exists and was modified most recently."""
        best: Path | None = None
        best_mtime = -1.0
        for p in self._candidate_paths():
            try:
                m = p.stat().st_mtime
                if m > best_mtime:
                    best_mtime = m
                    best = p
            except OSError:
                pass
        return best

    def _load(self):
        p = self._most_recent()
        if p is None:
            self._active_path = ''
            self._editor.setPlainText('')
            self._info.setText(
                'Watching global AGENTS.md and project AGENTS.md / '
                '.github/instructions/memory.instruction.md — '
                'OpenCode will write here when you ask it to remember something.'
            )
            self._status.setText('')
            return

        try:
            content = p.read_text(encoding='utf-8')
            mtime = p.stat().st_mtime
        except Exception as exc:
            self._status.setText(f'Read error: {exc}')
            return

        self._active_path = str(p)
        self._mtimes[str(p)] = mtime
        self._watcher.addPath(str(p))
        self._info.setText(f'Showing: {p}')

        if not self._editor.document().isModified():
            self._editor.setPlainText(content)
            self._editor.document().setModified(False)
        self._status.setText('')

    def _save(self):
        target = self._active_path or (
            str(Path(self._working_dir) / 'AGENTS.md') if self._working_dir else ''
        )
        if not target:
            return
        p = Path(target)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self._editor.toPlainText(), encoding='utf-8')
            self._mtimes[str(p)] = p.stat().st_mtime
            self._active_path = str(p)
            self._editor.document().setModified(False)
            self._watcher.addPath(str(p))
            self._info.setText(f'Showing: {p}')
            self._status.setText('Saved.')
        except Exception as exc:
            self._status.setText(f'Error: {exc}')

    def _on_file_changed(self, path: str):
        self._watcher.addPath(path)   # re-add: inotify drops path after firing
        self._load()

    def _poll_mtimes(self):
        for p in self._candidate_paths():
            if not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
            except Exception:
                continue
            if mtime > self._mtimes.get(str(p), 0.0):
                self._load()
                break


class _ContextStoreTab(QWidget):
    """Edits context-store.json. Saving also regenerates context-store.md."""

    _INFO = (
        'Static preferences injected into every OpenCode session via the '
        'instructions field in opencode.json. '
        'Editing here auto-syncs context-store.md — changes take effect from the next session.'
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(_info_label(self._INFO))
        self._editor = _make_editor('context-store.json — JSON array of preference entries…')

        bar = QHBoxLayout()
        self._status = _status_label()
        save_btn = QPushButton('Save')
        save_btn.setFixedWidth(72)
        reload_btn = QPushButton('Reload')
        reload_btn.setFixedWidth(72)
        fmt_btn = QPushButton('Format')
        fmt_btn.setFixedWidth(72)
        bar.addWidget(self._status, 1)
        bar.addWidget(fmt_btn)
        bar.addWidget(reload_btn)
        bar.addWidget(save_btn)

        layout.addWidget(self._editor, 1)
        layout.addLayout(bar)

        save_btn.clicked.connect(self._save)
        reload_btn.clicked.connect(self._load)
        fmt_btn.clicked.connect(self._format)
        self._load()

    def _load(self):
        self._editor.setPlainText(cfg.read_context_store_json())
        self._status.setText('')

    def _format(self):
        try:
            obj = json.loads(self._editor.toPlainText())
            self._editor.setPlainText(json.dumps(obj, indent=2))
            self._status.setText('')
        except json.JSONDecodeError as exc:
            self._status.setText(f'Invalid JSON: {exc}')

    def _save(self):
        try:
            cfg.write_context_store_json(self._editor.toPlainText())
            self._status.setText('Saved. (context-store.md synced)')
        except (json.JSONDecodeError, ValueError) as exc:
            self._status.setText(f'Invalid JSON — not saved: {exc}')
        except Exception as exc:
            self._status.setText(f'Error: {exc}')


class _JsonTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._editor = _make_editor('OpenCode JSON config…')

        bar = QHBoxLayout()
        self._status = _status_label()
        save_btn = QPushButton('Save')
        save_btn.setFixedWidth(72)
        reload_btn = QPushButton('Reload')
        reload_btn.setFixedWidth(72)
        fmt_btn = QPushButton('Format')
        fmt_btn.setFixedWidth(72)
        bar.addWidget(self._status, 1)
        bar.addWidget(fmt_btn)
        bar.addWidget(reload_btn)
        bar.addWidget(save_btn)

        layout.addWidget(self._editor, 1)
        layout.addLayout(bar)

        save_btn.clicked.connect(self._save)
        reload_btn.clicked.connect(self._load)
        fmt_btn.clicked.connect(self._format)
        self._load()

    def _load(self):
        self._editor.setPlainText(cfg.read_opencode_json())
        self._status.setText('')

    def _format(self):
        try:
            obj = json.loads(self._editor.toPlainText())
            self._editor.setPlainText(json.dumps(obj, indent=2))
            self._status.setText('')
        except json.JSONDecodeError as exc:
            self._status.setText(f'Invalid JSON: {exc}')

    def _save(self):
        try:
            cfg.write_opencode_json(self._editor.toPlainText())
            self._status.setText('Saved.')
        except json.JSONDecodeError as exc:
            self._status.setText(f'Invalid JSON — not saved: {exc}')
        except Exception as exc:
            self._status.setText(f'Error: {exc}')


class PreferencesPanel(QWidget):
    def __init__(self, working_dir: str = '', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()

        self._memory_tab = _MemoryTab(working_dir, self)
        tabs.addTab(self._memory_tab, 'Session Memory')

        tabs.addTab(
            _EditorTab(
                cfg.read_agents_md,
                cfg.write_agents_md,
                'Global system prompt (AGENTS.md)…',
                info=(
                    'AGENTS.md — auto-read as the global system prompt on every session. '
                    'For project-specific rules, add an AGENTS.md in the project root.'
                ),
            ),
            'System Prompt',
        )
        tabs.addTab(_ContextStoreTab(), 'Stored Preferences')
        tabs.addTab(
            _EditorTab(
                cfg.read_context_learn_md,
                cfg.write_context_learn_md,
                'Learning rules (context-learn.md)…',
                info=(
                    'context-learn.md — injected via the instructions field in opencode.json. '
                    'Controls when and how OpenCode saves new [REMEMBER:] entries.'
                ),
            ),
            'Learning Rules',
        )
        tabs.addTab(_JsonTab(), 'Config')

        layout.addWidget(tabs)

    def set_working_dir(self, path: str):
        self._memory_tab.set_working_dir(path)
