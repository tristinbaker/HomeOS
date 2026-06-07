from home_os_app.module_system import ModuleRegistry
from .module import rssreader_module


def register():
    ModuleRegistry.register(rssreader_module)
