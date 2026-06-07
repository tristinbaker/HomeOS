from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel, QMenuBar,
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence

from .module_system import ModuleDef, ModuleRegistry
from .home_screen import HomeScreen


class HomeOSWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('HomeOS')
        self.resize(1024, 700)

        self._settings = QSettings('HomeOS', 'HomeOS')
        self._module_tabs: dict[str, int] = {}
        self._module_widgets: dict[str, QWidget] = {}
        self._current_module_menus: list = []

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self._tabs)

        modules = ModuleRegistry.all()

        self._home = HomeScreen(modules)
        self._home.module_activated.connect(self._open_module)

        self._home_idx = self._tabs.addTab(self._home, '\U0001F3E0 Home')
        # Connect after home tab is added so _on_tab_changed can safely check _home_idx
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().setTabButton(
            self._home_idx,
            self._tabs.tabBar().ButtonPosition.RightSide,
            None,
        )
        self._tabs.tabBar().setTabButton(
            self._home_idx,
            self._tabs.tabBar().ButtonPosition.LeftSide,
            None,
        )

        self._setup_menus()

        geom = self._settings.value('window_geometry')
        if geom:
            self.restoreGeometry(geom)

    def _setup_menus(self):
        file_menu = self.menuBar().addMenu('&File')

        quit_action = QAction('&Quit', self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _clear_module_menus(self):
        for menu in self._current_module_menus:
            self.menuBar().removeAction(menu.menuAction())
            menu.deleteLater()
        self._current_module_menus.clear()

    def _open_module(self, module_def: ModuleDef):
        key = module_def.name
        if key in self._module_tabs:
            idx = self._module_tabs[key]
            self._tabs.setCurrentIndex(idx)
            return

        widget = module_def.create_widget()
        self._module_widgets[key] = widget

        icon = module_def.icon or ''
        idx = self._tabs.addTab(widget, f'{icon} {module_def.name}')
        self._module_tabs[key] = idx
        self._tabs.setCurrentIndex(idx)

    def _close_tab(self, idx):
        if idx == self._home_idx:
            return

        widget = self._tabs.widget(idx)
        if hasattr(widget, 'cleanup'):
            widget.cleanup()

        for key, tab_idx in list(self._module_tabs.items()):
            if tab_idx == idx:
                del self._module_tabs[key]
                self._module_widgets.pop(key, None)
                break

        self._tabs.removeTab(idx)

        for key in list(self._module_tabs.keys()):
            ti = self._module_tabs[key]
            if ti > idx:
                self._module_tabs[key] = ti - 1

    def _install_module_menus(self, widget, module_name: str = ''):
        self._clear_module_menus()
        if hasattr(widget, 'menus'):
            for menu in widget.menus(self):
                if menu.title().replace('&', '').strip().lower() == 'file' and module_name:
                    menu.setTitle(f'&{module_name}')
                self.menuBar().addMenu(menu)
                self._current_module_menus.append(menu)

    def _on_tab_changed(self, idx):
        self._clear_module_menus()
        if idx == self._home_idx:
            return
        widget = self._tabs.widget(idx)
        module_name = next(
            (name for name, tab_idx in self._module_tabs.items() if tab_idx == idx),
            '',
        )
        self._install_module_menus(widget, module_name)

    def closeEvent(self, event):
        self._settings.setValue('window_geometry', self.saveGeometry())
        for key, widget in self._module_widgets.items():
            if hasattr(widget, 'cleanup'):
                widget.cleanup()
        super().closeEvent(event)
