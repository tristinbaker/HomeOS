from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from home_os_app.theme import CARD_STYLE, THEME_QSS, paint_background
from ..data import (
    PLATFORMS, Game, System,
    art_cache_path, fetch_art, load_config, load_library,
    save_config, save_library, scan_system,
)

CARD_W, CARD_H = 148, 185
GRID_W, GRID_H = CARD_W + 18, CARD_H + 58


# ── Workers ───────────────────────────────────────────────────────────────────

class _ScanWorker(QThread):
    done = pyqtSignal(list)   # list[Game]

    def __init__(self, systems: list[System], existing: set[str], parent=None) -> None:
        super().__init__(parent)
        self._systems  = systems
        self._existing = existing

    def run(self) -> None:
        found: list[Game] = []
        for sys_ in self._systems:
            for g in scan_system(sys_):
                if g.rom_path not in self._existing:
                    found.append(g)
        self.done.emit(found)


class _ArtWorker(QThread):
    art_ready = pyqtSignal(str, str)   # rom_path, art_path

    def __init__(self, games: list[Game], systems: list[System],
                 api_key: str, parent=None) -> None:
        super().__init__(parent)
        self._games    = games
        self._sys_map  = {s.name: s for s in systems}
        self._api_key  = api_key

    def run(self) -> None:
        for game in self._games:
            cached = art_cache_path(game)
            if cached.exists():
                self.art_ready.emit(game.rom_path, str(cached))
                continue
            sys_ = self._sys_map.get(game.system)
            if not sys_ or not self._api_key:
                continue
            path = fetch_art(game, sys_.platform_id, self._api_key)
            if path:
                self.art_ready.emit(game.rom_path, path)
            time.sleep(0.3)  # be polite to the API


# ── Helpers ───────────────────────────────────────────────────────────────────

_PLACEHOLDER_COLORS = [
    '#1e40af', '#7e22ce', '#15803d',
    '#b45309', '#be123c', '#0e7490',
]


def _placeholder_pixmap(name: str, w: int = CARD_W, h: int = CARD_H) -> QPixmap:
    px = QPixmap(w, h)
    color = _PLACEHOLDER_COLORS[hash(name) % len(_PLACEHOLDER_COLORS)]
    px.fill(QColor(color))
    p = QPainter(px)
    f = QFont()
    f.setPointSize(48)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 160))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, (name[:1] or '?').upper())
    p.end()
    return px


def _art_pixmap(path: str) -> QPixmap:
    px = QPixmap(path)
    if px.isNull():
        return QPixmap()
    return px.scaled(CARD_W, CARD_H,
                     Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


# ── Add System dialog ─────────────────────────────────────────────────────────

class _AddSystemDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Add System')
        self.setModal(True)
        self.setFixedWidth(460)
        self.setStyleSheet(THEME_QSS)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(10)

        def _field(label: str, placeholder: str = '') -> QLineEdit:
            v.addWidget(_dim(label))
            le = QLineEdit()
            le.setPlaceholderText(placeholder)
            v.addWidget(le)
            return le

        def _dim(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet('color: rgba(255,255,255,0.55); background: transparent;')
            return lbl

        self._name = _field('System name', 'e.g. SNES')

        v.addWidget(_dim('ROM directory'))
        rom_row = QHBoxLayout()
        self._rom_dir = QLineEdit()
        self._rom_dir.setPlaceholderText('/home/user/roms/snes')
        browse_rom = QPushButton('Browse')
        browse_rom.setFixedHeight(34)
        browse_rom.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_rom.clicked.connect(self._browse_rom)
        rom_row.addWidget(self._rom_dir, 1)
        rom_row.addWidget(browse_rom)
        v.addLayout(rom_row)

        v.addWidget(_dim('Emulator path'))
        emu_row = QHBoxLayout()
        self._emu = QLineEdit()
        self._emu.setPlaceholderText('/usr/bin/snes9x')
        browse_emu = QPushButton('Browse')
        browse_emu.setFixedHeight(34)
        browse_emu.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_emu.clicked.connect(self._browse_emu)
        emu_row.addWidget(self._emu, 1)
        emu_row.addWidget(browse_emu)
        v.addLayout(emu_row)

        self._exts = _field('File extensions (space or comma separated)', '.sfc .smc')

        v.addWidget(_dim('Platform (for game art)'))
        self._platform = QComboBox()
        for name, pid in PLATFORMS:
            self._platform.addItem(name, pid)
        v.addWidget(self._platform)

        self._err = QLabel('')
        self._err.setStyleSheet('color: #f87171; font-size: 9px; background: transparent;')
        v.addWidget(self._err)

        btn_row = QHBoxLayout()
        cancel = QPushButton('Cancel')
        cancel.setFixedHeight(34)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton('Add')
        ok.setFixedHeight(34)
        ok.setDefault(True)
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self._accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        v.addLayout(btn_row)

    def _browse_rom(self) -> None:
        d = QFileDialog.getExistingDirectory(self, 'Select ROM Directory')
        if d:
            self._rom_dir.setText(d)

    def _browse_emu(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, 'Select Emulator')
        if f:
            self._emu.setText(f)

    def _accept(self) -> None:
        if not self._name.text().strip():
            self._err.setText('System name is required.')
            return
        if not self._rom_dir.text().strip():
            self._err.setText('ROM directory is required.')
            return
        if not self._emu.text().strip():
            self._err.setText('Emulator path is required.')
            return
        self.accept()

    def system(self) -> System:
        raw_exts = self._exts.text().replace(',', ' ').split()
        exts = [(e if e.startswith('.') else f'.{e}') for e in raw_exts] or ['.rom']
        return System(
            name         = self._name.text().strip(),
            rom_dir      = self._rom_dir.text().strip(),
            emulator_path= self._emu.text().strip(),
            extensions   = exts,
            platform_id  = self._platform.currentData(),
        )


# ── API key dialog ────────────────────────────────────────────────────────────

class _ApiKeyDialog(QDialog):
    def __init__(self, current_key: str = '', parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('TheGamesDB API Key')
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(THEME_QSS)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(10)

        info = QLabel(
            'Get a free API key at thegamesdb.net.\n'
            'Used only to fetch game box art (3 000 requests/month free).'
        )
        info.setWordWrap(True)
        info.setStyleSheet('color: rgba(255,255,255,0.55); font-size: 9px; background: transparent;')
        v.addWidget(info)

        self._key = QLineEdit(current_key)
        self._key.setPlaceholderText('Paste your API key here')
        v.addWidget(self._key)

        btn_row = QHBoxLayout()
        cancel = QPushButton('Cancel')
        cancel.setFixedHeight(34)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton('Save')
        ok.setFixedHeight(34)
        ok.setDefault(True)
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        v.addLayout(btn_row)

    def key(self) -> str:
        return self._key.text().strip()


# ── Main widget ───────────────────────────────────────────────────────────────

class ROMManagerContent(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._systems: list[System] = []
        self._games:   list[Game]   = []
        self._selected_system: str  = ''   # '' = All
        self._scan_worker:    _ScanWorker | None = None
        self._art_worker:     _ArtWorker  | None = None
        self._settings = QSettings('HomeOS', 'HomeOS')

        self._setup_ui()
        self._load()

    def paintEvent(self, event) -> None:
        paint_background(self)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)

        main = QVBoxLayout(self)
        main.setContentsMargins(24, 20, 24, 16)
        main.setSpacing(14)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(CARD_STYLE)
        hdr_h = QHBoxLayout(hdr)
        hdr_h.setContentsMargins(20, 14, 20, 14)
        hdr_h.setSpacing(10)

        title = QLabel('ROM Manager')
        tf = QFont()
        tf.setPointSize(10)
        title.setFont(tf)
        title.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        self._status_lbl = QLabel('')
        self._status_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.28); font-size: 9px; background: transparent;'
        )

        self._search = QLineEdit()
        self._search.setPlaceholderText('Search games…')
        self._search.setFixedHeight(34)
        self._search.setMaximumWidth(220)
        self._search.textChanged.connect(self._rebuild_grid)

        api_btn = QPushButton('⚙  API Key')
        api_btn.setFixedHeight(34)
        api_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        api_btn.setStyleSheet('QPushButton { color: #94a3b8; }')
        api_btn.clicked.connect(self._set_api_key)

        self._scan_btn = QPushButton('↻  Scan')
        self._scan_btn.setFixedHeight(34)
        self._scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_btn.setStyleSheet(
            'QPushButton { color: #94a3b8; }'
            ' QPushButton:disabled { color: rgba(255,255,255,0.20); }'
        )
        self._scan_btn.clicked.connect(self._scan)

        add_btn = QPushButton('＋  Add System')
        add_btn.setFixedHeight(34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet('QPushButton { color: #4ade80; }')
        add_btn.clicked.connect(self._add_system)

        hdr_h.addWidget(title)
        hdr_h.addWidget(self._status_lbl, 1)
        hdr_h.addWidget(self._search)
        hdr_h.addWidget(api_btn)
        hdr_h.addWidget(self._scan_btn)
        hdr_h.addWidget(add_btn)
        main.addWidget(hdr)

        # Body: system list | game grid
        body = QHBoxLayout()
        body.setSpacing(16)
        main.addLayout(body, 1)

        # Left: system list
        sys_panel = QWidget()
        sys_panel.setStyleSheet('background: transparent;')
        sys_panel.setFixedWidth(190)
        self._sys_layout = QVBoxLayout(sys_panel)
        self._sys_layout.setContentsMargins(0, 0, 0, 0)
        self._sys_layout.setSpacing(2)
        self._sys_layout.addStretch()
        body.addWidget(sys_panel)

        # Right: game grid
        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setIconSize(QSize(CARD_W, CARD_H))
        self._grid.setGridSize(QSize(GRID_W, GRID_H))
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setSpacing(6)
        self._grid.setWrapping(True)
        self._grid.setUniformItemSizes(True)
        self._grid.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                background: rgba(255,255,255,0.05);
                border-radius: 8px;
                color: rgba(255,255,255,0.80);
                font-size: 9px;
                padding: 4px;
            }
            QListWidget::item:hover {
                background: rgba(255,255,255,0.10);
            }
            QListWidget::item:selected {
                background: rgba(99,102,241,0.30);
                color: white;
            }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14);
                border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._grid.itemDoubleClicked.connect(self._launch)
        self._grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._grid_context_menu)
        body.addWidget(self._grid, 1)

    # ── System panel ──────────────────────────────────────────────────────────

    def _rebuild_sys_panel(self) -> None:
        while self._sys_layout.count():
            item = self._sys_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        all_count = len(self._games)
        self._sys_layout.addWidget(
            self._sys_row('All Games', all_count, self._selected_system == '')
        )
        for sys_ in self._systems:
            count = sum(1 for g in self._games if g.system == sys_.name)
            self._sys_layout.addWidget(
                self._sys_row(sys_.name, count, self._selected_system == sys_.name)
            )
        self._sys_layout.addStretch()

    def _sys_row(self, name: str, count: int, selected: bool) -> QWidget:
        row = QWidget()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        bg = 'rgba(255,255,255,0.10)' if selected else 'transparent'
        row.setStyleSheet(f'background: {bg}; border-radius: 6px;')

        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(6)

        lbl = QLabel(name)
        f = QFont()
        f.setPointSize(9)
        f.setBold(selected)
        lbl.setFont(f)
        lbl.setStyleSheet('background: transparent; color: rgba(255,255,255,0.85);')
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        cnt = QLabel(str(count))
        cnt.setStyleSheet('background: transparent; color: rgba(255,255,255,0.35); font-size: 8px;')

        h.addWidget(lbl, 1)
        h.addWidget(cnt)

        row.mousePressEvent = lambda _e, n=name: self._select_system(
            '' if n == 'All Games' else n
        )
        return row

    # ── Game grid ─────────────────────────────────────────────────────────────

    def _rebuild_grid(self) -> None:
        query = self._search.text().lower()
        if self._selected_system:
            visible = [g for g in self._games if g.system == self._selected_system]
        else:
            visible = self._games
        if query:
            visible = [g for g in visible if query in g.name.lower()]

        self._grid.clear()

        if not visible:
            return

        for game in sorted(visible, key=lambda g: g.name.lower()):
            item = QListWidgetItem(game.name)
            item.setData(Qt.ItemDataRole.UserRole, game)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

            cached = art_cache_path(game)
            if cached.exists():
                px = _art_pixmap(str(cached))
            else:
                px = _placeholder_pixmap(game.name)
            item.setIcon(QIcon(px))
            self._grid.addItem(item)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        self._systems = load_config()
        self._games   = load_library()
        self._rebuild_sys_panel()
        self._rebuild_grid()

    def _save(self) -> None:
        save_config(self._systems)
        save_library(self._games)

    def _select_system(self, name: str) -> None:
        self._selected_system = name
        self._rebuild_sys_panel()
        self._rebuild_grid()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _add_system(self) -> None:
        dlg = _AddSystemDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sys_ = dlg.system()
        if any(s.name == sys_.name for s in self._systems):
            return
        self._systems.append(sys_)
        self._save()
        self._rebuild_sys_panel()
        self._scan()

    def _set_api_key(self) -> None:
        current = self._settings.value('tgdb_api_key', '')
        dlg = _ApiKeyDialog(current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings.setValue('tgdb_api_key', dlg.key())

    def _scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText('Scanning…')
        self._status_lbl.setText('')

        existing = {g.rom_path for g in self._games}
        self._scan_worker = _ScanWorker(self._systems, existing, self)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_scan_done(self, new_games: list[Game]) -> None:
        before = len(self._games)
        self._games = [g for g in self._games if Path(g.rom_path).exists()]
        pruned = before - len(self._games)

        self._games.extend(new_games)
        self._save()
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText('↻  Scan')
        parts = []
        if new_games:
            parts.append(f'+{len(new_games)} new')
        if pruned:
            parts.append(f'{pruned} removed')
        self._status_lbl.setText('  ·  '.join(parts) if parts else 'Up to date')
        self._rebuild_sys_panel()
        self._rebuild_grid()
        self._fetch_art()

    def _fetch_art(self) -> None:
        api_key = self._settings.value('tgdb_api_key', '')
        if not api_key:
            return
        if self._art_worker and self._art_worker.isRunning():
            return
        needs_art = [g for g in self._games if not art_cache_path(g).exists()]
        if not needs_art:
            return
        self._art_worker = _ArtWorker(needs_art, self._systems, api_key, self)
        self._art_worker.art_ready.connect(self._on_art_ready)
        self._art_worker.start()

    def _on_art_ready(self, rom_path: str, art_path: str) -> None:
        for g in self._games:
            if g.rom_path == rom_path:
                g.art_path = art_path
                break
        self._save()
        # Update the matching list item's icon in place
        for i in range(self._grid.count()):
            item = self._grid.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole).rom_path == rom_path:
                item.setIcon(QIcon(_art_pixmap(art_path)))
                break

    def _grid_context_menu(self, pos) -> None:
        item = self._grid.itemAt(pos)
        if not item:
            return
        game: Game = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        menu.setStyleSheet(
            'QMenu { background: #1e1e2e; border: 1px solid rgba(255,255,255,0.10);'
            '  color: rgba(255,255,255,0.85); border-radius: 6px; padding: 4px; }'
            ' QMenu::item { padding: 6px 20px; border-radius: 4px; }'
            ' QMenu::item:selected { background: rgba(99,102,241,0.30); }'
        )
        change_art = menu.addAction('Change Art…')
        clear_art  = menu.addAction('Clear Art')

        action = menu.exec(self._grid.mapToGlobal(pos))

        if action == change_art:
            self._change_art(item, game)
        elif action == clear_art:
            self._clear_art(item, game)

    def _change_art(self, item: QListWidgetItem, game: Game) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select Art Image', '',
            'Images (*.jpg *.jpeg *.png *.webp *.bmp)',
        )
        if not path:
            return

        dest = art_cache_path(game)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

        for g in self._games:
            if g.rom_path == game.rom_path:
                g.art_path = str(dest)
                break
        self._save()

        item.setIcon(QIcon(_art_pixmap(str(dest))))

    def _clear_art(self, item: QListWidgetItem, game: Game) -> None:
        dest = art_cache_path(game)
        if dest.exists():
            dest.unlink()
        for g in self._games:
            if g.rom_path == game.rom_path:
                g.art_path = ''
                break
        self._save()
        item.setIcon(QIcon(_placeholder_pixmap(game.name)))

    def _launch(self, item: QListWidgetItem) -> None:
        game: Game = item.data(Qt.ItemDataRole.UserRole)
        sys_ = next((s for s in self._systems if s.name == game.system), None)
        if not sys_:
            return
        subprocess.Popen([sys_.emulator_path, game.rom_path])
