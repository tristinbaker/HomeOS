def register():
    from home_os_app.module_system import ModuleRegistry
    from .module import music_module
    ModuleRegistry.register(music_module)
