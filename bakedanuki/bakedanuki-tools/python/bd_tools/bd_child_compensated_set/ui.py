# coding: utf-8
"""子を維持する移動・回転の共通dockable Windowのlifecycle。"""

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
from .._dev.reopen_targets import CHILD_SET_CONTROL_ID
from .dock_window import (
    TRANSLATE_INITIAL_HEIGHT,
    TRANSLATE_INITIAL_WIDTH,
    ChildSetDockWindow,
    ChildSetTab,
)
from .types import ChildSetTarget

__all__ = ["WORKSPACE_CONTROL_NAME", "show", "restore", "close", "dispose"]


_controller = MayaDockableWindowController(
    ChildSetDockWindow,
    control_id=CHILD_SET_CONTROL_ID,
    restore=DockRestoreSpec(module="bd_tools.bd_child_compensated_set.ui"),
    dock_options=DockOptions(
        area=DockArea.RIGHT,
        allowed_area=DockArea.ALL,
        floating=True,
        initial_width=TRANSLATE_INITIAL_WIDTH,
        initial_height=TRANSLATE_INITIAL_HEIGHT,
        retain=False,
    ),
)
WORKSPACE_CONTROL_NAME: str = _controller.workspace_control_name


def show(
    tab: ChildSetTab | None = None,
    target: ChildSetTarget | None = None,
    anchor: qt.QPoint | None = None,
) -> ChildSetDockWindow:
    """共通Windowを表示し、タブ指定時は対応するタブを前面に出す。"""
    if tab not in (None, "translate", "rotation"):
        raise ValueError("移動または回転タブを指定してください")
    if tab is None and target is not None:
        raise ValueError("設定属性にはタブも指定してください")
    window = _controller.window
    if window is not None and qt.isValid(window) and window.is_disposed:
        _controller.dispose()
    first_open = not workspace_control.exists(
        WORKSPACE_CONTROL_NAME
    ) and not workspace_control.state_exists(WORKSPACE_CONTROL_NAME)
    window = _controller.show()
    window.register_reopen()
    if tab is not None:
        window.request_tab(
            tab, "translate" if tab == "translate" else target or "rotate"
        )
    if first_open and anchor is not None:
        window.set_initial_anchor(anchor)
    return window


def restore() -> ChildSetDockWindow:
    """MayaのuiScriptから保存済みworkspaceControlへ画面を接続する。"""
    window = _controller.restore()
    window.register_reopen()
    return window


def close() -> None:
    """移動・回転タブを含むworkspaceControlを閉じる。"""
    _controller.close()


def dispose() -> None:
    """WindowとMaya callbackを破棄し、reload前の参照を解放する。"""
    _controller.dispose()


register_reload_disposer(dispose)
