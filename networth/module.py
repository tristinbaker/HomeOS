from home_os_app.module_system import ModuleDef
from .ui.content_widget import NetWorthContent


def _create():
    return NetWorthContent()


networth_module = ModuleDef(
    name='Net Worth',
    icon='$',
    color='#15803d',
    create_widget=_create,
)
