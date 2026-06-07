from home_os_app.module_system import ModuleDef
from .ui.content_widget import OpenCodeEditorContent


def create_opencode_widget():
    return OpenCodeEditorContent()


opencode_module = ModuleDef(
    name='OpenCode Editor',
    icon='⟡',
    color='#7c3aed',
    create_widget=create_opencode_widget,
)
