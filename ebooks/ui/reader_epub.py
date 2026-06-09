from __future__ import annotations

import zipfile
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from home_os_app.theme import THEME_QSS


# ── Constants ─────────────────────────────────────────────────────────────────

_DARK_CSS = """\
<style id="_homeos_dark">
html, body {
    background-color: #0f0c29 !important;
    color: rgba(255,255,255,0.85) !important;
    overflow-x: hidden !important;
}
body {
    font-family: Georgia, 'Times New Roman', serif !important;
    font-size: 18px !important;
    line-height: 1.8 !important;
    max-width: 720px !important;
    margin: 0 auto !important;
    padding: 48px 24px !important;
}
h1, h2, h3, h4, h5, h6 { color: white !important; }
a { color: #818cf8 !important; }
img { max-width: 100% !important; height: auto !important; }
blockquote {
    border-left: 3px solid rgba(255,255,255,0.2) !important;
    padding-left: 1em !important;
    color: rgba(255,255,255,0.55) !important;
    margin-left: 0 !important;
}
p { margin-bottom: 1em !important; }
html::-webkit-scrollbar, body::-webkit-scrollbar { display: none !important; }
html { scrollbar-width: none !important; }
</style>"""

_FONT_SIZES = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 40, 48, 56, 64, 72, 84, 96]
_SPACINGS   = [1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]


# Height of the top-fade overlay; each page advances by (innerHeight - this).
# Keep small so the faded zone is at most a partial line, never a full paragraph.
_PAGE_OVERLAP = 15

# ── Helpers ───────────────────────────────────────────────────────────────────

def _inject_dark_css(html: str) -> str:
    lower = html.lower()
    if '</head>' in lower:
        idx = lower.rfind('</head>')
        return html[:idx] + _DARK_CSS + html[idx:]
    if '<body' in lower:
        idx = lower.find('<body')
        return html[:idx] + '<head>' + _DARK_CSS + '</head>' + html[idx:]
    return _DARK_CSS + html


class _NoNavPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if not url.isLocalFile():
                QDesktopServices.openUrl(url)
                return False
        return True


class _KeyFilter(QObject):
    """App-level filter — QWebEngineView swallows keys before Qt shortcuts fire."""

    def __init__(self, reader: EPUBReader, parent=None) -> None:
        super().__init__(parent)
        self._reader = reader
        self.active  = False

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if self.active and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Right:
                self._reader.next_page()
                return True
            if key == Qt.Key.Key_Left:
                self._reader.prev_page()
                return True
        return False


# ── Reader ────────────────────────────────────────────────────────────────────

class EPUBReader(QWidget):
    position_changed = pyqtSignal(int)

    def __init__(self, path: str, start_position: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._chapters: list[str] = []
        self._current     = 0
        self._page        = 0    # current page within chapter
        self._total_pages = 1
        self._target_page = 0    # -1 means scroll to last page after load
        self._tmp: tempfile.TemporaryDirectory | None = None

        self._load_settings()

        self._key_filter = _KeyFilter(self, self)
        QApplication.instance().installEventFilter(self._key_filter)
        self._key_filter.active = True

        self._setup_ui()
        self._load(path, start_position)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        s = QSettings('HomeOS', 'EBookReader')
        self._font_size    = int(s.value('font_size',    18))
        self._line_spacing = float(s.value('line_spacing', 1.8))
        self._margin_value = int(s.value('margin_value', 30))

    def _save_settings(self) -> None:
        s = QSettings('HomeOS', 'EBookReader')
        s.setValue('font_size',    self._font_size)
        s.setValue('line_spacing', self._line_spacing)
        s.setValue('margin_value', self._margin_value)

    def _settings_apply_js(self) -> str:
        # Computes max-width from actual clientWidth so slider 0=full, 100=500px narrow.
        font = self._font_size
        ls   = f'{self._line_spacing:.1f}'
        mv   = self._margin_value
        return (
            '(function(){'
            + f'var vw=document.documentElement.clientWidth;'
            + f'var maxW=Math.max(500,Math.round(vw+(500-vw)*{mv}/100))+"px";'
            + f'var css="body{{font-size:{font}px!important;max-width:"+maxW+"!important;transition:max-width 0.3s ease}}body,p,li,div,span,td,th,blockquote{{line-height:{ls}!important}}";'
            + 'var s=document.getElementById("_reader_settings");'
            + 'if(!s){s=document.createElement("style");s.id="_reader_settings";document.head.appendChild(s);}'
            + 's.textContent=css;'
            + '})()'
        )

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        v.addWidget(self._make_settings_bar())

        self._view = QWebEngineView()
        page = _NoNavPage(self._view)
        page.setBackgroundColor(QColor('#0f0c29'))
        self._view.setPage(page)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self._view.loadFinished.connect(self._on_load_finished)
        v.addWidget(self._view, 1)

        nav = QWidget()
        nav.setStyleSheet(
            'background: rgba(255,255,255,0.04);'
            ' border-top: 1px solid rgba(255,255,255,0.08);'
        )
        h = QHBoxLayout(nav)
        h.setContentsMargins(16, 8, 16, 8)

        self._prev_btn = QPushButton('← Prev')
        self._prev_btn.setFixedHeight(30)
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.clicked.connect(self.prev_page)

        self._pos_lbl = QLabel()
        self._pos_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(9)
        self._pos_lbl.setFont(f)
        self._pos_lbl.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        self._next_btn = QPushButton('Next →')
        self._next_btn.setFixedHeight(30)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.clicked.connect(self.next_page)

        h.addWidget(self._prev_btn)
        h.addStretch()
        h.addWidget(self._pos_lbl)
        h.addStretch()
        h.addWidget(self._next_btn)
        v.addWidget(nav)

    def _make_settings_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            'background: rgba(255,255,255,0.03);'
            ' border-bottom: 1px solid rgba(255,255,255,0.08);'
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 8, 20, 8)
        h.setSpacing(6)

        def dim(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                'color: rgba(255,255,255,0.35); background: transparent; font-size: 9px;'
            )
            return lbl

        def sep() -> QFrame:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFixedHeight(22)
            line.setStyleSheet('color: rgba(255,255,255,0.12);')
            return line

        # Font size
        h.addWidget(dim('Font'))
        self._font_dec_btn = QPushButton('A−')
        self._font_dec_btn.setFixedSize(34, 26)
        self._font_dec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font_dec_btn.clicked.connect(self._dec_font)
        self._font_lbl = QLabel(f'{self._font_size}px')
        self._font_lbl.setFixedWidth(38)
        self._font_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._font_lbl.setStyleSheet('color: white; background: transparent; font-size: 10px;')
        self._font_inc_btn = QPushButton('A+')
        self._font_inc_btn.setFixedSize(34, 26)
        self._font_inc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font_inc_btn.clicked.connect(self._inc_font)
        h.addWidget(self._font_dec_btn)
        h.addWidget(self._font_lbl)
        h.addWidget(self._font_inc_btn)

        h.addSpacing(8)
        h.addWidget(sep())
        h.addSpacing(8)

        # Line spacing
        h.addWidget(dim('Spacing'))
        self._spacing_dec_btn = QPushButton('−')
        self._spacing_dec_btn.setFixedSize(26, 26)
        self._spacing_dec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._spacing_dec_btn.clicked.connect(self._dec_spacing)
        self._spacing_lbl = QLabel(f'{self._line_spacing:.1f}')
        self._spacing_lbl.setFixedWidth(28)
        self._spacing_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spacing_lbl.setStyleSheet('color: white; background: transparent; font-size: 10px;')
        self._spacing_inc_btn = QPushButton('+')
        self._spacing_inc_btn.setFixedSize(26, 26)
        self._spacing_inc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._spacing_inc_btn.clicked.connect(self._inc_spacing)
        h.addWidget(self._spacing_dec_btn)
        h.addWidget(self._spacing_lbl)
        h.addWidget(self._spacing_inc_btn)

        h.addSpacing(8)
        h.addWidget(sep())
        h.addSpacing(8)

        # Margin slider
        h.addWidget(dim('Margins'))
        narrow_lbl = QLabel('Full')
        narrow_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.30); background: transparent; font-size: 9px;'
        )
        self._margin_slider = QSlider(Qt.Orientation.Horizontal)
        self._margin_slider.setRange(0, 100)
        self._margin_slider.setValue(self._margin_value)
        self._margin_slider.setFixedWidth(130)
        self._margin_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: rgba(255,255,255,0.15);
                border-radius: 1px;
            }
            QSlider::handle:horizontal {
                background: rgba(255,255,255,0.75);
                border: none;
                width: 12px; height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover { background: white; }
            QSlider::sub-page:horizontal {
                background: rgba(255,255,255,0.45);
                border-radius: 1px;
            }
        """)
        self._margin_slider.valueChanged.connect(self._on_margin_changed)
        wide_lbl = QLabel('Narrow')
        wide_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.30); background: transparent; font-size: 9px;'
        )
        h.addWidget(narrow_lbl)
        h.addWidget(self._margin_slider)
        h.addWidget(wide_lbl)

        h.addStretch()
        return bar

    # ── EPUB loading ──────────────────────────────────────────────────────────

    def _load(self, path: str, start: int) -> None:
        try:
            import ebooklib
            from ebooklib import epub
        except ImportError:
            self._view.setHtml(
                '<body style="color:white;background:#0f0c29;padding:40px;font-family:sans-serif">'
                '<b>ebooklib</b> is not installed. Run: <code>pip install ebooklib</code>'
                '</body>'
            )
            return

        self._tmp = tempfile.TemporaryDirectory(prefix='homeos_epub_')
        try:
            with zipfile.ZipFile(path) as z:
                z.extractall(self._tmp.name)
        except Exception as e:
            self._view.setHtml(
                f'<body style="color:white;background:#0f0c29;padding:40px;font-family:sans-serif">'
                f'Failed to open EPUB:<br>{e}</body>'
            )
            return

        book = epub.read_epub(path, options={'ignore_ncx': True})
        tmp_root = Path(self._tmp.name)
        opf_dirs = [f.parent for f in tmp_root.rglob('*.opf')]
        opf_dir  = opf_dirs[0] if opf_dirs else tmp_root

        self._chapters = []
        for item_id, _linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            href = item.get_name()
            file_path = opf_dir / href
            if not file_path.exists():
                file_path = tmp_root / href
            if not file_path.exists():
                candidates = list(tmp_root.rglob(Path(href).name))
                file_path = candidates[0] if candidates else None
            if file_path is None or not file_path.exists():
                continue
            try:
                content = file_path.read_text(errors='replace')
                file_path.write_text(
                    _inject_dark_css(content), encoding='utf-8', errors='replace'
                )
                self._chapters.append(str(file_path))
            except Exception:
                pass

        if self._chapters:
            self._current = max(0, min(start, len(self._chapters) - 1))
            self._show_chapter(self._current, target_page=0)
        else:
            self._view.setHtml(
                '<body style="color:white;background:#0f0c29;padding:40px;font-family:sans-serif">'
                'No readable chapters found in this EPUB.</body>'
            )
        self._update_nav()

    def _show_chapter(self, index: int, target_page: int = 0) -> None:
        self._current     = index
        self._target_page = target_page
        self._page        = 0
        self._total_pages = 1
        self._view.load(QUrl.fromLocalFile(self._chapters[index]))
        self.position_changed.emit(index)

    def _on_load_finished(self, ok: bool) -> None:
        font = self._font_size
        ls   = f'{self._line_spacing:.1f}'
        mv   = self._margin_value
        setup_js = (
            '(function(){'
            # Block arrow-key browser scroll (Python filter handles actual navigation)
            + 'document.addEventListener("keydown",function(e){'
            + 'var k=["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"," ","PageUp","PageDown"];'
            + 'if(k.indexOf(e.key)!==-1)e.preventDefault();},true);'
            # Apply typography settings
            + f'var vw=document.documentElement.clientWidth;'
            + f'var maxW=Math.max(500,Math.round(vw+(500-vw)*{mv}/100))+"px";'
            + f'var css="body{{font-size:{font}px!important;max-width:"+maxW+"!important;transition:max-width 0.3s ease}}body,p,li,div,span,td,th,blockquote{{line-height:{ls}!important}}";'
            + 'var s=document.getElementById("_reader_settings");'
            + 'if(!s){s=document.createElement("style");s.id="_reader_settings";document.head.appendChild(s);}'
            + 's.textContent=css;'
            # Fixed top-fade overlay: covers clipped text at each page boundary.
            # position:fixed keeps it anchored to the viewport regardless of scroll.
            + 'if(!document.getElementById("_top_fade")){'
            + 'var f=document.createElement("div");f.id="_top_fade";'
            + 'f.style.cssText="position:fixed;top:0;left:0;right:0;height:15px;'
            + 'background:linear-gradient(to bottom,#0f0c29 30%,rgba(15,12,41,0) 100%);'
            + 'pointer-events:none;z-index:9999;";'
            + 'document.body.appendChild(f);}'
            + '})()'
        )
        self._view.page().runJavaScript(setup_js)
        QTimer.singleShot(150, self._calculate_initial_page)

    def _calculate_initial_page(self) -> None:
        target = self._target_page
        overlap = _PAGE_OVERLAP
        js = f"""(function() {{
            var step = Math.max(1, window.innerHeight - {overlap});
            var total = Math.max(1, Math.ceil(
                document.documentElement.scrollHeight / step
            ));
            var page = {target} === -1 ? total - 1 : Math.min({target}, total - 1);
            window.scrollTo(0, page * step);
            return [total, page];
        }})()"""
        self._view.page().runJavaScript(js, self._on_chapter_ready)

    def _on_chapter_ready(self, result) -> None:
        if isinstance(result, (list, tuple)) and len(result) == 2:
            self._total_pages = max(1, int(result[0]))
            self._page        = max(0, int(result[1]))
        self._update_nav()

    # ── Typography settings ───────────────────────────────────────────────────

    def _apply_settings(self) -> None:
        self._view.page().runJavaScript(self._settings_apply_js())
        self._save_settings()
        QTimer.singleShot(350, self._recalculate_pages)

    def _recalculate_pages(self) -> None:
        page = self._page
        overlap = _PAGE_OVERLAP
        js = f"""(function() {{
            var step = Math.max(1, window.innerHeight - {overlap});
            var total = Math.max(1, Math.ceil(
                document.documentElement.scrollHeight / step
            ));
            var page = Math.min({page}, total - 1);
            window.scrollTo(0, page * step);
            return [total, page];
        }})()"""
        self._view.page().runJavaScript(js, self._on_chapter_ready)

    def _inc_font(self) -> None:
        try:
            idx = _FONT_SIZES.index(self._font_size)
        except ValueError:
            idx = 3
        if idx < len(_FONT_SIZES) - 1:
            self._font_size = _FONT_SIZES[idx + 1]
            self._font_lbl.setText(f'{self._font_size}px')
            self._apply_settings()

    def _dec_font(self) -> None:
        try:
            idx = _FONT_SIZES.index(self._font_size)
        except ValueError:
            idx = 3
        if idx > 0:
            self._font_size = _FONT_SIZES[idx - 1]
            self._font_lbl.setText(f'{self._font_size}px')
            self._apply_settings()

    def _inc_spacing(self) -> None:
        candidates = [s for s in _SPACINGS if s > self._line_spacing + 0.05]
        if candidates:
            self._line_spacing = candidates[0]
            self._spacing_lbl.setText(f'{self._line_spacing:.1f}')
            self._apply_settings()

    def _dec_spacing(self) -> None:
        candidates = [s for s in _SPACINGS if s < self._line_spacing - 0.05]
        if candidates:
            self._line_spacing = candidates[-1]
            self._spacing_lbl.setText(f'{self._line_spacing:.1f}')
            self._apply_settings()

    def _on_margin_changed(self, value: int) -> None:
        self._margin_value = value
        self._apply_settings()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _update_nav(self) -> None:
        total_ch = len(self._chapters)
        if total_ch:
            self._pos_lbl.setText(
                f'p. {self._page + 1} / {self._total_pages}'
                f'  ·  Ch. {self._current + 1} / {total_ch}'
            )
        else:
            self._pos_lbl.setText('')
        at_start = self._current == 0 and self._page == 0
        at_end   = (self._current == total_ch - 1
                    and self._page >= self._total_pages - 1)
        self._prev_btn.setEnabled(not at_start)
        self._next_btn.setEnabled(not at_end)

    def next_page(self) -> None:
        if self._page < self._total_pages - 1:
            self._page += 1
            self._view.page().runJavaScript(
                f'(function(){{var s=Math.max(1,window.innerHeight-{_PAGE_OVERLAP});'
                f'window.scrollTo(0,{self._page}*s);}})();'
            )
            self._update_nav()
        elif self._current < len(self._chapters) - 1:
            self._show_chapter(self._current + 1, target_page=0)
            self._update_nav()

    def prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._view.page().runJavaScript(
                f'(function(){{var s=Math.max(1,window.innerHeight-{_PAGE_OVERLAP});'
                f'window.scrollTo(0,{self._page}*s);}})();'
            )
            self._update_nav()
        elif self._current > 0:
            self._show_chapter(self._current - 1, target_page=-1)
            self._update_nav()

    @property
    def current_position(self) -> int:
        return self._current

    def cleanup(self) -> None:
        self._key_filter.active = False
        QApplication.instance().removeEventFilter(self._key_filter)
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
