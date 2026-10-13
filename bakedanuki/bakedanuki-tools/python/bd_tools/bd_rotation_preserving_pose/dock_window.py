# coding: utf-8
"""姿勢を維持する回転設定画面をMayaのdockへ接続する。"""

from __future__ import annotations

from typing import cast

from bd_util.maya.ui import (
    MayaDockableWindow,
    register_open_tool,
    unregister_open_tool,
)
from bd_util.maya.ui.dock import workspace_control
from bd_util.ui import qt

from .._dev.reopen_targets import ROTATION_SET_REOPEN
from .._shared.window_position import centered_position_within_screen
from .types import RotationTarget
from .window import (
    INITIAL_HEIGHT,
    INITIAL_WIDTH,
    RotationSetWindow,
)

__all__ = ["RotationSetDockWindow"]

_REOPEN_OWNER, _REOPEN_TOOL_ID, _REOPEN_MODULE, _REOPEN_FUNCTION = (
    ROTATION_SET_REOPEN
)


class RotationSetDockWindow(MayaDockableWindow):
    """姿勢維持の入力画面とworkspaceControlの寿命を管理する。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """入力ページと初回配置用の遅延処理を用意する。"""
        super().__init__(parent)
        self.setWindowTitle("回転をセット（姿勢を維持）")
        self.resize(INITIAL_WIDTH, INITIAL_HEIGHT)
        self._disposed = False
        self._initial_anchor: qt.QPoint | None = None
        self._reopen_token = object()
        self._anchor_timer = qt.QTimer(self)
        self._anchor_timer.setSingleShot(True)
        self._anchor_timer.timeout.connect(self._position_initial_window)

        self.rotation_page = RotationSetWindow(self, as_page=True)
        self.scroll_area = qt.QScrollArea(self)
        self.scroll_area.setFrameShape(qt.QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumSize(0, 0)
        self.scroll_area.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Ignored
        )
        self.scroll_area.setWidget(self.rotation_page)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)

        self.dock_attached.connect(self.rotation_page.refresh)
        self.dock_closed.connect(self._shutdown)
        self.dock_about_to_dispose.connect(self._shutdown)

    @property
    def is_disposed(self) -> bool:
        """入力画面のMaya監視を終了したか返す。"""
        return self._disposed

    def register_reopen(self) -> None:
        """reload後に再表示するdockable toolとして登録する。"""
        register_open_tool(
            _REOPEN_OWNER,
            _REOPEN_TOOL_ID,
            _REOPEN_MODULE,
            _REOPEN_FUNCTION,
            token=self._reopen_token,
        )

    def request_target(self, target: RotationTarget) -> None:
        """指定された属性を今回の設定先として表示する。"""
        self.rotation_page.set_initial_target(target)

    def set_initial_anchor(self, position: qt.QPoint) -> None:
        """初回の浮動表示だけ指定位置へ寄せる。"""
        self._initial_anchor = qt.QPoint(position)
        self._anchor_timer.start(0)

    def _workspace_name(self) -> str:
        """固定objectNameからMayaのworkspaceControl名を返す。"""
        return f"{self.objectName()}WorkspaceControl"

    def _is_floating(self) -> bool:
        """現在のworkspaceControlが浮動中か返す。"""
        name = self._workspace_name()
        try:
            return workspace_control.exists(
                name
            ) and workspace_control.is_floating(name)
        except (ValueError, TypeError, RuntimeError):
            return False

    def _position_initial_window(self) -> None:
        """浮動枠を指定位置中心に置き、画面の作業領域へ収める。"""
        anchor = self._initial_anchor
        self._initial_anchor = None
        if anchor is None or self._disposed or not self._is_floating():
            return
        host = workspace_control.find_floating_host(
            self._workspace_name(), self
        )
        if host is None:
            return
        screen = cast(
            qt.QtGui.QScreen | None, qt.QtGui.QGuiApplication.screenAt(anchor)
        )
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, host.screen())
        if screen is None:
            return
        host.move(
            centered_position_within_screen(
                anchor, host.frameGeometry().size(), screen.availableGeometry()
            )
        )

    def _shutdown(self) -> None:
        """Maya側の終了時に入力監視とreload登録を解除する。"""
        if self._disposed:
            return
        self._disposed = True
        self._anchor_timer.stop()
        unregister_open_tool(
            _REOPEN_OWNER, _REOPEN_TOOL_ID, token=self._reopen_token
        )
        self.rotation_page.dispose()

    def closeEvent(self, event: qt.QCloseEvent) -> None:
        """Qt側から閉じた場合もMaya callbackを残さない。"""
        self._shutdown()
        super().closeEvent(event)
