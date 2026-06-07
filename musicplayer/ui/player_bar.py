from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSlider, QLabel
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtMultimedia import QMediaPlayer


class _SeekSlider(QSlider):
    """QSlider that jumps to the clicked position instead of stepping by a page."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._seek_to(event.position().x())
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_to(event.position().x())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
        else:
            super().mouseReleaseEvent(event)

    def _seek_to(self, x: float):
        ratio = max(0.0, min(1.0, x / max(self.width(), 1)))
        value = round(ratio * self.maximum())
        self.setValue(value)
        self.sliderMoved.emit(value)


class PlayerBar(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setObjectName('playerBar')
        self.setFixedHeight(56)
        self.setStyleSheet("""
            #playerBar {
                background-color: rgba(10, 8, 35, 0.88);
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self.now_playing = QLabel('No track loaded')
        self.now_playing.setStyleSheet('font-weight: bold;')
        self.now_playing.setMinimumWidth(200)

        self.prev_btn = QPushButton('\u23EE')
        self.prev_btn.setToolTip('Previous')
        self.prev_btn.setFixedSize(36, 28)

        self.play_btn = QPushButton('\u25B6')
        self.play_btn.setToolTip('Play')
        self.play_btn.setFixedSize(36, 28)

        self.next_btn = QPushButton('\u23ED')
        self.next_btn.setToolTip('Next')
        self.next_btn.setFixedSize(36, 28)

        self.time_label = QLabel('0:00 / 0:00')
        self.time_label.setStyleSheet('font-family: monospace;')
        self.time_label.setMinimumWidth(100)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.seek_slider = _SeekSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setToolTip('Seek')

        self.vol_label = QLabel('\U0001F50A')
        self.vol_label.setToolTip('Volume')

        self.vol_slider = _SeekSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.controller.volume)
        self.vol_slider.setFixedWidth(100)
        self.vol_slider.setToolTip('Volume')

        self.lyrics_btn = QPushButton('♫')
        self.lyrics_btn.setToolTip('Show Lyrics')
        self.lyrics_btn.setCheckable(True)
        self.lyrics_btn.setFixedWidth(36)

        self.love_btn = QPushButton('♥')
        self.love_btn.setToolTip('Love on Last.FM')
        self.love_btn.setCheckable(True)
        self.love_btn.setFixedWidth(36)
        self.love_btn.setEnabled(False)

        self.lastfm_label = QLabel()
        self.lastfm_label.setStyleSheet('color: #d51007; font-size: 11px;')
        self.lastfm_label.setVisible(False)

        layout.addWidget(self.now_playing, 1)
        layout.addSpacing(12)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.next_btn)
        layout.addSpacing(8)
        layout.addWidget(self.time_label)
        layout.addWidget(self.seek_slider, 2)
        layout.addSpacing(8)
        layout.addWidget(self.vol_label)
        layout.addWidget(self.vol_slider)
        layout.addSpacing(8)
        layout.addWidget(self.lyrics_btn)
        layout.addWidget(self.love_btn)
        layout.addSpacing(4)
        layout.addWidget(self.lastfm_label)

        self.prev_btn.clicked.connect(self.controller.previous)
        self.play_btn.clicked.connect(self.controller.play_pause)
        self.next_btn.clicked.connect(self.controller.next)
        self.seek_slider.sliderMoved.connect(self.controller.seek)
        self.vol_slider.valueChanged.connect(self.controller.set_volume)

    def _connect_signals(self):
        self.controller.position_changed.connect(self._on_position_changed)
        self.controller.duration_changed.connect(self._on_duration_changed)
        self.controller.playback_state_changed.connect(self._on_playback_state_changed)
        self.controller.track_changed.connect(self._on_track_changed)
        self.controller.volume_changed.connect(self._on_volume_changed)

    @pyqtSlot(int)
    def _on_position_changed(self, pos):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(pos)
            self.seek_slider.blockSignals(False)
        self._update_time_label(pos, self.seek_slider.maximum())

    @pyqtSlot(int)
    def _on_duration_changed(self, dur):
        self.seek_slider.blockSignals(True)
        self.seek_slider.setRange(0, max(0, dur))
        self.seek_slider.blockSignals(False)
        self._update_time_label(self.seek_slider.value(), dur)

    def _update_time_label(self, pos, dur):
        self.time_label.setText(f"{self._fmt(pos // 1000)} / {self._fmt(dur // 1000)}")

    @staticmethod
    def _fmt(seconds):
        m = seconds // 60
        s = seconds % 60
        return f"{m}:{s:02d}"

    @pyqtSlot(object)
    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText('\u23F8')
            self.play_btn.setToolTip('Pause')
        else:
            self.play_btn.setText('\u25B6')
            self.play_btn.setToolTip('Play')

    @pyqtSlot(object)
    def _on_track_changed(self, track):
        text = f"{track.artist} \u2014 {track.title}" if track.title else track.artist
        self.now_playing.setText(text)

    @pyqtSlot(int)
    def _on_volume_changed(self, vol):
        self.vol_slider.blockSignals(True)
        self.vol_slider.setValue(vol)
        self.vol_slider.blockSignals(False)
        if vol == 0:
            self.vol_label.setText('\U0001F507')
        elif vol < 33:
            self.vol_label.setText('\U0001F508')
        elif vol < 66:
            self.vol_label.setText('\U0001F509')
        else:
            self.vol_label.setText('\U0001F50A')
