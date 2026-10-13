# coding: utf-8
"""子の位置・姿勢を維持して移動や回転を設定するツール。"""

from .dock_window import ChildSetDockWindow, ChildSetTab
from .types import ChildSetTarget
from .ui import (
    WORKSPACE_CONTROL_NAME,
    close,
    dispose,
    restore,
    show,
)

__all__ = [
    "ChildSetDockWindow",
    "ChildSetTab",
    "ChildSetTarget",
    "WORKSPACE_CONTROL_NAME",
    "close",
    "dispose",
    "restore",
    "show",
]
