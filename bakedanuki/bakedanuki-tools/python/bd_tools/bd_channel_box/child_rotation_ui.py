# coding: utf-8
"""子を維持する共通Windowの回転タブを開く入口。"""

from __future__ import annotations

from bd_util.ui import qt

from . import child_set_ui
from .child_set_dock_window import ChildSetDockWindow
from .controller import RoundTransformKind

__all__ = ["show", "close", "dispose"]


def show(
    initial_target: RoundTransformKind,
    anchor: qt.QPoint | None = None,
) -> ChildSetDockWindow:
    """クリックした回転属性を設定先にして共通Windowを表示する。"""
    if initial_target not in ("rotate", "rotateAxis", "jointOrient"):
        raise ValueError("回転属性を指定してください")
    return child_set_ui.show("rotation", initial_target, anchor)


def close() -> None:
    """移動・回転の共通Windowを閉じる。"""
    child_set_ui.close()


def dispose() -> None:
    """移動・回転の共通Windowと監視を破棄する。"""
    child_set_ui.dispose()
