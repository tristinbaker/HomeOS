from home_os_app.module_system import ModuleRegistry
from .module import rommanager_module


def register():
    ModuleRegistry.register(rommanager_module)
