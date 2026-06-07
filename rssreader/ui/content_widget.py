from __future__ import annotations

from urllib.request import Request, urlopen

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from home_os_app.theme import CARD_STYLE, THEME_QSS, paint_background
from ..data import Article, Feed, fetch_feed, load_data, relative_time, save_data


# ── Workers ───────────────────────────────────────────────────────────────────

class _FullArticleWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            from readability import Document
            req = Request(self._url)
            req.add_header('User-Agent', 'Mozilla/5.0 (compatible; HomeOS/1.0)')
            with urlopen(req, timeout=20) as r:
                html = r.read().decode('utf-8', errors='replace')
            self.finished.emit(Document(html).summary())
        except Exception as exc:
            self.error.emit(str(exc)[:120])


class _FeedFetchWorker(QThread):
    feed_done = pyqtSignal(str, str, list)  # url, title, articles
    feed_error = pyqtSignal(str, str)       # url, error message
    all_done = pyqtSignal()

    def __init__(self, urls: list[str], parent=None) -> None:
        super().__init__(parent)
        self._urls = urls

    def run(self) -> None:
        for url in self._urls:
            try:
                title, articles = fetch_feed(url)
                self.feed_done.emit(url, title, articles)
            except Exception as exc:
                self.feed_error.emit(url, str(exc))
        self.all_done.emit()


# ── Add Feed dialog ───────────────────────────────────────────────────────────

class _AddFeedDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Add Feed')
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(THEME_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        lbl = QLabel('RSS or Atom feed URL')
        lbl.setStyleSheet('color: rgba(255,255,255,0.60); background: transparent;')

        self._input = QLineEdit()
        self._input.setPlaceholderText('https://example.com/feed.xml')
        self._input.returnPressed.connect(self._accept)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel = QPushButton('Cancel')
        cancel.setFixedHeight(34)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton('Add')
        ok.setFixedHeight(34)
        ok.setDefault(True)
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self._accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)

        layout.addWidget(lbl)
        layout.addWidget(self._input)
        layout.addSpacing(4)
        layout.addLayout(btn_row)

    def _accept(self) -> None:
        if self._input.text().strip():
            self.accept()

    def url(self) -> str:
        return self._input.text().strip()


# ── Feed row (left panel) ─────────────────────────────────────────────────────

class _FeedRow(QWidget):
    clicked = pyqtSignal(str)   # feed url, or '' for All
    remove_clicked = pyqtSignal(str)

    def __init__(self, url: str, title: str, unread: int, selected: bool,
                 removable: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = selected
        self._update_bg()

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 8, 8)
        h.setSpacing(6)

        name = QLabel(title)
        nf = QFont()
        nf.setPointSize(10)
        nf.setBold(selected)
        name.setFont(nf)
        name.setStyleSheet('background: transparent; color: rgba(255,255,255,0.85);')
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(name, 1)

        if unread > 0:
            badge = QLabel(str(unread))
            bf = QFont()
            bf.setPointSize(8)
            bf.setBold(True)
            badge.setFont(bf)
            badge.setFixedSize(22, 16)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                'background: rgba(99,102,241,0.55); color: white; border-radius: 8px;'
            )
            h.addWidget(badge)

        if removable:
            rm = QPushButton('✕')
            rm.setFixedSize(18, 18)
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.setStyleSheet(
                'QPushButton { background: transparent; border: none;'
                ' color: rgba(255,255,255,0.45); font-size: 10px; }'
                ' QPushButton:hover { color: #f87171; }'
            )
            rm.clicked.connect(lambda: self.remove_clicked.emit(self._url))
            h.addWidget(rm)

    def _update_bg(self) -> None:
        bg = 'rgba(255,255,255,0.10)' if self._selected else 'transparent'
        self.setStyleSheet(f'background: {bg}; border-radius: 6px;')

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._url)
        super().mousePressEvent(event)


# ── Article card (middle list, compact) ───────────────────────────────────────

class _ArticleCard(QWidget):
    clicked = pyqtSignal(object)  # Article

    def __init__(self, article: Article, feed_title: str, selected: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self._article = article
        self._selected = selected
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        if not article.read:
            dot = QLabel()
            dot.setFixedSize(7, 7)
            dot.setStyleSheet('background: #6366f1; border-radius: 3px;')
            title_row.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        title_lbl = QLabel(article.title or '(no title)')
        tf = QFont()
        tf.setPointSize(9)
        tf.setBold(not article.read)
        title_lbl.setFont(tf)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet('background: transparent; color: white;')
        title_row.addWidget(title_lbl, 1)
        v.addLayout(title_row)

        meta_parts = []
        if feed_title:
            meta_parts.append(feed_title)
        rel = relative_time(article.published)
        if rel:
            meta_parts.append(rel)
        if meta_parts:
            meta_lbl = QLabel('  ·  '.join(meta_parts))
            mf = QFont()
            mf.setPointSize(7)
            meta_lbl.setFont(mf)
            meta_lbl.setStyleSheet('background: transparent; color: rgba(255,255,255,0.30);')
            v.addWidget(meta_lbl)

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet('background: rgba(99,102,241,0.18); border-radius: 6px;')
        else:
            self.setStyleSheet('background: transparent; border-radius: 6px;')

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._article)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        if not self._selected:
            self.setStyleSheet('background: rgba(255,255,255,0.06); border-radius: 6px;')
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._update_style()
        super().leaveEvent(event)


# ── Article detail pane (right panel) ────────────────────────────────────────

class _ArticleDetailPane(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet('background: transparent;')
        self._link = ''
        self._summary_html = ''
        self._summary_text = ''
        self._showing_full = False
        self._fetch_worker: _FullArticleWorker | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 4, 8, 8)
        v.setSpacing(0)

        # Empty state
        self._empty_lbl = QLabel('Select an article to read')
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ef = QFont()
        ef.setPointSize(11)
        self._empty_lbl.setFont(ef)
        self._empty_lbl.setStyleSheet('color: rgba(255,255,255,0.18); background: transparent;')
        v.addWidget(self._empty_lbl, 1, Qt.AlignmentFlag.AlignCenter)

        # Article content (hidden until selected)
        self._content = QWidget()
        self._content.setStyleSheet('background: transparent;')
        self._content.hide()
        cv = QVBoxLayout(self._content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)

        self._title_lbl = QLabel()
        self._title_lbl.setWordWrap(True)
        tf = QFont()
        tf.setPointSize(13)
        tf.setBold(True)
        self._title_lbl.setFont(tf)
        self._title_lbl.setStyleSheet('color: white; background: transparent;')
        cv.addWidget(self._title_lbl)

        self._meta_lbl = QLabel()
        mf = QFont()
        mf.setPointSize(8)
        self._meta_lbl.setFont(mf)
        self._meta_lbl.setStyleSheet('color: rgba(255,255,255,0.35); background: transparent;')
        cv.addWidget(self._meta_lbl)

        cv.addSpacing(8)

        self._browser = QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url))
        self._browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._browser.setStyleSheet(
            'QTextBrowser { background: transparent; border: none; }'
            ' QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }'
            ' QScrollBar::handle:vertical { background: rgba(255,255,255,0.14);'
            '   border-radius: 2px; min-height: 20px; }'
            ' QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
        )
        self._browser.document().setDefaultStyleSheet(
            'body { color: rgba(255,255,255,0.80); font-family: sans-serif;'
            '  font-size: 13px; line-height: 1.65; margin: 0; padding: 0; }'
            ' a { color: #818cf8; }'
            ' img { max-width: 100%; height: auto; }'
            ' p { margin: 0 0 10px 0; }'
            ' h1, h2, h3, h4 { color: white; margin: 12px 0 6px 0; }'
            ' blockquote { border-left: 3px solid rgba(255,255,255,0.18);'
            '  margin: 0 0 10px 0; padding-left: 12px; color: rgba(255,255,255,0.50); }'
            ' pre { background: rgba(255,255,255,0.06); border-radius: 4px; padding: 8px; }'
            ' code { background: rgba(255,255,255,0.06); border-radius: 3px;'
            '  padding: 1px 4px; font-size: 12px; }'
            ' ul, ol { margin: 0 0 10px 0; padding-left: 20px; }'
        )
        cv.addWidget(self._browser, 1)

        cv.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._full_btn = QPushButton('Load Full Article')
        self._full_btn.setFixedHeight(30)
        self._full_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._full_btn.setStyleSheet(
            'QPushButton { color: #4ade80; font-size: 9px;'
            '  background: rgba(74,222,128,0.10); border-radius: 6px; }'
            ' QPushButton:hover { background: rgba(74,222,128,0.20); }'
            ' QPushButton:disabled { color: rgba(255,255,255,0.25);'
            '  background: rgba(255,255,255,0.05); }'
        )
        self._full_btn.clicked.connect(self._toggle_full)

        open_btn = QPushButton('Open in Browser')
        open_btn.setFixedHeight(30)
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(
            'QPushButton { color: #818cf8; font-size: 9px;'
            '  background: rgba(99,102,241,0.12); border-radius: 6px; }'
            ' QPushButton:hover { background: rgba(99,102,241,0.24); }'
        )
        open_btn.clicked.connect(self._open_in_browser)

        btn_row.addWidget(self._full_btn, 1)
        btn_row.addWidget(open_btn, 1)
        cv.addLayout(btn_row)

        v.addWidget(self._content, 1)

    def show_article(self, article: Article, feed_title: str) -> None:
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.finished.disconnect()
            self._fetch_worker.error.disconnect()
            self._fetch_worker.quit()

        self._link = article.link or ''
        self._summary_html = article.summary_html or ''
        self._summary_text = article.summary or ''
        self._showing_full = False
        self._fetch_worker = None

        self._title_lbl.setText(article.title or '(no title)')

        meta_parts = []
        if feed_title:
            meta_parts.append(feed_title)
        rel = relative_time(article.published)
        if rel:
            meta_parts.append(rel)
        self._meta_lbl.setText('  ·  '.join(meta_parts))

        self._render_summary()
        self._full_btn.setText('Load Full Article')
        self._full_btn.setEnabled(bool(self._link))

        self._empty_lbl.hide()
        self._content.show()

    def clear(self) -> None:
        self._link = ''
        self._content.hide()
        self._empty_lbl.show()

    def _render_summary(self) -> None:
        if self._summary_html:
            self._browser.setHtml(self._summary_html)
        elif self._summary_text:
            self._browser.setPlainText(self._summary_text)
        else:
            self._browser.setPlainText('No content available.')
        self._browser.verticalScrollBar().setValue(0)

    def _toggle_full(self) -> None:
        if self._showing_full:
            self._showing_full = False
            self._full_btn.setText('Load Full Article')
            self._render_summary()
            return

        self._full_btn.setEnabled(False)
        self._full_btn.setText('Loading…')
        self._fetch_worker = _FullArticleWorker(self._link, self)
        self._fetch_worker.finished.connect(self._on_full_loaded)
        self._fetch_worker.error.connect(self._on_full_error)
        self._fetch_worker.start()

    def _on_full_loaded(self, html: str) -> None:
        self._showing_full = True
        self._browser.setHtml(html)
        self._browser.verticalScrollBar().setValue(0)
        self._full_btn.setText('Show Summary')
        self._full_btn.setEnabled(True)

    def _on_full_error(self, msg: str) -> None:
        self._full_btn.setText('Load Full Article')
        self._full_btn.setEnabled(True)
        self._meta_lbl.setText(f'Failed to load: {msg}')

    def _open_in_browser(self) -> None:
        if self._link:
            QDesktopServices.openUrl(QUrl(self._link))


# ── Main content widget ───────────────────────────────────────────────────────

class RSSReaderContent(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._feeds: list[Feed] = []
        self._articles: list[Article] = []
        self._selected_feed: str = ''       # '' = All
        self._selected_article_id: str = ''
        self._worker: _FeedFetchWorker | None = None

        self._setup_ui()
        self._load()

    def paintEvent(self, event) -> None:
        paint_background(self)

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)

        main = QVBoxLayout(self)
        main.setContentsMargins(24, 20, 24, 16)
        main.setSpacing(14)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(CARD_STYLE)
        hdr_h = QHBoxLayout(hdr)
        hdr_h.setContentsMargins(20, 14, 20, 14)
        hdr_h.setSpacing(10)

        title = QLabel('RSS Reader')
        tf = QFont()
        tf.setPointSize(10)
        title.setFont(tf)
        title.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        self._status_lbl = QLabel('')
        self._status_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.28); font-size: 9px; background: transparent;'
        )

        self._refresh_btn = QPushButton('↻  Refresh All')
        self._refresh_btn.setFixedHeight(34)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setStyleSheet(
            'QPushButton { color: #94a3b8; }'
            ' QPushButton:disabled { color: rgba(255,255,255,0.25); }'
        )
        self._refresh_btn.clicked.connect(self._refresh_all)

        self._remove_btn = QPushButton('✕  Remove Feed')
        self._remove_btn.setFixedHeight(34)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setEnabled(False)
        self._remove_btn.setStyleSheet(
            'QPushButton { color: #f87171; }'
            ' QPushButton:disabled { color: rgba(255,255,255,0.20); }'
        )
        self._remove_btn.clicked.connect(lambda: self._remove_feed(self._selected_feed))

        self._add_btn = QPushButton('＋  Add Feed')
        self._add_btn.setFixedHeight(34)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet('QPushButton { color: #4ade80; }')
        self._add_btn.clicked.connect(self._add_feed)

        hdr_h.addWidget(title)
        hdr_h.addWidget(self._status_lbl, 1)
        hdr_h.addWidget(self._refresh_btn)
        hdr_h.addWidget(self._remove_btn)
        hdr_h.addWidget(self._add_btn)
        main.addWidget(hdr)

        # Outer splitter: feed panel | (article list + detail)
        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.setStyleSheet(
            'QSplitter { background: transparent; }'
            ' QSplitter::handle { background: rgba(255,255,255,0.06); width: 1px; }'
        )
        main.addWidget(outer, 1)

        # Left: feed panel
        feed_panel = QWidget()
        feed_panel.setStyleSheet('background: transparent;')
        feed_panel.setMinimumWidth(160)
        feed_panel.setMaximumWidth(240)
        self._feed_layout = QVBoxLayout(feed_panel)
        self._feed_layout.setContentsMargins(0, 0, 8, 0)
        self._feed_layout.setSpacing(2)
        self._feed_layout.addStretch()
        outer.addWidget(feed_panel)

        # Inner splitter: article list | article detail
        inner = QSplitter(Qt.Orientation.Horizontal)
        inner.setStyleSheet(
            'QSplitter { background: transparent; }'
            ' QSplitter::handle { background: rgba(255,255,255,0.06); width: 1px; }'
        )
        outer.addWidget(inner)

        # Middle: article list
        list_panel = QWidget()
        list_panel.setStyleSheet('background: transparent;')
        list_panel.setMinimumWidth(200)
        list_panel.setMaximumWidth(360)
        list_v = QVBoxLayout(list_panel)
        list_v.setContentsMargins(8, 0, 8, 0)
        list_v.setSpacing(0)

        self._article_scroll = QScrollArea()
        self._article_scroll.setWidgetResizable(True)
        self._article_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._article_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._article_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._article_scroll.viewport().setAutoFillBackground(False)

        self._article_container = QWidget()
        self._article_container.setStyleSheet('background: transparent;')
        self._article_layout = QVBoxLayout(self._article_container)
        self._article_layout.setContentsMargins(0, 0, 0, 0)
        self._article_layout.setSpacing(4)
        self._article_layout.addStretch()
        self._article_scroll.setWidget(self._article_container)
        list_v.addWidget(self._article_scroll)
        inner.addWidget(list_panel)

        # Right: article detail pane
        self._detail_pane = _ArticleDetailPane()
        self._detail_pane.setMinimumWidth(280)
        inner.addWidget(self._detail_pane)

        inner.setStretchFactor(0, 0)
        inner.setStretchFactor(1, 1)
        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        self._feeds, self._articles = load_data()
        self._rebuild_feed_panel()
        self._rebuild_article_panel()

    def _save(self) -> None:
        save_data(self._feeds, self._articles)

    def _feed_title(self, url: str) -> str:
        for f in self._feeds:
            if f.url == url:
                return f.title or url
        return url

    def _unread_count(self, url: str | None = None) -> int:
        arts = self._articles if url is None else [a for a in self._articles if a.feed_url == url]
        return sum(1 for a in arts if not a.read)

    # ── UI rebuild ────────────────────────────────────────────────────────────

    def _rebuild_feed_panel(self) -> None:
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        all_row = _FeedRow('', 'All Feeds', self._unread_count(), self._selected_feed == '', removable=False)
        all_row.clicked.connect(self._select_feed)
        self._feed_layout.addWidget(all_row)

        for feed in self._feeds:
            row = _FeedRow(
                feed.url, feed.title or feed.url,
                self._unread_count(feed.url),
                self._selected_feed == feed.url,
            )
            row.clicked.connect(self._select_feed)
            row.remove_clicked.connect(self._remove_feed)
            self._feed_layout.addWidget(row)

        self._feed_layout.addStretch()

    def _rebuild_article_panel(self) -> None:
        while self._article_layout.count():
            item = self._article_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if self._selected_feed == '':
            articles = self._articles
        else:
            articles = [a for a in self._articles if a.feed_url == self._selected_feed]

        articles = sorted(articles, key=lambda a: a.published, reverse=True)

        if not articles:
            if not self._feeds:
                msg = 'No feeds added yet.\nClick  ＋ Add Feed  to get started.'
            else:
                msg = 'No articles yet. Click  ↻ Refresh All  to fetch.'
            empty = QLabel(msg)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            ef = QFont()
            ef.setPointSize(11)
            empty.setFont(ef)
            empty.setStyleSheet('color: rgba(255,255,255,0.25); background: transparent;')
            self._article_layout.addWidget(empty)
        else:
            for article in articles:
                feed_title = self._feed_title(article.feed_url) if self._selected_feed == '' else ''
                selected = article.id == self._selected_article_id
                card = _ArticleCard(article, feed_title, selected)
                card.clicked.connect(self._select_article)
                self._article_layout.addWidget(card)

        self._article_layout.addStretch()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _select_feed(self, url: str) -> None:
        self._selected_feed = url
        self._selected_article_id = ''
        self._detail_pane.clear()
        self._remove_btn.setEnabled(bool(url))
        self._rebuild_feed_panel()
        self._rebuild_article_panel()

    def _select_article(self, article: Article) -> None:
        self._selected_article_id = article.id
        feed_title = self._feed_title(article.feed_url)
        self._detail_pane.show_article(article, feed_title)

        was_unread = not article.read
        for a in self._articles:
            if a.id == article.id:
                a.read = True
                break

        if was_unread:
            self._save()
            self._rebuild_feed_panel()

        self._rebuild_article_panel()

    def _add_feed(self) -> None:
        dlg = _AddFeedDialog(self)
        dlg.setStyleSheet(self.styleSheet())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url = dlg.url()
        if any(f.url == url for f in self._feeds):
            return
        self._feeds.append(Feed(url=url))
        self._save()
        self._rebuild_feed_panel()
        self._refresh_urls([url])

    def _remove_feed(self, url: str) -> None:
        self._feeds = [f for f in self._feeds if f.url != url]
        self._articles = [a for a in self._articles if a.feed_url != url]
        if self._selected_feed == url:
            self._selected_feed = ''
            self._remove_btn.setEnabled(False)
        if any(a.id == self._selected_article_id and a.feed_url == url
               for a in self._articles):
            self._selected_article_id = ''
            self._detail_pane.clear()
        self._save()
        self._rebuild_feed_panel()
        self._rebuild_article_panel()

    def _refresh_all(self) -> None:
        self._refresh_urls([f.url for f in self._feeds])

    def _refresh_urls(self, urls: list[str]) -> None:
        if not urls:
            return
        if self._worker and self._worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText('Fetching…')
        self._status_lbl.setText('')

        self._worker = _FeedFetchWorker(urls, self)
        self._worker.feed_done.connect(self._on_feed_done)
        self._worker.feed_error.connect(self._on_feed_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _on_feed_done(self, url: str, title: str, new_articles: list) -> None:
        for feed in self._feeds:
            if feed.url == url:
                feed.title = title
                break

        existing_ids = {a.id for a in self._articles}
        added = 0
        for article in new_articles:
            if article.id not in existing_ids:
                self._articles.append(article)
                added += 1

        self._save()
        self._status_lbl.setText(f'+{added} new' if added else 'Up to date')
        self._rebuild_feed_panel()
        self._rebuild_article_panel()

    def _on_feed_error(self, url: str, msg: str) -> None:
        self._status_lbl.setText(f'Error: {msg[:50]}')

    def _on_all_done(self) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText('↻  Refresh All')
