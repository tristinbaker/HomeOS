from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput


class PlayerController(QObject):
    track_changed = pyqtSignal(object)
    playback_state_changed = pyqtSignal(object)
    position_changed = pyqtSignal(int)
    duration_changed = pyqtSignal(int)
    volume_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self._playlist = []
        self._current_index = -1
        self._volume = 50

        self.audio_output.setVolume(0.5)

        self.player.positionChanged.connect(self.position_changed.emit)
        self.player.durationChanged.connect(self.duration_changed.emit)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status)

    def set_playlist(self, tracks, start_index=0):
        self._playlist = list(tracks)
        self._current_index = start_index if self._playlist else -1
        if self._playlist:
            self._load_current()

    def play_track(self, track):
        self._playlist = [track]
        self._current_index = 0
        self._load_current()
        self.play()

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def stop(self):
        self.player.stop()

    def next(self):
        if self._current_index < len(self._playlist) - 1:
            self._current_index += 1
            self._load_current()
            self.play()
        else:
            self.stop()

    def previous(self):
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current()
            self.play()
        else:
            self.seek(0)

    def seek(self, position_ms):
        self.player.setPosition(position_ms)

    def set_volume(self, vol):
        self._volume = max(0, min(100, vol))
        self.audio_output.setVolume(self._volume / 100.0)
        self.volume_changed.emit(self._volume)

    def _load_current(self):
        if 0 <= self._current_index < len(self._playlist):
            track = self._playlist[self._current_index]
            self.player.setSource(QUrl.fromLocalFile(track.path))
            self.track_changed.emit(track)

    def _on_state_changed(self, state):
        self.playback_state_changed.emit(state)

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next()

    @property
    def volume(self):
        return self._volume

    @property
    def current_track(self):
        if 0 <= self._current_index < len(self._playlist):
            return self._playlist[self._current_index]
        return None

    @property
    def playback_state(self):
        return self.player.playbackState()
