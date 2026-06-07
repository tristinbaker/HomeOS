from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QTreeView, QListView, QStyledItemDelegate, QStyle, QHeaderView,
    QPushButton, QLabel, QProgressBar, QTreeWidget, QTreeWidgetItem, QLineEdit,
)
from PyQt6.QtCore import Qt, QSize, QModelIndex, QAbstractListModel, pyqtSignal, QRect, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap

from ..library import AlbumListModel, ArtistListModel


# ── Shared grid delegate base ────────────────────────────────────────────────

class _GridDelegate(QStyledItemDelegate):
    """Base delegate for the album/artist grid — subclasses supply the image."""

    _ITEM_W = 160
    _ITEM_H = 180

    def _get_pixmap(self, index) -> QPixmap | None:
        raise NotImplementedError

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        label = index.data(Qt.ItemDataRole.DisplayRole) or ''

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, option.palette.alternateBase())

        padding = 8
        w = rect.width() - 2 * padding
        art_size = min(w, 120)
        art_x = rect.left() + (rect.width() - art_size) // 2
        art_y = rect.top() + padding
        art_rect = QRect(art_x, art_y, art_size, art_size)

        pm = self._get_pixmap(index)
        if pm is not None:
            scaled = pm.scaled(
                art_size, art_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = art_rect.center().x() - scaled.width() // 2
            y = art_rect.center().y() - scaled.height() // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 24, 60))
            painter.drawRoundedRect(art_rect, 6, 6)

        painter.setPen(QColor(255, 255, 255))
        name_rect = QRect(
            rect.left() + padding, art_rect.bottom() + padding,
            w, rect.bottom() - art_rect.bottom() - padding * 2,
        )
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            label,
        )
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(self._ITEM_W, self._ITEM_H)


class AlbumDelegate(_GridDelegate):
    def __init__(self, album_model, parent=None):
        super().__init__(parent)
        self._album_model = album_model
        self._pixmaps: dict = {}
        album_model.modelReset.connect(self._pixmaps.clear)

    def _get_pixmap(self, index) -> QPixmap | None:
        name = index.data(Qt.ItemDataRole.DisplayRole) or ''
        pm = self._pixmaps.get(name)
        if pm is None:
            cover_path = self._album_model.cover_path(index)
            if cover_path:
                raw = QPixmap(cover_path)
                if not raw.isNull():
                    pm = raw
                    self._pixmaps[name] = pm
        return pm


class ArtistDelegate(_GridDelegate):
    def __init__(self, artist_model, parent=None):
        super().__init__(parent)
        self._artist_model = artist_model
        self._pixmaps: dict = {}
        artist_model.modelReset.connect(self._pixmaps.clear)

    def _get_pixmap(self, index) -> QPixmap | None:
        name = index.data(Qt.ItemDataRole.DisplayRole) or ''
        pm = self._pixmaps.get(name)
        if pm is None:
            img_path = self._artist_model.image_path(index)
            if img_path:
                raw = QPixmap(img_path)
                if not raw.isNull():
                    pm = raw
                    self._pixmaps[name] = pm
        return pm

    def on_image_ready(self, artist_name):
        self._pixmaps.pop(artist_name, None)


# ── Album detail panel ───────────────────────────────────────────────────────

class AlbumDetailPanel(QWidget):
    play_requested = pyqtSignal(list, int)
    back_requested = pyqtSignal()
    artist_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks = []

        back_btn = QPushButton("← Back")
        back_btn.setFlat(True)
        back_btn.clicked.connect(self.back_requested)

        self._art_label = QLabel()
        self._art_label.setFixedSize(200, 200)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet("background: rgba(30, 24, 60, 0.9); border-radius: 8px;")

        self._title_label = QLabel()
        title_font = self._title_label.font()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)

        self._artist_btn = QPushButton()
        self._artist_btn.setFlat(True)
        self._artist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._artist_btn.clicked.connect(
            lambda: self.artist_clicked.emit(self._artist_btn.text())
        )

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(12, 0, 0, 0)
        info_layout.addWidget(self._title_label)
        info_layout.addWidget(self._artist_btn)
        info_layout.addStretch()

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._art_label)
        header_layout.addLayout(info_layout, 1)

        self._track_view = QTreeWidget()
        self._track_view.setColumnCount(3)
        self._track_view.setHeaderLabels(['#', 'Title', ''])
        self._track_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._track_view.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._track_view.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._track_view.header().setStretchLastSection(False)
        self._track_view.setRootIsDecorated(False)
        self._track_view.setAlternatingRowColors(True)
        self._track_view.setStyleSheet(
            "QTreeWidget::item:selected,"
            "QTreeWidget::item:selected:!active {"
            "  background-color: rgba(29, 78, 216, 0.55);"
            "  color: white;"
            "}"
        )
        self._track_view.itemDoubleClicked.connect(self._on_track_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(header_layout)
        layout.addWidget(self._track_view, 1)
        self.setLayout(layout)

    def load_album(self, album_name, tracks, cover_path):
        self._tracks = tracks
        artist = tracks[0].artist if tracks else 'Unknown Artist'
        self._title_label.setText(album_name)
        self._artist_btn.setText(artist)

        if cover_path:
            pm = QPixmap(cover_path).scaled(
                200, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._art_label.setPixmap(pm)
            self._art_label.setStyleSheet('')
        else:
            self._art_label.clear()
            self._art_label.setStyleSheet("background: rgba(30, 24, 60, 0.9); border-radius: 8px;")

        self._track_view.clear()
        for i, track in enumerate(tracks):
            dur = int(track.duration)
            num = f"{track.track_number:02d}" if track.track_number else f"{i + 1:02d}"
            item = QTreeWidgetItem([num, track.title, f"{dur // 60}:{dur % 60:02d}"])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._track_view.addTopLevelItem(item)

    def set_playing_track(self, track):
        self._track_view.clearSelection()
        if track is None:
            return
        for i in range(self._track_view.topLevelItemCount()):
            item = self._track_view.topLevelItem(i)
            idx = item.data(0, Qt.ItemDataRole.UserRole)
            if idx is not None and 0 <= idx < len(self._tracks):
                if self._tracks[idx].path == track.path:
                    self._track_view.setCurrentItem(item)
                    self._track_view.scrollToItem(item)
                    return

    def _on_track_double_clicked(self, item, _column):
        start = item.data(0, Qt.ItemDataRole.UserRole)
        if start is not None:
            self.play_requested.emit(self._tracks, start)


# ── Artist detail panel ──────────────────────────────────────────────────────

class _ArtistAlbumModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._albums = []

    def load(self, albums):
        self.beginResetModel()
        self._albums = list(albums)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._albums)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        album_name, tracks, _ = self._albums[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return album_name
        if role == Qt.ItemDataRole.UserRole:
            return tracks
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def cover_path(self, index):
        if not index.isValid():
            return None
        _, _, path = self._albums[index.row()]
        return path

    def album_tracks_from_index(self, index):
        if not index.isValid():
            return [], -1
        _, tracks, _ = self._albums[index.row()]
        return tracks, 0


class ArtistDetailPanel(QWidget):
    album_selected = pyqtSignal(str, list, object)
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        back_btn = QPushButton("← Back")
        back_btn.setFlat(True)
        back_btn.clicked.connect(self.back_requested)

        self._artist_photo = QLabel()
        self._artist_photo.setFixedSize(120, 120)
        self._artist_photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._artist_photo.setStyleSheet("background: rgba(30, 24, 60, 0.9); border-radius: 60px;")

        self._artist_label = QLabel()
        artist_font = self._artist_label.font()
        artist_font.setPointSize(artist_font.pointSize() + 6)
        artist_font.setBold(True)
        self._artist_label.setFont(artist_font)
        self._artist_label.setWordWrap(True)

        header_right = QVBoxLayout()
        header_right.setContentsMargins(12, 0, 0, 0)
        header_right.addWidget(self._artist_label)
        header_right.addStretch()

        header_layout = QHBoxLayout()
        header_layout.addWidget(self._artist_photo)
        header_layout.addLayout(header_right, 1)

        self._album_model = _ArtistAlbumModel()

        self._grid_view = QListView()
        self._grid_view.setModel(self._album_model)
        self._grid_view.setViewMode(QListView.ViewMode.IconMode)
        self._grid_view.setMovement(QListView.Movement.Static)
        self._grid_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid_view.setUniformItemSizes(True)
        self._grid_view.setWordWrap(True)
        self._grid_view.setSpacing(8)
        self._grid_view.setItemDelegate(AlbumDelegate(self._album_model))
        self._grid_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._grid_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_view.doubleClicked.connect(self._on_album_double_click)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(header_layout)
        layout.addWidget(self._grid_view, 1)
        self.setLayout(layout)

    def load_artist(self, artist_name, albums, artist_image_path=None):
        """albums: list of (album_name, tracks, cover_path)."""
        self._artist_label.setText(artist_name)
        self._album_model.load(albums)

        if artist_image_path:
            pm = QPixmap(artist_image_path).scaled(
                120, 120,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._artist_photo.setPixmap(pm)
            self._artist_photo.setStyleSheet("border-radius: 60px;")
        else:
            self._artist_photo.clear()
            self._artist_photo.setStyleSheet(
                "background: rgba(30, 24, 60, 0.9); border-radius: 60px;"
            )

    def _on_album_double_click(self, index):
        album_name = self._album_model.data(index, Qt.ItemDataRole.DisplayRole)
        tracks, _ = self._album_model.album_tracks_from_index(index)
        if tracks:
            cover_path = self._album_model.cover_path(index)
            self.album_selected.emit(album_name, tracks, cover_path)


# ── Main library panel ───────────────────────────────────────────────────────

_IDX_TREE = 0
_IDX_ALBUM_GRID = 1
_IDX_ALBUM_DETAIL = 2
_IDX_ARTIST_DETAIL = 3
_IDX_ARTIST_GRID = 4
_IDX_SEARCH = 5
_IDX_LOADING = 6


class LibraryPanel(QWidget):
    play_album_requested = pyqtSignal(list, int)
    album_detail_opened = pyqtSignal(str)   # album_name — emitted whenever detail view shown
    tracks_loaded = pyqtSignal()            # emitted once after _do_set_tracks completes

    def __init__(self, tree_model, parent=None):
        super().__init__(parent)
        self._tree_model = tree_model
        self._album_model = AlbumListModel(self)
        self._artist_model = ArtistListModel(self)
        self._nav_stack = []
        self._current_playing_track = None
        self._pre_search_idx = _IDX_ALBUM_GRID
        self._current_sort_mode = 'artist'
        self._search_cover_cache: dict = {}  # album_name → scaled QPixmap (48×48)

        # Debounce timer: only run search 150ms after the user stops typing
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._run_search_debounced)

        # Search bar
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText('Search artists, albums, tracks…')
        self._search_bar.setClearButtonEnabled(True)
        self._search_bar.textChanged.connect(self._on_search_changed)

        # Tree view (artist-tree mode, kept as fallback)
        self._tree_view = QTreeView()
        self._tree_view.setModel(tree_model)
        self._tree_view.setAnimated(True)
        self._tree_view.setHeaderHidden(False)
        self._tree_view.setUniformRowHeights(True)
        self._tree_view.setExpandsOnDoubleClick(False)
        self._tree_view.header().setStretchLastSection(True)
        self._tree_view.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._tree_view.doubleClicked.connect(self._on_tree_double_click)

        # Album grid view
        self._grid_view = QListView()
        self._grid_view.setModel(self._album_model)
        self._grid_view.setViewMode(QListView.ViewMode.IconMode)
        self._grid_view.setMovement(QListView.Movement.Static)
        self._grid_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid_view.setUniformItemSizes(True)
        self._grid_view.setWordWrap(True)
        self._grid_view.setSpacing(8)
        self._grid_view.setItemDelegate(AlbumDelegate(self._album_model))
        self._grid_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._grid_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_view.doubleClicked.connect(self._on_grid_double_click)

        # Album detail panel
        self._detail_panel = AlbumDetailPanel()
        self._detail_panel.back_requested.connect(self._navigate_back)
        self._detail_panel.play_requested.connect(self.play_album_requested)
        self._detail_panel.artist_clicked.connect(self._navigate_to_artist)

        # Artist detail panel
        self._artist_panel = ArtistDetailPanel()
        self._artist_panel.back_requested.connect(self._navigate_back)
        self._artist_panel.album_selected.connect(self._on_artist_album_selected)

        # Artist photo grid view
        self._artist_grid_view = QListView()
        self._artist_grid_view.setModel(self._artist_model)
        self._artist_grid_view.setViewMode(QListView.ViewMode.IconMode)
        self._artist_grid_view.setMovement(QListView.Movement.Static)
        self._artist_grid_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._artist_grid_view.setUniformItemSizes(True)
        self._artist_grid_view.setWordWrap(True)
        self._artist_grid_view.setSpacing(8)
        self._artist_delegate = ArtistDelegate(self._artist_model)
        self._artist_grid_view.setItemDelegate(self._artist_delegate)
        self._artist_grid_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._artist_grid_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._artist_grid_view.doubleClicked.connect(self._on_artist_grid_double_click)
        self._artist_model.dataChanged.connect(self._on_artist_image_updated)

        # Search results
        self._search_results = QTreeWidget()
        self._search_results.setHeaderHidden(True)
        self._search_results.setRootIsDecorated(True)
        self._search_results.setIndentation(16)
        self._search_results.setIconSize(QSize(48, 48))
        self._search_results.itemClicked.connect(self._on_search_activated)

        # Loading page shown while models are being populated
        _loading_page = QWidget()
        _loading_layout = QVBoxLayout(_loading_page)
        _loading_layout.addStretch(1)
        _loading_lbl = QLabel('Loading library…')
        _loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _loading_lbl.setStyleSheet('color: rgba(255,255,255,0.6); font-size: 13px;')
        self._loading_bar = QProgressBar()
        self._loading_bar.setRange(0, 0)   # indeterminate
        self._loading_bar.setMaximumWidth(260)
        self._loading_bar.setFixedHeight(6)
        self._loading_bar.setTextVisible(False)
        self._loading_bar.setStyleSheet(
            'QProgressBar { background: rgba(255,255,255,0.1); border-radius: 3px; border: none; }'
            'QProgressBar::chunk { background: #1d4ed8; border-radius: 3px; }'
        )
        _loading_layout.addWidget(_loading_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        _loading_layout.addSpacing(10)
        _loading_layout.addWidget(self._loading_bar, 0, Qt.AlignmentFlag.AlignCenter)
        _loading_layout.addStretch(1)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._tree_view)         # 0
        self._stack.addWidget(self._grid_view)          # 1
        self._stack.addWidget(self._detail_panel)       # 2
        self._stack.addWidget(self._artist_panel)       # 3
        self._stack.addWidget(self._artist_grid_view)   # 4
        self._stack.addWidget(self._search_results)     # 5
        self._stack.addWidget(_loading_page)            # 6

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._stack, 1)
        self.setLayout(layout)

    # ── Navigation ────────────────────────────────────────────────────────

    def _navigate_to(self, index):
        self._nav_stack.append(self._stack.currentIndex())
        self._stack.setCurrentIndex(index)

    def _navigate_back(self):
        if self._nav_stack:
            self._stack.setCurrentIndex(self._nav_stack.pop())

    def _navigate_to_artist(self, artist_name):
        # Use the artist model's already-expanded track list so compound tags
        # like "X & Y" are correctly attributed to both X and Y.
        artist_track_paths: set = set()
        artist_img = None
        for row in range(self._artist_model.rowCount()):
            idx = self._artist_model.index(row, 0)
            if self._artist_model.artist_name_from_index(idx) == artist_name:
                artist_track_paths = {
                    t.path for t in self._artist_model.artist_tracks_from_index(idx)
                }
                artist_img = self._artist_model.image_path(idx)
                break

        albums = []
        for row in range(self._album_model.rowCount()):
            idx = self._album_model.index(row, 0)
            album_tracks = self._album_model.data(idx, Qt.ItemDataRole.UserRole)
            if album_tracks and any(t.path in artist_track_paths for t in album_tracks):
                album_name = self._album_model.data(idx, Qt.ItemDataRole.DisplayRole)
                cover_path = self._album_model.cover_path(idx)
                albums.append((album_name, album_tracks, cover_path))
        albums.sort(key=lambda x: x[0].lower())

        self._artist_panel.load_artist(artist_name, albums, artist_img)
        self._navigate_to(_IDX_ARTIST_DETAIL)

    def _on_artist_album_selected(self, album_name, tracks, cover_path):
        self._detail_panel.load_album(album_name, tracks, cover_path)
        self._detail_panel.set_playing_track(self._current_playing_track)
        self._navigate_to(_IDX_ALBUM_DETAIL)
        self.album_detail_opened.emit(album_name)

    # ── Public interface ───────────────────────────────────────────────────

    def set_tracks(self, tracks):
        self._stack.setCurrentIndex(_IDX_LOADING)
        # Yield to the event loop so the loading page renders before the
        # blocking model-population work (os.path.exists × albums/artists) starts.
        QTimer.singleShot(0, lambda: self._do_set_tracks(tracks))

    def _do_set_tracks(self, tracks):
        self._album_model.load_tracks(tracks)
        self._artist_model.load_tracks(tracks)
        self.set_sort_mode(self._current_sort_mode)
        self.tracks_loaded.emit()

    def set_sort_mode(self, mode):
        self._current_sort_mode = mode
        self._nav_stack.clear()
        if mode == 'album':
            self._stack.setCurrentIndex(_IDX_ALBUM_GRID)
        else:
            self._stack.setCurrentIndex(_IDX_ARTIST_GRID)

    def navigate_to_album(self, album_name: str):
        """Re-open the album detail view for the given album name."""
        for row in range(self._album_model.rowCount()):
            idx = self._album_model.index(row, 0)
            if self._album_model.data(idx, Qt.ItemDataRole.DisplayRole) == album_name:
                tracks, _ = self._album_model.album_tracks_from_index(idx)
                if tracks:
                    cover = self._album_model.cover_path(idx)
                    self._detail_panel.load_album(album_name, tracks, cover)
                    self._detail_panel.set_playing_track(self._current_playing_track)
                    self._navigate_to(_IDX_ALBUM_DETAIL)
                return

    def expandToDepth(self, depth):
        self._tree_view.expandToDepth(depth)

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, text):
        text = text.strip()
        if not text:
            self._search_timer.stop()
            self._stack.setCurrentIndex(self._pre_search_idx)
            return
        if self._stack.currentIndex() != _IDX_SEARCH:
            self._pre_search_idx = self._stack.currentIndex()
            self._stack.setCurrentIndex(_IDX_SEARCH)
        self._search_timer.start()  # restarts the 150ms countdown on each keystroke

    def _run_search_debounced(self):
        text = self._search_bar.text().strip()
        if text:
            self._run_search(text)

    _MAX_ARTISTS = 6
    _MAX_ALBUMS = 6
    _MAX_TRACKS = 15

    def _run_search(self, query):
        q = query.lower()
        tracks = self._tree_model.all_tracks()

        artist_hits: dict = {}  # lowercase_key -> best display name
        album_hits: dict = {}
        track_hits: list = []

        for t in tracks:
            if q in t.artist.lower():
                key = t.artist.lower()
                existing = artist_hits.get(key)
                if existing is None or (t.artist[:1].isupper() and not existing[:1].isupper()):
                    artist_hits[key] = t.artist
            if q in t.album.lower():
                album_hits.setdefault((t.album, t.artist), True)
            if q in t.title.lower():
                track_hits.append(t)

        # Sort all hits then slice — the widget only ever gets a small fixed
        # number of items regardless of library size, keeping item creation fast.
        sorted_artists = sorted(artist_hits.values(), key=str.lower)
        sorted_albums = sorted(album_hits)
        sorted_tracks = sorted(track_hits, key=lambda x: x.title.lower())

        artist_overflow = max(0, len(sorted_artists) - self._MAX_ARTISTS)
        album_overflow = max(0, len(sorted_albums) - self._MAX_ALBUMS)
        track_overflow = max(0, len(sorted_tracks) - self._MAX_TRACKS)

        sorted_artists = sorted_artists[:self._MAX_ARTISTS]
        sorted_albums = sorted_albums[:self._MAX_ALBUMS]
        sorted_tracks = sorted_tracks[:self._MAX_TRACKS]

        self._search_results.setUpdatesEnabled(False)
        self._search_results.clear()

        header_font = self._search_results.font()
        header_font.setBold(True)
        dim_color = QColor(180, 180, 180)

        if sorted_artists:
            group = QTreeWidgetItem(['Artists'])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setFont(0, header_font)
            for name in sorted_artists:
                item = QTreeWidgetItem([name])
                item.setData(0, Qt.ItemDataRole.UserRole, ('artist', name))
                group.addChild(item)
            if artist_overflow:
                more = QTreeWidgetItem([f'… and {artist_overflow} more'])
                more.setFlags(Qt.ItemFlag.ItemIsEnabled)
                more.setForeground(0, dim_color)
                group.addChild(more)
            self._search_results.addTopLevelItem(group)
            group.setExpanded(True)

        if sorted_albums:
            group = QTreeWidgetItem(['Albums'])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setFont(0, header_font)
            for album, artist in sorted_albums:
                item = QTreeWidgetItem([f"{album}  —  {artist}"])
                item.setData(0, Qt.ItemDataRole.UserRole, ('album', album, artist))
                pm = self._search_cover_cache.get(album)
                if pm is None:
                    cover = self._album_model.cover_path_by_name(album)
                    if cover:
                        raw = QPixmap(cover)
                        if not raw.isNull():
                            pm = raw.scaled(
                                48, 48,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            self._search_cover_cache[album] = pm
                if pm is not None:
                    item.setIcon(0, QIcon(pm))
                group.addChild(item)
            if album_overflow:
                more = QTreeWidgetItem([f'… and {album_overflow} more'])
                more.setFlags(Qt.ItemFlag.ItemIsEnabled)
                more.setForeground(0, dim_color)
                group.addChild(more)
            self._search_results.addTopLevelItem(group)
            group.setExpanded(True)

        if sorted_tracks:
            group = QTreeWidgetItem(['Tracks'])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setFont(0, header_font)
            for t in sorted_tracks:
                item = QTreeWidgetItem([f"{t.title}  —  {t.artist}"])
                item.setData(0, Qt.ItemDataRole.UserRole, ('track', t))
                group.addChild(item)
            if track_overflow:
                more = QTreeWidgetItem([f'… and {track_overflow} more'])
                more.setFlags(Qt.ItemFlag.ItemIsEnabled)
                more.setForeground(0, dim_color)
                group.addChild(more)
            self._search_results.addTopLevelItem(group)
            group.setExpanded(True)

        if not sorted_artists and not sorted_albums and not sorted_tracks:
            self._search_results.addTopLevelItem(QTreeWidgetItem(['No results']))

        self._search_results.setUpdatesEnabled(True)

    def _on_search_activated(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        self._search_bar.clear()
        kind = data[0]
        if kind == 'artist':
            self._navigate_to_artist(data[1])
        elif kind == 'album':
            album_name, artist = data[1], data[2]
            for row in range(self._album_model.rowCount()):
                idx = self._album_model.index(row, 0)
                if self._album_model.data(idx) == album_name:
                    tracks, _ = self._album_model.album_tracks_from_index(idx)
                    cover = self._album_model.cover_path(idx)
                    self._detail_panel.load_album(album_name, tracks, cover)
                    self._detail_panel.set_playing_track(self._current_playing_track)
                    self._navigate_to(_IDX_ALBUM_DETAIL)
                    self.album_detail_opened.emit(album_name)
                    break
        elif kind == 'track':
            t = data[1]
            # Find the full album so we can open the album detail screen
            for row in range(self._album_model.rowCount()):
                idx = self._album_model.index(row, 0)
                album_tracks = self._album_model.data(idx, Qt.ItemDataRole.UserRole)
                if album_tracks and any(tr.path == t.path for tr in album_tracks):
                    album_name = self._album_model.data(idx, Qt.ItemDataRole.DisplayRole)
                    cover = self._album_model.cover_path(idx)
                    start = next(i for i, tr in enumerate(album_tracks) if tr.path == t.path)
                    self._detail_panel.load_album(album_name, album_tracks, cover)
                    self._detail_panel.set_playing_track(None)
                    self._navigate_to(_IDX_ALBUM_DETAIL)
                    self.play_album_requested.emit(album_tracks, start)
                    return
            # Fallback if album not found in model
            self.play_album_requested.emit([t], 0)

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_tree_double_click(self, index):
        artist_name, albums = self._tree_model.artist_albums_from_index(index)
        if artist_name:
            album_data = [
                (name, tracks, self._album_model.cover_path_by_name(name))
                for name, tracks in albums
            ]
            artist_img = None
            for row in range(self._artist_model.rowCount()):
                idx = self._artist_model.index(row, 0)
                if self._artist_model.artist_name_from_index(idx) == artist_name:
                    artist_img = self._artist_model.image_path(idx)
                    break
            self._artist_panel.load_artist(artist_name, album_data, artist_img)
            self._navigate_to(_IDX_ARTIST_DETAIL)
            return
        tracks, start = self._tree_model.album_tracks_from_index(index)
        if tracks:
            self.play_album_requested.emit(tracks, start)

    def _on_grid_double_click(self, index):
        album_name = self._album_model.data(index, Qt.ItemDataRole.DisplayRole)
        tracks, _ = self._album_model.album_tracks_from_index(index)
        if not tracks:
            return
        cover_path = self._album_model.cover_path(index)
        self._detail_panel.load_album(album_name, tracks, cover_path)
        self._detail_panel.set_playing_track(self._current_playing_track)
        self._navigate_to(_IDX_ALBUM_DETAIL)
        self.album_detail_opened.emit(album_name)

    def _on_artist_grid_double_click(self, index):
        artist_name = self._artist_model.artist_name_from_index(index)
        if artist_name:
            self._navigate_to_artist(artist_name)

    def _on_artist_image_updated(self, top_left, bottom_right, _roles=None):
        # Flush the delegate's pixmap cache for updated artists so it repaints
        for row in range(top_left.row(), bottom_right.row() + 1):
            idx = self._artist_model.index(row, 0)
            name = self._artist_model.artist_name_from_index(idx)
            self._artist_delegate.on_image_ready(name)

    def on_track_changed(self, track):
        self._current_playing_track = track
        self._detail_panel.set_playing_track(track)
