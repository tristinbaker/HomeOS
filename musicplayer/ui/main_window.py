from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QProgressBar
from PyQt6.QtCore import Qt, QSettings

from .content_widget import MusicPlayerContent


class MainWindow(QMainWindow):
    """Thin shell for backward compatibility — wraps MusicPlayerContent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content = MusicPlayerContent(self)
        self.setCentralWidget(self.content)

        self.settings = self.content.settings

        for menu in self.content.menus(self):
            self.menuBar().addMenu(menu)

        self._scan_progress = QProgressBar(self.statusBar())
        self._scan_progress.setMaximumWidth(200)
        self._scan_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._scan_progress)
        self.statusBar().showMessage('Ready')

        self.content.status_message.connect(self._on_status)
        self.content.title_changed.connect(self.setWindowTitle)

    def _on_status(self, msg, timeout):
        self.statusBar().showMessage(msg, timeout)

    def closeEvent(self, event):
        self.content.cleanup()
        super().closeEvent(event)
