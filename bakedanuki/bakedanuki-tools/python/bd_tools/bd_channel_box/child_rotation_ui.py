# coding: utf-8
"""子を維持する回転設定Windowのlifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import MayaWindowController
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .child_compensated_set_window import ChildCompensatedSetWindow
from .controller import RoundTransformKind

__all__ = ["show", "close", "dispose"]


def _create_window(parent: qt.QWidget | None) -> ChildCompensatedSetWindow:
    """回転設定用の独立した通常Windowを作る。"""
    return ChildCompensatedSetWindow(parent, initial_target="rotate")


_controller = MayaWindowController(_create_window)


def show(
    initial_target: RoundTransformKind,
    anchor: qt.QPoint | None = None,
) -> ChildCompensatedSetWindow:
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
    """回転設定Windowを閉じる。"""
    _controller.close()


def dispose() -> None:
    """WindowとMaya callbackを破棄する。"""
    _controller.dispose()


register_reload_disposer(dispose)
