# coding: utf-8
"""現在姿勢を維持して回転属性の値を設定するツール。"""

from .dock_window import RotationSetDockWindow
from .types import RotationTarget
from .ui import (
    WORKSPACE_CONTROL_NAME,
    close,
    dispose,
    restore,
    show,
)

__all__ = [
    "RotationSetDockWindow",
    "RotationTarget",
    "WORKSPACE_CONTROL_NAME",
    "close",
    "dispose",
    "restore",
    "show",
]
