from home_os_app.module_system import ModuleDef
from .ui.content_widget import RSSReaderContent


rssreader_module = ModuleDef(
    name='RSS Reader',
    icon='≡',
    color='#b45309',
    create_widget=RSSReaderContent,
)
