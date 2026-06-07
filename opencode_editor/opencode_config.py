import json
from collections import defaultdict
from pathlib import Path

_CONFIG_DIR = Path.home() / '.config' / 'opencode'


def config_dir() -> Path:
    return _CONFIG_DIR


def read_agents_md() -> str:
    try:
        return (_CONFIG_DIR / 'AGENTS.md').read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def write_agents_md(content: str):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (_CONFIG_DIR / 'AGENTS.md').write_text(content, encoding='utf-8')


def read_context_learn_md() -> str:
    try:
        return (_CONFIG_DIR / 'context-learn.md').read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def write_context_learn_md(content: str):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (_CONFIG_DIR / 'context-learn.md').write_text(content, encoding='utf-8')


def read_context_store_json() -> str:
    """Return the raw JSON text of context-store.json (the canonical source)."""
    try:
        return (_CONFIG_DIR / 'context-store.json').read_text(encoding='utf-8')
    except FileNotFoundError:
        return '[]'


def write_context_store_json(content: str):
    """Validate JSON, write context-store.json, and regenerate context-store.md."""
    entries = json.loads(content)  # raises on invalid JSON
    if not isinstance(entries, list):
        raise ValueError('context-store.json must be a JSON array')
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (_CONFIG_DIR / 'context-store.json').write_text(content, encoding='utf-8')
    (_CONFIG_DIR / 'context-store.md').write_text(
        _generate_context_store_md(entries), encoding='utf-8'
    )


def _generate_context_store_md(entries: list) -> str:
    """Regenerate context-store.md from context-store.json entries."""
    lines = [
        '# Context Store',
        '',
        'The following context entries provide persistent guidance across sessions.',
        '',
    ]
    by_cat: dict = defaultdict(list)
    for entry in entries:
        if entry.get('enabled', True):
            by_cat[entry.get('category', 'general')].append(entry)

    for cat, items in by_cat.items():
        lines.append(f'## {cat.capitalize()}')
        lines.append('')
        for item in items:
            lines.append(f'### {item["title"]}')
            tags = item.get('tags', [])
            if tags:
                lines.append('*Tags: ' + ' '.join(f'`#{t}`' for t in tags) + '*')
            lines.append('')
            lines.append(item.get('content', ''))
            lines.append('')
            lines.append('---')
            lines.append('')

    return '\n'.join(lines)


# Legacy helpers kept for any callers that still reference them.

def read_context_store_md() -> str:
    try:
        return (_CONFIG_DIR / 'context-store.md').read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def write_context_store_md(content: str):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (_CONFIG_DIR / 'context-store.md').write_text(content, encoding='utf-8')


def read_opencode_json() -> str:
    try:
        return (_CONFIG_DIR / 'opencode.json').read_text(encoding='utf-8')
    except FileNotFoundError:
        return '{}'


def write_opencode_json(content: str):
    json.loads(content)  # raises ValueError on invalid JSON
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (_CONFIG_DIR / 'opencode.json').write_text(content, encoding='utf-8')
