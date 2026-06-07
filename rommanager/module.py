from home_os_app.module_system import ModuleDef
from .ui.content_widget import ROMManagerContent

rommanager_module = ModuleDef(
    name='ROM Manager',
    icon='⊞',
    color='#7c3aed',
    create_widget=ROMManagerContent,
)
