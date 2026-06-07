#!/usr/bin/env python3
"""
Download missing .lrc files for your music library using lrclib.net.

Usage:
    python download_lrc.py /path/to/music
    python download_lrc.py              # reads last folder from music player settings
    python download_lrc.py --dry-run /path/to/music
    python download_lrc.py --workers 16 /path/to/music
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import mutagen
except ImportError:
    print("mutagen is required: pip install mutagen", file=sys.stderr)
    sys.exit(1)

# ── Audio extensions ──────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = frozenset({
    '.mp3', '.flac', '.wav', '.ogg', '.m4a',
    '.wma', '.opus', '.aiff',
})

ARTIST_KEYS = ('albumartist', 'wm/albumartist', 'artist', '\xa9art', 'tpe1', 'author')
ALBUM_KEYS  = ('album', '\xa9alb', 'talb', 'wm/albumtitle')
TITLE_KEYS  = ('title', '\xa9nam', 'tit2', 'wm/title')

# ── LRC parsing ───────────────────────────────────────────────────────────────

_LRC_RE = re.compile(r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)')


def _parse_lrc(text: str) -> list:
    lines = []
    for raw in text.splitlines():
        m = _LRC_RE.match(raw.strip())
        if m:
            mins, secs, frac, lyric = m.groups()
            ms = int(mins) * 60000 + int(secs) * 1000
            if frac:
                ms += int(frac) * (100 if len(frac) == 1 else 10 if len(frac) == 2 else 1)
            lines.append((ms, lyric.strip()))
    return lines


def _title_match(a: str, b: str) -> bool:
    if a.lower() == b.lower():
        return True
    a_norm = re.sub(r'[^a-z0-9 ]', '', a.lower()).strip()
    b_norm = re.sub(r'[^a-z0-9 ]', '', b.lower()).strip()
    return bool(a_norm and b_norm and a_norm == b_norm)


def _artist_match(tag: str, api_name: str) -> bool:
    if tag.lower() == api_name.lower():
        return True
    parts = {p.strip().lower() for p in re.split(r'[,&]', tag) if p.strip()}
    api_lower = api_name.lower()
    return api_lower in parts or any(api_lower in p or p in api_lower for p in parts)


# ── Tag reading ───────────────────────────────────────────────────────────────

def _first_tag(tags: dict, keys):
    for k in keys:
        if tags.get(k):
            return tags[k]
    return ''


def read_tags(path: str):
    """Return (artist, album, title, duration) or None on failure."""
    try:
        audio = mutagen.File(path)
        if audio is None:
            return None
        duration = getattr(getattr(audio, 'info', None), 'length', 0.0)
        flat = {}
        if audio.tags:
            for k, v in audio.tags.items():
                if isinstance(v, list) and v:
                    first = v[0]
                    flat[k.lower()] = str(first[0]) if isinstance(first, tuple) else str(first)
                elif not isinstance(v, list):
                    flat[k.lower()] = str(v)
        return (
            _first_tag(flat, ARTIST_KEYS) or 'Unknown Artist',
            _first_tag(flat, ALBUM_KEYS)  or 'Unknown Album',
            _first_tag(flat, TITLE_KEYS)  or Path(path).stem,
            duration,
        )
    except Exception:
        return None


# ── lrclib.net fetch ──────────────────────────────────────────────────────────

def fetch_synced_lrc(artist: str, album: str, title: str, duration: float) -> tuple[str | None, list[str]]:
    """
    Try lrclib.net GET then SEARCH.
    Returns (lrc_text_or_None, list_of_debug_lines).
    """
    msgs: list[str] = []

    # GET — exact match with duration + album
    url = (
        'https://lrclib.net/api/get?'
        f'artist_name={quote(artist, safe="")}'
        f'&track_name={quote(title, safe="")}'
        f'&album_name={quote(album, safe="")}'
        f'&duration={int(duration)}'
    )
    msgs.append(f'    [GET]    {url}')
    try:
        with urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read())
        synced = data.get('syncedLyrics') or ''
        if synced and _parse_lrc(synced):
            msgs.append('    → synced lyrics found via GET')
            return synced, msgs
        msgs.append(f'    GET: no synced lyrics  (plain: {"yes" if data.get("plainLyrics") else "no"})')
    except HTTPError as e:
        msgs.append(f'    GET: HTTP {e.code}')
    except Exception as e:
        msgs.append(f'    GET: error — {e}')

    # SEARCH — relaxed, no duration/album required
    params = urlencode({'artist_name': artist, 'track_name': title})
    msgs.append(f'    [SEARCH] https://lrclib.net/api/search?{params}')
    try:
        req = Request(f'https://lrclib.net/api/search?{params}', headers={'User-Agent': 'LRCDownloader/1.0'})
        with urlopen(req, timeout=12) as resp:
            results = json.loads(resp.read())
        msgs.append(f'    SEARCH: {len(results)} result(s)')
        for r in results:
            r_artist = r.get('artistName', '')
            r_title  = r.get('trackName', '')
            if not _artist_match(artist, r_artist):
                msgs.append(f'      skip — artist mismatch: {r_artist!r}')
                continue
            if not _title_match(title, r_title):
                msgs.append(f'      skip — title mismatch:  {r_title!r}')
                continue
            synced = r.get('syncedLyrics') or ''
            if synced and _parse_lrc(synced):
                msgs.append(f'    → synced lyrics found via SEARCH ({r_artist} — {r_title})')
                return synced, msgs
            msgs.append(f'      match but no synced lyrics ({r_artist} — {r_title})')
    except Exception as e:
        msgs.append(f'    SEARCH: error — {e}')

    return None, msgs


# ── Per-file worker ───────────────────────────────────────────────────────────

_RESULTS = ('skipped', 'found', 'not_found', 'error')

def process_file(path: str, folder: str, dry_run: bool) -> tuple[str, list[str]]:
    """
    Process one audio file. Returns (result_key, log_lines).
    result_key is one of: 'skipped', 'found', 'not_found', 'error'.
    """
    rel = os.path.relpath(path, folder)
    lrc_path = Path(path).with_suffix('.lrc')
    lines: list[str] = [f'  {rel}']

    if lrc_path.exists():
        lines.append('    ✓ .lrc exists — skip')
        return 'skipped', lines

    tags = read_tags(path)
    if tags is None:
        lines.append('    ✗ could not read audio tags')
        return 'error', lines

    artist, album, title, duration = tags
    lines.append(f'    Artist: {artist}')
    lines.append(f'    Album:  {album}')
    lines.append(f'    Title:  {title}  ({duration:.0f}s)')

    synced, fetch_msgs = fetch_synced_lrc(artist, album, title, duration)
    lines.extend(fetch_msgs)

    if synced:
        n = len(_parse_lrc(synced))
        if dry_run:
            lines.append(f'    → would write {lrc_path.name}  ({n} lines)')
        else:
            try:
                lrc_path.write_text(synced, encoding='utf-8')
                lines.append(f'    ✓ saved {lrc_path.name}  ({n} lines)')
            except OSError as e:
                lines.append(f'    ✗ write failed: {e}')
                return 'error', lines
        return 'found', lines
    else:
        lines.append('    — not on lrclib.net')
        return 'not_found', lines


# ── Utilities ─────────────────────────────────────────────────────────────────

def find_audio_files(root: str) -> list[str]:
    paths = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if Path(f).suffix.lower() in AUDIO_EXTENSIONS:
                paths.append(os.path.join(dirpath, f))
    return sorted(paths)


def music_folder_from_settings() -> str:
    try:
        from PyQt6.QtCore import QCoreApplication, QSettings
        if QCoreApplication.instance() is None:
            QCoreApplication(sys.argv)
        return QSettings('MusicPlayer', 'MusicPlayer').value('last_folder', '')
    except Exception:
        return ''


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Download missing .lrc files from lrclib.net')
    parser.add_argument('folder', nargs='?',
                        help='Root music folder (default: from music player settings)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would be downloaded without writing files')
    parser.add_argument('--workers', type=int, default=8, metavar='N',
                        help='Concurrent download threads (default: 8)')
    args = parser.parse_args()

    folder = args.folder
    if not folder:
        print('No folder given — reading from music player settings…')
        folder = music_folder_from_settings()

    if not folder or not os.path.isdir(folder):
        print(f'ERROR: music folder not found: {folder!r}', file=sys.stderr)
        print('Usage: python download_lrc.py /path/to/music', file=sys.stderr)
        sys.exit(1)

    print(f'Music folder : {folder}')
    print(f'Workers      : {args.workers}')
    if args.dry_run:
        print('Mode         : DRY RUN — nothing will be written')
    print()

    print('Scanning for audio files…')
    files = find_audio_files(folder)
    total = len(files)
    print(f'Found {total} audio file(s)\n')

    counts = {k: 0 for k in _RESULTS}
    done = 0
    print_lock = threading.Lock()
    start = time.monotonic()

    def _on_done(path, result, log_lines):
        nonlocal done
        with print_lock:
            done += 1
            elapsed = time.monotonic() - start
            rate = done / elapsed if elapsed > 0 else 0
            eta_s = (total - done) / rate if rate > 0 else 0
            eta = f'{int(eta_s // 60)}m{int(eta_s % 60):02d}s' if eta_s > 0 else '—'
            print(f'[{done}/{total}  {rate:.1f}/s  ETA {eta}]')
            for line in log_lines:
                print(line)
            print()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_file, path, folder, args.dry_run): path
            for path in files
        }
        for future in as_completed(futures):
            try:
                result, log_lines = future.result()
            except Exception as e:
                result, log_lines = 'error', [f'  {os.path.relpath(futures[future], folder)}', f'    ✗ unexpected error: {e}']
            counts[result] += 1
            _on_done(futures[future], result, log_lines)

    elapsed = time.monotonic() - start
    print('━' * 64)
    print(f'Finished in {int(elapsed // 60)}m{int(elapsed % 60):02d}s')
    print(f'  Downloaded : {counts["found"]}')
    print(f'  Skipped    : {counts["skipped"]}  (already had .lrc)')
    print(f'  Not found  : {counts["not_found"]}  (lrclib.net has no synced lyrics)')
    print(f'  Errors     : {counts["error"]}')
    if args.dry_run:
        print('  (dry run — nothing was written)')


if __name__ == '__main__':
    main()
