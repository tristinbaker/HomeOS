from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ..session_tracker import FileEvent, SessionTracker

_COLOR_READ = QColor(200, 200, 200, 160)
_COLOR_WRITE = QColor(167, 139, 250)   # light purple — write/patch
_COLOR_EDIT = QColor(124, 58, 237)     # accent purple — edit


def _event_color(event: FileEvent) -> QColor:
    if event.tool == 'edit':
        return _COLOR_EDIT
    if event.is_write:
        return _COLOR_WRITE
    return _COLOR_READ


class SessionLogPanel(QWidget):
    def __init__(self, tracker: SessionTracker, parent=None):
        super().__init__(parent)
        self._tracker = tracker
        self._setup_ui()
        tracker.files_changed.connect(self._on_files_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        lbl = QLabel('Files touched this session')
        lbl.setStyleSheet('color: rgba(255,255,255,0.55); font-size: 11px;')

        clear_btn = QPushButton('Clear')
        clear_btn.setFixedHeight(22)
        clear_btn.clicked.connect(self._clear)

        header.addWidget(lbl, 1)
        header.addWidget(clear_btn)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)

        self._empty_label = QLabel('No activity yet.\nStart an OpenCode session in this directory.')
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet('color: rgba(255,255,255,0.3); font-size: 12px;')

        layout.addLayout(header)
        layout.addWidget(self._empty_label, 1)
        layout.addWidget(self._list, 1)
        self._list.setVisible(False)

    def _on_files_changed(self, events: list):
        self._empty_label.setVisible(False)
        self._list.setVisible(True)
        for event in events:
            ts = event.detected_at.strftime('%H:%M:%S')
            text = f'{ts}  {event.path}  [{event.action}]'
            item = QListWidgetItem(text)
            item.setForeground(_event_color(event))
            self._list.insertItem(0, item)

    def _clear(self):
        self._list.clear()
        self._list.setVisible(False)
        self._empty_label.setVisible(True)
