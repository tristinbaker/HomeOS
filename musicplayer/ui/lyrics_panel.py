import json
import os
import re
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import urlopen, Request

from PyQt6.QtCore import Qt, QObject, QRunnable, QStandardPaths, QThreadPool, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QVBoxLayout, QWidget,
)

# Matches [mm:ss], [mm:ss.xx], [mm:ss.xxx], [m:ss.x] — all real-world LRC variants.
_LRC_RE = re.compile(r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)')


def _parse_lrc(text):
    lines = []
    for raw in text.splitlines():
        m = _LRC_RE.match(raw.strip())
        if m:
            mins, secs, frac, lyric = m.groups()
            ms = int(mins) * 60000 + int(secs) * 1000
            if frac:
                # 1-digit = deciseconds, 2-digit = centiseconds, 3-digit = milliseconds
                ms += int(frac) * (100 if len(frac) == 1 else 10 if len(frac) == 2 else 1)
            lines.append((ms, lyric.strip()))
    return sorted(lines, key=lambda x: x[0])


def _lrc_title_match(a: str, b: str) -> bool:
    """Case-insensitive title comparison that ignores punctuation and parens."""
    if a.lower() == b.lower():
        return True
    a_norm = re.sub(r'[^a-z0-9 ]', '', a.lower()).strip()
    b_norm = re.sub(r'[^a-z0-9 ]', '', b.lower()).strip()
    return bool(a_norm and b_norm and a_norm == b_norm)


def _lrc_artist_match(tag: str, api_name: str) -> bool:
    """True if api_name matches the artist tag or any component of it.

    Handles compound tags like "Artist A & Artist B" where lrclib.net
    stores individual artists.
    """
    if tag.lower() == api_name.lower():
        return True
    parts = {p.strip().lower() for p in re.split(r'[,&]', tag) if p.strip()}
    api_lower = api_name.lower()
    return api_lower in parts or any(api_lower in p or p in api_lower for p in parts)


class _FetchSignals(QObject):
    done = pyqtSignal(str, object, str)  # key, synced_lines_or_None, plain_text


class _FetchTask(QRunnable):
    def __init__(self, track, signals):
        super().__init__()
        self.setAutoDelete(True)
        self._artist = track.artist
        self._title = track.title
        self._album = track.album
        self._duration = track.duration
        self._path = track.path
        self._signals = signals
        self._cancelled = False
        self._key = f"{track.artist}\x00{track.title}"

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return

        # 1. Local .lrc file alongside the audio
        try:
            lrc_path = Path(self._path).with_suffix('.lrc')
            if lrc_path.exists():
                lines = _parse_lrc(lrc_path.read_text(encoding='utf-8', errors='ignore'))
                if lines and not self._cancelled:
                    self._signals.done.emit(self._key, lines, '')
                    return
        except Exception:
            pass

        plain_fallback = ''  # best plain-text found so far; used only if no synced found

        # 2. lrclib.net GET — exact match with duration/album
        try:
            url = (
                'https://lrclib.net/api/get?'
                f'artist_name={quote(self._artist, safe="")}'
                f'&track_name={quote(self._title, safe="")}'
                f'&album_name={quote(self._album, safe="")}'
                f'&duration={int(self._duration)}'
            )
            with urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            synced_text = data.get('syncedLyrics') or ''
            if synced_text:
                lines = _parse_lrc(synced_text)
                if lines:
                    try:
                        Path(self._path).with_suffix('.lrc').write_text(
                            synced_text, encoding='utf-8'
                        )
                    except Exception:
                        pass
                    if not self._cancelled:
                        self._signals.done.emit(self._key, lines, '')
                        return
            # Hold GET's plain text — try SEARCH for synced lyrics before using it
            plain_fallback = (data.get('plainLyrics') or '').strip()
        except Exception:
            pass

        if self._cancelled:
            return

        # 3. lrclib.net SEARCH — relaxed: no duration/album; handles special
        #    characters and compound artist tags that defeat the GET endpoint.
        try:
            params = urlencode({'artist_name': self._artist, 'track_name': self._title})
            req = Request(
                f'https://lrclib.net/api/search?{params}',
                headers={'User-Agent': 'HomeOS/1.0'},
            )
            with urlopen(req, timeout=8) as resp:
                results = json.loads(resp.read())
            for r in results:
                r_artist = r.get('artistName', '')
                r_title = r.get('trackName', '')
                if not _lrc_artist_match(self._artist, r_artist):
                    continue
                if not _lrc_title_match(self._title, r_title):
                    continue
                synced_text = r.get('syncedLyrics') or ''
                if synced_text:
                    lines = _parse_lrc(synced_text)
                    if lines:
                        try:
                            Path(self._path).with_suffix('.lrc').write_text(
                                synced_text, encoding='utf-8'
                            )
                        except Exception:
                            pass
                        if not self._cancelled:
                            self._signals.done.emit(self._key, lines, '')
                            return
                # Prefer GET's plain over SEARCH's plain if we already have one
                if not plain_fallback:
                    plain_fallback = (r.get('plainLyrics') or '').strip()
        except Exception:
            pass

        if self._cancelled:
            return

        # Use lrclib.net plain text (from GET or SEARCH) instead of hitting lyrics.ovh
        if plain_fallback:
            if not self._cancelled:
                self._signals.done.emit(self._key, None, plain_fallback)
            return

        # 4. lyrics.ovh — last resort plain text
        try:
            url = (
                'https://api.lyrics.ovh/v1/'
                + quote(self._artist, safe='')
                + '/'
                + quote(self._title, safe='')
            )
            with urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            plain = (data.get('lyrics') or '').strip()
            if not self._cancelled:
                self._signals.done.emit(self._key, None, plain or '(No lyrics found)')
        except URLError:
            if not self._cancelled:
                self._signals.done.emit(
                    self._key, None, '(Could not fetch lyrics — check your connection)'
                )
        except Exception:
            if not self._cancelled:
                self._signals.done.emit(self._key, None, '(An error occurred while fetching lyrics)')


class LyricsPanel(QWidget):
    seek_requested = pyqtSignal(int)  # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_key = None
        self._cache = {}
        self._pending_task = None
        self._signals = _FetchSignals()
        self._signals.done.connect(self._on_fetch_done)

        self._synced_lines = []
        self._is_synced = False
        self._current_idx = -1
        self._duration_ms = 0
        self._loading = False
        self._track_path = None
        self._offset_ms = 0
        self._offsets = self._load_offsets()

        self._header = QLabel('Lyrics')
        font = self._header.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self._header.setFont(font)

        self._offset_minus = QPushButton('−')
        self._offset_minus.setFixedSize(26, 20)
        self._offset_minus.setToolTip('Shift lyrics later by 100ms')
        self._offset_minus.clicked.connect(lambda: self._adjust_offset(-100))

        self._offset_label = QLabel('+0ms')
        self._offset_label.setStyleSheet('font-family: monospace; font-size: 10px;')
        self._offset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._offset_label.setMinimumWidth(56)

        self._offset_plus = QPushButton('+')
        self._offset_plus.setFixedSize(26, 20)
        self._offset_plus.setToolTip('Shift lyrics earlier by 100ms')
        self._offset_plus.clicked.connect(lambda: self._adjust_offset(100))

        self._offset_row = QWidget()
        offset_layout = QHBoxLayout(self._offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 2)
        offset_layout.setSpacing(2)
        offset_layout.addWidget(QLabel('Sync offset:'))
        offset_layout.addWidget(self._offset_minus)
        offset_layout.addWidget(self._offset_label)
        offset_layout.addWidget(self._offset_plus)
        offset_layout.addStretch()
        self._offset_minus.setEnabled(False)
        self._offset_plus.setEnabled(False)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setWordWrap(True)
        self._list.setSpacing(2)
        self._list.itemClicked.connect(self._on_line_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._header)
        layout.addWidget(self._offset_row)
        layout.addWidget(self._list, 1)
        self.setLayout(layout)
        self.setMinimumWidth(220)

    def load_track(self, track):
        self._current_idx = -1
        self._synced_lines = []
        self._is_synced = False
        self._loading = False
        self._list.clear()
        self._offset_minus.setEnabled(False)
        self._offset_plus.setEnabled(False)

        if track is None:
            self._header.setText('Lyrics')
            self._current_key = None
            self._track_path = None
            self._duration_ms = 0
            self._offset_ms = 0
            return

        key = f"{track.artist}\x00{track.title}"
        self._header.setText(f"{track.artist} — {track.title}")
        self._duration_ms = int(track.duration * 1000)
        self._current_key = key
        self._track_path = track.path
        self._offset_ms = self._offsets.get(track.path, 0)
        self._offset_label.setText(self._fmt_offset())

        if key in self._cache:
            self._apply_cache(key)
            return

        if self._pending_task:
            self._pending_task.cancel()
        self._loading = True
        self._list.addItem('Loading…')
        task = _FetchTask(track, self._signals)
        self._pending_task = task
        QThreadPool.globalInstance().start(task)

    def update_position(self, position_ms):
        if self._loading or not self._list.count():
            return

        if self._is_synced:
            adjusted = position_ms + self._offset_ms
            idx = -1
            for i, (ms, _) in enumerate(self._synced_lines):
                if ms <= adjusted:
                    idx = i
                else:
                    break
            if idx < 0:
                return
        elif self._duration_ms > 0:
            count = self._list.count()
            frac = max(0.0, min(1.0, position_ms / self._duration_ms))
            idx = min(int(frac * count), count - 1)
        else:
            return

        if idx != self._current_idx:
            self._set_current_line(idx)

    def _set_current_line(self, idx):
        if 0 <= self._current_idx < self._list.count():
            self._style_item(self._list.item(self._current_idx), current=False)
        self._current_idx = idx
        item = self._list.item(idx)
        if item:
            self._style_item(item, current=True)
            self._list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _style_item(self, item, current):
        font = item.font()
        font.setBold(current)
        item.setFont(font)
        item.setForeground(
            QBrush(QColor('#6ea8ff') if current else QColor(255, 255, 255, 150))
        )

    def _apply_cache(self, key):
        entry = self._cache[key]
        synced = entry['synced']
        plain = entry['plain']
        if synced:
            self._is_synced = True
            self._synced_lines = synced
            for _, text in synced:
                self._list.addItem(text)
            self._list.setCursor(Qt.CursorShape.PointingHandCursor)
            self._offset_minus.setEnabled(True)
            self._offset_plus.setEnabled(True)
        else:
            self._is_synced = False
            self._synced_lines = []
            for line in (plain or '').splitlines():
                self._list.addItem(line)
            self._list.unsetCursor()
            self._offset_minus.setEnabled(False)
            self._offset_plus.setEnabled(False)

    def _on_fetch_done(self, key, synced_lines, plain_text):
        # Don't overwrite a cached synced-lyrics entry with a plain-only result
        # (stale cancelled tasks can still emit plain text after we've already
        # received synced lyrics for the same track from a newer task).
        existing = self._cache.get(key)
        if existing and existing.get('synced') and not synced_lines:
            return
        self._cache[key] = {'synced': synced_lines, 'plain': plain_text}
        if key == self._current_key:
            self._loading = False
            self._list.clear()
            self._current_idx = -1
            self._apply_cache(key)

    def _on_line_clicked(self, item):
        if not self._is_synced:
            return
        row = self._list.row(item)
        if 0 <= row < len(self._synced_lines):
            ms, _ = self._synced_lines[row]
            self.seek_requested.emit(ms - self._offset_ms)

    def _adjust_offset(self, delta_ms):
        self._offset_ms += delta_ms
        self._offset_label.setText(self._fmt_offset())
        if self._track_path is not None:
            self._offsets[self._track_path] = self._offset_ms
            self._save_offsets()

    def _fmt_offset(self):
        sign = '+' if self._offset_ms >= 0 else ''
        return f'{sign}{self._offset_ms}ms'

    def _offsets_path(self):
        data_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        return os.path.join(data_dir, 'lyrics_offsets.json')

    def _load_offsets(self):
        try:
            path = self._offsets_path()
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_offsets(self):
        try:
            path = self._offsets_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._offsets, f, indent=2)
        except Exception:
            pass
