from PyQt6.QtCore import (
    Qt, QDateTime, QEasingCurve, QPropertyAnimation, QRectF, QSettings,
    QSize, QThread, QTimer, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .flow_layout import FlowLayout
from .module_system import ModuleDef
from .weather import fetch_weather, geocode, wmo_desc, wmo_emoji


_CARD_SIZE = QSize(135, 150)


def _hex_lighter(hex_color, factor):
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f'#{r:02x}{g:02x}{b:02x}'


# ── Weather workers ───────────────────────────────────────────────────────────

class _WeatherFetchWorker(QThread):
    finished = pyqtSignal(float, float, int)  # temp_f, feels_like_f, weather_code
    error    = pyqtSignal(str)

    def __init__(self, lat: float, lon: float, parent=None) -> None:
        super().__init__(parent)
        self._lat = lat
        self._lon = lon

    def run(self) -> None:
        try:
            w = fetch_weather(self._lat, self._lon)
            self.finished.emit(w['temp_f'], w['feels_like_f'], w['weather_code'])
        except Exception as exc:
            self.error.emit(str(exc))


class _GeocodeWorker(QThread):
    finished = pyqtSignal(float, float, str)  # lat, lon, display_name
    error    = pyqtSignal(str)

    def __init__(self, city: str, parent=None) -> None:
        super().__init__(parent)
        self._city = city

    def run(self) -> None:
        try:
            lat, lon, name = geocode(self._city)
            self.finished.emit(lat, lon, name)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Location settings dialog ──────────────────────────────────────────────────

class _LocationDialog(QDialog):
    location_saved = pyqtSignal(float, float, str)

    def __init__(self, current_city: str = '', parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Weather Location')
        self.setModal(True)
        self.setFixedWidth(340)
        self._worker: _GeocodeWorker | None = None

        from .theme import THEME_QSS
        self.setStyleSheet(THEME_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        lbl = QLabel('Enter your city name')
        lbl.setStyleSheet('color: rgba(255,255,255,0.60); background: transparent;')

        self._input = QLineEdit()
        self._input.setPlaceholderText('e.g. Atlanta')
        self._input.setText(current_city)
        self._input.returnPressed.connect(self._save)

        self._error_lbl = QLabel('')
        self._error_lbl.setStyleSheet('color: #f87171; background: transparent; font-size: 10px;')
        self._error_lbl.setWordWrap(True)
        self._error_lbl.hide()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        cancel = QPushButton('Cancel')
        cancel.setFixedHeight(34)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)

        self._save_btn = QPushButton('Save')
        self._save_btn.setFixedHeight(34)
        self._save_btn.setDefault(True)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._save)

        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._save_btn)

        layout.addWidget(lbl)
        layout.addWidget(self._input)
        layout.addWidget(self._error_lbl)
        layout.addSpacing(4)
        layout.addLayout(btn_row)

    def _save(self) -> None:
        city = self._input.text().strip()
        if not city:
            return
        self._save_btn.setEnabled(False)
        self._save_btn.setText('Locating…')
        self._error_lbl.hide()

        self._worker = _GeocodeWorker(city, self)
        self._worker.finished.connect(self._on_geocoded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_geocoded(self, lat: float, lon: float, name: str) -> None:
        self.location_saved.emit(lat, lon, name)
        self.accept()

    def _on_error(self, msg: str) -> None:
        self._save_btn.setEnabled(True)
        self._save_btn.setText('Save')
        self._error_lbl.setText(f'Could not find location: {msg}')
        self._error_lbl.show()


# ── Weather widget ────────────────────────────────────────────────────────────

class _WeatherWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._settings = QSettings('HomeOS', 'HomeOS')
        self._fetch_worker: _WeatherFetchWorker | None = None

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(30 * 60 * 1000)
        self._refresh_timer.timeout.connect(self._fetch)

        self._setup_ui()
        self._load_and_fetch()

    def _setup_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main row: emoji + temp + description + gear
        main_row = QHBoxLayout()
        main_row.setSpacing(8)
        main_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._emoji_lbl = QLabel('')
        ef = QFont()
        ef.setPointSize(22)
        self._emoji_lbl.setFont(ef)
        self._emoji_lbl.setStyleSheet('background: transparent; color: white;')

        self._temp_lbl = QLabel('')
        tf = QFont()
        tf.setPointSize(22)
        tf.setWeight(QFont.Weight.Light)
        self._temp_lbl.setFont(tf)
        self._temp_lbl.setStyleSheet('background: transparent; color: white;')

        self._desc_lbl = QLabel('')
        df = QFont()
        df.setPointSize(12)
        self._desc_lbl.setFont(df)
        self._desc_lbl.setStyleSheet('background: transparent; color: rgba(255,255,255,0.65);')

        main_row.addWidget(self._emoji_lbl)
        main_row.addWidget(self._temp_lbl)
        main_row.addWidget(self._desc_lbl)

        # Location row
        loc_row = QHBoxLayout()
        loc_row.setSpacing(8)
        loc_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._loc_lbl = QLabel('')
        lf = QFont()
        lf.setPointSize(10)
        self._loc_lbl.setFont(lf)
        self._loc_lbl.setStyleSheet('background: transparent; color: rgba(255,255,255,0.40);')

        self._gear_btn = QPushButton('⚙')
        self._gear_btn.setFixedSize(22, 22)
        self._gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gear_btn.setToolTip('Set weather location')
        self._gear_btn.setStyleSheet(
            'QPushButton { background: transparent; border: none; color: rgba(255,255,255,0.30);'
            ' font-size: 13px; }'
            ' QPushButton:hover { color: rgba(255,255,255,0.70); }'
        )
        self._gear_btn.clicked.connect(self._open_settings)

        loc_row.addWidget(self._loc_lbl)
        loc_row.addWidget(self._gear_btn)

        # "No location" prompt shown when not configured
        self._prompt_btn = QPushButton('⚙  Set weather location')
        self._prompt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prompt_btn.setStyleSheet(
            'QPushButton { background: transparent; border: none;'
            ' color: rgba(255,255,255,0.28); font-size: 11px; }'
            ' QPushButton:hover { color: rgba(255,255,255,0.60); }'
        )
        self._prompt_btn.clicked.connect(self._open_settings)

        v.addLayout(main_row)
        v.addLayout(loc_row)
        v.addWidget(self._prompt_btn, 0, Qt.AlignmentFlag.AlignCenter)

    def _load_and_fetch(self) -> None:
        lat = self._settings.value('weather_lat', None)
        lon = self._settings.value('weather_lon', None)
        city = self._settings.value('weather_city', '')

        if lat is not None and lon is not None:
            self._show_configured(city)
            self._fetch()
            self._refresh_timer.start()
        else:
            self._show_unconfigured()

    def _show_configured(self, city: str) -> None:
        self._prompt_btn.hide()
        self._emoji_lbl.show()
        self._temp_lbl.show()
        self._desc_lbl.show()
        self._loc_lbl.show()
        self._gear_btn.show()
        self._loc_lbl.setText(city)
        if not self._temp_lbl.text():
            self._temp_lbl.setText('—')

    def _show_unconfigured(self) -> None:
        self._prompt_btn.show()
        self._emoji_lbl.hide()
        self._temp_lbl.hide()
        self._desc_lbl.hide()
        self._loc_lbl.hide()
        self._gear_btn.hide()

    def _fetch(self) -> None:
        lat = self._settings.value('weather_lat', None)
        lon = self._settings.value('weather_lon', None)
        if lat is None or lon is None:
            return
        if self._fetch_worker and self._fetch_worker.isRunning():
            return
        self._fetch_worker = _WeatherFetchWorker(float(lat), float(lon), self)
        self._fetch_worker.finished.connect(self._on_weather)
        self._fetch_worker.start()

    def _on_weather(self, temp_f: float, feels_like_f: float, code: int) -> None:
        self._emoji_lbl.setText(wmo_emoji(code))
        self._temp_lbl.setText(f'{round(temp_f)}°F')
        city = self._settings.value('weather_city', '')
        self._desc_lbl.setText(wmo_desc(code))
        self._loc_lbl.setText(f'{city}  ·  Feels like {round(feels_like_f)}°F')

    def _open_settings(self) -> None:
        current_city = self._settings.value('weather_city', '')
        dlg = _LocationDialog(current_city, self)
        dlg.location_saved.connect(self._on_location_saved)
        dlg.exec()

    def _on_location_saved(self, lat: float, lon: float, name: str) -> None:
        self._settings.setValue('weather_lat', lat)
        self._settings.setValue('weather_lon', lon)
        self._settings.setValue('weather_city', name)
        self._show_configured(name)
        self._fetch()
        self._refresh_timer.start()


# ── Clock ─────────────────────────────────────────────────────────────────────

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


# ── Module card ───────────────────────────────────────────────────────────────

class ModuleCard(QWidget):
    clicked = pyqtSignal(ModuleDef)

    def __init__(self, module_def: ModuleDef, parent=None):
        super().__init__(parent)
        self._module_def = module_def
        self.setFixedSize(_CARD_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self._sheen_pos = -0.4

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

    @pyqtProperty(float)
    def sheen_pos(self):
        return self._sheen_pos

    @sheen_pos.setter
    def sheen_pos(self, value):
        self._sheen_pos = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)

        clip = QPainterPath()
        clip.addRoundedRect(rect, 16, 16)
        painter.setClipPath(clip)

        light_factor = 0.38 if self._hovered else 0.26
        dark_factor  = 0.12 if self._hovered else 0.0
        top_color    = QColor(_hex_lighter(self._module_def.color, light_factor))
        bot_color    = QColor(_hex_lighter(self._module_def.color, dark_factor))

        bg_grad = QLinearGradient(0, 0, 0, h)
        bg_grad.setColorAt(0, top_color)
        bg_grad.setColorAt(1, bot_color)
        painter.fillPath(clip, QBrush(bg_grad))

        cx = self._sheen_pos * w
        sw = w * 0.55
        sheen_grad = QLinearGradient(cx - sw, 0, cx + sw, h)
        sheen_grad.setColorAt(0.0,  QColor(255, 255, 255, 0))
        sheen_grad.setColorAt(0.35, QColor(255, 255, 255, 0))
        sheen_grad.setColorAt(0.5,  QColor(255, 255, 255, 52))
        sheen_grad.setColorAt(0.65, QColor(255, 255, 255, 0))
        sheen_grad.setColorAt(1.0,  QColor(255, 255, 255, 0))
        painter.fillPath(clip, QBrush(sheen_grad))

        painter.setClipping(False)
        border_alpha = 160 if self._hovered else 60
        border_width = 2.0
        pen = QPen(QColor(255, 255, 255, border_alpha), border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = border_width / 2
        painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), 15, 15)

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


# ── Home screen ───────────────────────────────────────────────────────────────

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
        weather = _WeatherWidget()

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
        layout.addSpacing(16)
        layout.addWidget(weather, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(24)
        layout.addWidget(divider, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(28)
        layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(44)
        layout.addWidget(flow_wrapper)
        layout.addStretch(2)

    def set_modules(self, modules: list[ModuleDef]):
        self._modules = list(modules)
        self._build_grid()
