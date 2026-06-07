"""
Pure audio tag parser and directory walker.

No Qt imports — safe to import inside ProcessPoolExecutor 'spawn' workers.
"""
import mutagen
import os
import re
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTENSIONS = frozenset({
    '.mp3', '.flac', '.wav', '.ogg', '.m4a',
    '.wma', '.opus', '.aiff',
})

# First match wins; albumartist before artist so per-track performer names
# don't override the album artist (e.g. "Malice" vs "Clipse").
ARTIST_KEYS = (
    'albumartist', 'wm/albumartist',
    'artist', '\xa9art', '\xa9art', 'tpe1', 'author',
)
ALBUM_KEYS = ('album', '\xa9alb', 'talb', 'wm/albumtitle',)
TITLE_KEYS = ('title', '\xa9nam', 'tit2', 'wm/title',)
TRACK_KEYS = ('tracknumber', 'trck', '\xa9trk', 'trkn', 'wm/tracknumber',)

_DISC_RE = re.compile(
    r'\s*[-–]?\s*[\(\[]?\s*(cd|disc|disk)\s*\d+\s*[\)\]]?\s*$',
    re.IGNORECASE,
)


def _canonical_album(name: str) -> str:
    return _DISC_RE.sub('', name).strip()


@dataclass
class AudioTrack:
    path: str
    artist: str = 'Unknown Artist'
    album: str = 'Unknown Album'
    title: str = ''
    track_number: int = 0
    duration: float = 0.0
    mtime: float = 0.0

    def __lt__(self, other):
        return (
            self.artist.lower(),
            self.album.lower(),
            self.track_number or 9999,
            self.title.lower(),
        ) < (
            other.artist.lower(),
            other.album.lower(),
            other.track_number or 9999,
            other.title.lower(),
        )


def _first_tag(tags, keys):
    for k in keys:
        val = tags.get(k)
        if val:
            return val
    return ''


def parse_track(path: str, mtime: float = 0.0):
    """Read audio tags from *path* and return an AudioTrack, or None on failure."""
    try:
        audio = mutagen.File(path)
        if audio is None:
            return None

        info = getattr(audio, 'info', None)
        duration = info.length if info else 0.0

        artist = album = title = ''
        track_number = 0

        if audio.tags:
            tags = {}
            for k, v in audio.tags.items():
                if isinstance(v, list) and v:
                    first = v[0]
                    tags[k.lower()] = str(first[0]) if isinstance(first, tuple) else str(first)
                elif isinstance(v, list):
                    tags[k.lower()] = ''
                else:
                    tags[k.lower()] = str(v)

            artist = _first_tag(tags, ARTIST_KEYS)
            album = _first_tag(tags, ALBUM_KEYS)
            title = _first_tag(tags, TITLE_KEYS)
            track_str = _first_tag(tags, TRACK_KEYS)

            if not track_str:
                for k in ('trkn', '\xa9trk'):
                    val = audio.tags.get(k)
                    if isinstance(val, list) and val:
                        item = val[0]
                        if isinstance(item, tuple) and item:
                            track_number = int(item[0])
                            break

            if track_str:
                if '/' in track_str:
                    track_str = track_str.split('/')[0]
                try:
                    track_number = int(track_str)
                except ValueError:
                    pass

        if track_number == 0:
            m = re.match(r'^(\d{1,3})[.\s\-]', Path(path).stem)
            if m:
                track_number = int(m.group(1))

        if not title:
            title = Path(path).stem

        return AudioTrack(
            path=path,
            artist=artist or 'Unknown Artist',
            album=album or 'Unknown Album',
            title=title,
            track_number=track_number,
            duration=duration,
            mtime=mtime,
        )
    except Exception:
        return None


def parallel_walk(root: str, n_workers: int = 16, cancelled=None) -> dict:
    """
    BFS directory walk using a thread pool. Returns {path: mtime} for all audio files.

    Parallel directory listing is the key win on NAS: each scandir() call is a
    separate network round-trip, and doing them concurrently cuts the walk phase
    from O(total_dirs × latency) to roughly O(depth × latency).
    """
    from concurrent.futures import ThreadPoolExecutor

    result = {}

    def _scan_dir(dirpath):
        local = {}
        subdirs = []
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            subdirs.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if os.path.splitext(entry.name)[1].lower() in AUDIO_EXTENSIONS:
                                local[entry.path] = entry.stat().st_mtime
                    except OSError:
                        pass
        except OSError:
            pass
        return local, subdirs

    pending = [root]
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        while pending:
            if cancelled is not None and cancelled():
                break
            futures = [executor.submit(_scan_dir, d) for d in pending]
            pending = []
            for f in futures:
                try:
                    files, subdirs = f.result()
                    result.update(files)
                    pending.extend(subdirs)
                except Exception:
                    pass

    return result
