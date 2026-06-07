"""
Embedded pseudo-terminal widget.

Uses pyte for VT100/xterm emulation, ptyprocess for PTY management,
and QPainter for rendering the character grid.
"""

import threading
from typing import Optional

import pyte
import pyte.modes as mo
from ptyprocess import PtyProcess

from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QKeyEvent,
    QMouseEvent, QWheelEvent, QResizeEvent, QBrush,
)
from PyQt6.QtWidgets import QWidget, QSizePolicy


# ── Color palette ──────────────────────────────────────────────────────────

_DEFAULT_FG = QColor(204, 204, 204)
_DEFAULT_BG = QColor(13, 10, 30)   # dark to match app theme

_ANSI_16 = [
    QColor(0, 0, 0),        # 0  black
    QColor(187, 0, 0),      # 1  red
    QColor(0, 187, 0),      # 2  green
    QColor(187, 187, 0),    # 3  yellow/brown
    QColor(0, 0, 187),      # 4  blue
    QColor(187, 0, 187),    # 5  magenta
    QColor(0, 187, 187),    # 6  cyan
    QColor(187, 187, 187),  # 7  light gray / white
    QColor(85, 85, 85),     # 8  bright black / dark gray
    QColor(255, 85, 85),    # 9  bright red
    QColor(85, 255, 85),    # 10 bright green
    QColor(255, 255, 85),   # 11 bright yellow
    QColor(85, 85, 255),    # 12 bright blue
    QColor(255, 85, 255),   # 13 bright magenta
    QColor(85, 255, 255),   # 14 bright cyan
    QColor(255, 255, 255),  # 15 bright white
]

_NAMED = {
    'black': 0, 'red': 1, 'green': 2, 'brown': 3, 'yellow': 3,
    'blue': 4, 'magenta': 5, 'cyan': 6, 'white': 7,
}


def _qcolor(c, default: QColor) -> QColor:
    if c is None or c == 'default':
        return default
    if isinstance(c, int):
        if c < 16:
            return _ANSI_16[c]
        if c < 232:
            n = c - 16
            b = (n % 6) * 51
            g = ((n // 6) % 6) * 51
            r = (n // 36) * 51
            return QColor(r, g, b)
        v = (c - 232) * 10 + 8
        return QColor(v, v, v)
    if isinstance(c, str) and c in _NAMED:
        return _ANSI_16[_NAMED[c]]
    if isinstance(c, (list, tuple)) and len(c) == 3:
        return QColor(int(c[0]), int(c[1]), int(c[2]))
    return default


# ── Screen with mode tracking ──────────────────────────────────────────────

_MOUSE_MODES = frozenset({1000, 1002, 1003, 1005, 1006, 1015})


class _Screen(pyte.Screen):
    """pyte.Screen with cursor-key and mouse-tracking mode awareness."""

    def __init__(self, cols: int, rows: int):
        super().__init__(cols, rows)
        self.app_cursor_keys = False
        self.mouse_reporting = False

    def set_mode(self, *modes, private: bool = False):
        super().set_mode(*modes, private=private)
        if private:
            if 1 in modes:
                self.app_cursor_keys = True
            if _MOUSE_MODES.intersection(modes):
                self.mouse_reporting = True

    def reset_mode(self, *modes, private: bool = False):
        super().reset_mode(*modes, private=private)
        if private:
            if 1 in modes:
                self.app_cursor_keys = False
            if _MOUSE_MODES.intersection(modes):
                self.mouse_reporting = False


# ── Key mapping ────────────────────────────────────────────────────────────

_FKEYS = [
    b'\x1bOP', b'\x1bOQ', b'\x1bOR', b'\x1bOS',
    b'\x1b[15~', b'\x1b[17~', b'\x1b[18~', b'\x1b[19~',
    b'\x1b[20~', b'\x1b[21~', b'\x1b[23~', b'\x1b[24~',
]


def _key_to_bytes(ev: QKeyEvent, app_cursor: bool) -> Optional[bytes]:
    key = ev.key()
    ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
    shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
    alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)

    if ctrl:
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return bytes([key - Qt.Key.Key_A + 1])
        extras = {
            Qt.Key.Key_BracketLeft:  b'\x1b',
            Qt.Key.Key_Backslash:    b'\x1c',
            Qt.Key.Key_BracketRight: b'\x1d',
        }
        if key in extras:
            return extras[key]

    specials = {
        Qt.Key.Key_Return:    b'\r',
        Qt.Key.Key_Enter:     b'\r',
        Qt.Key.Key_Backspace: b'\x7f',
        Qt.Key.Key_Delete:    b'\x1b[3~',
        Qt.Key.Key_Escape:    b'\x1b',
        Qt.Key.Key_Tab:       b'\x1b[Z' if shift else b'\t',
        Qt.Key.Key_Insert:    b'\x1b[2~',
        Qt.Key.Key_PageUp:    b'\x1b[5~',
        Qt.Key.Key_PageDown:  b'\x1b[6~',
    }
    if key in specials:
        return specials[key]

    arrows_app = {
        Qt.Key.Key_Up:    b'\x1bOA',
        Qt.Key.Key_Down:  b'\x1bOB',
        Qt.Key.Key_Right: b'\x1bOC',
        Qt.Key.Key_Left:  b'\x1bOD',
        Qt.Key.Key_Home:  b'\x1bOH',
        Qt.Key.Key_End:   b'\x1bOF',
    }
    arrows_norm = {
        Qt.Key.Key_Up:    b'\x1b[A',
        Qt.Key.Key_Down:  b'\x1b[B',
        Qt.Key.Key_Right: b'\x1b[C',
        Qt.Key.Key_Left:  b'\x1b[D',
        Qt.Key.Key_Home:  b'\x1b[H',
        Qt.Key.Key_End:   b'\x1b[F',
    }
    arrows = arrows_app if app_cursor else arrows_norm
    if key in arrows:
        return arrows[key]

    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return _FKEYS[key - Qt.Key.Key_F1]

    if alt and ev.text():
        return b'\x1b' + ev.text().encode('utf-8', errors='replace')

    text = ev.text()
    if text:
        return text.encode('utf-8', errors='replace')

    return None


# ── TerminalPanel ──────────────────────────────────────────────────────────

class TerminalPanel(QWidget):
    """
    Embeds a child process in a PTY and renders its output.
    Handles VT100/xterm sequences via pyte, forwards keyboard + mouse input.
    """

    process_exited = pyqtSignal()
    _data_ready = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[PtyProcess] = None
        self._screen: Optional[_Screen] = None
        self._stream: Optional[pyte.ByteStream] = None
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None

        self._font = QFont('Monospace')
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setPointSize(10)
        fm = QFontMetrics(self._font)
        self._cw = fm.horizontalAdvance('M')
        self._ch = fm.height()
        self._asc = fm.ascent()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)

        self._data_ready.connect(self.update, Qt.ConnectionType.QueuedConnection)

    # ── Public ──────────────────────────────────────────────────────────

    def start(self, cmd: list[str], cwd: str):
        self.stop()
        cols = self._calc_cols()
        rows = self._calc_rows()
        self._screen = _Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)
        self._process = PtyProcess.spawn(cmd, cwd=cwd, dimensions=(rows, cols))
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.setFocus()

    def stop(self):
        if self._process is not None:
            try:
                if self._process.isalive():
                    self._process.terminate(force=True)
            except Exception:
                pass
            self._process = None

    def is_running(self) -> bool:
        return self._process is not None and self._process.isalive()

    # ── Internal ────────────────────────────────────────────────────────

    def _calc_cols(self) -> int:
        return max(10, self.width() // self._cw)

    def _calc_rows(self) -> int:
        return max(5, self.height() // self._ch)

    def _write(self, data: bytes):
        if self._process and self._process.isalive():
            try:
                self._process.write(data)
            except Exception:
                pass

    def _read_loop(self):
        while self._process and self._process.isalive():
            try:
                data = self._process.read(4096)
                if data:
                    with self._lock:
                        self._stream.feed(data)
                    self._data_ready.emit()
            except EOFError:
                break
            except Exception:
                break
        self.process_exited.emit()

    # ── Qt events ───────────────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        if self._screen is None or self._process is None:
            return
        cols = self._calc_cols()
        rows = self._calc_rows()
        with self._lock:
            self._screen.resize(rows, cols)
        try:
            self._process.setwinsize(rows, cols)
        except Exception:
            pass

    def keyPressEvent(self, event: QKeyEvent):
        if self._screen is None:
            super().keyPressEvent(event)
            return
        seq = _key_to_bytes(event, self._screen.app_cursor_keys)
        if seq:
            self._write(seq)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self.setFocus()
        if self._screen is None:
            return
        col = int(event.position().x()) // self._cw + 1
        row = int(event.position().y()) // self._ch + 1
        btn = {
            Qt.MouseButton.LeftButton:   0,
            Qt.MouseButton.MiddleButton: 1,
            Qt.MouseButton.RightButton:  2,
        }.get(event.button(), 0)
        self._write(f'\x1b[<{btn};{col};{row}M'.encode())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._screen is None:
            return
        col = int(event.position().x()) // self._cw + 1
        row = int(event.position().y()) // self._ch + 1
        btn = {
            Qt.MouseButton.LeftButton:   0,
            Qt.MouseButton.MiddleButton: 1,
            Qt.MouseButton.RightButton:  2,
        }.get(event.button(), 0)
        self._write(f'\x1b[<{btn};{col};{row}m'.encode())

    def wheelEvent(self, event: QWheelEvent):
        if self._screen is None:
            return
        dy = event.angleDelta().y()
        seq = b'\x1b[5~' if dy > 0 else b'\x1b[6~'
        for _ in range(max(1, abs(dy) // 120)):
            self._write(seq)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self._font)
        painter.fillRect(self.rect(), _DEFAULT_BG)

        if self._screen is None:
            painter.setPen(_DEFAULT_FG)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                'Press Launch OpenCode to start a session.',
            )
            return

        with self._lock:
            screen = self._screen
            buf = screen.buffer
            cursor = screen.cursor
            cols = screen.columns
            lines = screen.lines

        bold_font = QFont(self._font)
        bold_font.setBold(True)

        for row in range(lines):
            line = buf[row]
            for col in range(cols):
                ch = line[col]

                fg = _qcolor(ch.fg, _DEFAULT_FG)
                bg = _qcolor(ch.bg, _DEFAULT_BG)

                x = col * self._cw
                y = row * self._ch

                if ch.reverse:
                    fg, bg = bg, fg

                if bg != _DEFAULT_BG:
                    painter.fillRect(QRect(x, y, self._cw, self._ch), bg)

                char = ch.data
                if char and char != ' ':
                    painter.setFont(bold_font if ch.bold else self._font)
                    painter.setPen(fg)
                    painter.drawText(x, y + self._asc, char)

        # Cursor block
        if cursor.x < cols and cursor.y < lines:
            cx = cursor.x * self._cw
            cy = cursor.y * self._ch
            painter.fillRect(
                QRect(cx, cy, self._cw, self._ch),
                QColor(255, 255, 255, 190),
            )
            ch = buf[cursor.y][cursor.x]
            if ch.data and ch.data != ' ':
                painter.setFont(self._font)
                painter.setPen(Qt.GlobalColor.black)
                painter.drawText(cx, cy + self._asc, ch.data)
