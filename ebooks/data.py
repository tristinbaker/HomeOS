from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH  = Path.home() / '.local' / 'share' / 'home_os' / 'ebooks_config.json'
LIBRARY_PATH = Path.home() / '.local' / 'share' / 'home_os' / 'ebooks_library.json'
COVERS_DIR   = Path.home() / '.local' / 'share' / 'home_os' / 'ebook_covers'


@dataclass
class Book:
    path: str
    title: str
    author: str
    format: str           # 'epub' or 'pdf'
    cover_path: str = ''
    last_position: int = 0  # spine index for EPUB, page index for PDF


def cover_cache_path(book: Book) -> Path:
    stem = Path(book.path).stem
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in stem)
    return COVERS_DIR / f'{safe}.jpg'


def load_config() -> list[str]:
    if not CONFIG_PATH.exists():
        return []
    try:
        return json.loads(CONFIG_PATH.read_text()).get('folders', [])
    except Exception:
        return []


def save_config(folders: list[str]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({'folders': folders}, indent=2))


def load_library() -> list[Book]:
    if not LIBRARY_PATH.exists():
        return []
    try:
        return [Book(**b) for b in json.loads(LIBRARY_PATH.read_text())]
    except Exception:
        return []


def save_library(books: list[Book]) -> None:
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps([asdict(b) for b in books], indent=2))


def scan_folder(folder: str, existing_paths: set[str]) -> list[Book]:
    found: list[Book] = []
    for p in Path(folder).rglob('*'):
        if p.suffix.lower() in {'.epub', '.pdf'} and str(p) not in existing_paths:
            found.append(Book(
                path=str(p),
                title=p.stem,
                author='',
                format=p.suffix.lower().lstrip('.'),
            ))
    return found


def extract_metadata_epub(path: str) -> tuple[str, str, bytes | None]:
    try:
        import ebooklib
        from ebooklib import epub
        book = epub.read_epub(path, options={'ignore_ncx': True})
        titles  = book.get_metadata('DC', 'title')
        authors = book.get_metadata('DC', 'creator')
        title  = titles[0][0]  if titles  else Path(path).stem
        author = authors[0][0] if authors else ''

        cover_bytes = None

        # 1. EPUB3: item with properties="cover-image" (ebooklib ITEM_COVER)
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_COVER:
                cover_bytes = item.get_content()
                break

        # 2. EPUB2: <meta name="cover" content="item-id"> in OPF manifest
        if cover_bytes is None:
            for meta in book.get_metadata('OPF', 'cover'):
                cover_id = (meta[1] or {}).get('content', '') if len(meta) > 1 else ''
                if cover_id:
                    item = book.get_item_with_id(cover_id)
                    if item and item.get_type() == ebooklib.ITEM_IMAGE:
                        cover_bytes = item.get_content()
                        break

        # 3. Image whose filename or item ID contains "cover"
        if cover_bytes is None:
            for item in book.get_items():
                if item.get_type() != ebooklib.ITEM_IMAGE:
                    continue
                name    = item.get_name().lower()
                item_id = (getattr(item, 'id', '') or '').lower()
                if 'cover' in name or 'cover' in item_id:
                    cover_bytes = item.get_content()
                    break

        # No "first image" fallback — wrong covers are worse than no covers.
        return title, author, cover_bytes
    except Exception:
        return Path(path).stem, '', None


def extract_metadata_pdf(path: str) -> tuple[str, str, bytes | None]:
    try:
        import fitz
        doc = fitz.open(path)
        meta   = doc.metadata or {}
        title  = (meta.get('title',  '') or '').strip() or Path(path).stem
        author = (meta.get('author', '') or '').strip()
        cover_bytes = None
        if doc.page_count > 0:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.4, 0.4))
            cover_bytes = pix.tobytes('jpeg')
        doc.close()
        return title, author, cover_bytes
    except Exception:
        return Path(path).stem, '', None
