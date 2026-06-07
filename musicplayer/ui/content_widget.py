import os
import time

from PyQt6.QtWidgets import (
    QFileDialog, QSplitter, QWidget, QVBoxLayout,
    QProgressBar, QMenu,
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QThread, QStandardPaths, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QKeySequence, QLinearGradient, QPainter

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
    QTreeView::item, QListView::item, QTreeWidget::item, QListWidget::item {
        padding: 3px 6px;
    }
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
    QPushButton:pressed  { background: rgba(255, 255, 255, 0.04); }
    QPushButton:checked  {
        background: rgba(29, 78, 216, 0.6);
        border-color: rgba(80, 120, 240, 0.9);
    }
    QPushButton:disabled {
        color: rgba(255, 255, 255, 0.25);
        background: rgba(255, 255, 255, 0.03);
        border-color: rgba(255, 255, 255, 0.05);
    }
    QPushButton:flat {
        background: transparent;
        border: none;
        padding: 4px 8px;
    }
    QPushButton:flat:hover {
        background: rgba(255, 255, 255, 0.1);
        border-radius: 4px;
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
        background: transparent;
        width: 6px;
        margin: 2px 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 3px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover  { background: rgba(255, 255, 255, 0.35); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical  { height: 0; border: none; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical  { background: none; }
    QScrollBar:horizontal {
        background: transparent;
        height: 6px;
        margin: 0 2px;
    }
    QScrollBar::handle:horizontal {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 3px;
        min-width: 24px;
    }
    QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 0.35); }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

    QProgressBar {
        background: rgba(255, 255, 255, 0.1);
        border: none;
        border-radius: 4px;
        color: white;
        text-align: center;
        font-size: 11px;
    }
    QProgressBar::chunk {
        background: #1d4ed8;
        border-radius: 4px;
    }

    QSplitter::handle:horizontal {
        background: rgba(255, 255, 255, 0.06);
        width: 1px;
    }
"""

from ..lastfm import LastFMClient
from ..library import LibraryModel, ScanWorker, save_library_cache, load_library_cache
from ..playback import PlayerController
from .lastfm_auth_dialog import LastFMAuthDialog
from .lastfm_setup_dialog import LastFMSetupDialog
from .library_panel import LibraryPanel
from .lyrics_panel import LyricsPanel
from .player_bar import PlayerBar


class MusicPlayerContent(QWidget):
    title_changed = pyqtSignal(str)
    status_message = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings('MusicPlayer', 'MusicPlayer')
        self.library_model = LibraryModel(self)
        self.player = PlayerController(self)
        self.lastfm = LastFMClient()
        cache_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        self._cache_path = os.path.join(cache_dir, 'library_cache.json')

        self._scrobble_track = None
        self._scrobble_start_time = 0.0
        self._scrobble_threshold_ms = 0
        self._scrobbled = False

        self._scan_thread = None
        self._scan_worker = None
        self._is_scanning = False
        self._scan_path = ''

        # Restore volume before PlayerBar is constructed — it reads player.volume on init.
        saved_vol = int(self.settings.value('volume', 50))
        self.player.set_volume(saved_vol)

        self._setup_actions()
        self._setup_ui()
        self._connect_signals()
        self.setStyleSheet(_THEME_QSS)

        QTimer.singleShot(0, self._restore_state)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor('#0f0c29'))
        gradient.setColorAt(0.5, QColor('#302b63'))
        gradient.setColorAt(1.0, QColor('#24243e'))
        painter.fillRect(self.rect(), QBrush(gradient))

    def _setup_actions(self):
        self._open_action = QAction('&Open Folder\u2026', self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self._open_folder)

        self._refresh_action = QAction('&Refresh Library', self)
        self._refresh_action.setShortcut(QKeySequence('Ctrl+R'))
        self._refresh_action.triggered.connect(self._refresh_library)

        self._sort_action = QAction('Sort by &Artist', self)
        self._sort_action.setCheckable(True)
        self._sort_action.setChecked(True)
        self._sort_action.setShortcut(QKeySequence('Ctrl+Shift+A'))
        self._sort_action.toggled.connect(self._toggle_sort)

        self._lastfm_connect_action = QAction('Connect to Last.FM\u2026', self)
        self._lastfm_connect_action.triggered.connect(self._on_connect_lastfm)

        self._lastfm_disconnect_action = QAction('Disconnect Last.FM', self)
        self._lastfm_disconnect_action.triggered.connect(self._on_disconnect_lastfm)
        self._lastfm_disconnect_action.setVisible(False)

        self._lastfm_reset_api_action = QAction('Reset API Credentials\u2026', self)
        self._lastfm_reset_api_action.triggered.connect(self._on_reset_api_credentials)

    def menus(self, parent=None) -> list[QMenu]:
        file_menu = QMenu('&File', parent)
        file_menu.addAction(self._open_action)
        file_menu.addSeparator()
        file_menu.addAction(self._refresh_action)
        file_menu.addSeparator()

        view_menu = QMenu('&View', parent)
        view_menu.addAction(self._sort_action)

        account_menu = QMenu('&Account', parent)
        account_menu.addAction(self._lastfm_connect_action)
        account_menu.addAction(self._lastfm_disconnect_action)
        account_menu.addSeparator()
        account_menu.addAction(self._lastfm_reset_api_action)

        return [file_menu, view_menu, account_menu]

    def _setup_ui(self):
        self.library_panel = LibraryPanel(self.library_model, self)
        self.library_panel.set_sort_mode(LibraryModel.SORT_ALBUM)
        self.library_model.set_sort_mode(LibraryModel.SORT_ALBUM)
        self.player_bar = PlayerBar(self.player, self)
        self.lyrics_panel = LyricsPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.library_panel)
        splitter.addWidget(self.lyrics_panel)
        self.lyrics_panel.setVisible(False)

        self._scan_progress = QProgressBar()
        self._scan_progress.setMaximumWidth(200)
        self._scan_progress.setFixedHeight(16)
        self._scan_progress.setVisible(False)
        self._scan_progress.setTextVisible(True)

        progress_row = QWidget()
        progress_layout = QVBoxLayout(progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(0)
        progress_layout.addWidget(self._scan_progress)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter, 1)
        layout.addWidget(progress_row, 0)
        layout.addWidget(self.player_bar, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(central)

    def _toggle_sort(self, by_album):
        mode = LibraryModel.SORT_ALBUM if by_album else LibraryModel.SORT_ARTIST
        self.library_model.set_sort_mode(mode)
        self.library_panel.set_sort_mode(mode)
        self._sort_action.setText('Sort by &Artist' if by_album else 'Sort by &Album')
        self.settings.setValue('sort_mode', 'album' if by_album else 'artist')

    def _connect_signals(self):
        self.library_panel.play_album_requested.connect(self._play_album)
        self.player_bar.lyrics_btn.toggled.connect(self._toggle_lyrics)
        self.player_bar.love_btn.toggled.connect(self._on_love_toggled)
        self.player.track_changed.connect(self._on_track_for_lyrics)
        self.player.track_changed.connect(self._on_track_for_lastfm)
        self.player.track_changed.connect(self.library_panel.on_track_changed)
        self.player.position_changed.connect(self._on_position_changed)
        self.lyrics_panel.seek_requested.connect(self.player.seek)
        self.player.volume_changed.connect(lambda v: self.settings.setValue('volume', v))
        self.library_panel.album_detail_opened.connect(
            lambda name: self.settings.setValue('last_album', name)
        )

    def _toggle_lyrics(self, show):
        self.lyrics_panel.setVisible(show)
        if show:
            self.lyrics_panel.load_track(self.player.current_track)

    def _on_track_for_lyrics(self, track):
        if self.lyrics_panel.isVisible():
            self.lyrics_panel.load_track(track)

    def _on_position_changed(self, position_ms):
        if self.lyrics_panel.isVisible():
            self.lyrics_panel.update_position(position_ms)
        self._check_scrobble(position_ms)

    # --- Last.FM ---

    def _on_connect_lastfm(self):
        if not self.lastfm.has_api_credentials:
            self._show_api_setup(then_connect=True)
            return
        self._open_auth_dialog()

    def _show_api_setup(self, then_connect=False):
        dlg = LastFMSetupDialog(self)
        dlg.setStyleSheet(self.styleSheet())
        if then_connect:
            dlg.credentials_saved.connect(lambda k, s: self._on_api_credentials_saved(k, s, connect=True))
        else:
            dlg.credentials_saved.connect(lambda k, s: self._on_api_credentials_saved(k, s, connect=False))
        dlg.exec()

    def _on_api_credentials_saved(self, api_key, secret, connect=False):
        self.lastfm.load_api_credentials(api_key, secret)
        self.settings.setValue('lastfm_api_key', api_key)
        self.settings.setValue('lastfm_api_secret', secret)
        self.status_message.emit('Last.FM API credentials saved', 3000)
        if connect:
            self._open_auth_dialog()

    def _on_reset_api_credentials(self):
        self.lastfm.clear_session()
        self.lastfm.clear_api_credentials()
        self.settings.remove('lastfm_sk')
        self.settings.remove('lastfm_username')
        self.settings.remove('lastfm_api_key')
        self.settings.remove('lastfm_api_secret')
        self._update_lastfm_ui()
        self._show_api_setup(then_connect=False)

    def _open_auth_dialog(self):
        dlg = LastFMAuthDialog(self.lastfm, self)
        dlg.setStyleSheet(self.styleSheet())
        dlg.authenticated.connect(self._on_lastfm_authenticated)
        dlg.exec()

    def _on_lastfm_authenticated(self, key, username):
        self.lastfm.load_session(key, username)
        self.settings.setValue('lastfm_sk', key)
        self.settings.setValue('lastfm_username', username)
        self._update_lastfm_ui()
        self.status_message.emit(f'Connected to Last.FM as {username}', 5000)

    def _on_disconnect_lastfm(self):
        self.lastfm.clear_session()
        self.settings.remove('lastfm_sk')
        self.settings.remove('lastfm_username')
        self._update_lastfm_ui()
        self.status_message.emit('Disconnected from Last.FM', 3000)

    def _update_lastfm_ui(self):
        connected = self.lastfm.connected
        self._lastfm_connect_action.setVisible(not connected)
        self._lastfm_disconnect_action.setVisible(connected)
        self.player_bar.love_btn.setEnabled(
            connected and self.player.current_track is not None
        )
        if connected:
            self.player_bar.lastfm_label.setText(self.lastfm.username or '')
            self.player_bar.lastfm_label.setVisible(True)
        else:
            self.player_bar.lastfm_label.setVisible(False)

    def _on_track_for_lastfm(self, track):
        self._scrobble_track = track
        self._scrobble_start_time = time.time()
        self._scrobbled = False
        if track:
            dur_ms = int(track.duration * 1000)
            self._scrobble_threshold_ms = min(dur_ms // 2, 240_000)
        else:
            self._scrobble_threshold_ms = 0

        self.player_bar.love_btn.blockSignals(True)
        self.player_bar.love_btn.setChecked(False)
        self.player_bar.love_btn.blockSignals(False)
        self.player_bar.love_btn.setEnabled(
            self.lastfm.connected and track is not None
        )

        self.lastfm.now_playing(track)

    def _check_scrobble(self, position_ms):
        if (not self._scrobbled
                and self._scrobble_track is not None
                and self.lastfm.connected
                and position_ms >= 30_000
                and position_ms >= self._scrobble_threshold_ms):
            self._scrobbled = True
            self.lastfm.scrobble(self._scrobble_track, self._scrobble_start_time)

    def _on_love_toggled(self, loved):
        track = self.player.current_track
        if not track:
            return
        if loved:
            self.lastfm.love(track)
        else:
            self.lastfm.unlove(track)

    def _play_album(self, tracks, start):
        if tracks:
            self.player.set_playlist(tracks, start)
            self.player.play()

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Music Folder')
        if folder:
            self.settings.setValue('last_folder', folder)
            self._scan_folder(folder)

    def _scan_folder(self, path, existing_tracks=None):
        if hasattr(self, '_scan_thread') and self._scan_thread and self._scan_thread.isRunning():
            return

        self._is_scanning = True
        self._scan_progress.setRange(0, 0)
        self._scan_progress.setVisible(True)
        self._scan_progress.setFormat('Scanning\u2026')

        self._scan_worker = ScanWorker(path, existing_tracks or [])
        self._scan_thread = QThread(self)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_path = path
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._on_scan_thread_finished)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.progress.connect(self._on_scan_progress)

        self._scan_thread.start()

    def _on_scan_progress(self, current, total):
        self._scan_progress.setRange(0, total)
        self._scan_progress.setValue(current)
        self._scan_progress.setFormat(f'Processing {current} of {total}')

    def _on_scan_finished(self, tracks):
        self._is_scanning = False
        self._scan_progress.setVisible(False)
        self.library_model.load_tracks(tracks)
        self.library_panel.set_tracks(tracks)
        save_library_cache(self._cache_path, self._scan_path, tracks)
        n = len(tracks)
        self.status_message.emit(f'Loaded {n} track{"s" if n != 1 else ""}', 5000)

    def _on_scan_thread_finished(self):
        self._scan_thread.deleteLater()
        self._scan_thread = None
        dirname = os.path.basename(self._scan_path)
        self.title_changed.emit(f'Music Player \u2014 {dirname}')

    def _restore_state(self):
        api_key = self.settings.value('lastfm_api_key', '')
        api_secret = self.settings.value('lastfm_api_secret', '')
        if api_key and api_secret:
            self.lastfm.load_api_credentials(api_key, api_secret)

        sk = self.settings.value('lastfm_sk', '')
        username = self.settings.value('lastfm_username', '')
        if sk and username:
            self.lastfm.load_session(sk, username)
        self._update_lastfm_ui()

        sort_mode = self.settings.value('sort_mode', 'album')
        by_album = (sort_mode == 'album')
        self._sort_action.blockSignals(True)
        self._sort_action.setChecked(by_album)
        self._sort_action.blockSignals(False)
        self._toggle_sort(by_album)

        last_album = self.settings.value('last_album', '')
        if last_album:
            def _restore_album():
                self.library_panel.tracks_loaded.disconnect(_restore_album)
                self.library_panel.navigate_to_album(last_album)
            self.library_panel.tracks_loaded.connect(_restore_album)

        last_folder = self.settings.value('last_folder', '')
        if last_folder and os.path.isdir(last_folder):
            cached = load_library_cache(self._cache_path, last_folder)
            if cached is not None:
                self.library_model.load_tracks(cached)
                self.library_panel.set_tracks(cached)
                n = len(cached)
                dirname = os.path.basename(last_folder)
                self.title_changed.emit(f'Music Player \u2014 {dirname}')
                self.status_message.emit(
                    f'Loaded {n} track{"s" if n != 1 else ""} from cache', 5000
                )
            else:
                self._scan_folder(last_folder)

    def _refresh_library(self):
        last_folder = self.settings.value('last_folder', '')
        if last_folder and os.path.isdir(last_folder):
            existing = load_library_cache(self._cache_path, last_folder) or []
            self._scan_folder(last_folder, existing)

    def cleanup(self):
        self.player.stop()
        if hasattr(self, '_scan_thread') and self._scan_thread and self._scan_thread.isRunning():
            if hasattr(self, '_scan_worker') and self._scan_worker:
                self._scan_worker.cancel()
            self._scan_thread.quit()
            if not self._scan_thread.wait(5000):
                self._scan_thread.terminate()
                self._scan_thread.wait()
        self.library_panel._album_model._cancel_extraction()
