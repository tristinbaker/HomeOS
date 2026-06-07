import hashlib
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

_URL = 'https://ws.audioscrobbler.com/2.0/'


def _sign(params, secret):
    sig = ''.join(f"{k}{params[k]}" for k in sorted(params)) + secret
    return hashlib.md5(sig.encode()).hexdigest()


def _call(api_key, secret, params, post=False):
    p = dict(params)
    p['api_key'] = api_key
    p['api_sig'] = _sign(p, secret)
    p['format'] = 'json'
    if post:
        req = Request(_URL, data=urlencode(p).encode())
    else:
        req = Request(_URL + '?' + urlencode(p))
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())


class AuthSignals(QObject):
    token_ready = pyqtSignal(str, str)    # token, auth_url
    session_ready = pyqtSignal(str, str)  # session_key, username
    error = pyqtSignal(str)


class _AuthTask(QRunnable):
    def __init__(self, api_key, secret, signals, token=None):
        super().__init__()
        self.setAutoDelete(True)
        self._api_key = api_key
        self._secret = secret
        self._signals = signals
        self._token = token

    def run(self):
        try:
            if self._token is None:
                data = _call(self._api_key, self._secret, {'method': 'auth.getToken'})
                token = data['token']
                url = f'https://www.last.fm/api/auth/?api_key={self._api_key}&token={token}'
                self._signals.token_ready.emit(token, url)
            else:
                data = _call(self._api_key, self._secret,
                             {'method': 'auth.getSession', 'token': self._token})
                sess = data['session']
                self._signals.session_ready.emit(sess['key'], sess['name'])
        except Exception as e:
            self._signals.error.emit(str(e))


class _FireTask(QRunnable):
    def __init__(self, api_key, secret, params):
        super().__init__()
        self.setAutoDelete(True)
        self._api_key = api_key
        self._secret = secret
        self._params = params

    def run(self):
        try:
            _call(self._api_key, self._secret, self._params, post=True)
        except Exception:
            pass


class LastFMClient:
    def __init__(self):
        self._api_key: str = ''
        self._secret: str = ''
        self._sk: str = ''
        self._username: str = ''

    @property
    def has_api_credentials(self) -> bool:
        return bool(self._api_key and self._secret)

    @property
    def connected(self) -> bool:
        return bool(self._sk) and self.has_api_credentials

    @property
    def username(self):
        return self._username

    def load_api_credentials(self, api_key: str, secret: str) -> None:
        self._api_key = api_key
        self._secret = secret

    def clear_api_credentials(self) -> None:
        self._api_key = ''
        self._secret = ''

    def load_session(self, sk, username):
        self._sk = sk
        self._username = username

    def clear_session(self):
        self._sk = ''
        self._username = ''

    def start_auth(self, signals):
        QThreadPool.globalInstance().start(_AuthTask(self._api_key, self._secret, signals))

    def finish_auth(self, token, signals):
        QThreadPool.globalInstance().start(
            _AuthTask(self._api_key, self._secret, signals, token=token)
        )

    def _fire(self, params):
        QThreadPool.globalInstance().start(_FireTask(self._api_key, self._secret, params))

    def now_playing(self, track):
        if not self.connected or not track:
            return
        self._fire({
            'method': 'track.updateNowPlaying', 'sk': self._sk,
            'artist': track.artist or '', 'track': track.title or '',
            'album': track.album or '', 'duration': str(int(track.duration)),
        })

    def scrobble(self, track, timestamp):
        if not self.connected or not track:
            return
        self._fire({
            'method': 'track.scrobble', 'sk': self._sk,
            'artist': track.artist or '', 'track': track.title or '',
            'album': track.album or '', 'timestamp': str(int(timestamp)),
            'duration': str(int(track.duration)),
        })

    def love(self, track):
        if not self.connected or not track:
            return
        self._fire({
            'method': 'track.love', 'sk': self._sk,
            'artist': track.artist or '', 'track': track.title or '',
        })

    def unlove(self, track):
        if not self.connected or not track:
            return
        self._fire({
            'method': 'track.unlove', 'sk': self._sk,
            'artist': track.artist or '', 'track': track.title or '',
        })
