from __future__ import annotations

import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..data import ManualAccount, ManualSinkingFund, ManualTransaction

_PALETTE = [
    '#4ade80', '#60a5fa', '#a78bfa', '#f472b6',
    '#fb923c', '#fbbf24', '#34d399', '#e879f9',
    '#f87171', '#94a3b8',
]

_ACCOUNT_TYPES = [
    ('CHECKING',    'Checking'),
    ('SAVINGS',     'Savings'),
    ('INVESTMENT',  'Investments'),
    ('BROKERAGE',   'Brokerage'),
    ('RETIREMENT',  'Retirement'),
    ('401K',        '401(k)'),
    ('IRA',         'IRA'),
    ('ROTH',        'Roth IRA'),
    ('MORTGAGE',    'Mortgage'),
    ('LOAN',        'Loan'),
    ('CREDIT_CARD', 'Credit Card'),
    ('OTHER',       'Other'),
]

_LIABILITY_TYPES = frozenset({'MORTGAGE', 'LOAN', 'CREDIT_CARD'})


# ── Color picker ──────────────────────────────────────────────────────────────

class _ColorPicker(QWidget):
    color_changed = pyqtSignal(str)

    def __init__(self, selected: str = '#4ade80', parent=None):
        super().__init__(parent)
        self._selected = selected if selected in _PALETTE else _PALETTE[0]
        self._btns: dict[str, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for c in _PALETTE:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, color=c: self._select(color))
            self._btns[c] = btn
            layout.addWidget(btn)
        layout.addStretch()
        self._refresh_styles()

    def _select(self, color: str) -> None:
        self._selected = color
        self._refresh_styles()
        self.color_changed.emit(color)

    def _refresh_styles(self) -> None:
        for c, btn in self._btns.items():
            border = 'white' if c == self._selected else 'transparent'
            btn.setStyleSheet(
                f'background: {c}; border-radius: 11px; border: 2px solid {border};'
            )

    def set_color(self, color: str) -> None:
        if color in _PALETTE:
            self._select(color)

    @property
    def selected(self) -> str:
        return self._selected


# ── Account dialog ────────────────────────────────────────────────────────────

class AccountDialog(QDialog):
    account_saved = pyqtSignal(object)  # ManualAccount

    def __init__(self, existing: ManualAccount | None = None, parent=None):
        super().__init__(parent)
        self._existing = existing
        self.setWindowTitle('Edit Account' if existing else 'Add Account')
        self.setModal(True)
        self.setMinimumWidth(350)

        self._name = QLineEdit()
        self._name.setPlaceholderText('e.g. Chase Checking')

        self._type = QComboBox()
        for key, label in _ACCOUNT_TYPES:
            self._type.addItem(label, key)
        self._type.currentIndexChanged.connect(self._on_type_changed)

        self._balance = QDoubleSpinBox()
        self._balance.setRange(0, 99_999_999)
        self._balance.setDecimals(2)
        self._balance.setPrefix('$')
        self._balance.setSingleStep(100)

        self._is_liability = QCheckBox('This is a debt / liability')

        self._color = _ColorPicker()

        self._error = QLabel('')
        self._error.setStyleSheet('color: #f87171;')
        self._error.setVisible(False)

        save_btn = QPushButton('Save')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow('Name', self._name)
        form.addRow('Type', self._type)
        form.addRow('Balance', self._balance)
        form.addRow('', self._is_liability)
        form.addRow('Color', self._color)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addLayout(btn_row)

        if existing:
            self._load(existing)

    def _load(self, acct: ManualAccount) -> None:
        self._name.setText(acct.name)
        for i in range(self._type.count()):
            if self._type.itemData(i) == acct.type:
                self._type.setCurrentIndex(i)
                break
        self._balance.setValue(acct.balance)
        self._is_liability.setChecked(acct.is_liability)
        self._color.set_color(acct.color)

    def _on_type_changed(self) -> None:
        if self._type.currentData() in _LIABILITY_TYPES:
            self._is_liability.setChecked(True)

    def _on_save(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._error.setText('Name is required.')
            self._error.setVisible(True)
            return
        self.account_saved.emit(ManualAccount(
            id=self._existing.id if self._existing else str(uuid.uuid4()),
            name=name,
            type=self._type.currentData(),
            balance=self._balance.value(),
            is_liability=self._is_liability.isChecked(),
            color=self._color.selected,
        ))
        self.accept()


# ── Transaction dialog ────────────────────────────────────────────────────────

class TransactionDialog(QDialog):
    transaction_saved = pyqtSignal(object)  # ManualTransaction

    def __init__(self, account_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle('Add Transaction')
        self.setModal(True)
        self.setMinimumWidth(370)

        self._date_edit = QLineEdit()
        self._date_edit.setPlaceholderText('YYYY-MM-DD')
        self._date_edit.setText(datetime.now().strftime('%Y-%m-%d'))

        self._txn_type = QComboBox()
        for key, label in [('EXPENSE', 'Expense'), ('INCOME', 'Income'), ('TRANSFER', 'Transfer')]:
            self._txn_type.addItem(label, key)
        self._txn_type.currentIndexChanged.connect(self._on_type_changed)

        self._desc = QLineEdit()
        self._desc.setPlaceholderText('e.g. Grocery Store')

        self._amount = QDoubleSpinBox()
        self._amount.setRange(0, 99_999_999)
        self._amount.setDecimals(2)
        self._amount.setPrefix('$')
        self._amount.setSingleStep(10)

        self._category = QLineEdit()
        self._category.setText('Uncategorized')

        self._account = QComboBox()
        for n in account_names:
            self._account.addItem(n)

        self._to_lbl = QLabel('To Account')
        self._to_account = QComboBox()
        for n in account_names:
            self._to_account.addItem(n)
        self._to_lbl.setVisible(False)
        self._to_account.setVisible(False)

        self._error = QLabel('')
        self._error.setStyleSheet('color: #f87171;')
        self._error.setVisible(False)

        save_btn = QPushButton('Add')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow('Date', self._date_edit)
        form.addRow('Type', self._txn_type)
        form.addRow('Description', self._desc)
        form.addRow('Amount', self._amount)
        form.addRow('Category', self._category)
        form.addRow('Account', self._account)
        form.addRow(self._to_lbl, self._to_account)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addLayout(btn_row)

    def _on_type_changed(self) -> None:
        is_transfer = self._txn_type.currentData() == 'TRANSFER'
        self._to_lbl.setVisible(is_transfer)
        self._to_account.setVisible(is_transfer)

    def _on_save(self) -> None:
        date_str = self._date_edit.text().strip()
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            self._error.setText('Date must be YYYY-MM-DD.')
            self._error.setVisible(True)
            self._date_edit.setStyleSheet('border-color: #f87171;')
            return
        self._error.setVisible(False)

        txn_type = self._txn_type.currentData()
        to_account = self._to_account.currentText() if txn_type == 'TRANSFER' else ''

        self.transaction_saved.emit(ManualTransaction(
            id=str(uuid.uuid4()),
            date=date_str,
            note=self._desc.text().strip() or txn_type.title(),
            category=self._category.text().strip() or 'Uncategorized',
            amount=self._amount.value(),
            type=txn_type,
            account=self._account.currentText() if self._account.count() else '',
            to_account=to_account,
            category_color='#888888',
            account_color='#888888',
        ))
        self.accept()


# ── Sinking fund dialog ───────────────────────────────────────────────────────

class SinkingFundDialog(QDialog):
    fund_saved = pyqtSignal(object)  # ManualSinkingFund

    def __init__(self, existing: ManualSinkingFund | None = None, parent=None):
        super().__init__(parent)
        self._existing = existing
        self.setWindowTitle('Edit Sinking Fund' if existing else 'Add Sinking Fund')
        self.setModal(True)
        self.setMinimumWidth(340)

        self._name = QLineEdit()
        self._name.setPlaceholderText('e.g. Emergency Fund')

        self._current = QDoubleSpinBox()
        self._current.setRange(0, 99_999_999)
        self._current.setDecimals(2)
        self._current.setPrefix('$')
        self._current.setSingleStep(100)

        self._target = QDoubleSpinBox()
        self._target.setRange(0, 99_999_999)
        self._target.setDecimals(2)
        self._target.setPrefix('$')
        self._target.setSingleStep(100)

        self._color = _ColorPicker(selected='#a78bfa')

        self._error = QLabel('')
        self._error.setStyleSheet('color: #f87171;')
        self._error.setVisible(False)

        save_btn = QPushButton('Save')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow('Name', self._name)
        form.addRow('Current ($)', self._current)
        form.addRow('Target ($)', self._target)
        form.addRow('Color', self._color)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addLayout(btn_row)

        if existing:
            self._name.setText(existing.name)
            self._current.setValue(existing.current_cents / 100)
            self._target.setValue(existing.target_cents / 100)
            self._color.set_color(existing.color)

    def _on_save(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._error.setText('Name is required.')
            self._error.setVisible(True)
            return
        self.fund_saved.emit(ManualSinkingFund(
            id=self._existing.id if self._existing else str(uuid.uuid4()),
            name=name,
            color=self._color.selected,
            current_cents=int(self._current.value() * 100),
            target_cents=int(self._target.value() * 100),
        ))
        self.accept()
