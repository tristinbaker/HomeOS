import hashlib
import os
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import mutagen
from PyQt6.QtCore import (
    QAbstractItemModel, QAbstractListModel, QModelIndex, Qt,
    QObject, QRunnable, QStandardPaths, QThreadPool, pyqtSignal,
)

from ._scanner import (
    AudioTrack, AUDIO_EXTENSIONS, ARTIST_KEYS, ALBUM_KEYS, TITLE_KEYS,
    TRACK_KEYS, _canonical_album, parse_track, parallel_walk,
)

logger = logging.getLogger(__name__)


def _split_artist_names(artist: str, simple_artists: set) -> list[str]:
    """Split a compound artist tag into individual names.

    Splits on '&' and ',' only when every resulting part is already a known
    standalone artist name in the library.  This prevents breaking up names
    like "Crosby, Stills & Nash" (none of those solo names appear alone) while
    correctly expanding tags like "Christian Borle, Andrew Rannells" (both do).
    """
    if '&' not in artist and ',' not in artist:
        return [artist]
    unified = artist.replace('&', ',')
    parts = [p.strip() for p in unified.split(',') if p.strip()]
    if len(parts) > 1 and all(p.lower() in simple_artists for p in parts):
        return parts
    return [artist]


class TreeNode:
    __slots__ = ('name', 'parent', 'children', 'track')

    def __init__(self, name, parent=None, track=None):
        self.name = name
        self.parent = parent
        self.children = []
        self.track = track

    def row(self):
        if self.parent:
            return self.parent.children.index(self)
        return 0


class LibraryModel(QAbstractItemModel):
    SORT_ARTIST = 'artist'
    SORT_ALBUM = 'album'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = TreeNode('')
        self._tracks = []
        self._sort_mode = self.SORT_ARTIST

    def load_tracks(self, tracks):
        self._tracks = list(tracks)
        self._build_tree()

    def set_sort_mode(self, mode):
        if mode == self._sort_mode:
            return
        self._sort_mode = mode
        self._build_tree()

    def sort_mode(self):
        return self._sort_mode

    def _build_tree(self):
        self.beginResetModel()
        self.root = TreeNode('')

        if self._sort_mode == self.SORT_ARTIST:
            key = lambda t: (t.artist.lower(), t.album.lower(), t.track_number or 9999, t.title.lower())
            self._build_artist_tree(sorted(self._tracks, key=key))
        else:
            key = lambda t: (t.album.lower(), t.track_number or 9999, t.title.lower())
            self._build_album_tree(sorted(self._tracks, key=key))

        self.endResetModel()

    def _build_artist_tree(self, tracks):
        # Use lowercase keys throughout so "Deafheaven" and "deafheaven" merge.
        simple_artists = {
            t.artist.lower() for t in tracks if '&' not in t.artist and ',' not in t.artist
        }

        # Determine the best display name per artist (prefer uppercase-initial over all-lowercase).
        canonical_name: dict[str, str] = {}
        for track in tracks:
            for name in _split_artist_names(track.artist, simple_artists):
                key = name.lower()
                existing = canonical_name.get(key)
                if existing is None or (name[:1].isupper() and not existing[:1].isupper()):
                    canonical_name[key] = name

        artist_map: dict[str, TreeNode] = {}
        album_map: dict[tuple, TreeNode] = {}

        def _add_track_to_artist(artist_name, track):
            key = artist_name.lower()
            display = canonical_name.get(key, artist_name)

            artist_node = artist_map.get(key)
            if artist_node is None:
                artist_node = TreeNode(display, self.root)
                self.root.children.append(artist_node)
                artist_map[key] = artist_node

            canonical = _canonical_album(track.album)
            album_key = (key, canonical)
            album_node = album_map.get(album_key)
            if album_node is None:
                album_node = TreeNode(canonical, artist_node)
                artist_node.children.append(album_node)
                album_map[album_key] = album_node

            display_track = (
                f"{track.track_number:02d}. {track.title}"
                if track.track_number else track.title
            )
            album_node.children.append(TreeNode(display_track, album_node, track))

        for track in tracks:
            parts = _split_artist_names(track.artist, simple_artists)
            for part in parts:
                _add_track_to_artist(part, track)

    def _build_album_tree(self, tracks):
        album_map = {}
        for track in tracks:
            canonical = _canonical_album(track.album)
            album_node = album_map.get(canonical)
            if album_node is None:
                album_node = TreeNode(canonical, self.root)
                self.root.children.append(album_node)
                album_map[canonical] = album_node

            display = (
                f"{track.track_number:02d}. {track.title}"
                if track.track_number else track.title
            )
            track_node = TreeNode(display, album_node, track)
            album_node.children.append(track_node)

    def track_at_index(self, index):
        if not index.isValid():
            return None
        return index.internalPointer().track

    def album_tracks_from_index(self, index):
        node = index.internalPointer() if index.isValid() else None
        if node is None:
            return [], -1

        if node.track:
            album_node = node.parent
        elif node.children and node.children[0].track:
            album_node = node
        else:
            return [], -1
        if album_node is None:
            return [], -1

        tracks = []
        start = 0
        for i, child in enumerate(album_node.children):
            if child.track:
                tracks.append(child.track)
                if child is node:
                    start = i
        return tracks, start

    def artist_albums_from_index(self, index):
        """For an artist node (SORT_ARTIST mode only), return (artist_name, [(album_name, tracks)])."""
        if self._sort_mode != self.SORT_ARTIST:
            return None, []
        node = index.internalPointer() if index.isValid() else None
        if not node or node.track or node.parent is not self.root:
            return None, []
        albums = []
        for album_node in node.children:
            tracks = [c.track for c in album_node.children if c.track]
            if tracks:
                albums.append((album_node.name, tracks))
        return node.name, albums

    def all_tracks(self):
        return list(self._tracks)

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        if row >= len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        child = index.internalPointer()
        parent_node = child.parent
        if parent_node is None or parent_node is self.root:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        if role == Qt.ItemDataRole.ToolTipRole and node.track:
            dur = int(node.track.duration)
            return (
                f"{node.track.artist} \u2014 {node.track.album}\n"
                f"{node.track.title}\n"
                f"{dur // 60}:{dur % 60:02d}"
            )
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            label = 'Artist \u2192 Album' if self._sort_mode == self.SORT_ARTIST else 'Album'
            return label
        return None


def _extract_cover(filepath):
    try:
        audio = mutagen.File(filepath)
        if audio is None:
            return None
        if hasattr(audio, 'pictures') and audio.pictures:
            return audio.pictures[0].data
        if audio.tags:
            for key in audio.tags.keys():
                if key.startswith('APIC:'):
                    return audio.tags[key].data
            apic = audio.tags.get('APIC')
            if apic:
                return apic.data
            covr = audio.tags.get('covr')
            if covr:
                if isinstance(covr, list) and len(covr) > 0:
                    item = covr[0]
                    return item.data if hasattr(item, 'data') else bytes(item)
                return covr.data if hasattr(covr, 'data') else None
    except Exception:
        pass
    return None


_IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.webp', '.bmp'})
_COVER_STEMS = ('cover', 'folder', 'front', 'album', 'artwork', 'thumb', 'albumart')


def _find_folder_image(directory):
    try:
        entries = os.listdir(directory)
    except OSError:
        return None
    by_lower = {e.lower(): e for e in entries}
    for stem in _COVER_STEMS:
        for ext in ('.jpg', '.jpeg', '.png', '.webp'):
            candidate = stem + ext
            if candidate in by_lower:
                return os.path.join(directory, by_lower[candidate])
    for entry in entries:
        if os.path.splitext(entry)[1].lower() in _IMAGE_EXTENSIONS:
            return os.path.join(directory, entry)
    return None


_COVER_CACHE_DIR = None


def _get_cover_cache_dir():
    global _COVER_CACHE_DIR
    if _COVER_CACHE_DIR is None:
        _COVER_CACHE_DIR = os.path.join(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            ),
            'covers',
        )
        os.makedirs(_COVER_CACHE_DIR, exist_ok=True)
    return _COVER_CACHE_DIR


_FETCH_SEMAPHORE = threading.Semaphore(2)  # max 2 concurrent art fetches
_USER_AGENT = 'HomeOS/1.0 (tristin.baker@kin.com)'

# ── Artist image helpers ─────────────────────────────────────────────────────

_ARTIST_IMAGE_STEMS = ('artist',)   # only an explicitly named artist.jpg avoids album art confusion


def _get_artist_folder(tracks) -> str | None:
    """Common parent of all track directories for this artist.

    Multi-album: commonpath of album dirs → returns the artist folder.
    Single-album or flat: returns the one unique directory (may be an album dir).
    """
    dirs = {os.path.dirname(t.path) for t in tracks if t.path}
    if not dirs:
        return None
    if len(dirs) == 1:
        return list(dirs)[0]
    try:
        return os.path.commonpath(list(dirs))
    except ValueError:
        return None


def _find_artist_folder_image(directory: str) -> str | None:
    try:
        entries = os.listdir(directory)
    except OSError:
        return None
    by_lower = {e.lower(): e for e in entries}
    for stem in _ARTIST_IMAGE_STEMS:
        for ext in ('.jpg', '.jpeg', '.png', '.webp'):
            candidate = stem + ext
            if candidate in by_lower:
                return os.path.join(directory, by_lower[candidate])
    return None


def _name_similarity(a: str, b: str) -> float:
    """Rough Dice-coefficient similarity for short strings (no deps)."""
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    def bigrams(s):
        return {s[i:i+2] for i in range(len(s) - 1)}
    sa, sb = bigrams(a), bigrams(b)
    if not sa or not sb:
        return 0.0
    return 2 * len(sa & sb) / (len(sa) + len(sb))


def _deezer_image_valid(url: str) -> bool:
    """Return False for Deezer placeholder images (empty hash or MD5 of empty string)."""
    if not url:
        return False
    # Empty hash pattern: /images/artist//size
    if '/artist//' in url:
        return False
    # d41d8cd98f00b204e9800998ecf8427e is MD5 of empty string — Deezer uses it as placeholder
    if 'd41d8cd98f00b204e9800998ecf8427e' in url:
        return False
    return True


def _fetch_artist_deezer(artist: str) -> bytes | None:
    """Deezer: free, no auth, returns up to 1000x1000 artist photos."""
    params = urllib.parse.urlencode({'q': artist, 'limit': 10})
    try:
        req = urllib.request.Request(
            f'https://api.deezer.com/search/artist?{params}',
            headers={'User-Agent': _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            items = json.loads(resp.read()).get('data', [])

        # Score results: prefer exact / close name matches
        scored = []
        for r in items:
            sim = _name_similarity(artist, r.get('name', ''))
            if sim >= 0.6:
                scored.append((sim, r))
        scored.sort(key=lambda x: -x[0])

        for _, r in scored:
            pic = r.get('picture_xl') or r.get('picture_big') or ''
            if not _deezer_image_valid(pic):
                continue
            img_req = urllib.request.Request(pic, headers={'User-Agent': _USER_AGENT})
            with urllib.request.urlopen(img_req, timeout=8) as resp:
                data = resp.read()
            if len(data) > 10_000:   # skip tiny placeholder images
                return data
    except Exception:
        pass
    return None


def _fetch_artist_theaudiodb(artist: str) -> bytes | None:
    """TheAudioDB free tier: good coverage for artist thumbnails."""
    params = urllib.parse.urlencode({'s': artist})
    try:
        req = urllib.request.Request(
            f'https://theaudiodb.com/api/v1/json/2/search.php?{params}',
            headers={'User-Agent': _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            artists_data = json.loads(resp.read()).get('artists')
        if not artists_data:
            return None
        for a in artists_data[:5]:
            if _name_similarity(artist, a.get('strArtist', '')) < 0.6:
                continue
            # Prefer thumb (portrait) over banner
            url = a.get('strArtistThumb') or ''
            if url:
                img_req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
                with urllib.request.urlopen(img_req, timeout=8) as resp:
                    data = resp.read()
                if len(data) > 10_000:
                    return data
    except Exception:
        pass
    return None


def _fetch_artist_itunes(artist: str) -> bytes | None:
    """iTunes musicArtist search — limited coverage, last resort."""
    params = urllib.parse.urlencode({
        'term': artist,
        'entity': 'musicArtist',
        'limit': 5,
    })
    try:
        req = urllib.request.Request(
            f'https://itunes.apple.com/search?{params}',
            headers={'User-Agent': _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            results = json.loads(resp.read()).get('results', [])
        for r in results:
            art_url = r.get('artworkUrl100', '')
            if art_url:
                art_url = art_url.replace('100x100bb', '400x400bb')
                img_req = urllib.request.Request(art_url, headers={'User-Agent': _USER_AGENT})
                with urllib.request.urlopen(img_req, timeout=8) as resp:
                    return resp.read()
    except Exception:
        pass
    return None


def _fetch_artist_art_online(artist: str) -> bytes | None:
    """Try Deezer → TheAudioDB → iTunes in order."""
    data = _fetch_artist_deezer(artist)
    if data:
        return data
    data = _fetch_artist_theaudiodb(artist)
    if data:
        return data
    return _fetch_artist_itunes(artist)


# ── Album art helpers ────────────────────────────────────────────────────────

def _fetch_itunes(artist: str, album: str) -> bytes | None:
    params = urllib.parse.urlencode({
        'term': f'{artist} {album}',
        'entity': 'album',
        'limit': 5,
    })
    try:
        req = urllib.request.Request(
            f'https://itunes.apple.com/search?{params}',
            headers={'User-Agent': _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            results = json.loads(resp.read()).get('results', [])
        for r in results:
            art_url = r.get('artworkUrl100', '')
            if art_url:
                art_url = art_url.replace('100x100bb', '600x600bb')
                img_req = urllib.request.Request(art_url, headers={'User-Agent': _USER_AGENT})
                with urllib.request.urlopen(img_req, timeout=8) as resp:
                    return resp.read()
    except Exception:
        pass
    return None


def _fetch_musicbrainz(artist: str, album: str) -> bytes | None:
    params = urllib.parse.urlencode({
        'query': f'release:"{album}" artist:"{artist}"',
        'fmt': 'json',
        'limit': 5,
    })
    try:
        req = urllib.request.Request(
            f'https://musicbrainz.org/ws/2/release/?{params}',
            headers={'User-Agent': _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            releases = json.loads(resp.read()).get('releases', [])
        for release in releases[:3]:
            mbid = release.get('id')
            if not mbid:
                continue
            try:
                caa_req = urllib.request.Request(
                    f'https://coverartarchive.org/release/{mbid}/front-500',
                    headers={'User-Agent': _USER_AGENT},
                )
                with urllib.request.urlopen(caa_req, timeout=8) as resp:
                    return resp.read()
            except Exception:
                pass
            time.sleep(0.3)  # respect MusicBrainz rate limit
    except Exception:
        pass
    return None


def _fetch_art_online(artist: str, album: str) -> bytes | None:
    with _FETCH_SEMAPHORE:
        data = _fetch_itunes(artist, album)
        if data:
            return data
        return _fetch_musicbrainz(artist, album)


class _CoverSignals(QObject):
    cover_ready = pyqtSignal(str, str)  # album_name, cover_path (empty = no cover)


class _CoverTask(QRunnable):
    def __init__(self, album_name, tracks, signals):
        super().__init__()
        self.setAutoDelete(True)
        self._album_name = album_name
        self._tracks = tracks
        self._signals = signals
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        path = AlbumListModel._extract_one(self._album_name, self._tracks)
        if not self._cancelled:
            self._signals.cover_ready.emit(self._album_name, path or '')


class AlbumListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._albums = []
        self._album_row = {}
        self._cover_paths = {}
        self._pending_tasks = []
        self._signals = _CoverSignals()
        self._signals.cover_ready.connect(self._on_cover_ready)
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(4)

    def load_tracks(self, tracks):
        self._cancel_extraction()
        self.beginResetModel()
        album_map = {}
        for t in tracks:
            album_map.setdefault(_canonical_album(t.album), []).append(t)
        for key in album_map:
            # Sort by original album name first (preserves disc order), then track number
            album_map[key].sort(key=lambda t: (t.album.lower(), t.track_number or 9999, t.title.lower()))
        self._albums = sorted(album_map.items(), key=lambda x: x[0].lower())
        self._album_row = {name: i for i, (name, _) in enumerate(self._albums)}

        # Synchronously populate covers already on disk — first paint is instant,
        # no per-album signal round-trips needed for the cached majority.
        cache_dir = _get_cover_cache_dir()
        self._cover_paths = {}
        uncached = []
        for album_name, album_tracks in self._albums:
            cache_key = hashlib.md5(album_name.lower().encode('utf-8')).hexdigest()
            path = os.path.join(cache_dir, f'{cache_key}.jpg')
            if os.path.exists(path):
                self._cover_paths[album_name] = path
            else:
                uncached.append((album_name, album_tracks))

        self.endResetModel()
        self._start_extraction(uncached)

    def _start_extraction(self, albums):
        if not albums:
            return
        for album_name, tracks in albums:
            task = _CoverTask(album_name, tracks, self._signals)
            self._pending_tasks.append(task)
            self._pool.start(task)

    def _cancel_extraction(self):
        for task in self._pending_tasks:
            task.cancel()
        self._pending_tasks.clear()
        self._pool.clear()

    def _on_cover_ready(self, album_name, cover_path):
        self._cover_paths[album_name] = cover_path or None
        row = self._album_row.get(album_name)
        if row is not None:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx)

    @staticmethod
    def _extract_one(album_name, tracks):
        import shutil
        cache_dir = _get_cover_cache_dir()
        key = hashlib.md5(album_name.lower().encode('utf-8')).hexdigest()
        path = os.path.join(cache_dir, f'{key}.jpg')
        noart = os.path.join(cache_dir, f'{key}.noart')

        if os.path.exists(path):
            return path
        if os.path.exists(noart):
            return None

        # 1. Embedded cover art in audio tags
        for track in tracks:
            data = _extract_cover(track.path)
            if data:
                with open(path, 'wb') as f:
                    f.write(data)
                return path

        # 2. Image files in the album's folder(s)
        checked_dirs = set()
        for track in tracks:
            directory = os.path.dirname(track.path)
            if directory in checked_dirs:
                continue
            checked_dirs.add(directory)
            img = _find_folder_image(directory)
            if img:
                shutil.copy2(img, path)
                return path

        # 3. Online fetch (iTunes → MusicBrainz/CAA)
        artist = tracks[0].artist if tracks else ''
        data = _fetch_art_online(artist, album_name)
        if data:
            with open(path, 'wb') as f:
                f.write(data)
            return path

        # Mark as no-art so we don't hit the network again next session
        open(noart, 'w').close()
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        album_name, tracks = self._albums[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return album_name
        if role == Qt.ItemDataRole.UserRole:
            return tracks
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{album_name}\n{len(tracks)} tracks"
        return None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._albums)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def cover_path(self, index):
        if not index.isValid():
            return None
        album_name, _ = self._albums[index.row()]
        return self._cover_paths.get(album_name)

    def cover_path_by_name(self, album_name):
        return self._cover_paths.get(album_name)

    def track_at_index(self, index):
        if not index.isValid():
            return None
        _, tracks = self._albums[index.row()]
        return tracks[0] if tracks else None

    def album_tracks_from_index(self, index):
        if not index.isValid():
            return [], -1
        _, tracks = self._albums[index.row()]
        return tracks, 0


class _ArtistSignals(QObject):
    image_ready = pyqtSignal(str, str)  # artist_name, image_path (empty = none)


class _ArtistImageTask(QRunnable):
    def __init__(self, artist_name, tracks, signals):
        super().__init__()
        self.setAutoDelete(True)
        self._artist_name = artist_name
        self._tracks = tracks
        self._signals = signals
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        path = ArtistListModel._fetch_artist_image(self._artist_name, self._tracks)
        if not self._cancelled:
            self._signals.image_ready.emit(self._artist_name, path or '')


class ArtistListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._artists = []            # [(artist_name, [tracks])]
        self._artist_row: dict = {}
        self._image_paths: dict = {}
        self._pending_tasks = []
        self._signals = _ArtistSignals()
        self._signals.image_ready.connect(self._on_image_ready)
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(3)

    def load_tracks(self, tracks):
        self._cancel_tasks()
        self.beginResetModel()

        simple_artists = {
            t.artist.lower() for t in tracks if '&' not in t.artist and ',' not in t.artist
        }

        # Canonical display name per artist: prefer uppercase-initial over all-lowercase.
        canonical_name: dict[str, str] = {}
        for t in tracks:
            for name in _split_artist_names(t.artist, simple_artists):
                key = name.lower()
                existing = canonical_name.get(key)
                if existing is None or (name[:1].isupper() and not existing[:1].isupper()):
                    canonical_name[key] = name

        artist_map: dict[str, list] = {}
        for t in tracks:
            for name in _split_artist_names(t.artist, simple_artists):
                artist_map.setdefault(name.lower(), []).append(t)

        self._artists = sorted(
            [(canonical_name[k], v) for k, v in artist_map.items()],
            key=lambda x: x[0].lower(),
        )
        self._artist_row = {name: i for i, (name, _) in enumerate(self._artists)}

        # Synchronously populate images already on disk
        self._image_paths = {}
        uncached = []
        for artist_name, artist_tracks in self._artists:
            img = self._find_cached(artist_name, artist_tracks)
            if img:
                self._image_paths[artist_name] = img
            else:
                uncached.append((artist_name, artist_tracks))

        self.endResetModel()
        self._start_tasks(uncached)

    def _find_cached(self, artist_name, _tracks) -> str | None:
        # Only check the app cache here (one os.path.exists per artist, all in the
        # same directory so the OS can cache the lookup). The background task will
        # check the music folder for a local artist.jpg — doing os.listdir() on
        # every artist directory here on the main thread is the primary source of
        # startup lag for large libraries.
        cache_dir = _get_cover_cache_dir()
        key = hashlib.md5(('artist:' + artist_name.lower()).encode()).hexdigest()
        path = os.path.join(cache_dir, f'artist_{key}.jpg')
        return path if os.path.exists(path) else None

    def _start_tasks(self, artists):
        for artist_name, tracks in artists:
            task = _ArtistImageTask(artist_name, tracks, self._signals)
            self._pending_tasks.append(task)
            self._pool.start(task)

    def _cancel_tasks(self):
        for task in self._pending_tasks:
            task.cancel()
        self._pending_tasks.clear()
        self._pool.clear()

    def _on_image_ready(self, artist_name, image_path):
        self._image_paths[artist_name] = image_path or None
        row = self._artist_row.get(artist_name)
        if row is not None:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx)

    @staticmethod
    def _fetch_artist_image(artist_name, tracks) -> str | None:
        cache_dir = _get_cover_cache_dir()
        key = hashlib.md5(('artist:' + artist_name.lower()).encode()).hexdigest()
        cache_path = os.path.join(cache_dir, f'artist_{key}.jpg')
        noart_path = os.path.join(cache_dir, f'artist_{key}.noart')

        folder = _get_artist_folder(tracks)
        if folder and os.path.isdir(folder):
            img = _find_artist_folder_image(folder)
            if img:
                return img

        if os.path.exists(cache_path):
            return cache_path
        if os.path.exists(noart_path):
            return None

        with _FETCH_SEMAPHORE:
            data = _fetch_artist_art_online(artist_name)

        if data:
            # Prefer artist folder; fall back to cover cache
            if folder and os.path.isdir(folder):
                try:
                    save_path = os.path.join(folder, 'artist.jpg')
                    with open(save_path, 'wb') as f:
                        f.write(data)
                    return save_path
                except OSError:
                    pass
            try:
                with open(cache_path, 'wb') as f:
                    f.write(data)
                return cache_path
            except OSError:
                pass

        try:
            open(noart_path, 'w').close()
        except OSError:
            pass
        return None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._artists)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        artist_name, tracks = self._artists[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return artist_name
        if role == Qt.ItemDataRole.UserRole:
            return tracks
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{artist_name}\n{len(tracks)} tracks"
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def image_path(self, index) -> str | None:
        if not index.isValid():
            return None
        return self._image_paths.get(self._artists[index.row()][0])

    def artist_name_from_index(self, index) -> str:
        return self._artists[index.row()][0] if index.isValid() else ''

    def artist_tracks_from_index(self, index) -> list:
        return self._artists[index.row()][1] if index.isValid() else []


class ScanWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)

    def __init__(self, root_path, existing_tracks=None, parent=None):
        super().__init__(parent)
        self.root_path = root_path
        self._existing = {t.path: t for t in (existing_tracks or [])}
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

        # Phase 1: parallel BFS walk — concurrent scandir() calls cut NAS round-trips
        # from O(total_dirs × latency) to roughly O(depth × latency).
        all_files = parallel_walk(
            self.root_path, n_workers=16, cancelled=lambda: self._cancelled,
        )

        if self._cancelled:
            self.finished.emit([])
            return

        total = len(all_files)
        if total == 0:
            self.finished.emit([])
            return

        # Phase 2: reuse tracks whose mtime hasn't changed (incremental refresh).
        reused = []
        to_parse = []
        for path, mtime in all_files.items():
            existing = self._existing.get(path)
            if existing is not None and abs(existing.mtime - mtime) < 1.0:
                reused.append(existing)
            else:
                to_parse.append((path, mtime))

        completed = len(reused)
        self.progress.emit(completed, total)

        # Phase 3: parse new/changed files.
        # ProcessPoolExecutor bypasses the GIL so mutagen (mostly pure Python) runs
        # truly in parallel. Each process also gets its own OS file handles, which
        # may yield separate SMB/NFS connections to the NAS.
        parsed = []
        if to_parse and not self._cancelled:
            n_procs = min(len(to_parse), os.cpu_count() or 4)
            ctx = multiprocessing.get_context('spawn')
            try:
                with ProcessPoolExecutor(max_workers=n_procs, mp_context=ctx) as executor:
                    futures = {
                        executor.submit(parse_track, path, mtime): path
                        for path, mtime in to_parse
                    }
                    for future in as_completed(futures):
                        if self._cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            self.finished.emit(reused + parsed)
                            return
                        completed += 1
                        self.progress.emit(completed, total)
                        try:
                            track = future.result()
                            if track:
                                parsed.append(track)
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("ProcessPoolExecutor failed (%s), falling back to threads", exc)
                with ThreadPoolExecutor(max_workers=32) as executor:
                    futures = {
                        executor.submit(parse_track, path, mtime): path
                        for path, mtime in to_parse
                    }
                    for future in as_completed(futures):
                        if self._cancelled:
                            self.finished.emit(reused + parsed)
                            return
                        completed += 1
                        self.progress.emit(completed, total)
                        try:
                            track = future.result()
                            if track:
                                parsed.append(track)
                        except Exception:
                            pass

        self.finished.emit(reused + parsed)


class AudioScanner:
    @staticmethod
    def scan(root_path, progress_callback=None):
        tracks = []
        for dirpath, _, filenames in os.walk(root_path):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in AUDIO_EXTENSIONS:
                    continue
                track = parse_track(os.path.join(dirpath, fname))
                if track:
                    tracks.append(track)
            if progress_callback:
                progress_callback(dirpath)
        return tracks

    _parse_track = staticmethod(parse_track)


CACHE_VERSION = 4


def save_library_cache(cache_path, root_path, tracks):
    data = {
        'version': CACHE_VERSION,
        'root_path': root_path,
        'scanned_at': time.time(),
        'tracks': [
            {
                'p': t.path,
                'a': t.artist,
                'b': t.album,
                't': t.title,
                'n': t.track_number,
                'd': t.duration,
                'm': t.mtime,
            }
            for t in tracks
        ],
    }
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump(data, f, separators=(',', ':'))


def load_library_cache(cache_path, root_path):
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    if data.get('version') != CACHE_VERSION:
        return None
    if data.get('root_path') != root_path:
        return None

    return [
        AudioTrack(
            path=t['p'],
            artist=t.get('a', 'Unknown Artist'),
            album=t.get('b', 'Unknown Album'),
            title=t.get('t', ''),
            track_number=t.get('n', 0),
            duration=t.get('d', 0.0),
            mtime=t.get('m', 0.0),
        )
        for t in data['tracks']
    ]
