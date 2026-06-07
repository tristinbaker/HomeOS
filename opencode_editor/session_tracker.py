import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

_DB_PATH = Path.home() / '.local' / 'share' / 'opencode' / 'opencode.db'
_WRITE_TOOLS = frozenset({'write', 'edit', 'patch'})
_LOOKBACK_MS = 86_400 * 1000  # 24 hours in milliseconds

_QUERY_BASE = """
    SELECT e.rowid, e.data
    FROM event e
    JOIN session s ON e.aggregate_id = s.id
    WHERE e.type = 'message.part.updated.1'
      AND json_extract(e.data, '$.part.state.status') = 'completed'
      AND json_extract(e.data, '$.part.tool') IN ('read','write','edit','patch')
      AND s.directory = ?
"""


@dataclass
class FileEvent:
    tool: str
    path: str
    detected_at: datetime

    @property
    def action(self) -> str:
        return {'write': 'written', 'edit': 'edited', 'patch': 'patched'}.get(self.tool, 'read')

    @property
    def is_write(self) -> bool:
        return self.tool in _WRITE_TOOLS


class SessionTracker(QObject):
    files_changed = pyqtSignal(list)  # list[FileEvent]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_rowid: int = -1
        self._working_dir: str = ''
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll)

    def set_working_dir(self, path: str):
        self._working_dir = path
        self._last_rowid = -1
        self._load_initial()

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def poll_now(self):
        self._poll()

    # ------------------------------------------------------------------

    def _parse_rows(self, rows) -> list[FileEvent]:
        now = datetime.now()
        events = []
        for row in rows:
            rowid = row[0]
            raw = row[1]
            self._last_rowid = max(self._last_rowid, rowid)
            try:
                data = json.loads(raw)
                part = data.get('part', {})
                tool = part.get('tool', '')
                file_path = part.get('state', {}).get('input', {}).get('filePath', '')
                if file_path and not file_path.endswith('/'):
                    events.append(FileEvent(tool, file_path, now))
            except Exception:
                continue
        return events

    def _connect(self):
        if not _DB_PATH.exists():
            return None
        try:
            return sqlite3.connect(f'file:{_DB_PATH}?mode=ro', uri=True, timeout=1.0)
        except Exception:
            return None

    def _load_initial(self):
        if not self._working_dir:
            return
        con = self._connect()
        if con is None:
            return
        try:
            import time as _time
            cutoff = int(_time.time() * 1000) - _LOOKBACK_MS
            sql = _QUERY_BASE + ' AND s.time_created >= ? ORDER BY e.rowid ASC'
            rows = con.execute(sql, (self._working_dir, cutoff)).fetchall()
        except Exception:
            rows = []
        finally:
            con.close()

        events = self._parse_rows(rows)
        if events:
            self.files_changed.emit(events)

    def _poll(self):
        if not self._working_dir:
            return
        con = self._connect()
        if con is None:
            return
        try:
            sql = _QUERY_BASE + ' AND e.rowid > ? ORDER BY e.rowid ASC'
            rows = con.execute(sql, (self._working_dir, self._last_rowid)).fetchall()
        except Exception:
            rows = []
        finally:
            con.close()

        events = self._parse_rows(rows)
        if events:
            self.files_changed.emit(events)
