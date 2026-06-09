from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from home_os_app.theme import CARD_STYLE, THEME_QSS, paint_background
from ..data import (
    Book, COVERS_DIR, cover_cache_path,
    extract_metadata_epub, extract_metadata_pdf,
    load_config, load_library, save_config, save_library, scan_folder,
)

CARD_W, CARD_H = 120, 160
GRID_W, GRID_H = CARD_W + 24, CARD_H + 80  # +80 gives room for three label lines

_SORT_BTN_QSS = (
    'QPushButton {'
    '  background: rgba(255,255,255,0.06);'
    '  border: 1px solid rgba(255,255,255,0.10);'
    '  border-radius: 5px;'
    '  color: rgba(255,255,255,0.45);'
    '  padding: 2px 10px;'
    '  font-size: 10px;'
    '}'
    'QPushButton:checked {'
    '  background: rgba(255,255,255,0.15);'
    '  color: white;'
    '  border-color: rgba(255,255,255,0.22);'
    '}'
    'QPushButton:hover { background: rgba(255,255,255,0.11); }'
)

_PLACEHOLDER_COLORS = [
    '#1e40af', '#7e22ce', '#15803d',
    '#b45309', '#be123c', '#0e7490',
]


def _placeholder_pixmap(title: str, fmt: str = '', w: int = CARD_W, h: int = CARD_H) -> QPixmap:
    px = QPixmap(w, h)
    color = _PLACEHOLDER_COLORS[abs(hash(title)) % len(_PLACEHOLDER_COLORS)]
    px.fill(QColor(color))
    p = QPainter(px)

    f = QFont()
    f.setPointSize(36)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 200))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, (title[:1] or '?').upper())

    if fmt:
        from PyQt6.QtCore import QRect
        f2 = QFont()
        f2.setPointSize(7)
        f2.setBold(True)
        p.setFont(f2)
        badge = QRect(w - 38, h - 20, 34, 16)
        p.fillRect(badge, QColor(0, 0, 0, 130))
        p.setPen(QColor(255, 255, 255, 160))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, fmt.upper())

    p.end()
    return px


def _cover_pixmap(path: str) -> QPixmap:
    px = QPixmap(path)
    if px.isNull():
        return QPixmap()
    return px.scaled(CARD_W, CARD_H,
                     Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


# ── Workers ───────────────────────────────────────────────────────────────────

class _ScanWorker(QThread):
    done = pyqtSignal(list)

    def __init__(self, folders: list[str], existing: set[str], parent=None) -> None:
        super().__init__(parent)
        self._folders  = folders
        self._existing = existing

    def run(self) -> None:
        found: list[Book] = []
        seen = set(self._existing)
        for folder in self._folders:
            for b in scan_folder(folder, seen):
                found.append(b)
                seen.add(b.path)
        self.done.emit(found)


class _MetaWorker(QThread):
    book_done = pyqtSignal(str, str, str, str)   # path, title, author, cover_path

    def __init__(self, books: list[Book], parent=None) -> None:
        super().__init__(parent)
        self._books = books

    def run(self) -> None:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        for book in self._books:
            try:
                if book.format == 'epub':
                    title, author, cover_bytes = extract_metadata_epub(book.path)
                else:
                    title, author, cover_bytes = extract_metadata_pdf(book.path)
                cover_path = ''
                if cover_bytes:
                    dest = cover_cache_path(book)
                    dest.write_bytes(cover_bytes)
                    cover_path = str(dest)
                self.book_done.emit(book.path, title, author, cover_path)
            except Exception:
                pass


# ── Main widget ───────────────────────────────────────────────────────────────

class LibraryContent(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._books: list[Book]    = []
        self._folders: list[str]   = []
        self._selected_folder: str = ''   # '' = All Books
        self._sort_mode: str       = 'title'
        self._current_book: Book | None = None
        self._scan_worker: _ScanWorker | None = None
        self._meta_worker: _MetaWorker | None = None

        self._setup_ui()
        self._load()

    def paintEvent(self, event) -> None:
        paint_background(self)

    # ── UI setup ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._make_library_page())
        self._stack.addWidget(self._make_reader_page())
        root.addWidget(self._stack)

    def _make_library_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet('background: transparent;')
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 16)
        v.setSpacing(14)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(CARD_STYLE)
        hdr_h = QHBoxLayout(hdr)
        hdr_h.setContentsMargins(20, 14, 20, 14)
        hdr_h.setSpacing(10)

        title_lbl = QLabel('eBook Library')
        tf = QFont()
        tf.setPointSize(10)
        title_lbl.setFont(tf)
        title_lbl.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        self._status_lbl = QLabel('')
        self._status_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.28); font-size: 9px; background: transparent;'
        )

        sort_box = QWidget()
        sort_box.setStyleSheet('background: transparent;')
        sort_h = QHBoxLayout(sort_box)
        sort_h.setContentsMargins(0, 0, 0, 0)
        sort_h.setSpacing(3)

        self._sort_title_btn = QPushButton('Title')
        self._sort_title_btn.setFixedHeight(28)
        self._sort_title_btn.setCheckable(True)
        self._sort_title_btn.setChecked(True)
        self._sort_title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_title_btn.setStyleSheet(_SORT_BTN_QSS)
        self._sort_title_btn.clicked.connect(lambda: self._set_sort('title'))

        self._sort_author_btn = QPushButton('Author')
        self._sort_author_btn.setFixedHeight(28)
        self._sort_author_btn.setCheckable(True)
        self._sort_author_btn.setChecked(False)
        self._sort_author_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_author_btn.setStyleSheet(_SORT_BTN_QSS)
        self._sort_author_btn.clicked.connect(lambda: self._set_sort('author'))

        sort_h.addWidget(self._sort_title_btn)
        sort_h.addWidget(self._sort_author_btn)

        self._search = QLineEdit()
        self._search.setPlaceholderText('Search books…')
        self._search.setFixedHeight(34)
        self._search.setMaximumWidth(220)
        self._search.textChanged.connect(self._rebuild_grid)

        self._scan_btn = QPushButton('↻  Scan')
        self._scan_btn.setFixedHeight(34)
        self._scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_btn.setStyleSheet(
            'QPushButton { color: #94a3b8; }'
            ' QPushButton:disabled { color: rgba(255,255,255,0.20); }'
        )
        self._scan_btn.clicked.connect(self._scan)

        add_btn = QPushButton('＋  Add Folder')
        add_btn.setFixedHeight(34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet('QPushButton { color: #4ade80; }')
        add_btn.clicked.connect(self._add_folder)

        hdr_h.addWidget(title_lbl)
        hdr_h.addWidget(self._status_lbl, 1)
        hdr_h.addWidget(sort_box)
        hdr_h.addWidget(self._search)
        hdr_h.addWidget(self._scan_btn)
        hdr_h.addWidget(add_btn)
        v.addWidget(hdr)

        # Body
        body = QHBoxLayout()
        body.setSpacing(16)
        v.addLayout(body, 1)

        # Left: folder/shelf panel
        shelf_panel = QWidget()
        shelf_panel.setStyleSheet('background: transparent;')
        shelf_panel.setFixedWidth(190)
        self._shelf_layout = QVBoxLayout(shelf_panel)
        self._shelf_layout.setContentsMargins(0, 0, 0, 0)
        self._shelf_layout.setSpacing(2)
        self._shelf_layout.addStretch()
        body.addWidget(shelf_panel)

        # Right: book cover grid
        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setIconSize(QSize(CARD_W, CARD_H))
        self._grid.setGridSize(QSize(GRID_W, GRID_H))
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setSpacing(10)
        self._grid.setWrapping(True)
        self._grid.setWordWrap(True)
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
            QListWidget::item:hover  { background: rgba(255,255,255,0.10); }
            QListWidget::item:selected { background: rgba(3,105,161,0.35); color: white; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.14);
                border-radius: 2px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._grid.itemDoubleClicked.connect(self._open_book)
        body.addWidget(self._grid, 1)

        return page

    def _make_reader_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet('background: transparent;')
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 20, 24, 0)
        v.setSpacing(14)

        # Back bar
        bar = QWidget()
        bar.setStyleSheet(CARD_STYLE)
        bar_h = QHBoxLayout(bar)
        bar_h.setContentsMargins(16, 12, 16, 12)
        bar_h.setSpacing(12)

        back_btn = QPushButton('← Library')
        back_btn.setFixedHeight(30)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet('QPushButton { color: #7dd3fc; }')
        back_btn.clicked.connect(self._close_reader)

        self._reader_title_lbl = QLabel('')
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        self._reader_title_lbl.setFont(f)
        self._reader_title_lbl.setStyleSheet('color: white; background: transparent;')
        self._reader_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._reader_author_lbl = QLabel('')
        self._reader_author_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.45); font-size: 9px; background: transparent;'
        )

        bar_h.addWidget(back_btn)
        bar_h.addWidget(self._reader_title_lbl, 1)
        bar_h.addWidget(self._reader_author_lbl)
        v.addWidget(bar)

        # Reader body — reader widget is swapped in here
        self._reader_body = QWidget()
        self._reader_body.setStyleSheet('background: transparent;')
        self._reader_body_layout = QVBoxLayout(self._reader_body)
        self._reader_body_layout.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._reader_body, 1)

        return page

    # ── Shelf panel ───────────────────────────────────────────────────────────

    def _rebuild_shelf_panel(self) -> None:
        while self._shelf_layout.count():
            item = self._shelf_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        self._shelf_layout.addWidget(
            self._shelf_row('All Books', len(self._books), self._selected_folder == '')
        )
        for folder in self._folders:
            fp = Path(folder)
            count = sum(1 for b in self._books if Path(b.path).is_relative_to(fp))
            self._shelf_layout.addWidget(
                self._shelf_row(fp.name, count, self._selected_folder == folder, folder)
            )
        self._shelf_layout.addStretch()

    def _shelf_row(self, name: str, count: int, selected: bool,
                   full_path: str = '') -> QWidget:
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

        row.mousePressEvent = lambda _e, fp=full_path: self._select_folder(fp)
        return row

    # ── Book grid ─────────────────────────────────────────────────────────────

    def _rebuild_grid(self) -> None:
        query = self._search.text().lower().strip()

        if self._selected_folder:
            fp = Path(self._selected_folder)
            visible = [b for b in self._books if Path(b.path).is_relative_to(fp)]
        else:
            visible = list(self._books)

        if query:
            visible = [b for b in visible
                       if query in b.title.lower() or query in b.author.lower()]

        if self._sort_mode == 'author':
            sort_key = lambda b: (b.author.lower(), b.title.lower())
        else:
            sort_key = lambda b: b.title.lower()

        self._grid.clear()
        for book in sorted(visible, key=sort_key):
            label = book.title if len(book.title) <= 44 else book.title[:42] + '…'
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, book)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

            cached = cover_cache_path(book)
            if cached.exists():
                px = _cover_pixmap(str(cached))
            else:
                px = _placeholder_pixmap(book.title, book.format)
            item.setIcon(QIcon(px))
            self._grid.addItem(item)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        self._folders = load_config()
        self._books   = load_library()
        self._rebuild_shelf_panel()
        self._rebuild_grid()
        # Fetch covers for any books that don't have them yet (e.g. if deps were
        # missing on a previous scan, or this is the first run after install).
        self._fetch_metadata(self._books)

    def _save(self) -> None:
        save_config(self._folders)
        save_library(self._books)

    def _set_sort(self, mode: str) -> None:
        self._sort_mode = mode
        self._sort_title_btn.setChecked(mode == 'title')
        self._sort_author_btn.setChecked(mode == 'author')
        self._rebuild_grid()

    def _select_folder(self, folder: str) -> None:
        self._selected_folder = folder
        self._rebuild_shelf_panel()
        self._rebuild_grid()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, 'Select eBook Folder')
        if not folder or folder in self._folders:
            return
        self._folders.append(folder)
        self._save()
        self._rebuild_shelf_panel()
        self._scan()

    def _scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        if not self._folders:
            self._status_lbl.setText('Add a folder first')
            return
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText('Scanning…')
        self._status_lbl.setText('')

        existing = {b.path for b in self._books}
        self._scan_worker = _ScanWorker(self._folders, existing, self)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_scan_done(self, new_books: list[Book]) -> None:
        before = len(self._books)
        self._books = [b for b in self._books if Path(b.path).exists()]
        pruned = before - len(self._books)

        self._books.extend(new_books)
        self._save()
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText('↻  Scan')

        parts = []
        if new_books:
            parts.append(f'+{len(new_books)} new')
        if pruned:
            parts.append(f'{pruned} removed')
        self._status_lbl.setText('  ·  '.join(parts) if parts else 'Up to date')

        self._rebuild_shelf_panel()
        self._rebuild_grid()
        self._fetch_metadata(new_books)

    def _fetch_metadata(self, books: list[Book]) -> None:
        if self._meta_worker and self._meta_worker.isRunning():
            return
        needs = [b for b in books if not cover_cache_path(b).exists()]
        if not needs:
            return
        self._meta_worker = _MetaWorker(needs, self)
        self._meta_worker.book_done.connect(self._on_meta_done)
        self._meta_worker.start()

    def _on_meta_done(self, path: str, title: str, author: str, cover_path: str) -> None:
        for b in self._books:
            if b.path == path:
                b.title      = title
                b.author     = author
                b.cover_path = cover_path
                break
        self._save()
        self._rebuild_grid()

    def _open_book(self, item: QListWidgetItem) -> None:
        book: Book = item.data(Qt.ItemDataRole.UserRole)
        self._current_book = book

        # Clean up any existing reader
        while self._reader_body_layout.count():
            child = self._reader_body_layout.takeAt(0)
            if w := child.widget():
                if hasattr(w, 'cleanup'):
                    w.cleanup()
                w.deleteLater()

        self._reader_title_lbl.setText(book.title)
        self._reader_author_lbl.setText(book.author or '')

        from .reader_epub import EPUBReader
        from .reader_pdf  import PDFReader

        if book.format == 'epub':
            reader = EPUBReader(book.path, book.last_position, self)
        else:
            reader = PDFReader(book.path, book.last_position, self)

        reader.position_changed.connect(self._on_position_changed)
        self._reader_body_layout.addWidget(reader)
        self._stack.setCurrentIndex(1)

    def _close_reader(self) -> None:
        self._stack.setCurrentIndex(0)
        while self._reader_body_layout.count():
            child = self._reader_body_layout.takeAt(0)
            if w := child.widget():
                if hasattr(w, 'cleanup'):
                    w.cleanup()
                w.deleteLater()

    def _on_position_changed(self, pos: int) -> None:
        if self._current_book is None:
            return
        for b in self._books:
            if b.path == self._current_book.path:
                b.last_position = pos
                break
        self._current_book.last_position = pos
        save_library(self._books)
