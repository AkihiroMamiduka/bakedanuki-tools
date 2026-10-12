# coding: utf-8
"""子を維持する共通Windowの移動タブを開く入口。"""

from __future__ import annotations

from bd_util.ui import qt

from . import child_set_ui
from .child_set_dock_window import ChildSetDockWindow

__all__ = ["show", "close", "dispose"]


def show(anchor: qt.QPoint | None = None) -> ChildSetDockWindow:
    """現在選択に追従する共通Windowの移動タブを表示する。"""
    return child_set_ui.show("translate", "translate", anchor)


def close() -> None:
    """移動・回転の共通Windowを閉じる。"""
    child_set_ui.close()


def dispose() -> None:
    """移動・回転の共通Windowと監視を破棄する。"""
    child_set_ui.dispose()
