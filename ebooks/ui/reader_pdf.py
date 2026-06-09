from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from home_os_app.theme import THEME_QSS

_RENDER_DPI = 150


class PDFReader(QWidget):
    position_changed = pyqtSignal(int)

    def __init__(self, path: str, start_position: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._doc = None
        self._total = 0
        self._current = 0

        self._setup_ui()
        self._load(path, start_position)

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet('QScrollArea { background: #0f0c29; border: none; }')

        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._page_label.setStyleSheet('background: #0f0c29; padding: 16px 0;')
        self._page_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._scroll.setWidget(self._page_label)
        v.addWidget(self._scroll, 1)

        nav = QWidget()
        nav.setStyleSheet(
            'background: rgba(255,255,255,0.04);'
            ' border-top: 1px solid rgba(255,255,255,0.08);'
        )
        h = QHBoxLayout(nav)
        h.setContentsMargins(16, 10, 16, 10)

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

    def _load(self, path: str, start: int) -> None:
        try:
            import fitz
        except ImportError:
            self._page_label.setText(
                'PyMuPDF (fitz) is not installed.\nRun: pip install PyMuPDF'
            )
            self._page_label.setStyleSheet(
                'color: white; background: #0f0c29; padding: 40px;'
                ' font-family: sans-serif; qproperty-alignment: AlignCenter;'
            )
            return
        try:
            self._doc = fitz.open(path)
            self._total = self._doc.page_count
            self._current = max(0, min(start, self._total - 1))
            self._render_page(self._current)
        except Exception as e:
            self._page_label.setText(f'Failed to open PDF:\n{e}')

    def _render_page(self, index: int) -> None:
        if self._doc is None:
            return
        import fitz
        zoom = _RENDER_DPI / 72.0
        pix  = self._doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img  = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        px   = QPixmap.fromImage(img)

        max_w = self._scroll.viewport().width() - 32
        if max_w > 0 and px.width() > max_w:
            px = px.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)

        self._page_label.setPixmap(px)
        self._scroll.verticalScrollBar().setValue(0)
        self._current = index
        self._update_nav()
        self.position_changed.emit(index)

    def _update_nav(self) -> None:
        self._pos_lbl.setText(f'Page {self._current + 1} of {self._total}' if self._total else '')
        self._prev_btn.setEnabled(self._current > 0)
        self._next_btn.setEnabled(self._current < self._total - 1)

    def next_page(self) -> None:
        if self._current < self._total - 1:
            self._render_page(self._current + 1)

    def prev_page(self) -> None:
        if self._current > 0:
            self._render_page(self._current - 1)

    @property
    def current_position(self) -> int:
        return self._current

    def cleanup(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
