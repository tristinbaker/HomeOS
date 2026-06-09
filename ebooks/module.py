from home_os_app.module_system import ModuleDef
from .ui.content_widget import LibraryContent

library_module = ModuleDef(
    name='Library',
    icon='◫',
    color='#0369a1',
    create_widget=LibraryContent,
)
