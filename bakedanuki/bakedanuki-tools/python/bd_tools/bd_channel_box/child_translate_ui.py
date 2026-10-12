# coding: utf-8
"""子の座標を維持する移動設定Windowのlifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import MayaWindowController
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .child_compensated_set_window import ChildCompensatedSetWindow

__all__ = ["show", "close", "dispose"]


def _create_window(parent: qt.QWidget | None) -> ChildCompensatedSetWindow:
    """移動設定用の独立した通常Windowを作る。"""
    return ChildCompensatedSetWindow(parent, initial_target="translate")


_controller = MayaWindowController(_create_window)


def show(anchor: qt.QPoint | None = None) -> ChildCompensatedSetWindow:
    """現在選択に追従する移動設定Windowを表示する。"""
    window = _controller.window
    if window is not None and qt.isValid(window) and window.is_disposed:
        _controller.dispose()
    window = _controller.show()
    window.set_initial_target("translate")
    if anchor is not None:
        window.set_anchor_position(anchor)
    return window


def close() -> None:
    """移動設定Windowを閉じる。"""
    _controller.close()


def dispose() -> None:
    """WindowとMaya callbackを破棄する。"""
    _controller.dispose()


register_reload_disposer(dispose)
