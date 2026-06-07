import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont

# Status code → (label, color)
_STATUS_META = {
    'M':  ('Modified',  QColor(250, 200,  60)),   # yellow
    'A':  ('Added',     QColor( 80, 200, 120)),   # green
    'D':  ('Deleted',   QColor(240,  80,  80)),   # red
    'R':  ('Renamed',   QColor(130, 180, 255)),   # blue
    'C':  ('Copied',    QColor(130, 180, 255)),
    'U':  ('Conflict',  QColor(255, 120,  60)),   # orange
    '?':  ('Untracked', QColor(160, 160, 160)),   # grey
    '!':  ('Ignored',   QColor( 80,  80,  80)),
}
_POLL_MS = 3000


def _run_git(args: list[str], cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ['git'] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def _parse_status(output: str, git_root: str) -> dict[str, list[tuple[str, str]]]:
    """Return {group_label: [(abs_path, xy_code), ...]} from git status --porcelain."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for line in output.splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        path_part = line[3:]
        # Handle renames: "old -> new"
        if ' -> ' in path_part:
            path_part = path_part.split(' -> ')[-1].strip()
        path_part = path_part.strip().strip('"')

        abs_path = str(Path(git_root) / path_part)

        # Determine display group from the two-char XY code
        x, y = xy[0], xy[1]
        if x == '?' and y == '?':
            code = '?'
        elif x == '!' and y == '!':
            code = '!'
        elif x != ' ' and x != '?':
            code = x   # staged change
        else:
            code = y   # unstaged change

        label, _ = _STATUS_META.get(code, ('Changed', QColor(200, 200, 200)))
        groups.setdefault(label, []).append((abs_path, xy.strip()))

    return groups


class GitChangesPanel(QWidget):
    file_open_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._working_dir = ''
        self._git_root = ''
        self._setup_ui()

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self.refresh)
        self._poll.start()

    # ── Public ──────────────────────────────────────────────────────────

    def set_working_dir(self, path: str):
        self._working_dir = path
        # Find the git root for this directory
        root = _run_git(['rev-parse', '--show-toplevel'], path)
        self._git_root = root.strip() if root else ''
        self.refresh()

    def refresh(self):
        if not self._working_dir:
            self._show_placeholder('No directory selected.')
            return

        if not self._git_root:
            # Re-check in case the directory was just initialised
            root = _run_git(['rev-parse', '--show-toplevel'], self._working_dir)
            if root:
                self._git_root = root.strip()
            else:
                self._show_placeholder('Not a git repository.')
                return

        output = _run_git(['status', '--porcelain', '-u'], self._git_root)
        if output is None:
            self._show_placeholder('git status failed.')
            return

        self._tree.setVisible(True)
        self._placeholder.setVisible(False)
        self._populate(output)

    # ── UI ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header bar
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(6, 4, 6, 4)
        hl.setSpacing(4)
        lbl = QLabel('Changes')
        lbl.setStyleSheet('color: rgba(255,255,255,0.5); font-size: 11px;')
        refresh_btn = QPushButton('↻')
        refresh_btn.setFixedSize(22, 22)
        refresh_btn.setFlat(True)
        refresh_btn.setToolTip('Refresh')
        refresh_btn.setStyleSheet(
            'QPushButton { color: rgba(255,255,255,0.5); font-size: 14px; border: none; }'
            'QPushButton:hover { color: white; }'
        )
        refresh_btn.clicked.connect(self.refresh)
        hl.addWidget(lbl)
        hl.addStretch()
        hl.addWidget(refresh_btn)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(14)
        self._tree.setAlternatingRowColors(False)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setVisible(False)

        # Placeholder
        self._placeholder = QLabel('Not a git repository.')
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet('color: rgba(255,255,255,0.28); font-size: 12px;')

        layout.addWidget(header)
        layout.addWidget(self._tree, 1)
        layout.addWidget(self._placeholder, 1)

    def _show_placeholder(self, msg: str):
        self._placeholder.setText(msg)
        self._placeholder.setVisible(True)
        self._tree.setVisible(False)

    def _populate(self, output: str):
        # Remember which groups were expanded
        expanded = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top and top.isExpanded():
                expanded.add(top.text(0))

        self._tree.clear()

        if not output.strip():
            self._show_placeholder('No changes.')
            return

        groups = _parse_status(output, self._git_root)

        mono = QFont('Monospace')
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)

        for label, files in groups.items():
            _, color = _STATUS_META.get(label[0], _STATUS_META.get('?', ('', QColor(200,200,200))))
            # Use the label key to look up color correctly
            for code, (clabel, ccolor) in _STATUS_META.items():
                if clabel == label:
                    color = ccolor
                    break

            group_item = QTreeWidgetItem([f'{label}  ({len(files)})'])
            group_item.setForeground(0, color)
            bold = QFont()
            bold.setBold(True)
            bold.setPointSize(10)
            group_item.setFont(0, bold)
            self._tree.addTopLevelItem(group_item)

            for abs_path, xy in files:
                rel = str(Path(abs_path).relative_to(self._git_root))
                child = QTreeWidgetItem([rel])
                child.setFont(0, mono)
                child.setForeground(0, QColor(220, 220, 220))
                child.setData(0, Qt.ItemDataRole.UserRole, abs_path)
                child.setToolTip(0, abs_path)
                group_item.addChild(child)

            group_item.setExpanded(label in expanded or label not in expanded)

        self._tree.expandAll()

    def _on_double_click(self, item: QTreeWidgetItem, _col: int):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and Path(path).is_file():
            self.file_open_requested.emit(path)
