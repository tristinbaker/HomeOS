from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import psutil
from PyQt6.QtCore import QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout,
    QWidget,
)

from home_os_app.theme import THEME_QSS, CARD_STYLE, paint_background
from ..data import (
    MountInfo, NASData, IOState, WatchedFolder,
    fetch, fmt_size, load_watched_folders, mount_all, mount_one,
    save_watched_folders,
)


def _ago(iso_str: str) -> str:
    try:
        delta = datetime.now() - datetime.fromisoformat(iso_str)
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return ""


def _bar_color(pct: float) -> QColor:
    if pct < 60:
        return QColor('#4ade80')
    if pct < 80:
        return QColor('#facc15')
    return QColor('#f87171')


def _btn(label: str, color: str = 'white') -> QPushButton:
    b = QPushButton(label)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if color != 'white':
        b.setStyleSheet(f"QPushButton {{ color: {color}; }} QPushButton:disabled {{ color: rgba(255,255,255,0.25); }}")
    return b


# ── Bars ──────────────────────────────────────────────────────────────────────

class _UsageBar(QWidget):
    def __init__(self, percent: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pct = percent
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_percent(self, p: float) -> None:
        self._pct = p
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 5, 5)
        if self._pct > 0:
            fill_w = max(float(h), w * min(1.0, self._pct / 100))
            painter.setBrush(_bar_color(self._pct))
            painter.drawRoundedRect(QRectF(0, 0, fill_w, h), 5, 5)


class _RelBar(QWidget):
    """Bar sized relative to a maximum value — used in folder browser."""
    def __init__(self, fraction: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frac = max(0.0, min(1.0, fraction))
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 15))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 3, 3)
        if self._frac > 0:
            painter.setBrush(QColor('#60a5fa'))
            painter.drawRoundedRect(QRectF(0, 0, max(float(h), w * self._frac), h), 3, 3)


# ── Sudo password dialog ──────────────────────────────────────────────────────

class _SudoDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('sudo')
        self.setModal(True)
        self.setFixedWidth(320)
        self.setStyleSheet(THEME_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        prompt = QLabel('Enter your sudo password to mount:')
        pf = QFont()
        pf.setPointSize(10)
        prompt.setFont(pf)
        prompt.setStyleSheet('color: rgba(255,255,255,0.70); background: transparent;')
        prompt.setWordWrap(True)

        self._input = QLineEdit()
        self._input.setEchoMode(QLineEdit.EchoMode.Password)
        self._input.setPlaceholderText('Password')
        self._input.returnPressed.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel = _btn('Cancel', '#94a3b8')
        cancel.clicked.connect(self.reject)
        ok = _btn('Mount', '#60a5fa')
        ok.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)

        layout.addWidget(prompt)
        layout.addWidget(self._input)
        layout.addLayout(btn_row)
        self._input.setFocus()

    def password(self) -> str:
        return self._input.text()


# ── Add Folder dialog ─────────────────────────────────────────────────────────

class _AddFolderDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Add Folder')
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(THEME_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        path_lbl = QLabel('Folder path')
        path_lbl.setStyleSheet('color: rgba(255,255,255,0.60); background: transparent;')

        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText('/home/user/Documents')

        browse_btn = _btn('Browse…', '#94a3b8')
        browse_btn.setFixedHeight(36)
        browse_btn.clicked.connect(self._browse)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.addWidget(self._path_input, 1)
        path_row.addWidget(browse_btn)

        name_lbl = QLabel('Display name  (optional — defaults to folder name)')
        name_lbl.setStyleSheet('color: rgba(255,255,255,0.60); background: transparent;')

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText('My Documents')

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel = _btn('Cancel', '#94a3b8')
        cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        ok = _btn('Add Folder', '#60a5fa')
        ok.setFixedHeight(34)
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)

        layout.addWidget(path_lbl)
        layout.addLayout(path_row)
        layout.addSpacing(2)
        layout.addWidget(name_lbl)
        layout.addWidget(self._name_input)
        layout.addSpacing(6)
        layout.addLayout(btn_row)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, 'Select Folder', str(Path.home()))
        if path:
            self._path_input.setText(path)
            if not self._name_input.text():
                self._name_input.setText(Path(path).name)

    def _accept(self) -> None:
        if self._path_input.text().strip():
            self.accept()

    def result_folder(self) -> WatchedFolder:
        path = self._path_input.text().strip()
        name = self._name_input.text().strip() or Path(path).name
        return WatchedFolder(name=name, path=path)


# ── Workers ───────────────────────────────────────────────────────────────────

class _FolderSizeWorker(QThread):
    """Runs `du -sb <path>` to get total size of a directory tree."""
    finished = pyqtSignal(int)  # bytes, or -1 on error

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        import subprocess
        try:
            r = subprocess.run(
                ['du', '-sb', '--', self._path],
                capture_output=True, text=True, timeout=120,
            )
            parts = r.stdout.split('\t', 1)
            if len(parts) == 2:
                self.finished.emit(int(parts[0]))
                return
        except Exception:
            pass
        self.finished.emit(-1)


class _FetchWorker(QThread):
    finished = pyqtSignal(object, object)
    error    = pyqtSignal(str)

    def __init__(self, prev_io: IOState | None, parent=None) -> None:
        super().__init__(parent)
        self._prev_io = prev_io

    def run(self) -> None:
        try:
            data, io_state = fetch(self._prev_io)
            self.finished.emit(data, io_state)
        except Exception as exc:
            self.error.emit(str(exc))


class _MountWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, path: str | None, password: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._password = password

    def run(self) -> None:
        if self._path is None:
            ok, msg = mount_all(self._password)
        else:
            ok, msg = mount_one(self._path, self._password)
        self.finished.emit(ok, msg)


class _DuWorker(QThread):
    """Sizes the immediate children of a directory using du -sb."""
    finished = pyqtSignal(list)

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        import subprocess
        results: list[tuple[str, bool, int]] = []
        try:
            with os.scandir(self._path) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except Exception:
            self.finished.emit([])
            return

        dirs  = [e for e in entries if e.is_dir(follow_symlinks=False)]
        files = [e for e in entries if not e.is_dir(follow_symlinks=False)]

        for f in files:
            try:
                results.append((f.name, False, f.stat().st_size))
            except Exception:
                pass

        if dirs:
            r = subprocess.run(
                ['du', '-sb', '--'] + [e.path for e in dirs],
                capture_output=True, text=True,
            )
            size_map: dict[str, int] = {}
            for line in r.stdout.splitlines():
                parts = line.split('\t', 1)
                if len(parts) == 2:
                    try:
                        size_map[parts[1]] = int(parts[0])
                    except ValueError:
                        pass
            for d in dirs:
                results.append((d.name, True, size_map.get(d.path, 0)))

        results.sort(key=lambda x: x[2], reverse=True)
        self.finished.emit(results)


# ── Folder browser ────────────────────────────────────────────────────────────

class _EntryRow(QWidget):
    navigate = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        full_path: str,
        is_dir: bool,
        size: int,
        max_size: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_dir = is_dir
        self._full_path = full_path
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet('background: transparent;')

        if is_dir:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 6)
        v.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot_color = '#60a5fa' if is_dir else '#94a3b8'
        dot.setStyleSheet(f'background: {dot_color}; border-radius: 4px;')

        name_lbl = QLabel(name)
        nf = QFont()
        nf.setPointSize(10)
        name_lbl.setFont(nf)
        name_lbl.setStyleSheet('color: rgba(255,255,255,0.85); background: transparent;')

        arrow = QLabel('›') if is_dir else QLabel('')
        arrow.setFixedWidth(12)
        af = QFont()
        af.setPointSize(12)
        arrow.setFont(af)
        arrow.setStyleSheet('color: rgba(255,255,255,0.30); background: transparent;')
        arrow.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        size_lbl = QLabel(fmt_size(size))
        sf = QFont()
        sf.setPointSize(9)
        sf.setBold(True)
        size_lbl.setFont(sf)
        size_lbl.setFixedWidth(80)
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        size_lbl.setStyleSheet('color: rgba(255,255,255,0.55); background: transparent;')

        top.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(name_lbl, 1)
        top.addWidget(size_lbl)
        top.addWidget(arrow)

        frac = size / max_size if max_size > 0 else 0.0
        bar = _RelBar(frac)

        v.addLayout(top)
        v.addWidget(bar)

    def mousePressEvent(self, event) -> None:
        if self._is_dir and event.button() == Qt.MouseButton.LeftButton:
            self.navigate.emit(self._full_path)
        super().mousePressEvent(event)


class _FolderBrowserWidget(QWidget):
    done = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stack: list[str] = []
        self._worker: _DuWorker | None = None
        self.setStyleSheet('background: transparent;')
        self._setup_ui()

    def _setup_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(10)

        nav = QWidget()
        nav.setStyleSheet(CARD_STYLE)
        nav_h = QHBoxLayout(nav)
        nav_h.setContentsMargins(14, 10, 14, 10)
        nav_h.setSpacing(10)

        self._back_btn = _btn('← Back', '#94a3b8')
        self._back_btn.setFixedHeight(30)
        self._back_btn.clicked.connect(self._go_back)

        self._breadcrumb = QLabel('')
        bcf = QFont()
        bcf.setPointSize(10)
        bcf.setBold(True)
        self._breadcrumb.setFont(bcf)
        self._breadcrumb.setStyleSheet('color: rgba(255,255,255,0.75); background: transparent;')

        self._loading_lbl = QLabel('')
        lf = QFont()
        lf.setPointSize(9)
        self._loading_lbl.setFont(lf)
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._loading_lbl.setStyleSheet('color: rgba(255,255,255,0.35); background: transparent;')

        nav_h.addWidget(self._back_btn)
        nav_h.addWidget(self._breadcrumb, 1)
        nav_h.addWidget(self._loading_lbl)
        main.addWidget(nav)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        scroll.viewport().setAutoFillBackground(False)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet('background: transparent;')
        self._list_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        main.addWidget(scroll, 1)

    def browse(self, path: str) -> None:
        self._stack = [path]
        self._load(path)

    def _navigate(self, path: str) -> None:
        self._stack.append(path)
        self._load(path)

    def _go_back(self) -> None:
        if len(self._stack) > 1:
            self._stack.pop()
            self._load(self._stack[-1])
        else:
            self.done.emit()

    def _load(self, path: str) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()

        parts = path.rstrip('/').split('/')
        crumb = ' / '.join(parts[-3:]) if len(parts) >= 3 else path
        self._breadcrumb.setText(crumb)
        self._loading_lbl.setText('Computing sizes…')
        self._back_btn.setEnabled(False)

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        self._worker = _DuWorker(path, self)
        self._worker.finished.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, entries: list[tuple[str, bool, int]]) -> None:
        self._loading_lbl.setText('')
        self._back_btn.setEnabled(True)
        current_path = self._stack[-1] if self._stack else ''

        if not entries:
            empty = QLabel('Empty or inaccessible')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet('color: rgba(255,255,255,0.25); font-size: 11px; background: transparent;')
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        max_size = max(size for _, _, size in entries) or 1

        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(16, 8, 16, 8)
        card_v.setSpacing(0)

        for i, (name, is_dir, size) in enumerate(entries):
            full_path = os.path.join(current_path, name)
            row = _EntryRow(name, full_path, is_dir, size, max_size)
            row.navigate.connect(self._navigate)
            card_v.addWidget(row)

            if i < len(entries) - 1:
                div = QWidget()
                div.setFixedHeight(1)
                div.setStyleSheet('background: rgba(255,255,255,0.05);')
                card_v.addWidget(div)

        self._list_layout.addWidget(card)
        self._list_layout.addStretch()


# ── Mount card (NAS shares) ───────────────────────────────────────────────────

class _MountCard(QWidget):
    mount_requested  = pyqtSignal(str)
    browse_requested = pyqtSignal(str)

    def __init__(self, info: MountInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(CARD_STYLE)
        self._path = info.path
        self._build(info)

    def _build(self, info: MountInfo) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        name_lbl = QLabel(info.name)
        nf = QFont()
        nf.setPointSize(12)
        nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setStyleSheet('color: white; background: transparent;')

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot_color = '#4ade80' if info.is_mounted else '#f87171'
        dot.setStyleSheet(f'background: {dot_color}; border-radius: 4px;')

        status_lbl = QLabel('Mounted' if info.is_mounted else 'Not mounted')
        sf = QFont()
        sf.setPointSize(9)
        status_lbl.setFont(sf)
        status_lbl.setStyleSheet(f'color: {dot_color}; background: transparent;')

        hdr.addWidget(name_lbl, 1)
        hdr.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addWidget(status_lbl)

        src_lbl = QLabel(info.source)
        srcf = QFont()
        srcf.setPointSize(8)
        src_lbl.setFont(srcf)
        src_lbl.setStyleSheet('color: rgba(255,255,255,0.30); background: transparent;')

        v.addLayout(hdr)
        v.addWidget(src_lbl)

        if info.is_mounted:
            self._bar = _UsageBar(info.percent)
            v.addWidget(self._bar)

            stats_row = QHBoxLayout()
            stats_lbl = QLabel(
                f"{fmt_size(info.used)} used  ·  {fmt_size(info.free)} free  ·  {fmt_size(info.total)} total"
            )
            stf = QFont()
            stf.setPointSize(9)
            stats_lbl.setFont(stf)
            stats_lbl.setStyleSheet('color: rgba(255,255,255,0.42); background: transparent;')

            pct_lbl = QLabel(f"{info.percent:.1f}%")
            pf = QFont()
            pf.setPointSize(9)
            pf.setBold(True)
            pct_lbl.setFont(pf)
            pct_lbl.setStyleSheet(
                f'color: {_bar_color(info.percent).name()}; background: transparent;'
            )

            stats_row.addWidget(stats_lbl, 1)
            stats_row.addWidget(pct_lbl)
            v.addLayout(stats_row)

            browse_btn = _btn('Browse →', '#60a5fa')
            browse_btn.setFixedHeight(28)
            browse_btn.clicked.connect(lambda: self.browse_requested.emit(self._path))
            v.addWidget(browse_btn, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            self._bar = None
            mount_btn = _btn('Mount', '#60a5fa')
            mount_btn.setFixedHeight(28)
            mount_btn.clicked.connect(lambda: self.mount_requested.emit(self._path))
            v.addWidget(mount_btn, 0, Qt.AlignmentFlag.AlignLeft)

    def update_info(self, info: MountInfo) -> None:
        old = self.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old)
        self._build(info)


# ── Folder card (user-added local paths) ──────────────────────────────────────

class _FolderCard(QWidget):
    browse_requested = pyqtSignal(str)
    remove_requested = pyqtSignal(str)

    def __init__(self, folder: WatchedFolder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(CARD_STYLE)
        self._path = folder.path
        self._fs_total = 0

        try:
            u = psutil.disk_usage(folder.path)
            self._fs_total = u.total
            fs_free = u.free
            accessible = True
        except Exception:
            fs_free = 0
            accessible = False

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        name_lbl = QLabel(folder.name)
        nf = QFont()
        nf.setPointSize(12)
        nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setStyleSheet('color: white; background: transparent;')

        rm_btn = QPushButton('✕')
        rm_btn.setFixedSize(22, 22)
        rm_btn.setToolTip('Remove folder')
        rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rm_btn.setStyleSheet(
            'QPushButton { background: rgba(248,113,113,0.15); border: none; border-radius: 11px;'
            ' color: #f87171; font-size: 11px; }'
            ' QPushButton:hover { background: rgba(248,113,113,0.30); }'
        )
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self._path))

        hdr.addWidget(name_lbl, 1)
        hdr.addWidget(rm_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        path_lbl = QLabel(folder.path)
        pf = QFont()
        pf.setPointSize(8)
        path_lbl.setFont(pf)
        path_lbl.setStyleSheet('color: rgba(255,255,255,0.30); background: transparent;')

        v.addLayout(hdr)
        v.addWidget(path_lbl)

        if accessible:
            self._bar = _UsageBar(0.0)
            v.addWidget(self._bar)

            stats_row = QHBoxLayout()
            self._size_lbl = QLabel('Calculating…')
            stf = QFont()
            stf.setPointSize(9)
            self._size_lbl.setFont(stf)
            self._size_lbl.setStyleSheet('color: rgba(255,255,255,0.42); background: transparent;')

            self._pct_lbl = QLabel('')
            pf2 = QFont()
            pf2.setPointSize(9)
            pf2.setBold(True)
            self._pct_lbl.setFont(pf2)
            self._pct_lbl.setStyleSheet('color: rgba(255,255,255,0.42); background: transparent;')

            stats_row.addWidget(self._size_lbl, 1)
            stats_row.addWidget(self._pct_lbl)
            v.addLayout(stats_row)

            ctx_lbl = QLabel(f"{fmt_size(fs_free)} free on drive  ·  {fmt_size(self._fs_total)} total")
            cf = QFont()
            cf.setPointSize(8)
            ctx_lbl.setFont(cf)
            ctx_lbl.setStyleSheet('color: rgba(255,255,255,0.28); background: transparent;')
            v.addWidget(ctx_lbl)

            browse_btn = _btn('Browse →', '#60a5fa')
            browse_btn.setFixedHeight(28)
            browse_btn.clicked.connect(lambda: self.browse_requested.emit(self._path))
            v.addWidget(browse_btn, 0, Qt.AlignmentFlag.AlignLeft)

            self._worker = _FolderSizeWorker(self._path, self)
            self._worker.finished.connect(self._on_size_ready)
            self._worker.start()
        else:
            err_lbl = QLabel('Folder not accessible')
            ef = QFont()
            ef.setPointSize(9)
            err_lbl.setFont(ef)
            err_lbl.setStyleSheet('color: #f87171; background: transparent;')
            v.addWidget(err_lbl)

    def _on_size_ready(self, size: int) -> None:
        try:
            if size < 0:
                self._size_lbl.setText('Could not calculate size')
                return
            pct = (size / self._fs_total * 100) if self._fs_total > 0 else 0.0
            self._bar.set_percent(pct)
            self._size_lbl.setText(f"📁  {fmt_size(size)}")
            color = _bar_color(pct).name()
            self._pct_lbl.setText(f"{pct:.1f}%")
            self._pct_lbl.setStyleSheet(f'color: {color}; background: transparent;')
        except RuntimeError:
            pass  # card was deleted before worker finished


# ── Main widget ───────────────────────────────────────────────────────────────

class NASStorageContent(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._prev_io: IOState | None = None
        self._fetch_worker: _FetchWorker | None = None
        self._mount_worker: _MountWorker | None = None
        self._last_nas_data: NASData | None = None
        self._watched_folders: list[WatchedFolder] = load_watched_folders()

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(60_000)
        self._auto_timer.timeout.connect(self._refresh)

        self._setup_ui()
        self._refresh()

    def paintEvent(self, event) -> None:
        paint_background(self)

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 20, 24, 16)
        main.setSpacing(14)

        # ── Header card ───────────────────────────────────────────────────────
        hdr_card = QWidget()
        hdr_card.setStyleSheet(CARD_STYLE)
        hdr_h = QHBoxLayout(hdr_card)
        hdr_h.setContentsMargins(20, 14, 20, 14)
        hdr_h.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(4)

        title = QLabel('Storage Analyzer')
        tf = QFont()
        tf.setPointSize(10)
        title.setFont(tf)
        title.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        host_row = QHBoxLayout()
        host_row.setSpacing(6)
        self._host_dot = QLabel()
        self._host_dot.setFixedSize(8, 8)
        self._host_dot.setStyleSheet('background: #888888; border-radius: 4px;')
        self._host_dot.setVisible(False)
        self._host_lbl = QLabel('')
        hf = QFont()
        hf.setPointSize(11)
        hf.setBold(True)
        self._host_lbl.setFont(hf)
        self._host_lbl.setStyleSheet('color: rgba(255,255,255,0.80); background: transparent;')
        host_row.addWidget(self._host_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        host_row.addWidget(self._host_lbl)
        host_row.addStretch()

        left.addWidget(title)
        left.addLayout(host_row)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._add_folder_btn = _btn('＋  Add Folder', '#4ade80')
        self._add_folder_btn.setFixedHeight(34)
        self._add_folder_btn.clicked.connect(self._add_folder)

        self._mount_all_btn = _btn('⊕  Mount All', '#60a5fa')
        self._mount_all_btn.setFixedHeight(34)
        self._mount_all_btn.setVisible(False)
        self._mount_all_btn.clicked.connect(self._do_mount_all)

        self._refresh_btn = _btn('↻  Refresh', '#94a3b8')
        self._refresh_btn.setFixedHeight(34)
        self._refresh_btn.clicked.connect(self._refresh)

        btn_row.addWidget(self._add_folder_btn)
        btn_row.addWidget(self._mount_all_btn)
        btn_row.addWidget(self._refresh_btn)

        self._status_lbl = QLabel('')
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_lbl.setStyleSheet('color: rgba(255,255,255,0.28); font-size: 9px; background: transparent;')

        right.addLayout(btn_row)
        right.addWidget(self._status_lbl)

        hdr_h.addLayout(left, 1)
        hdr_h.addLayout(right)
        main.addWidget(hdr_card)

        # ── Network I/O (only shown when NAS mounts present) ──────────────────
        self._io_card = QWidget()
        self._io_card.setStyleSheet(CARD_STYLE)
        self._io_card.setVisible(False)
        io_h = QHBoxLayout(self._io_card)
        io_h.setContentsMargins(20, 10, 20, 10)
        io_h.setSpacing(24)

        io_title = QLabel('Network I/O')
        itf = QFont()
        itf.setPointSize(9)
        io_title.setFont(itf)
        io_title.setStyleSheet('color: rgba(255,255,255,0.38); background: transparent;')

        self._rx_lbl = QLabel('↓  —')
        self._tx_lbl = QLabel('↑  —')
        for lbl in (self._rx_lbl, self._tx_lbl):
            f = QFont()
            f.setPointSize(10)
            f.setBold(True)
            lbl.setFont(f)
            lbl.setStyleSheet('color: rgba(255,255,255,0.70); background: transparent;')

        io_h.addWidget(io_title)
        io_h.addWidget(self._rx_lbl)
        io_h.addWidget(self._tx_lbl)
        io_h.addStretch()
        main.addWidget(self._io_card)

        # ── Stacked: grid ↔ browser ───────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet('background: transparent;')
        main.addWidget(self._stack, 1)

        # Page 0: cards grid
        grid_page = QWidget()
        grid_page.setStyleSheet('background: transparent;')
        grid_page.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        grid_v = QVBoxLayout(grid_page)
        grid_v.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        scroll.viewport().setAutoFillBackground(False)

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet('background: transparent;')
        self._grid_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._grid_widget)
        grid_v.addWidget(scroll)
        self._stack.addWidget(grid_page)

        # Page 1: folder browser
        self._browser = _FolderBrowserWidget()
        self._browser.done.connect(lambda: self._stack.setCurrentIndex(0))
        self._stack.addWidget(self._browser)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._fetch_worker and self._fetch_worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("…")
        self._fetch_worker = _FetchWorker(self._prev_io, self)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_fetch_done(self, data: NASData, io_state) -> None:
        self._prev_io = io_state
        self._last_nas_data = data
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻  Refresh")
        self._status_lbl.setText(f"Updated {_ago(data.fetched_at)}")

        has_nas = bool(data.mounts)
        self._mount_all_btn.setVisible(has_nas)
        self._host_dot.setVisible(has_nas)
        self._io_card.setVisible(has_nas)

        if has_nas:
            self._host_lbl.setText(data.host or '—')
            if data.host_online:
                self._host_dot.setStyleSheet('background: #4ade80; border-radius: 4px;')
                self._host_lbl.setStyleSheet('color: rgba(255,255,255,0.80); background: transparent;')
            else:
                self._host_dot.setStyleSheet('background: #f87171; border-radius: 4px;')
                self._host_lbl.setStyleSheet('color: #f87171; background: transparent;')
            self._rx_lbl.setText(f"↓  {data.net_io.rx_mbps:.1f} MB/s")
            self._tx_lbl.setText(f"↑  {data.net_io.tx_mbps:.1f} MB/s")

        self._populate_grid()
        self._auto_timer.start()

    def _on_fetch_error(self, msg: str) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻  Refresh")
        self._status_lbl.setText(f"Error: {msg[:60]}")
        self._mount_all_btn.setVisible(False)
        self._host_dot.setVisible(False)
        self._io_card.setVisible(False)
        self._populate_grid()

    def _populate_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        cards: list[QWidget] = []

        if self._last_nas_data:
            for info in self._last_nas_data.mounts:
                card = _MountCard(info)
                card.mount_requested.connect(self._do_mount_one)
                card.browse_requested.connect(self._on_browse)
                cards.append(card)

        for folder in self._watched_folders:
            card = _FolderCard(folder)
            card.browse_requested.connect(self._on_browse)
            card.remove_requested.connect(self._remove_folder)
            cards.append(card)

        for i, card in enumerate(cards):
            self._grid.addWidget(card, i // 2, i % 2)

        if not cards:
            empty = QLabel('No folders added yet.\nClick  ＋ Add Folder  to get started.')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            ef = QFont()
            ef.setPointSize(11)
            empty.setFont(ef)
            empty.setStyleSheet('color: rgba(255,255,255,0.25); background: transparent;')
            self._grid.addWidget(empty, 0, 0, 1, 2)

    def _on_browse(self, path: str) -> None:
        self._stack.setCurrentIndex(1)
        self._browser.browse(path)

    # ── Add / remove folders ──────────────────────────────────────────────────

    def _add_folder(self) -> None:
        dlg = _AddFolderDialog(self)
        dlg.setStyleSheet(self.styleSheet())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        folder = dlg.result_folder()
        if any(f.path == folder.path for f in self._watched_folders):
            return
        self._watched_folders.append(folder)
        save_watched_folders(self._watched_folders)
        self._populate_grid()

    def _remove_folder(self, path: str) -> None:
        self._watched_folders = [f for f in self._watched_folders if f.path != path]
        save_watched_folders(self._watched_folders)
        self._populate_grid()

    # ── Mount actions ─────────────────────────────────────────────────────────

    def _do_mount_all(self) -> None:
        dlg = _SudoDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        self._mount_all_btn.setEnabled(False)
        self._mount_all_btn.setText("Mounting…")
        self._status_lbl.setText("")
        self._mount_worker = _MountWorker(None, password, self)
        self._mount_worker.finished.connect(self._on_mount_done)
        self._mount_worker.start()

    def _do_mount_one(self, path: str) -> None:
        dlg = _SudoDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        self._mount_all_btn.setEnabled(False)
        self._status_lbl.setText(f"Mounting {path}…")
        self._mount_worker = _MountWorker(path, password, self)
        self._mount_worker.finished.connect(self._on_mount_done)
        self._mount_worker.start()

    def _on_mount_done(self, ok: bool, msg: str) -> None:
        self._mount_all_btn.setEnabled(True)
        self._mount_all_btn.setText("⊕  Mount All")
        if ok:
            self._status_lbl.setText("Mounted — refreshing…")
            self._refresh()
        else:
            self._status_lbl.setText(f"Mount failed: {msg[:60]}")
