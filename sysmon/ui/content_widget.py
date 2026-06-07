from __future__ import annotations

import time

import psutil
try:
    import pynvml as nvml
    nvml.nvmlInit()
    _NVML_OK = True
except Exception:
    _NVML_OK = False
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from home_os_app.theme import CARD_STYLE, THEME_QSS, paint_background


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_bytes(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} PB'


def _pct_color(pct: float, base: str) -> str:
    if pct >= 90:
        return '#ef4444'
    if pct >= 75:
        return '#f59e0b'
    return base


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet('color: rgba(255,255,255,0.70); background: transparent; letter-spacing: 1px;')
    f = QFont()
    f.setPointSize(9)
    f.setBold(True)
    lbl.setFont(f)
    return lbl


# ── Bar widget ────────────────────────────────────────────────────────────────

class _Bar(QWidget):
    def __init__(self, color: str = '#0ea5e9', height: int = 5, parent=None) -> None:
        super().__init__(parent)
        self._pct = 0.0
        self._color = color
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, pct: float, color: str | None = None) -> None:
        self._pct = max(0.0, min(100.0, pct))
        if color is not None:
            self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(0, 0, w, h, r, r)
        fw = int(w * self._pct / 100)
        if fw > r * 2:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(0, 0, fw, h, r, r)
        p.end()


# ── Main content widget ───────────────────────────────────────────────────────

class SysMonContent(QWidget):
    _INTERVAL_MS = 2000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Establish baselines so first real tick has meaningful deltas
        psutil.cpu_percent(percpu=True)
        net = psutil.net_io_counters()
        self._prev_net_sent = net.bytes_sent
        self._prev_net_recv = net.bytes_recv
        self._prev_net_t = time.monotonic()

        self._setup_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        # First refresh after a short delay so cpu_percent has a real interval
        QTimer.singleShot(500, self._refresh)

    def paintEvent(self, event) -> None:
        paint_background(self)

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 20, 24, 16)
        main.setSpacing(14)
        main.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14);
                border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        scroll.viewport().setAutoFillBackground(False)

        body = QWidget()
        body.setStyleSheet('background: transparent;')
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(12)
        bv.addWidget(self._build_cpu_card())
        bv.addWidget(self._build_mem_card())
        if _NVML_OK:
            bv.addWidget(self._build_gpu_card())
        bv.addWidget(self._build_net_card())
        bv.addWidget(self._build_process_card())
        bv.addStretch()

        scroll.setWidget(body)
        main.addWidget(scroll, 1)

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setStyleSheet(CARD_STYLE)
        h = QHBoxLayout(hdr)
        h.setContentsMargins(20, 14, 20, 14)
        h.setSpacing(10)

        title = QLabel('System Monitor')
        tf = QFont()
        tf.setPointSize(10)
        title.setFont(tf)
        title.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        self._live_dot = QLabel('● Live')
        self._live_dot.setStyleSheet('color: #4ade80; font-size: 9px; background: transparent;')

        h.addWidget(title)
        h.addStretch()
        h.addWidget(self._live_dot)
        return hdr

    def _build_cpu_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        # Title + big pct
        row = QHBoxLayout()
        row.addWidget(_section_label('CPU'))
        row.addStretch()
        self._cpu_info_lbl = QLabel('')
        self._cpu_info_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.30); font-size: 8px; background: transparent;'
        )
        row.addWidget(self._cpu_info_lbl)
        v.addLayout(row)

        self._cpu_pct_lbl = QLabel('0%')
        pf = QFont()
        pf.setPointSize(26)
        pf.setBold(True)
        self._cpu_pct_lbl.setFont(pf)
        self._cpu_pct_lbl.setStyleSheet('color: white; background: transparent;')
        v.addWidget(self._cpu_pct_lbl)

        self._cpu_bar = _Bar('#0ea5e9', 6)
        v.addWidget(self._cpu_bar)

        # Per-core grid
        core_count = psutil.cpu_count(logical=True)
        self._core_bars: list[_Bar] = []
        self._core_lbls: list[QLabel] = []
        cols = min(8, core_count)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        for i in range(core_count):
            cell = QWidget()
            cell.setStyleSheet('background: transparent;')
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(3)
            lbl = QLabel(f'C{i}  0%')
            lf = QFont()
            lf.setPointSize(7)
            lbl.setFont(lf)
            lbl.setStyleSheet('color: rgba(255,255,255,0.40); background: transparent;')
            bar = _Bar('#0ea5e9', 3)
            cv.addWidget(lbl)
            cv.addWidget(bar)
            self._core_bars.append(bar)
            self._core_lbls.append(lbl)
            grid.addWidget(cell, i // cols, i % cols)
        v.addLayout(grid)

        return card

    def _build_mem_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        v.addWidget(_section_label('MEMORY'))

        # RAM
        ram_row = QHBoxLayout()
        self._ram_lbl = QLabel('RAM')
        self._ram_lbl.setStyleSheet('color: rgba(255,255,255,0.75); background: transparent;')
        self._ram_val_lbl = QLabel('')
        self._ram_val_lbl.setStyleSheet('color: white; background: transparent;')
        ram_row.addWidget(self._ram_lbl)
        ram_row.addStretch()
        ram_row.addWidget(self._ram_val_lbl)
        v.addLayout(ram_row)
        self._ram_bar = _Bar('#8b5cf6', 6)
        v.addWidget(self._ram_bar)

        # Swap
        swap_row = QHBoxLayout()
        self._swap_lbl = QLabel('Swap')
        self._swap_lbl.setStyleSheet('color: rgba(255,255,255,0.75); background: transparent;')
        self._swap_val_lbl = QLabel('')
        self._swap_val_lbl.setStyleSheet('color: rgba(255,255,255,0.60); background: transparent;')
        swap_row.addWidget(self._swap_lbl)
        swap_row.addStretch()
        swap_row.addWidget(self._swap_val_lbl)
        v.addLayout(swap_row)
        self._swap_bar = _Bar('#6366f1', 4)
        v.addWidget(self._swap_bar)

        return card

    def _build_gpu_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        v.addWidget(_section_label('GPU'))

        self._gpu_ui: list[dict] = []
        count = nvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = nvml.nvmlDeviceGetHandleByIndex(i)
            name = nvml.nvmlDeviceGetName(handle)

            if i > 0:
                sep = QWidget()
                sep.setFixedHeight(1)
                sep.setStyleSheet('background: rgba(255,255,255,0.07);')
                v.addWidget(sep)

            # Name + temp row
            name_row = QHBoxLayout()
            name_lbl = QLabel(name)
            nf = QFont()
            nf.setPointSize(9)
            nf.setBold(True)
            name_lbl.setFont(nf)
            name_lbl.setStyleSheet('color: white; background: transparent;')
            temp_lbl = QLabel('')
            temp_lbl.setStyleSheet('color: rgba(255,255,255,0.50); font-size: 9px; background: transparent;')
            name_row.addWidget(name_lbl, 1)
            name_row.addWidget(temp_lbl)
            v.addLayout(name_row)

            # Core util
            util_row = QHBoxLayout()
            util_row.addWidget(QLabel('Core'))
            util_row.itemAt(0).widget().setStyleSheet(
                'color: rgba(255,255,255,0.45); font-size: 8px; background: transparent;'
            )
            util_lbl = QLabel('0%')
            util_lbl.setStyleSheet('color: white; font-size: 8px; background: transparent;')
            util_row.addStretch()
            util_row.addWidget(util_lbl)
            v.addLayout(util_row)
            util_bar = _Bar('#10b981', 5)
            v.addWidget(util_bar)

            # VRAM
            vram_row = QHBoxLayout()
            vram_row.addWidget(QLabel('VRAM'))
            vram_row.itemAt(0).widget().setStyleSheet(
                'color: rgba(255,255,255,0.45); font-size: 8px; background: transparent;'
            )
            vram_lbl = QLabel('')
            vram_lbl.setStyleSheet('color: rgba(255,255,255,0.70); font-size: 8px; background: transparent;')
            vram_row.addStretch()
            vram_row.addWidget(vram_lbl)
            v.addLayout(vram_row)
            vram_bar = _Bar('#6366f1', 5)
            v.addWidget(vram_bar)

            # Power + fan + clock row
            detail_lbl = QLabel('')
            detail_lbl.setStyleSheet(
                'color: rgba(255,255,255,0.28); font-size: 8px; background: transparent;'
            )
            v.addWidget(detail_lbl)

            self._gpu_ui.append({
                'handle': handle,
                'util_lbl': util_lbl,
                'util_bar': util_bar,
                'vram_lbl': vram_lbl,
                'vram_bar': vram_bar,
                'temp_lbl': temp_lbl,
                'detail_lbl': detail_lbl,
            })

        return card

    def _build_net_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        v.addWidget(_section_label('NETWORK'))

        speed_row = QHBoxLayout()
        speed_row.setSpacing(32)

        up_col = QVBoxLayout()
        self._net_up_lbl = QLabel('↑  0 B/s')
        uf = QFont()
        uf.setPointSize(14)
        uf.setBold(True)
        self._net_up_lbl.setFont(uf)
        self._net_up_lbl.setStyleSheet('color: #f59e0b; background: transparent;')
        up_sub = QLabel('Upload')
        up_sub.setStyleSheet('color: rgba(255,255,255,0.30); font-size: 8px; background: transparent;')
        up_col.addWidget(self._net_up_lbl)
        up_col.addWidget(up_sub)

        dn_col = QVBoxLayout()
        self._net_dn_lbl = QLabel('↓  0 B/s')
        df = QFont()
        df.setPointSize(14)
        df.setBold(True)
        self._net_dn_lbl.setFont(df)
        self._net_dn_lbl.setStyleSheet('color: #0ea5e9; background: transparent;')
        dn_sub = QLabel('Download')
        dn_sub.setStyleSheet('color: rgba(255,255,255,0.30); font-size: 8px; background: transparent;')
        dn_col.addWidget(self._net_dn_lbl)
        dn_col.addWidget(dn_sub)

        speed_row.addLayout(up_col)
        speed_row.addLayout(dn_col)
        speed_row.addStretch()
        v.addLayout(speed_row)

        self._net_total_lbl = QLabel('')
        self._net_total_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.28); font-size: 8px; background: transparent;'
        )
        v.addWidget(self._net_total_lbl)

        return card

    def _build_process_card(self) -> QWidget:
        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(8)

        v.addWidget(_section_label('TOP PROCESSES'))

        # Header row
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        for text, stretch, align in [
            ('Name', 1, Qt.AlignmentFlag.AlignLeft),
            ('CPU', 0, Qt.AlignmentFlag.AlignRight),
            ('Mem', 0, Qt.AlignmentFlag.AlignRight),
        ]:
            lbl = QLabel(text)
            if not stretch:
                lbl.setFixedWidth(60)
            lbl.setStyleSheet('color: rgba(255,255,255,0.55); font-size: 9px; background: transparent;')
            lbl.setAlignment(align)
            if stretch:
                hdr_row.addWidget(lbl, 1)
            else:
                hdr_row.addWidget(lbl)
        v.addLayout(hdr_row)

        # Process rows (up to 10)
        self._proc_rows: list[tuple[QLabel, QLabel, QLabel]] = []
        for _ in range(10):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            name_lbl = QLabel('')
            name_lbl.setStyleSheet('color: rgba(255,255,255,0.75); font-size: 9px; background: transparent;')
            cpu_lbl = QLabel('')
            cpu_lbl.setFixedWidth(60)
            cpu_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            cpu_lbl.setStyleSheet('color: rgba(255,255,255,0.60); font-size: 9px; background: transparent;')
            mem_lbl = QLabel('')
            mem_lbl.setFixedWidth(60)
            mem_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            mem_lbl.setStyleSheet('color: rgba(255,255,255,0.45); font-size: 9px; background: transparent;')
            row.addWidget(name_lbl, 1)
            row.addWidget(cpu_lbl)
            row.addWidget(mem_lbl)
            v.addLayout(row)
            self._proc_rows.append((name_lbl, cpu_lbl, mem_lbl))

        return card

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._update_cpu()
        self._update_mem()
        if _NVML_OK:
            self._update_gpu()
        self._update_net()
        self._update_processes()

    def _update_cpu(self) -> None:
        per_core = psutil.cpu_percent(percpu=True)
        overall = sum(per_core) / len(per_core)
        color = _pct_color(overall, '#0ea5e9')

        self._cpu_pct_lbl.setText(f'{overall:.0f}%')
        self._cpu_pct_lbl.setStyleSheet(f'color: {color}; background: transparent;')
        self._cpu_bar.set_value(overall, color)

        freq = psutil.cpu_freq()
        load = psutil.getloadavg()
        freq_str = f'{freq.current / 1000:.2f} GHz' if freq else ''
        load_str = f'Load {load[0]:.2f}  {load[1]:.2f}  {load[2]:.2f}'
        self._cpu_info_lbl.setText(f'{freq_str}   {load_str}')

        for i, (pct, bar, lbl) in enumerate(
            zip(per_core, self._core_bars, self._core_lbls)
        ):
            c = _pct_color(pct, '#0ea5e9')
            bar.set_value(pct, c)
            lbl.setText(f'C{i}  {pct:.0f}%')

    def _update_mem(self) -> None:
        ram = psutil.virtual_memory()
        used = ram.total - ram.available
        ram_color = _pct_color(ram.percent, '#8b5cf6')
        self._ram_bar.set_value(ram.percent, ram_color)
        self._ram_val_lbl.setText(
            f'{_fmt_bytes(used)} / {_fmt_bytes(ram.total)}  ({ram.percent:.0f}%)'
        )

        swap = psutil.swap_memory()
        if swap.total:
            swap_color = _pct_color(swap.percent, '#6366f1')
            self._swap_bar.set_value(swap.percent, swap_color)
            self._swap_val_lbl.setText(
                f'{_fmt_bytes(swap.used)} / {_fmt_bytes(swap.total)}  ({swap.percent:.0f}%)'
            )
        else:
            self._swap_val_lbl.setText('No swap')
            self._swap_bar.set_value(0)

    def _update_net(self) -> None:
        now = time.monotonic()
        net = psutil.net_io_counters()
        elapsed = max(now - self._prev_net_t, 0.001)

        up_bps = (net.bytes_sent - self._prev_net_sent) / elapsed
        dn_bps = (net.bytes_recv - self._prev_net_recv) / elapsed

        self._prev_net_sent = net.bytes_sent
        self._prev_net_recv = net.bytes_recv
        self._prev_net_t = now

        self._net_up_lbl.setText(f'↑  {_fmt_bytes(up_bps)}/s')
        self._net_dn_lbl.setText(f'↓  {_fmt_bytes(dn_bps)}/s')
        self._net_total_lbl.setText(
            f'Total sent {_fmt_bytes(net.bytes_sent)}   '
            f'Total received {_fmt_bytes(net.bytes_recv)}'
        )

    def _update_gpu(self) -> None:
        for ui in self._gpu_ui:
            h = ui['handle']
            try:
                util = nvml.nvmlDeviceGetUtilizationRates(h)
                mem = nvml.nvmlDeviceGetMemoryInfo(h)
                temp = nvml.nvmlDeviceGetTemperature(h, nvml.NVML_TEMPERATURE_GPU)
                power_mw = nvml.nvmlDeviceGetPowerUsage(h)
                try:
                    limit_mw = nvml.nvmlDeviceGetPowerManagementLimit(h)
                    power_str = f'{power_mw / 1000:.0f} W / {limit_mw / 1000:.0f} W'
                except Exception:
                    power_str = f'{power_mw / 1000:.0f} W'
                try:
                    fan = nvml.nvmlDeviceGetFanSpeed(h)
                    fan_str = f'Fan {fan}%'
                except Exception:
                    fan_str = ''
                try:
                    clock = nvml.nvmlDeviceGetClockInfo(h, nvml.NVML_CLOCK_GRAPHICS)
                    clock_str = f'{clock} MHz'
                except Exception:
                    clock_str = ''

                core_pct = float(util.gpu)
                vram_pct = mem.used / mem.total * 100

                core_color = _pct_color(core_pct, '#10b981')
                vram_color = _pct_color(vram_pct, '#6366f1')
                temp_color = '#ef4444' if temp >= 85 else '#f59e0b' if temp >= 70 else 'rgba(255,255,255,0.50)'

                ui['util_lbl'].setText(f'{core_pct:.0f}%')
                ui['util_bar'].set_value(core_pct, core_color)
                ui['vram_lbl'].setText(
                    f'{_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)}  ({vram_pct:.0f}%)'
                )
                ui['vram_bar'].set_value(vram_pct, vram_color)
                ui['temp_lbl'].setText(f'{temp}°C')
                ui['temp_lbl'].setStyleSheet(
                    f'color: {temp_color}; font-size: 9px; background: transparent;'
                )
                details = '  ·  '.join(filter(None, [power_str, fan_str, clock_str]))
                ui['detail_lbl'].setText(details)
            except Exception:
                pass

    def _update_processes(self) -> None:
        procs = []
        for p in psutil.process_iter(['name', 'cpu_percent', 'memory_percent']):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda p: p.get('cpu_percent') or 0.0, reverse=True)
        top = procs[:10]

        for i, (name_lbl, cpu_lbl, mem_lbl) in enumerate(self._proc_rows):
            if i < len(top):
                p = top[i]
                name = (p.get('name') or '?')[:28]
                cpu = p.get('cpu_percent') or 0.0
                mem = p.get('memory_percent') or 0.0
                cpu_color = _pct_color(cpu, 'rgba(255,255,255,0.60)')
                name_lbl.setText(name)
                cpu_lbl.setText(f'{cpu:.1f}%')
                cpu_lbl.setStyleSheet(
                    f'color: {cpu_color}; font-size: 9px; background: transparent;'
                )
                mem_lbl.setText(f'{mem:.1f}%')
            else:
                name_lbl.setText('')
                cpu_lbl.setText('')
                mem_lbl.setText('')
