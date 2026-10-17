# coding: utf-8
"""選択ノードのbool・float系属性を入力するツール。"""

from importlib import import_module
from typing import TYPE_CHECKING, cast

from . import icon

if TYPE_CHECKING:
    from . import config
    from .ui import (
        ChannelBoxWindow,
        WORKSPACE_CONTROL_NAME,
        close,
        dispose,
        reset_layout,
        restore,
        show,
    )

__all__ = [
    "config",
    "ChannelBoxWindow",
    "WORKSPACE_CONTROL_NAME",
    "close",
    "dispose",
    "icon",
    "reset_layout",
    "restore",
    "show",
]


def __getattr__(name: str) -> object:
    """公開APIが参照された時点で必要なmoduleを読み込む。"""
    if name == "config":
        value: object = import_module(".config", __name__)
    elif name in __all__ and name != "icon":
        value = cast(object, getattr(import_module(".ui", __name__), name))
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # 一度解決した公開APIは通常のmodule属性として保持する
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """UIを読み込まずに公開APIを属性候補へ含める。"""
    return sorted(set(globals()) | set(__all__))
