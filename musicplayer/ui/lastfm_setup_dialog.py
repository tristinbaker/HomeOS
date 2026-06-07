import webbrowser

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

_API_CREATE_URL = 'https://www.last.fm/api/account/create'


class LastFMSetupDialog(QDialog):
    """Collect a Last.FM API key and shared secret from the user."""

    credentials_saved = pyqtSignal(str, str)  # api_key, secret

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Last.FM API Setup')
        self.setModal(True)
        self.setMinimumWidth(440)

        instructions = QLabel(
            'Scrobbling requires a Last.FM API key registered to you.\n'
            'It only takes a minute — create one for free, then paste the\n'
            '"API key" and "Shared secret" values below.'
        )
        instructions.setWordWrap(True)
        instructions.setAlignment(Qt.AlignmentFlag.AlignLeft)

        get_key_btn = QPushButton('Open last.fm/api/account/create ↗')
        get_key_btn.clicked.connect(lambda: webbrowser.open(_API_CREATE_URL))

        key_label = QLabel('API Key')
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText('32-character hex key')

        secret_label = QLabel('Shared Secret')
        self._secret_edit = QLineEdit()
        self._secret_edit.setPlaceholderText('32-character hex secret')
        self._secret_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._error_label = QLabel('')
        self._error_label.setStyleSheet('color: #f87171;')
        self._error_label.setVisible(False)

        save_btn = QPushButton('Save & Continue')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(cancel_btn)
        row.addStretch()
        row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.addWidget(instructions)
        layout.addSpacing(4)
        layout.addWidget(get_key_btn)
        layout.addSpacing(6)
        layout.addWidget(key_label)
        layout.addWidget(self._key_edit)
        layout.addWidget(secret_label)
        layout.addWidget(self._secret_edit)
        layout.addWidget(self._error_label)
        layout.addSpacing(4)
        layout.addLayout(row)

    def _on_save(self):
        key = self._key_edit.text().strip()
        secret = self._secret_edit.text().strip()
        if not key or not secret:
            self._error_label.setText('Both fields are required.')
            self._error_label.setVisible(True)
            return
        self._error_label.setVisible(False)
        self.credentials_saved.emit(key, secret)
        self.accept()
