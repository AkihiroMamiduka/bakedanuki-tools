# coding: utf-8
"""現在姿勢を維持する回転設定のdockable Window lifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import (
    DockArea,
    DockOptions,
    DockRestoreSpec,
    MayaDockableWindowController,
)
from bd_util.maya.ui.dock import workspace_control
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .._dev.reopen_targets import ROTATION_SET_CONTROL_ID
from .dock_window import RotationSetDockWindow
from .types import RotationTarget
from .window import INITIAL_HEIGHT, INITIAL_WIDTH

__all__ = ["WORKSPACE_CONTROL_NAME", "show", "restore", "close", "dispose"]


_controller = MayaDockableWindowController(
    RotationSetDockWindow,
    control_id=ROTATION_SET_CONTROL_ID,
    restore=DockRestoreSpec(module="bd_tools.bd_rotation_preserving_pose.ui"),
    dock_options=DockOptions(
        area=DockArea.RIGHT,
        allowed_area=DockArea.ALL,
        floating=True,
        initial_width=INITIAL_WIDTH,
        initial_height=INITIAL_HEIGHT,
        retain=False,
    ),
)
WORKSPACE_CONTROL_NAME: str = _controller.workspace_control_name


def show(
    initial_target: RotationTarget | None = None,
    anchor: qt.QPoint | None = None,
) -> RotationSetDockWindow:
    """設定先の指定を反映し、保存済みのMaya配置でWindowを表示する。"""
    if initial_target not in (None, "rotate", "rotateAxis", "jointOrient"):
        raise ValueError("回転属性を指定してください")
    window = _controller.window
    if window is not None and qt.isValid(window) and window.is_disposed:
        _controller.dispose()
    first_open = not workspace_control.exists(
        WORKSPACE_CONTROL_NAME
    ) and not workspace_control.state_exists(WORKSPACE_CONTROL_NAME)
    window = _controller.show()
    window.register_reopen()
    if initial_target is not None:
        window.request_target(initial_target)
    else:
        window.rotation_page.refresh()
    if first_open and anchor is not None:
        window.set_initial_anchor(anchor)
    return window


def restore() -> RotationSetDockWindow:
    """MayaのuiScriptから保存済みworkspaceControlへ画面を接続する。"""
    window = _controller.restore()
    window.register_reopen()
    return window


def close() -> None:
    """姿勢維持のworkspaceControlを閉じる。"""
    _controller.close()


def dispose() -> None:
    """WindowとMaya callbackを破棄し、reload前の参照を解放する。"""
    _controller.dispose()


register_reload_disposer(dispose)
