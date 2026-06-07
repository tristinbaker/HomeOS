from home_os_app.module_system import ModuleDef
from .ui.content_widget import MusicPlayerContent


def create_music_widget():
    return MusicPlayerContent()


music_module = ModuleDef(
    name='Music Player',
    icon='♫',
    color='#1d4ed8',
    create_widget=create_music_widget,
)
