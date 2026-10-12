# coding: utf-8
"""現在姿勢を維持する回転設定Windowのlifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import MayaWindowController
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .controller import RotationDestination
from .rotation_set_window import RotationSetWindow

__all__ = ["show", "close", "dispose"]


_controller = MayaWindowController(RotationSetWindow)


def show(
    initial_target: RotationDestination,
    anchor: qt.QPoint | None = None,
) -> RotationSetWindow:
    """クリックした回転属性を設定先にしてWindowを表示する。"""
    if initial_target not in ("rotate", "rotateAxis", "jointOrient"):
        raise ValueError("回転属性を指定してください")
    window = _controller.window
    if window is not None and qt.isValid(window) and window.is_disposed:
        _controller.dispose()
    window = _controller.show()
    window.set_initial_target(initial_target)
    if anchor is not None:
        window.set_anchor_position(anchor)
    return window


def close() -> None:
    """姿勢維持の回転設定Windowを閉じる。"""
    _controller.close()


def dispose() -> None:
    """WindowとMaya callbackを破棄する。"""
    _controller.dispose()


register_reload_disposer(dispose)
