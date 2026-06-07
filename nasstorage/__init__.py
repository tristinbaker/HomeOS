from .module import nasstorage_module
from home_os_app.module_system import ModuleRegistry


def register() -> None:
    ModuleRegistry.register(nasstorage_module)
