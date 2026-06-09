from home_os_app.module_system import ModuleRegistry
from .module import library_module


def register():
    ModuleRegistry.register(library_module)
