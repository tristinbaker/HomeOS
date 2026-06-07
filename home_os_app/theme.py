from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter

# Shared QSS — mirrors the music player's _THEME_QSS, extended with tab styles.
THEME_QSS = """
    QWidget {
        color: white;
        background: transparent;
    }

    QTreeView, QListView, QTreeWidget, QListWidget {
        background: rgba(255, 255, 255, 0.05);
        alternate-background-color: rgba(255, 255, 255, 0.03);
        border: none;
        border-radius: 8px;
        outline: none;
        selection-background-color: rgba(29, 78, 216, 0.55);
        selection-color: white;
    }
    QTreeView::item, QListView::item, QTreeWidget::item, QListWidget::item {
        padding: 3px 6px;
    }
    QTreeView::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {
        background: rgba(255, 255, 255, 0.07);
    }
    QTreeView::item:selected, QListWidget::item:selected, QTreeWidget::item:selected,
    QTreeView::item:selected:!active, QListWidget::item:selected:!active,
    QTreeWidget::item:selected:!active {
        background: rgba(29, 78, 216, 0.55);
        color: white;
    }

    QHeaderView { background: transparent; border: none; }
    QHeaderView::section {
        background: rgba(255, 255, 255, 0.06);
        color: rgba(255, 255, 255, 0.5);
        border: none;
        border-bottom: 1px solid rgba(255, 255, 255, 0.09);
        border-right: 1px solid rgba(255, 255, 255, 0.05);
        padding: 4px 8px;
        font-size: 11px;
    }
    QHeaderView::section:last-child { border-right: none; }

    QPushButton {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 6px;
        color: white;
        padding: 4px 10px;
    }
    QPushButton:hover {
        background: rgba(255, 255, 255, 0.15);
        border-color: rgba(255, 255, 255, 0.22);
    }
    QPushButton:pressed  { background: rgba(255, 255, 255, 0.04); }
    QPushButton:disabled {
        color: rgba(255, 255, 255, 0.25);
        background: rgba(255, 255, 255, 0.03);
        border-color: rgba(255, 255, 255, 0.05);
    }

    QScrollBar:vertical {
        background: transparent;
        width: 6px;
        margin: 2px 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 3px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover  { background: rgba(255, 255, 255, 0.35); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical  { height: 0; border: none; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical  { background: none; }

    QTabWidget::pane   { border: none; background: transparent; margin-top: 6px; }
    QTabBar::tab {
        background: rgba(255, 255, 255, 0.05);
        color: rgba(255, 255, 255, 0.45);
        padding: 7px 22px;
        border-radius: 7px;
        margin-right: 4px;
        font-size: 11px;
    }
    QTabBar::tab:selected { background: rgba(255, 255, 255, 0.12); color: white; }
    QTabBar::tab:hover    { background: rgba(255, 255, 255, 0.09); color: rgba(255, 255, 255, 0.7); }

    QDialog {
        background: #0f0c29;
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 12px;
    }

    QLineEdit {
        background: rgba(255, 255, 255, 0.07);
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 7px;
        padding: 8px 12px;
        font-size: 12px;
    }
    QLineEdit:focus { border-color: rgba(255, 255, 255, 0.35); }

    QComboBox {
        background: rgba(255, 255, 255, 0.07);
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 7px;
        padding: 6px 10px;
        font-size: 12px;
    }
    QComboBox:hover  { border-color: rgba(255, 255, 255, 0.28); }
    QComboBox:focus  { border-color: rgba(255, 255, 255, 0.35); }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid rgba(255, 255, 255, 0.55);
        width: 0;
        height: 0;
    }
    QComboBox QAbstractItemView {
        background: #1e1b3a;
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 6px;
        selection-background-color: rgba(99, 102, 241, 0.55);
        selection-color: white;
        outline: none;
        padding: 4px;
    }
    QComboBox QAbstractItemView::item {
        padding: 6px 10px;
        border-radius: 4px;
        min-height: 24px;
    }
    QComboBox QAbstractItemView::item:hover {
        background: rgba(255, 255, 255, 0.08);
    }

    QDoubleSpinBox, QSpinBox {
        background: rgba(255, 255, 255, 0.07);
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 7px;
        padding: 6px 10px;
        font-size: 12px;
    }
    QDoubleSpinBox:focus, QSpinBox:focus { border-color: rgba(255, 255, 255, 0.35); }
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QSpinBox::up-button,       QSpinBox::down-button {
        background: rgba(255, 255, 255, 0.08);
        border: none;
        width: 18px;
    }
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover,
    QSpinBox::up-button:hover,       QSpinBox::down-button:hover {
        background: rgba(255, 255, 255, 0.16);
    }

    QCheckBox { spacing: 8px; }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid rgba(255, 255, 255, 0.25);
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.05);
    }
    QCheckBox::indicator:checked {
        background: #6366f1;
        border-color: #6366f1;
    }

    QFormLayout QLabel { color: rgba(255, 255, 255, 0.60); }
"""

CARD_STYLE = (
    'background: rgba(255,255,255,0.05);'
    ' border: none;'
    ' border-radius: 8px;'
)


def paint_background(widget) -> None:
    """Paint the shared app gradient — call from a widget's paintEvent."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 0, widget.height())
    gradient.setColorAt(0.0, QColor('#0f0c29'))
    gradient.setColorAt(0.5, QColor('#302b63'))
    gradient.setColorAt(1.0, QColor('#24243e'))
    painter.fillRect(widget.rect(), QBrush(gradient))
