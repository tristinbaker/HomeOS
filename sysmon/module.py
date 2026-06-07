from home_os_app.module_system import ModuleDef
from .ui.content_widget import SysMonContent

sysmon_module = ModuleDef(
    name='System Monitor',
    icon='∿',
    color='#0ea5e9',
    create_widget=SysMonContent,
)
