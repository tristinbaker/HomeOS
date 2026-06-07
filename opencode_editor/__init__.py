def register():
    from home_os_app.module_system import ModuleRegistry
    from .module import opencode_module
    ModuleRegistry.register(opencode_module)
