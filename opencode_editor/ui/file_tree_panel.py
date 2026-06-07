import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QLineEdit,
    QPushButton, QLabel, QFileDialog,
)
from PyQt6.QtCore import Qt, QDir, pyqtSignal
from PyQt6.QtGui import QFileSystemModel


class FileTreePanel(QWidget):
    working_dir_changed = pyqtSignal(str)
    file_open_requested = pyqtSignal(str)

    def __init__(self, root_path: str = '', parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.set_root(root_path or os.getcwd())

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(4)

        self._path_bar = QLineEdit()
        self._path_bar.setPlaceholderText('Directory path…')
        self._path_bar.returnPressed.connect(self._navigate_to_path_bar)

        browse_btn = QPushButton('…')
        browse_btn.setFixedWidth(28)
        browse_btn.setFlat(True)
        browse_btn.setToolTip('Browse for directory')
        browse_btn.clicked.connect(self._browse)

        header_layout.addWidget(QLabel('Dir:'))
        header_layout.addWidget(self._path_bar, 1)
        header_layout.addWidget(browse_btn)

        # Tree
        self._model = QFileSystemModel()
        self._model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setAnimated(False)
        self._tree.setIndentation(16)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._tree.setAlternatingRowColors(True)
        self._tree.doubleClicked.connect(self._on_double_click)

        # Hide size / type / date columns — keep name only
        for col in (1, 2, 3):
            self._tree.setColumnHidden(col, True)
        self._tree.header().setStretchLastSection(True)

        layout.addWidget(header)
        layout.addWidget(self._tree, 1)

    def set_root(self, path: str):
        if not os.path.isdir(path):
            return
        self._model.setRootPath(path)
        self._tree.setRootIndex(self._model.index(path))
        self._path_bar.setText(path)
        self.working_dir_changed.emit(path)

    def current_root(self) -> str:
        return self._path_bar.text()

    def _navigate_to_path_bar(self):
        self.set_root(self._path_bar.text().strip())

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self, 'Select Working Directory', self._path_bar.text()
        )
        if path:
            self.set_root(path)

    def _on_double_click(self, index):
        if self._model.isDir(index):
            return
        path = self._model.filePath(index)
        self.file_open_requested.emit(path)
