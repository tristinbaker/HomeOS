from home_os_app.module_system import ModuleDef
from .ui.content_widget import NASStorageContent


nasstorage_module = ModuleDef(
    name='Storage Analyzer',
    icon='⛁',
    color='#0369a1',
    create_widget=NASStorageContent,
)
