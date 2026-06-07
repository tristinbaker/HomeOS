from home_os_app.module_system import ModuleRegistry
from .module import sysmon_module


def register():
    ModuleRegistry.register(sysmon_module)
