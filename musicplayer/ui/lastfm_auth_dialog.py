import webbrowser

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ..lastfm import AuthSignals, LastFMClient


class LastFMAuthDialog(QDialog):
    authenticated = pyqtSignal(str, str)  # session_key, username

    def __init__(self, client: LastFMClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._token = None
        self._auth_url = None

        self._sigs = AuthSignals()
        self._sigs.token_ready.connect(self._on_token_ready)
        self._sigs.session_ready.connect(self._on_session_ready)
        self._sigs.error.connect(self._on_error)

        self.setWindowTitle('Connect to Last.FM')
        self.setModal(True)
        self.setMinimumWidth(380)

        self._status = QLabel('Fetching authorization token…')
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._open_btn = QPushButton('Authorize in Browser')
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_browser)

        self._connect_btn = QPushButton("I've Authorized — Connect")
        self._connect_btn.setEnabled(False)
        self._connect_btn.setDefault(True)
        self._connect_btn.clicked.connect(self._on_connect_clicked)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(cancel_btn)
        row.addStretch()
        row.addWidget(self._connect_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.addWidget(self._status)
        layout.addWidget(self._open_btn)
        layout.addLayout(row)
        self.setLayout(layout)

        client.start_auth(self._sigs)

    def _on_token_ready(self, token, url):
        self._token = token
        self._auth_url = url
        self._status.setText(
            'Click "Authorize in Browser" to grant access on Last.FM,\n'
            'then click "Connect".'
        )
        self._open_btn.setEnabled(True)
        self._connect_btn.setEnabled(True)

    def _open_browser(self):
        if self._auth_url:
            webbrowser.open(self._auth_url)

    def _on_connect_clicked(self):
        if not self._token:
            return
        self._connect_btn.setEnabled(False)
        self._open_btn.setEnabled(False)
        self._status.setText('Connecting…')
        self._client.finish_auth(self._token, self._sigs)

    def _on_session_ready(self, key, name):
        self.authenticated.emit(key, name)
        self.accept()

    def _on_error(self, msg):
        self._status.setText(
            f'Error: {msg}\n\nMake sure you authorized on Last.FM, then try again.'
        )
        if self._token:
            self._connect_btn.setEnabled(True)
            self._open_btn.setEnabled(True)
