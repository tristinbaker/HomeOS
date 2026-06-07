#!/usr/bin/env python3
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap, QFont
from PyQt6.QtWidgets import QApplication

from musicplayer import register as register_music_module
from opencode_editor import register as register_opencode_module
from networth import register as register_networth_module
from nasstorage import register as register_nasstorage_module
from rssreader import register as register_rss_module
from sysmon import register as register_sysmon_module
from rommanager import register as register_rommanager_module
from home_os_app import HomeOSWindow


def _make_emoji_icon(emoji: str, size: int = 64) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    font = QFont()
    font.setPixelSize(int(size * 0.82))
    painter.setFont(font)
    painter.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    painter.end()
    return QIcon(px)


if __name__ == '__main__':
    register_music_module()
    register_opencode_module()
    register_networth_module()
    register_nasstorage_module()
    register_rss_module()
    register_sysmon_module()
    register_rommanager_module()

    app = QApplication(sys.argv)
    app.setApplicationName('HomeOS')
    app.setOrganizationName('HomeOS')
    app.setWindowIcon(_make_emoji_icon('🏠'))

    window = HomeOSWindow()
    window.show()
    sys.exit(app.exec())
