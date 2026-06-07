from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

_SEL   = 'background: rgba(99,102,241,0.28); border: 2px solid #6366f1; border-radius: 10px;'
_UNSEL = 'background: rgba(255,255,255,0.04); border: 2px solid rgba(255,255,255,0.10); border-radius: 10px;'


class SourceSetupDialog(QDialog):
    """First-launch dialog: choose LifeOS backup or manual entry."""

    def __init__(self, current: str = 'lifeos', parent=None):
        super().__init__(parent)
        self._selected = current
        self.setWindowTitle('Net Worth Tracker Setup')
        self.setModal(True)
        self.setMinimumWidth(440)

        intro = QLabel('How would you like to manage your financial data?')
        intro.setWordWrap(True)
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro_f = QFont()
        intro_f.setPointSize(11)
        intro.setFont(intro_f)
        intro.setStyleSheet('color: rgba(255,255,255,0.7); background: transparent;')

        self._lifeos_card = self._make_card(
            'lifeos',
            '📱  LifeOS Backup',
            'Syncs from the LifeOS finance app via ADB\non a USB-connected Android phone.',
        )
        self._manual_card = self._make_card(
            'manual',
            '✏️  Manual Entry',
            'Add and manage your own accounts,\ntransactions, and sinking funds in the app.',
        )

        self._ok_btn = QPushButton('Get Started')
        self._ok_btn.setDefault(True)
        self._ok_btn.setFixedHeight(36)
        self._ok_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.setFixedHeight(36)
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._ok_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addWidget(self._lifeos_card)
        layout.addWidget(self._manual_card)
        layout.addSpacing(6)
        layout.addLayout(btn_row)

        self._select(current)

    def _make_card(self, source_id: str, title: str, desc: str) -> QWidget:
        # Outer frame — styled widget (border + background applied here only)
        frame = QWidget()
        frame.setObjectName(f'nw_card_{source_id}')
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        frame.mousePressEvent = lambda _e, sid=source_id: self._select(sid)

        inner = QVBoxLayout(frame)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(5)

        title_lbl = QLabel(title)
        tf = QFont()
        tf.setPointSize(11)
        tf.setBold(True)
        title_lbl.setFont(tf)
        title_lbl.setStyleSheet('color: white; background: transparent; border: none;')

        desc_lbl = QLabel(desc)
        df = QFont()
        df.setPointSize(9)
        desc_lbl.setFont(df)
        desc_lbl.setStyleSheet('color: rgba(255,255,255,0.52); background: transparent; border: none;')

        inner.addWidget(title_lbl)
        inner.addWidget(desc_lbl)
        return frame

    def _select(self, source_id: str) -> None:
        self._selected = source_id
        name_l = self._lifeos_card.objectName()
        name_m = self._manual_card.objectName()
        self._lifeos_card.setStyleSheet(
            f'QWidget#{name_l} {{ {_SEL if source_id == "lifeos" else _UNSEL} }}'
        )
        self._manual_card.setStyleSheet(
            f'QWidget#{name_m} {{ {_SEL if source_id == "manual" else _UNSEL} }}'
        )

    @property
    def selected_source(self) -> str:
        return self._selected
