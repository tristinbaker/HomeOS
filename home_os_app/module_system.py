from dataclasses import dataclass, field
from typing import Callable, Optional

from PyQt6.QtWidgets import QWidget


@dataclass
class ModuleDef:
    name: str
    icon: str
    color: str
    create_widget: Callable[[], QWidget]


class ModuleRegistry:
    _modules: list[ModuleDef] = []

    @classmethod
    def register(cls, module: ModuleDef) -> None:
        cls._modules.append(module)

    @classmethod
    def all(cls) -> list[ModuleDef]:
        return list(cls._modules)

    @classmethod
    def clear(cls) -> None:
        cls._modules.clear()
