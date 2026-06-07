from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from PyQt6.QtCore import QPointF, QRectF, Qt, QSettings, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from home_os_app.theme import THEME_QSS, CARD_STYLE, paint_background
from ..data import (
    AccountBalance, MortgageInfo, NetWorthSnapshot, SinkingFund, Transaction,
    fetch_snapshot, load_cache, pull_db, save_cache,
    ManualData, ManualAccount, ManualTransaction, ManualSinkingFund,
    load_manual, save_manual, manual_to_snapshot, manual_record_snapshot,
)
from .source_setup_dialog import SourceSetupDialog
from .manual_editors import AccountDialog, TransactionDialog, SinkingFundDialog

_SETTINGS_APP = 'HomeOS'
_SETTINGS_KEY = 'networth_source'

_ASSET_TYPE_ORDER = [
    'CHECKING', 'SAVINGS', 'INVESTMENT', 'BROKERAGE',
    'RETIREMENT', '401K', 'IRA', 'ROTH',
]

_TYPE_LABEL: dict[str, str] = {
    'CHECKING': 'Checking',
    'SAVINGS': 'Savings',
    'INVESTMENT': 'Investments',
    'BROKERAGE': 'Brokerage',
    'RETIREMENT': 'Retirement',
    '401K': '401(k)',
    'IRA': 'IRA',
    'ROTH': 'Roth IRA',
    'MORTGAGE': 'Mortgage',
    'LOAN': 'Loans',
    'CREDIT_CARD': 'Credit Cards',
    'CREDIT': 'Credit',
}


def _type_label(t: str) -> str:
    return _TYPE_LABEL.get(t, t.replace('_', ' ').title())


def _ago(iso_str: str) -> str:
    try:
        delta = datetime.now() - datetime.fromisoformat(iso_str)
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ""


def _fmt_date(iso: str) -> str:
    try:
        parts = iso.split('-')
        return f"{parts[1]}/{parts[2]}"
    except Exception:
        return iso


def _month_label(key: str) -> str:
    try:
        return datetime.strptime(key, "%Y-%m").strftime("%B %Y")
    except Exception:
        return key


# ── Worker ────────────────────────────────────────────────────────────────────

class _RefreshWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.progress.emit("Finding latest backup…")
            db_path = pull_db()
            self.progress.emit("Reading database…")
            snapshot = fetch_snapshot(db_path)
            db_path.unlink(missing_ok=True)
            self.progress.emit("Saving…")
            save_cache(snapshot)
            self.finished.emit(snapshot)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Chart ─────────────────────────────────────────────────────────────────────

class _ChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history: list[tuple[str, float]] = []
        self._hover_idx: int | None = None
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def set_history(self, history: list[tuple[str, float]]) -> None:
        self._history = history
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if len(self._history) < 2:
            return
        pl, pr = 64, 12
        n = len(self._history)
        frac = (event.position().x() - pl) / max(1, self.width() - pl - pr)
        idx = max(0, min(n - 1, round(frac * (n - 1))))
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover_idx = None
        self.update()

    def paintEvent(self, _event) -> None:
        if len(self._history) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        pl, pr, pt, pb = 64, 12, 12, 32

        values = [v for _, v in self._history]
        n = len(values)
        lo = 0
        hi = max(values) * 1.08

        def px(i: int) -> float:
            return pl + i / (n - 1) * (w - pl - pr)

        def py(v: float) -> float:
            return pt + (1.0 - (v - lo) / (hi - lo)) * (h - pt - pb)

        # Grid
        painter.setPen(QPen(QColor(255, 255, 255, 15), 1))
        for row in range(5):
            y = pt + row / 4 * (h - pt - pb)
            painter.drawLine(QPointF(pl, y), QPointF(w - pr, y))

        # Y labels
        small = QFont()
        small.setPointSize(8)
        painter.setFont(small)
        painter.setPen(QColor(255, 255, 255, 80))
        for row in range(5):
            v = hi - row / 4 * (hi - lo)
            y = pt + row / 4 * (h - pt - pb)
            painter.drawText(
                QRectF(0, y - 9, pl - 6, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"${v / 1_000:.0f}k",
            )

        # X labels (~5 spread)
        step = max(1, (n - 1) // 4)
        for i in range(0, n, step):
            painter.drawText(
                QRectF(px(i) - 22, h - pb + 4, 44, 16),
                Qt.AlignmentFlag.AlignCenter,
                self._history[i][0][5:],  # "MM-DD"
            )

        # Fill
        fill = QPainterPath()
        fill.moveTo(px(0), h - pb)
        fill.lineTo(px(0), py(values[0]))
        for i in range(1, n):
            fill.lineTo(px(i), py(values[i]))
        fill.lineTo(px(n - 1), h - pb)
        fill.closeSubpath()

        grad = QLinearGradient(0, pt, 0, h - pb)
        grad.setColorAt(0.0, QColor(74, 222, 128, 80))
        grad.setColorAt(1.0, QColor(74, 222, 128, 0))
        painter.fillPath(fill, QBrush(grad))

        # Line
        line = QPainterPath()
        line.moveTo(px(0), py(values[0]))
        for i in range(1, n):
            line.lineTo(px(i), py(values[i]))
        painter.setPen(QPen(QColor('#4ade80'), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line)

        # End dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#4ade80'))
        painter.drawEllipse(QPointF(px(n - 1), py(values[-1])), 4, 4)

        # Hover crosshair + tooltip
        if self._hover_idx is not None:
            hi_idx = self._hover_idx
            hx = px(hi_idx)
            hy = py(values[hi_idx])

            dash_pen = QPen(QColor(255, 255, 255, 60), 1, Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.drawLine(QPointF(hx, pt), QPointF(hx, h - pb))

            painter.setPen(QPen(QColor('#4ade80'), 2))
            painter.setBrush(QColor(15, 12, 41))
            painter.drawEllipse(QPointF(hx, hy), 5, 5)

            date_str = self._history[hi_idx][0][5:]
            val_str  = f"${values[hi_idx]:,.0f}"
            tip_text = f"{date_str}\n{val_str}"

            tip_font = QFont()
            tip_font.setPointSize(9)
            painter.setFont(tip_font)
            fm = painter.fontMetrics()
            lines = tip_text.split('\n')
            lw = max(fm.horizontalAdvance(l) for l in lines)
            lh = fm.height()
            pad = 8
            bw = lw + pad * 2
            bh = lh * len(lines) + pad * 2 - 2

            bx = hx + 10
            if bx + bw > w - pr:
                bx = hx - 10 - bw
            by = hy - bh / 2
            by = max(pt, min(by, h - pb - bh))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 12, 41, 220))
            painter.drawRoundedRect(QRectF(bx, by, bw, bh), 6, 6)

            painter.setPen(QColor(255, 255, 255, 200))
            for i, line in enumerate(lines):
                painter.drawText(
                    QRectF(bx + pad, by + pad + i * lh - 1, lw, lh),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    line,
                )


# ── Sinking fund bar ──────────────────────────────────────────────────────────

class _SinkingFundBar(QWidget):
    def __init__(self, fund: SinkingFund, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fund = fund
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        pct     = min(1.0, self._fund.current_cents / max(1, self._fund.target_cents))
        current = self._fund.current_cents / 100
        target  = self._fund.target_cents  / 100

        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor(255, 255, 255, 210))
        painter.drawText(
            QRectF(0, 0, w * 0.55, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._fund.name,
        )

        val_font = QFont()
        val_font.setPointSize(9)
        painter.setFont(val_font)
        painter.setPen(QColor(255, 255, 255, 120))
        painter.drawText(
            QRectF(0, 0, w, 22),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"${current:,.0f} / ${target:,.0f}  ({pct * 100:.1f}%)",
        )

        bar_y, bar_h = 28, 12
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(QRectF(0, bar_y, w, bar_h), 6, 6)

        if pct > 0:
            fill_w = max(float(bar_h), w * pct)
            painter.setBrush(QColor(self._fund.color or '#6366f1'))
            painter.drawRoundedRect(QRectF(0, bar_y, fill_w, bar_h), 6, 6)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _card(parent: QWidget | None = None) -> QWidget:
    w = QWidget(parent)
    w.setStyleSheet(CARD_STYLE)
    return w


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    f = QFont()
    f.setPointSize(8)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
    f.setBold(True)
    lbl.setFont(f)
    lbl.setStyleSheet('color: rgba(255,255,255,0.38); background: transparent;')
    lbl.setContentsMargins(0, 10, 0, 2)
    return lbl


def _icon_btn(icon: str, color: str = 'rgba(255,255,255,0.45)') -> QPushButton:
    btn = QPushButton(icon)
    btn.setFixedSize(24, 24)
    btn.setFlat(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f'QPushButton:flat {{ color: {color}; background: transparent; border: none; }}'
        f'QPushButton:flat:hover {{ background: rgba(255,255,255,0.09); border-radius: 4px; }}'
    )
    return btn


def _account_row(acct: AccountBalance) -> QWidget:
    row = QWidget()
    row.setStyleSheet('background: transparent;')
    row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    hbox = QHBoxLayout(row)
    hbox.setContentsMargins(0, 3, 0, 3)
    hbox.setSpacing(8)

    dot = QLabel()
    dot.setFixedSize(8, 8)
    dot.setStyleSheet(f"background: {acct.color or '#888888'}; border-radius: 4px;")

    name_lbl = QLabel(acct.name)
    nf = QFont()
    nf.setPointSize(10)
    name_lbl.setFont(nf)
    name_lbl.setStyleSheet('color: rgba(255,255,255,0.82); background: transparent;')

    amount_text  = f"-${acct.balance:,.2f}" if acct.is_liability else f"${acct.balance:,.2f}"
    amount_color = '#f87171'                if acct.is_liability else 'rgba(255,255,255,0.82)'

    amount_lbl = QLabel(amount_text)
    af = QFont()
    af.setPointSize(10)
    af.setBold(True)
    amount_lbl.setFont(af)
    amount_lbl.setStyleSheet(f'color: {amount_color}; background: transparent;')
    amount_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    hbox.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
    hbox.addWidget(name_lbl, 1)
    hbox.addWidget(amount_lbl)
    return row


def _manual_account_row(acct: AccountBalance, on_edit, on_delete) -> QWidget:
    row = _account_row(acct)
    hbox = row.layout()
    edit_btn = _icon_btn('✎')
    del_btn  = _icon_btn('✕', '#f87171')
    edit_btn.clicked.connect(on_edit)
    del_btn.clicked.connect(on_delete)
    hbox.addWidget(edit_btn)
    hbox.addWidget(del_btn)
    return row


def _manual_fund_wrapper(fund: SinkingFund, on_edit, on_delete) -> QWidget:
    container = QWidget()
    container.setStyleSheet('background: transparent;')
    container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    hbox = QHBoxLayout(container)
    hbox.setContentsMargins(0, 0, 0, 0)
    hbox.setSpacing(4)
    bar = _SinkingFundBar(fund)
    edit_btn = _icon_btn('✎')
    del_btn  = _icon_btn('✕', '#f87171')
    edit_btn.clicked.connect(on_edit)
    del_btn.clicked.connect(on_delete)
    hbox.addWidget(bar, 1)
    hbox.addWidget(edit_btn, 0, Qt.AlignmentFlag.AlignTop)
    hbox.addWidget(del_btn,  0, Qt.AlignmentFlag.AlignTop)
    return container


def _transaction_row(txn: Transaction) -> QWidget:
    row = QWidget()
    row.setStyleSheet('background: transparent;')
    row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    hbox = QHBoxLayout(row)
    hbox.setContentsMargins(0, 4, 0, 4)
    hbox.setSpacing(10)

    dot = QLabel()
    dot.setFixedSize(8, 8)
    dot_color = txn.category_color if txn.type != 'TRANSFER' else '#888888'
    dot.setStyleSheet(f"background: {dot_color}; border-radius: 4px;")

    date_lbl = QLabel(_fmt_date(txn.date))
    df = QFont()
    df.setPointSize(9)
    date_lbl.setFont(df)
    date_lbl.setFixedWidth(36)
    date_lbl.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

    if txn.type == 'TRANSFER' and txn.to_account:
        desc = f"{txn.account} → {txn.to_account}" if not txn.note or txn.note == 'Transfer' else txn.note
    else:
        desc = txn.note
    desc_lbl = QLabel(desc)
    descf = QFont()
    descf.setPointSize(10)
    desc_lbl.setFont(descf)
    desc_lbl.setStyleSheet('color: rgba(255,255,255,0.82); background: transparent;')
    desc_lbl.setMinimumWidth(80)

    cat_lbl = QLabel(txn.category)
    cf = QFont()
    cf.setPointSize(9)
    cat_lbl.setFont(cf)
    cat_lbl.setFixedWidth(130)
    cat_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    cat_lbl.setStyleSheet('color: rgba(255,255,255,0.40); background: transparent;')

    if txn.type == 'INCOME':
        amount_str   = f"+${txn.amount:,.2f}"
        amount_color = '#4ade80'
    elif txn.type == 'EXPENSE':
        amount_str   = f"-${txn.amount:,.2f}"
        amount_color = '#f87171'
    else:
        amount_str   = f"${txn.amount:,.2f}"
        amount_color = 'rgba(255,255,255,0.55)'

    amount_lbl = QLabel(amount_str)
    amf = QFont()
    amf.setPointSize(10)
    amf.setBold(True)
    amount_lbl.setFont(amf)
    amount_lbl.setFixedWidth(100)
    amount_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    amount_lbl.setStyleSheet(f'color: {amount_color}; background: transparent;')

    hbox.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
    hbox.addWidget(date_lbl)
    hbox.addWidget(desc_lbl, 1)
    hbox.addWidget(cat_lbl)
    hbox.addWidget(amount_lbl)
    return row


def _manual_txn_row(txn: Transaction, on_delete) -> QWidget:
    row = _transaction_row(txn)
    del_btn = _icon_btn('✕', '#f87171')
    del_btn.clicked.connect(on_delete)
    row.layout().addWidget(del_btn)
    return row


# ── Main widget ───────────────────────────────────────────────────────────────

class NetWorthContent(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _RefreshWorker | None = None
        self._snapshot: NetWorthSnapshot | None = None
        self._manual_data: ManualData | None = None
        self._source: str = 'lifeos'

        self._ago_timer = QTimer(self)
        self._ago_timer.setInterval(30_000)
        self._ago_timer.timeout.connect(self._update_sync_label)

        self._setup_ui()
        QTimer.singleShot(0, self._init_source)

    def paintEvent(self, event) -> None:
        paint_background(self)

    # ── Source init ───────────────────────────────────────────────────────────

    def _init_source(self) -> None:
        settings = QSettings(_SETTINGS_APP, 'NetWorth')
        source = settings.value(_SETTINGS_KEY, '')
        if not source:
            dlg = SourceSetupDialog(parent=self)
            dlg.setStyleSheet(THEME_QSS)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                source = dlg.selected_source
            else:
                source = 'lifeos'
            settings.setValue(_SETTINGS_KEY, source)
        self._source = source
        self._apply_mode()
        self._load_initial_data()

    def _apply_mode(self) -> None:
        is_manual = self._source == 'manual'
        self._refresh_btn.setVisible(not is_manual)
        self._sync_label.setVisible(not is_manual)
        self._add_acct_btn.setVisible(is_manual)
        self._add_fund_btn.setVisible(is_manual)
        self._add_txn_btn.setVisible(is_manual)

    def _load_initial_data(self) -> None:
        if self._source == 'manual':
            self._manual_data = load_manual()
            snap = manual_to_snapshot(self._manual_data)
            self._snapshot = snap
            self._populate(snap)
        else:
            cached = load_cache()
            if cached:
                self._snapshot = cached
                self._populate(cached)
                self._ago_timer.start()

    def _show_source_setup(self) -> None:
        dlg = SourceSetupDialog(current=self._source, parent=self)
        dlg.setStyleSheet(THEME_QSS)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_source = dlg.selected_source
        if new_source == self._source:
            return
        self._source = new_source
        QSettings(_SETTINGS_APP, 'NetWorth').setValue(_SETTINGS_KEY, new_source)
        self._manual_data = None
        self._snapshot = None
        # Clear UI
        self._nw_label.setText('—')
        self._breakdown_label.setText('')
        self._chart.set_history([])
        self._apply_mode()
        self._load_initial_data()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setStyleSheet(THEME_QSS)

        main = QVBoxLayout(self)
        main.setContentsMargins(24, 20, 24, 16)
        main.setSpacing(14)

        # ── Header card ──────────────────────────────────────────────────────
        hdr_card = _card()
        hdr_layout = QHBoxLayout(hdr_card)
        hdr_layout.setContentsMargins(20, 16, 20, 16)
        hdr_layout.setSpacing(0)

        left = QVBoxLayout()
        left.setSpacing(3)

        title_lbl = QLabel('Net Worth')
        tf = QFont()
        tf.setPointSize(10)
        title_lbl.setFont(tf)
        title_lbl.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        self._nw_label = QLabel('—')
        nwf = QFont()
        nwf.setPointSize(34)
        nwf.setBold(True)
        self._nw_label.setFont(nwf)
        self._nw_label.setStyleSheet('color: #4ade80; background: transparent;')

        self._breakdown_label = QLabel('Choose a data source to get started')
        bf = QFont()
        bf.setPointSize(10)
        self._breakdown_label.setFont(bf)
        self._breakdown_label.setStyleSheet('color: rgba(255,255,255,0.4); background: transparent;')

        left.addWidget(title_lbl)
        left.addWidget(self._nw_label)
        left.addWidget(self._breakdown_label)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self._refresh_btn = QPushButton('↻  Refresh')
        self._refresh_btn.setFixedSize(116, 34)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setStyleSheet(
            "QPushButton { color: #4ade80; } QPushButton:disabled { color: rgba(255,255,255,0.25); }"
        )
        self._refresh_btn.clicked.connect(self._start_refresh)

        self._sync_label = QLabel('')
        self._sync_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._sync_label.setStyleSheet('color: rgba(255,255,255,0.28); font-size: 9px; background: transparent;')

        source_btn = QPushButton('⚙ Change Source')
        source_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        source_btn.setStyleSheet(
            'QPushButton { color: rgba(255,255,255,0.25); background: transparent; border: none; font-size: 9px; padding: 0; }'
            'QPushButton:hover { color: rgba(255,255,255,0.55); }'
        )
        source_btn.clicked.connect(self._show_source_setup)

        right.addWidget(self._refresh_btn, 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._sync_label,  0, Qt.AlignmentFlag.AlignRight)
        right.addStretch()
        right.addWidget(source_btn, 0, Qt.AlignmentFlag.AlignRight)

        hdr_layout.addLayout(left, 1)
        hdr_layout.addLayout(right)
        main.addWidget(hdr_card)

        # ── Tab widget ───────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        main.addWidget(self._tabs, 1)

        # ── Overview tab ─────────────────────────────────────────────────────
        overview = QWidget()
        overview.setStyleSheet('background: transparent;')
        overview_v = QVBoxLayout(overview)
        overview_v.setContentsMargins(0, 0, 0, 0)
        overview_v.setSpacing(14)

        body = QHBoxLayout()
        body.setSpacing(14)

        acct_card = _card()
        acct_card.setFixedWidth(290)
        acct_outer = QVBoxLayout(acct_card)
        acct_outer.setContentsMargins(0, 0, 0, 0)
        acct_outer.setSpacing(0)

        # "+ Add Account" button (manual mode only, hidden initially)
        self._add_acct_btn = QPushButton('+ Add Account')
        self._add_acct_btn.setFixedHeight(34)
        self._add_acct_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_acct_btn.setStyleSheet(
            'QPushButton { color: #4ade80; background: transparent; border: none;'
            ' border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 11px; }'
            'QPushButton:hover { background: rgba(74,222,128,0.07); }'
        )
        self._add_acct_btn.hide()
        self._add_acct_btn.clicked.connect(self._on_add_account)
        acct_outer.addWidget(self._add_acct_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        scroll.viewport().setAutoFillBackground(False)

        self._acct_inner = QWidget()
        self._acct_inner.setStyleSheet('background: transparent;')
        self._acct_inner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._acct_layout = QVBoxLayout(self._acct_inner)
        self._acct_layout.setContentsMargins(16, 14, 16, 14)
        self._acct_layout.setSpacing(2)
        self._acct_layout.addStretch()

        scroll.setWidget(self._acct_inner)
        acct_outer.addWidget(scroll, 1)
        body.addWidget(acct_card)

        chart_card = _card()
        chart_v = QVBoxLayout(chart_card)
        chart_v.setContentsMargins(16, 12, 16, 10)
        chart_v.setSpacing(8)

        chart_title = QLabel('Net Worth Over Time')
        ctf = QFont()
        ctf.setPointSize(10)
        ctf.setBold(True)
        chart_title.setFont(ctf)
        chart_title.setStyleSheet('color: rgba(255,255,255,0.55); background: transparent;')

        self._chart = _ChartWidget()
        chart_v.addWidget(chart_title)
        chart_v.addWidget(self._chart, 1)
        body.addWidget(chart_card, 1)

        overview_v.addLayout(body, 1)

        # Sinking funds
        self._funds_card = _card()
        self._funds_card.hide()
        funds_v = QVBoxLayout(self._funds_card)
        funds_v.setContentsMargins(20, 12, 20, 14)
        funds_v.setSpacing(10)

        funds_hdr = QHBoxLayout()
        funds_title = QLabel('SINKING FUNDS')
        ftf = QFont()
        ftf.setPointSize(8)
        ftf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        ftf.setBold(True)
        funds_title.setFont(ftf)
        funds_title.setStyleSheet('color: rgba(255,255,255,0.38); background: transparent;')
        funds_hdr.addWidget(funds_title)
        funds_hdr.addStretch()

        self._add_fund_btn = QPushButton('+ Add')
        self._add_fund_btn.setFixedHeight(22)
        self._add_fund_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_fund_btn.setStyleSheet(
            'QPushButton { color: #4ade80; background: transparent; border: none; font-size: 10px; }'
            'QPushButton:hover { color: white; }'
        )
        self._add_fund_btn.hide()
        self._add_fund_btn.clicked.connect(self._on_add_fund)
        funds_hdr.addWidget(self._add_fund_btn)

        self._funds_layout = QVBoxLayout()
        self._funds_layout.setSpacing(8)
        funds_v.addLayout(funds_hdr)
        funds_v.addLayout(self._funds_layout)
        overview_v.addWidget(self._funds_card)

        self._tabs.addTab(overview, 'Overview')

        # ── Transactions tab ─────────────────────────────────────────────────
        txn_tab = QWidget()
        txn_tab.setStyleSheet('background: transparent;')
        txn_tab_v = QVBoxLayout(txn_tab)
        txn_tab_v.setContentsMargins(0, 4, 0, 0)
        txn_tab_v.setSpacing(6)

        self._add_txn_btn = QPushButton('+ Add Transaction')
        self._add_txn_btn.setFixedHeight(32)
        self._add_txn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_txn_btn.setStyleSheet(
            'QPushButton { color: #4ade80; background: rgba(74,222,128,0.07);'
            ' border: 1px solid rgba(74,222,128,0.20); border-radius: 6px; font-size: 11px; }'
            'QPushButton:hover { background: rgba(74,222,128,0.14); }'
        )
        self._add_txn_btn.hide()
        self._add_txn_btn.clicked.connect(self._on_add_transaction)
        txn_tab_v.addWidget(self._add_txn_btn, 0, Qt.AlignmentFlag.AlignRight)

        txn_outer = QScrollArea()
        txn_outer.setWidgetResizable(True)
        txn_outer.setFrameShape(QScrollArea.Shape.NoFrame)
        txn_outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        txn_outer.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 5px; background: transparent; margin: 4px 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.14); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        txn_outer.viewport().setAutoFillBackground(False)

        self._txn_inner = QWidget()
        self._txn_inner.setStyleSheet('background: transparent;')
        self._txn_inner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._txn_layout = QVBoxLayout(self._txn_inner)
        self._txn_layout.setContentsMargins(0, 4, 0, 16)
        self._txn_layout.setSpacing(0)
        self._txn_layout.addStretch()

        txn_outer.setWidget(self._txn_inner)
        txn_tab_v.addWidget(txn_outer, 1)
        self._tabs.addTab(txn_tab, 'Transactions')

    # ── Populate ──────────────────────────────────────────────────────────────

    def _populate(self, snap: NetWorthSnapshot) -> None:
        nw    = snap.net_worth
        color = '#4ade80' if nw >= 0 else '#f87171'
        self._nw_label.setStyleSheet(f'color: {color}; background: transparent;')
        self._nw_label.setText(f"${nw:,.0f}" if nw >= 0 else f"-${abs(nw):,.0f}")
        self._breakdown_label.setText(
            f"Assets  ${snap.total_assets:,.0f}  ·  Liabilities  ${snap.total_liabilities:,.0f}"
        )
        self._update_sync_label()
        self._chart.set_history(snap.history)

        md = self._manual_data if self._source == 'manual' else None
        self._populate_accounts(snap, md)
        self._populate_funds(snap, md)
        self._populate_transactions(snap.transactions, md)

    def _populate_accounts(self, snap: NetWorthSnapshot, md: ManualData | None) -> None:
        while self._acct_layout.count():
            item = self._acct_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if md is not None:
            # Manual mode — render with edit / delete buttons
            assets_idx  = [(i, a) for i, a in enumerate(md.accounts) if not a.is_liability]
            liab_idx    = [(i, a) for i, a in enumerate(md.accounts) if a.is_liability]

            def sort_key(pair):
                _, a = pair
                try:
                    return (_ASSET_TYPE_ORDER.index(a.type), a.name)
                except ValueError:
                    return (len(_ASSET_TYPE_ORDER), a.name)

            assets_idx.sort(key=sort_key)

            type_groups: dict[str, list] = {}
            for i, a in assets_idx:
                type_groups.setdefault(a.type, []).append((i, a))

            for type_key, group in type_groups.items():
                self._acct_layout.addWidget(_section_label(_type_label(type_key)))
                for idx, ma in group:
                    ab = AccountBalance(id=idx, name=ma.name, type=ma.type,
                                        color=ma.color, balance=ma.balance, is_liability=False)
                    row = _manual_account_row(
                        ab,
                        lambda i=idx: self._on_edit_account(i),
                        lambda i=idx: self._on_delete_account(i),
                    )
                    self._acct_layout.addWidget(row)

            if liab_idx:
                sep = QWidget()
                sep.setFixedHeight(1)
                sep.setStyleSheet('background: rgba(255,255,255,0.07);')
                sep.setContentsMargins(0, 6, 0, 0)
                self._acct_layout.addWidget(sep)
                self._acct_layout.addWidget(_section_label('Liabilities'))
                for idx, ma in liab_idx:
                    ab = AccountBalance(id=idx, name=ma.name, type=ma.type,
                                        color=ma.color, balance=ma.balance, is_liability=True)
                    row = _manual_account_row(
                        ab,
                        lambda i=idx: self._on_edit_account(i),
                        lambda i=idx: self._on_delete_account(i),
                    )
                    self._acct_layout.addWidget(row)

            if not md.accounts:
                hint = QLabel('Click + Add Account to get started.')
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hint.setWordWrap(True)
                hint.setStyleSheet('color: rgba(255,255,255,0.28); font-size: 11px; background: transparent;')
                self._acct_layout.addWidget(hint)

        else:
            # LifeOS mode — read-only
            assets      = [a for a in snap.accounts if not a.is_liability]
            liabilities = [a for a in snap.accounts if a.is_liability]

            def sort_key(a: AccountBalance):
                try:
                    return (_ASSET_TYPE_ORDER.index(a.type), a.name)
                except ValueError:
                    return (len(_ASSET_TYPE_ORDER), a.name)

            assets.sort(key=sort_key)
            type_groups: dict[str, list[AccountBalance]] = {}
            for a in assets:
                type_groups.setdefault(a.type, []).append(a)

            for type_key, group in type_groups.items():
                self._acct_layout.addWidget(_section_label(_type_label(type_key)))
                for acct in group:
                    self._acct_layout.addWidget(_account_row(acct))

            if liabilities:
                sep = QWidget()
                sep.setFixedHeight(1)
                sep.setStyleSheet('background: rgba(255,255,255,0.07);')
                sep.setContentsMargins(0, 6, 0, 0)
                self._acct_layout.addWidget(sep)
                self._acct_layout.addWidget(_section_label('Liabilities'))
                for acct in liabilities:
                    self._acct_layout.addWidget(_account_row(acct))

                if snap.mortgage:
                    m = snap.mortgage
                    info = QLabel(
                        f"APR {m.apr_percent:.1f}%  ·  {m.remaining_months} mo remaining  ·  ${m.monthly_payment:,.0f}/mo"
                    )
                    info_f = QFont()
                    info_f.setPointSize(8)
                    info.setFont(info_f)
                    info.setStyleSheet('color: rgba(255,255,255,0.30); background: transparent;')
                    info.setWordWrap(True)
                    info.setContentsMargins(16, 0, 0, 4)
                    self._acct_layout.addWidget(info)

        self._acct_layout.addStretch()

    def _populate_funds(self, snap: NetWorthSnapshot, md: ManualData | None) -> None:
        while self._funds_layout.count():
            item = self._funds_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if snap.sinking_funds:
            for i, fund in enumerate(snap.sinking_funds):
                if md is not None:
                    wrapper = _manual_fund_wrapper(
                        fund,
                        lambda idx=i: self._on_edit_fund(idx),
                        lambda idx=i: self._on_delete_fund(idx),
                    )
                    self._funds_layout.addWidget(wrapper)
                else:
                    self._funds_layout.addWidget(_SinkingFundBar(fund))
            self._funds_card.show()
        elif md is not None:
            # In manual mode, always show the funds card so the add button is accessible
            self._funds_card.show()
        else:
            self._funds_card.hide()

    def _populate_transactions(self, transactions: list[Transaction], md: ManualData | None) -> None:
        while self._txn_layout.count():
            item = self._txn_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if md is not None:
            # Manual mode: iterate raw ManualTransaction for delete IDs
            sorted_mt = sorted(md.transactions, key=lambda t: t.date, reverse=True)
            if not sorted_mt:
                hint = QLabel('No transactions yet — click + Add Transaction to get started.')
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hint.setWordWrap(True)
                hint.setStyleSheet('color: rgba(255,255,255,0.3); font-size: 12px; background: transparent;')
                self._txn_layout.addWidget(hint)
                self._txn_layout.addStretch()
                return

            month_groups: dict[str, list] = {}
            for mt in sorted_mt:
                month_groups.setdefault(mt.date[:7], []).append(mt)

            for month_key in sorted(month_groups.keys(), reverse=True):
                mt_list = month_groups[month_key]
                income   = sum(t.amount for t in mt_list if t.type == 'INCOME')
                expenses = sum(t.amount for t in mt_list if t.type == 'EXPENSE')

                month_hdr = self._month_header_widget(month_key, len(mt_list), income, expenses)
                self._txn_layout.addWidget(month_hdr)
                div = QWidget(); div.setFixedHeight(1); div.setStyleSheet('background: rgba(255,255,255,0.07);')
                self._txn_layout.addWidget(div)

                group_card = _card()
                group_v = QVBoxLayout(group_card)
                group_v.setContentsMargins(16, 6, 16, 6)
                group_v.setSpacing(0)

                for j, mt in enumerate(mt_list):
                    t = Transaction(date=mt.date, note=mt.note, category=mt.category,
                                    amount=mt.amount, type=mt.type, account=mt.account,
                                    to_account=mt.to_account, category_color=mt.category_color,
                                    account_color=mt.account_color)
                    group_v.addWidget(_manual_txn_row(t, lambda tid=mt.id: self._on_delete_transaction(tid)))
                    if j < len(mt_list) - 1:
                        row_div = QWidget(); row_div.setFixedHeight(1); row_div.setStyleSheet('background: rgba(255,255,255,0.05);')
                        group_v.addWidget(row_div)
                self._txn_layout.addWidget(group_card)
            self._txn_layout.addStretch()
            return

        # LifeOS mode (read-only)
        if not transactions:
            placeholder = QLabel('No transactions yet — hit Refresh to sync.')
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet('color: rgba(255,255,255,0.3); font-size: 12px; background: transparent;')
            self._txn_layout.addWidget(placeholder)
            self._txn_layout.addStretch()
            return

        month_groups2: dict[str, list[Transaction]] = {}
        for t in transactions:
            month_groups2.setdefault(t.date[:7], []).append(t)

        for month_key in sorted(month_groups2.keys(), reverse=True):
            txns = month_groups2[month_key]
            income   = sum(t.amount for t in txns if t.type == 'INCOME')
            expenses = sum(t.amount for t in txns if t.type == 'EXPENSE')

            self._txn_layout.addWidget(self._month_header_widget(month_key, len(txns), income, expenses))
            div = QWidget(); div.setFixedHeight(1); div.setStyleSheet('background: rgba(255,255,255,0.07);')
            self._txn_layout.addWidget(div)

            group_card = _card()
            group_v = QVBoxLayout(group_card)
            group_v.setContentsMargins(16, 6, 16, 6)
            group_v.setSpacing(0)

            for i, txn in enumerate(txns):
                group_v.addWidget(_transaction_row(txn))
                if i < len(txns) - 1:
                    row_div = QWidget(); row_div.setFixedHeight(1); row_div.setStyleSheet('background: rgba(255,255,255,0.05);')
                    group_v.addWidget(row_div)
            self._txn_layout.addWidget(group_card)

        self._txn_layout.addStretch()

    def _month_header_widget(self, month_key: str, count: int, income: float, expenses: float) -> QWidget:
        hdr = QWidget()
        hdr.setStyleSheet('background: transparent;')
        hdr.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        mh = QHBoxLayout(hdr)
        mh.setContentsMargins(0, 16, 0, 6)
        mh.setSpacing(10)

        name_lbl = QLabel(_month_label(month_key))
        nf = QFont(); nf.setPointSize(12); nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setStyleSheet('color: rgba(255,255,255,0.85); background: transparent;')

        count_lbl = QLabel(f"{count} transactions")
        cf = QFont(); cf.setPointSize(9)
        count_lbl.setFont(cf)
        count_lbl.setStyleSheet('color: rgba(255,255,255,0.35); background: transparent;')

        summary_lbl = QLabel(f"+${income:,.0f}  −${expenses:,.0f}" if income or expenses else "")
        sf = QFont(); sf.setPointSize(9)
        summary_lbl.setFont(sf)
        summary_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary_lbl.setStyleSheet('color: rgba(255,255,255,0.40); background: transparent;')

        mh.addWidget(name_lbl)
        mh.addWidget(count_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        mh.addStretch()
        mh.addWidget(summary_lbl)
        return hdr

    def _update_sync_label(self) -> None:
        if self._snapshot and self._source == 'lifeos':
            self._sync_label.setText(f"Last synced {_ago(self._snapshot.fetched_at)}")

    # ── LifeOS refresh ────────────────────────────────────────────────────────

    def _start_refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Syncing…")
        self._sync_label.setText("")
        self._worker = _RefreshWorker(self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self._sync_label.setText(msg)

    def _on_finished(self, snapshot: NetWorthSnapshot) -> None:
        self._snapshot = snapshot
        self._populate(snapshot)
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻  Refresh")
        self._ago_timer.start()

    def _on_error(self, msg: str) -> None:
        self._sync_label.setText(f"Error: {msg}")
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↻  Refresh")

    # ── Manual CRUD ───────────────────────────────────────────────────────────

    def _save_and_repopulate(self) -> None:
        if not self._manual_data:
            return
        manual_record_snapshot(self._manual_data)
        save_manual(self._manual_data)
        snap = manual_to_snapshot(self._manual_data)
        self._snapshot = snap
        self._populate(snap)

    # Accounts

    def _on_add_account(self) -> None:
        dlg = AccountDialog(parent=self)
        dlg.setStyleSheet(THEME_QSS)
        dlg.account_saved.connect(self._handle_account_add)
        dlg.exec()

    def _handle_account_add(self, account: ManualAccount) -> None:
        self._manual_data.accounts.append(account)
        self._save_and_repopulate()

    def _on_edit_account(self, idx: int) -> None:
        if not self._manual_data or idx >= len(self._manual_data.accounts):
            return
        dlg = AccountDialog(existing=self._manual_data.accounts[idx], parent=self)
        dlg.setStyleSheet(THEME_QSS)
        dlg.account_saved.connect(lambda a, i=idx: self._handle_account_edit(i, a))
        dlg.exec()

    def _handle_account_edit(self, idx: int, account: ManualAccount) -> None:
        self._manual_data.accounts[idx] = account
        self._save_and_repopulate()

    def _on_delete_account(self, idx: int) -> None:
        if not self._manual_data or idx >= len(self._manual_data.accounts):
            return
        del self._manual_data.accounts[idx]
        self._save_and_repopulate()

    # Sinking funds

    def _on_add_fund(self) -> None:
        dlg = SinkingFundDialog(parent=self)
        dlg.setStyleSheet(THEME_QSS)
        dlg.fund_saved.connect(self._handle_fund_add)
        dlg.exec()

    def _handle_fund_add(self, fund: ManualSinkingFund) -> None:
        self._manual_data.sinking_funds.append(fund)
        self._save_and_repopulate()

    def _on_edit_fund(self, idx: int) -> None:
        if not self._manual_data or idx >= len(self._manual_data.sinking_funds):
            return
        dlg = SinkingFundDialog(existing=self._manual_data.sinking_funds[idx], parent=self)
        dlg.setStyleSheet(THEME_QSS)
        dlg.fund_saved.connect(lambda f, i=idx: self._handle_fund_edit(i, f))
        dlg.exec()

    def _handle_fund_edit(self, idx: int, fund: ManualSinkingFund) -> None:
        self._manual_data.sinking_funds[idx] = fund
        self._save_and_repopulate()

    def _on_delete_fund(self, idx: int) -> None:
        if not self._manual_data or idx >= len(self._manual_data.sinking_funds):
            return
        del self._manual_data.sinking_funds[idx]
        self._save_and_repopulate()

    # Transactions

    def _on_add_transaction(self) -> None:
        if not self._manual_data:
            return
        names = [a.name for a in self._manual_data.accounts]
        dlg = TransactionDialog(account_names=names, parent=self)
        dlg.setStyleSheet(THEME_QSS)
        dlg.transaction_saved.connect(self._handle_transaction_add)
        dlg.exec()

    def _handle_transaction_add(self, txn: ManualTransaction) -> None:
        self._manual_data.transactions.append(txn)
        self._save_and_repopulate()

    def _on_delete_transaction(self, txn_id: str) -> None:
        if not self._manual_data:
            return
        self._manual_data.transactions = [
            t for t in self._manual_data.transactions if t.id != txn_id
        ]
        self._save_and_repopulate()
