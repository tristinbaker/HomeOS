from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen
import urllib.parse

CONFIG_PATH  = Path.home() / '.local' / 'share' / 'home_os' / 'rommanager_config.json'
LIBRARY_PATH = Path.home() / '.local' / 'share' / 'home_os' / 'rommanager_library.json'
ART_DIR      = Path.home() / '.local' / 'share' / 'home_os' / 'rom_art'

TGDB_BASE = 'https://api.thegamesdb.net/v1'

PLATFORMS: list[tuple[str, int]] = [
    ('NES / Famicom',          7),
    ('SNES',                   6),
    ('Nintendo 64',            3),
    ('GameCube',               2),
    ('Wii',                    9),
    ('Game Boy',               4),
    ('Game Boy Color',        41),
    ('Game Boy Advance',       5),
    ('Nintendo DS',            8),
    ('Sega Genesis',          36),
    ('Sega Game Gear',        21),
    ('Sega Saturn',           17),
    ('Sega Dreamcast',        16),
    ('PlayStation',           10),
    ('PlayStation 2',         11),
    ('PSP',                   13),
    ('Atari 2600',            22),
    ('Neo Geo',               24),
    ('Arcade',                23),
    ('Other',                  0),
]


@dataclass
class System:
    name: str
    rom_dir: str
    emulator_path: str
    extensions: list[str]   # e.g. ['.sfc', '.smc']
    platform_id: int = 0    # TheGamesDB platform ID


@dataclass
class Game:
    name: str       # cleaned display name
    rom_path: str   # absolute path to ROM file
    system: str     # system name
    art_path: str = ''
    tgdb_id: int = 0


def _clean_name(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', name)   # strip (USA), [!], etc.
    name = re.sub(r'\s+', ' ', name).strip()
    return name or Path(filename).stem


# ── Persistence ───────────────────────────────────────────────────────────────

def load_config() -> list[System]:
    try:
        raw = json.loads(CONFIG_PATH.read_text())
        return [System(**s) for s in raw.get('systems', [])]
    except Exception:
        return []


def save_config(systems: list[System]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({'systems': [asdict(s) for s in systems]}, indent=2))


def load_library() -> list[Game]:
    try:
        raw = json.loads(LIBRARY_PATH.read_text())
        return [Game(**g) for g in raw.get('games', [])]
    except Exception:
        return []


def save_library(games: list[Game]) -> None:
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps({'games': [asdict(g) for g in games]}, indent=2))


# ── Scanning ──────────────────────────────────────────────────────────────────

def scan_system(system: System) -> list[Game]:
    rom_dir = Path(system.rom_dir)
    if not rom_dir.is_dir():
        return []
    exts = {(e if e.startswith('.') else f'.{e}').lower() for e in system.extensions}
    return sorted(
        [
            Game(name=_clean_name(f.name), rom_path=str(f), system=system.name)
            for f in rom_dir.iterdir()
            if f.is_file() and f.suffix.lower() in exts
        ],
        key=lambda g: g.name.lower(),
    )


# ── Art fetching ──────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')


def art_cache_path(game: Game) -> Path:
    return ART_DIR / game.system / f'{_safe_filename(game.name)}.jpg'


def fetch_art(game: Game, platform_id: int, api_key: str) -> str | None:
    dest = art_cache_path(game)
    if dest.exists():
        return str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        params: dict = {
            'apikey': api_key,
            'name': game.name,
            'fields': 'id,game_title',
            'include': 'boxart',
        }
        if platform_id:
            params['filter[platform]'] = platform_id

        url = f'{TGDB_BASE}/Games/ByGameName?' + urllib.parse.urlencode(params)
        req = Request(url, headers={'User-Agent': 'HomeOS/1.0'})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        games_list = data.get('data', {}).get('games', [])
        if not games_list:
            return None

        game_id = games_list[0]['id']
        boxart    = data.get('include', {}).get('boxart', {})
        base_url  = boxart.get('base_url', {}).get('medium', '')
        images    = boxart.get('data', {}).get(str(game_id), [])

        front = next(
            (img for img in images
             if img.get('type') == 'boxart' and img.get('side') == 'front'),
            images[0] if images else None,
        )
        if not front or not base_url:
            return None

        img_url = base_url + front['filename']
        req2 = Request(img_url, headers={'User-Agent': 'HomeOS/1.0'})
        with urlopen(req2, timeout=15) as r:
            dest.write_bytes(r.read())

        return str(dest)
    except Exception:
        return None
