# coding: utf-8
"""子の位置・姿勢を維持して移動や回転を設定するツール。"""

from importlib import import_module
from typing import TYPE_CHECKING, cast

from . import icon
from .types import ChildSetTarget

if TYPE_CHECKING:
    from .dock_window import ChildSetDockWindow, ChildSetTab
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
    "icon",
    "restore",
    "show",
]


def __getattr__(name: str) -> object:
    """公開APIが参照された時点で必要なmoduleを読み込む。"""
    if name in {"ChildSetDockWindow", "ChildSetTab"}:
        module_name = ".dock_window"
    elif name in {
        "WORKSPACE_CONTROL_NAME",
        "close",
        "dispose",
        "restore",
        "show",
    }:
        module_name = ".ui"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # 型検査時の明示的な公開型を保ち、runtimeだけ遅延解決する
    value = cast(object, getattr(import_module(module_name, __name__), name))
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """UIを読み込まずに公開APIを属性候補へ含める。"""
    return sorted(set(globals()) | set(__all__))
