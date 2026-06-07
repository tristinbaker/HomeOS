from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

RSS_PATH = Path.home() / '.local' / 'share' / 'home_os' / 'rss_data.json'
_MAX_ARTICLES_PER_FEED = 50

_ATOM_NS = 'http://www.w3.org/2005/Atom'


@dataclass
class Feed:
    url: str
    title: str = ''
    last_fetched: str = ''


@dataclass
class Article:
    id: str
    feed_url: str
    title: str
    link: str
    summary: str
    published: str
    read: bool = False
    summary_html: str = ''


def _article_id(feed_url: str, link: str) -> str:
    return hashlib.md5(f'{feed_url}\x00{link}'.encode()).hexdigest()


def _strip_html(text: str) -> str:
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _parse_date(raw: str) -> str:
    """Normalize any date string to ISO format, or return raw on failure."""
    if not raw:
        return ''
    raw = raw.strip()
    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z'):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw).isoformat()
    except ValueError:
        return raw


def relative_time(iso: str) -> str:
    """Return a human-readable relative time string."""
    if not iso:
        return ''
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        secs = int((now - dt).total_seconds())
        if secs < 60:
            return 'just now'
        if secs < 3600:
            return f'{secs // 60}m ago'
        if secs < 86400:
            return f'{secs // 3600}h ago'
        if secs < 86400 * 7:
            return f'{secs // 86400}d ago'
        return dt.strftime('%b %-d')
    except Exception:
        return ''


def load_data() -> tuple[list[Feed], list[Article]]:
    try:
        raw = json.loads(RSS_PATH.read_text())
        feeds = [Feed(**f) for f in raw.get('feeds', [])]
        articles = [Article(**a) for a in raw.get('articles', [])]
        return feeds, articles
    except Exception:
        return [], []


def save_data(feeds: list[Feed], articles: list[Article]) -> None:
    RSS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RSS_PATH.write_text(json.dumps({
        'feeds':    [asdict(f) for f in feeds],
        'articles': [asdict(a) for a in articles],
    }, indent=2))


def fetch_feed(url: str) -> tuple[str, list[Article]]:
    """Fetch and parse an RSS or Atom feed. Returns (feed_title, articles)."""
    req = Request(url)
    req.add_header('User-Agent', 'HomeOS RSS/1.0')
    with urlopen(req, timeout=15) as r:
        content = r.read()

    root = ET.fromstring(content)

    if root.tag == f'{{{_ATOM_NS}}}feed' or root.tag == 'feed':
        return _parse_atom(url, root)
    else:
        return _parse_rss(url, root)


def _parse_atom(url: str, root: ET.Element) -> tuple[str, list[Article]]:
    def _find(el, tag):
        return el.find(f'{{{_ATOM_NS}}}{tag}') or el.find(tag)

    title_el = _find(root, 'title')
    feed_title = title_el.text if title_el is not None else url

    articles = []
    for entry in (root.findall(f'{{{_ATOM_NS}}}entry') or root.findall('entry')):
        t   = _find(entry, 'title')
        lnk = _find(entry, 'link')
        s   = _find(entry, 'summary') or _find(entry, 'content')
        p   = _find(entry, 'published') or _find(entry, 'updated')

        link = lnk.get('href', lnk.text or '') if lnk is not None else ''
        raw_html = s.text if s is not None else ''
        articles.append(Article(
            id          = _article_id(url, link),
            feed_url    = url,
            title       = _strip_html(t.text if t is not None else ''),
            link        = link,
            summary     = _strip_html(raw_html),
            published   = _parse_date(p.text if p is not None else ''),
            read        = False,
            summary_html= raw_html,
        ))
    return feed_title, articles[:_MAX_ARTICLES_PER_FEED]


def _parse_rss(url: str, root: ET.Element) -> tuple[str, list[Article]]:
    channel = root.find('channel')
    if channel is None:
        return url, []

    title_el = channel.find('title')
    feed_title = title_el.text if title_el is not None else url

    articles = []
    for item in channel.findall('item'):
        t   = item.find('title')
        lnk = item.find('link')
        s   = item.find('description')
        p   = item.find('pubDate')

        link = lnk.text or '' if lnk is not None else ''
        raw_html = s.text if s is not None else ''
        articles.append(Article(
            id          = _article_id(url, link),
            feed_url    = url,
            title       = _strip_html(t.text if t is not None else ''),
            link        = link,
            summary     = _strip_html(raw_html),
            published   = _parse_date(p.text if p is not None else ''),
            read        = False,
            summary_html= raw_html,
        ))
    return feed_title, articles[:_MAX_ARTICLES_PER_FEED]
