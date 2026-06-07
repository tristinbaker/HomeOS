from .module import networth_module
from home_os_app.module_system import ModuleRegistry


def register() -> None:
    ModuleRegistry.register(networth_module)
