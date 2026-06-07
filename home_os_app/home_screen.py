from PyQt6.QtCore import (
    Qt, QDateTime, QEasingCurve, QPropertyAnimation, QRectF, QSize, QTimer,
    pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from .flow_layout import FlowLayout
from .module_system import ModuleDef


_CARD_SIZE = QSize(135, 150)


def _hex_lighter(hex_color, factor):
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f'#{r:02x}{g:02x}{b:02x}'


class _ClockWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._time_label = QLabel()
        time_font = QFont()
        time_font.setPointSize(56)
        time_font.setWeight(QFont.Weight.Light)
        self._time_label.setFont(time_font)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_label.setStyleSheet('color: white; background: transparent;')

        self._date_label = QLabel()
        date_font = QFont()
        date_font.setPointSize(15)
        self._date_label.setFont(date_font)
        self._date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._date_label.setStyleSheet('color: rgba(255,255,255,0.6); background: transparent;')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._time_label)
        layout.addWidget(self._date_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        now = QDateTime.currentDateTime()
        self._time_label.setText(now.toString('h:mm AP'))
        self._date_label.setText(now.toString('dddd, MMMM d'))


class ModuleCard(QWidget):
    clicked = pyqtSignal(ModuleDef)

    def __init__(self, module_def: ModuleDef, parent=None):
        super().__init__(parent)
        self._module_def = module_def
        self.setFixedSize(_CARD_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self._sheen_pos = -0.4  # normalised x position of sheen centre (0–1)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(20)
        self._shadow.setColor(QColor(0, 0, 0, 100))
        self._shadow.setOffset(0, 6)
        self.setGraphicsEffect(self._shadow)

        self._anim = QPropertyAnimation(self, b'sheen_pos', self)
        self._anim.setDuration(600)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        icon_label = QLabel(module_def.icon)
        icon_font = QFont()
        icon_font.setPointSize(34)
        icon_label.setFont(icon_font)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon_label.setStyleSheet('background: transparent; color: white;')

        name_label = QLabel(module_def.name)
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        name_label.setStyleSheet('background: transparent; color: white;')

        layout.addStretch()
        layout.addWidget(icon_label)
        layout.addWidget(name_label)
        layout.addStretch()

    # --- sheen property (animated) ---

    @pyqtProperty(float)
    def sheen_pos(self):
        return self._sheen_pos

    @sheen_pos.setter
    def sheen_pos(self, value):
        self._sheen_pos = value
        self.update()

    # --- painting ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)

        # Clip everything to the rounded card shape
        clip = QPainterPath()
        clip.addRoundedRect(rect, 16, 16)
        painter.setClipPath(clip)

        # Background gradient (slightly lighter on hover)
        light_factor = 0.38 if self._hovered else 0.26
        dark_factor  = 0.12 if self._hovered else 0.0
        top_color    = QColor(_hex_lighter(self._module_def.color, light_factor))
        bot_color    = QColor(_hex_lighter(self._module_def.color, dark_factor))

        bg_grad = QLinearGradient(0, 0, 0, h)
        bg_grad.setColorAt(0, top_color)
        bg_grad.setColorAt(1, bot_color)
        painter.fillPath(clip, QBrush(bg_grad))

        # Sheen — diagonal stripe that sweeps left→right on hover
        cx = self._sheen_pos * w
        sw = w * 0.55  # half-width of the sheen band
        # Slightly diagonal: gradient goes from (cx-sw, 0) to (cx+sw, h)
        sheen_grad = QLinearGradient(cx - sw, 0, cx + sw, h)
        sheen_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        sheen_grad.setColorAt(0.35, QColor(255, 255, 255, 0))
        sheen_grad.setColorAt(0.5, QColor(255, 255, 255, 52))
        sheen_grad.setColorAt(0.65, QColor(255, 255, 255, 0))
        sheen_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(clip, QBrush(sheen_grad))

        # Border — remove clip so stroke sits exactly on the edge
        painter.setClipping(False)
        border_alpha = 160 if self._hovered else 60
        border_width = 2.0
        pen = QPen(QColor(255, 255, 255, border_alpha), border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Inset by half the pen width so it doesn't get clipped
        inset = border_width / 2
        painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), 15, 15)

    # --- interaction ---

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._module_def)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        self._anim.stop()
        self._anim.setStartValue(-0.4)
        self._anim.setEndValue(1.4)
        self._anim.start()
        self._shadow.setBlurRadius(32)
        self._shadow.setColor(QColor(0, 0, 0, 160))
        self._shadow.setOffset(0, 8)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._anim.stop()
        self._sheen_pos = -0.4
        self.update()
        self._shadow.setBlurRadius(20)
        self._shadow.setColor(QColor(0, 0, 0, 100))
        self._shadow.setOffset(0, 6)
        super().leaveEvent(event)


class HomeScreen(QWidget):
    module_activated = pyqtSignal(ModuleDef)

    def __init__(self, modules: list[ModuleDef] | None = None, parent=None):
        super().__init__(parent)
        self._modules = modules or []

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.frameShape().NoFrame)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        scroll.viewport().setAutoFillBackground(False)

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet('background: transparent;')
        self._scroll_content.setAutoFillBackground(False)

        scroll.setWidget(self._scroll_content)
        outer_layout.addWidget(scroll)

        self._build_grid()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor('#0f0c29'))
        gradient.setColorAt(0.5, QColor('#302b63'))
        gradient.setColorAt(1.0, QColor('#24243e'))
        painter.fillRect(self.rect(), QBrush(gradient))

    def _build_grid(self):
        layout = QVBoxLayout(self._scroll_content)
        layout.setContentsMargins(32, 56, 32, 56)
        layout.setSpacing(0)

        clock = _ClockWidget()

        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setFixedWidth(280)
        divider.setStyleSheet('background: rgba(255,255,255,0.12);')

        subtitle = QLabel('Select a module to get started')
        subtitle_font = QFont()
        subtitle_font.setPointSize(13)
        subtitle.setFont(subtitle_font)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet('color: rgba(255,255,255,0.45); background: transparent;')

        flow = FlowLayout(spacing=20)
        flow_wrapper = QWidget()
        flow_wrapper.setLayout(flow)
        flow_wrapper.setStyleSheet('background: transparent;')

        for mod in self._modules:
            card = ModuleCard(mod)
            card.clicked.connect(self.module_activated.emit)
            flow.addWidget(card)
            flow_wrapper.setMinimumWidth(_CARD_SIZE.width())

        layout.addStretch(1)
        layout.addWidget(clock, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(28)
        layout.addWidget(divider, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(28)
        layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(44)
        layout.addWidget(flow_wrapper)
        layout.addStretch(2)

    def set_modules(self, modules: list[ModuleDef]):
        self._modules = list(modules)
        self._build_grid()
