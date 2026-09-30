# coding: utf-8
"""bdChannelBoxの公開Windowとlifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import (
    DockArea,
    DockOptions,
    DockRestoreSpec,
    MayaDockableWindow,
    MayaDockableWindowController,
    MayaUiStateTracker,
    create_ui_state_manager,
    register_open_tool,
    reset_and_show_ui_layout,
    unregister_open_tool,
)
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .._dev.reopen_targets import (
    CHANNEL_BOX_CONTROL_ID,
    CHANNEL_BOX_REOPEN,
)
from .widget import ChannelBoxWidget

# 入力欄の幅を維持したまま、属性名の左側に残る余白を調整する
_INITIAL_WIDTH = 320
_MINIMUM_WIDTH = 280
_PREFERENCES_SETTINGS_PATH = "bd_channel_box/preferences/main"
_REOPEN_OWNER, _REOPEN_TOOL_ID, _REOPEN_MODULE, _REOPEN_FUNCTION = (
    CHANNEL_BOX_REOPEN
)


class ChannelBoxWindow(MayaDockableWindow):
    """Mayaへドッキングできる値入力用Window。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """Windowを構成し、現在の選択を表示する。"""
        super().__init__(parent)
        self.setObjectName("bdChannelBoxWindow")
        self.setWindowTitle("bdChannelBox")
        self.resize(_INITIAL_WIDTH, 360)
        # 保存済みの狭いタブ幅で復元されても値欄とstep欄を確保する
        self.setMinimumWidth(_MINIMUM_WIDTH)
        self.widget = ChannelBoxWidget(self)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)

        # Maya側のcloseとcontroller破棄は子WidgetのcloseEventに依存しない
        self.dock_closed.connect(self.widget.dispose)
        self.dock_about_to_dispose.connect(self.widget.dispose)

        # 配置とは別に入力操作の好みを保存し、Maya再起動時にも復元する
        self.ui_state = create_ui_state_manager(_PREFERENCES_SETTINGS_PATH)
        self.ui_state.register_checkable_action(
            "wheel_editing_without_focus",
            self.widget.wheel_editing_action,
        )
        self.ui_state.register_float_step_profile(
            "attribute_steps", self.widget.step_profile
        )
        for value, action in self.widget.search_visibility_actions.items():
            self.ui_state.register_checkable_action(
                f"search_visibility_{value}", action
            )
        self.ui_state_tracker = MayaUiStateTracker.for_dockable(
            self.ui_state,
            self,
        )
        self._reopen_token = object()
        self.dock_closed.connect(self._unregister_reopen)
        self.dock_about_to_dispose.connect(self._unregister_reopen)

    def register_reopen(self) -> None:
        """表示済みWindowを再読込後の再表示対象へ登録する。"""
        register_open_tool(
            _REOPEN_OWNER,
            _REOPEN_TOOL_ID,
            _REOPEN_MODULE,
            _REOPEN_FUNCTION,
            token=self._reopen_token,
        )

    def _unregister_reopen(self) -> None:
        """Maya側の終了通知を再表示対象へ反映する。"""
        unregister_open_tool(
            _REOPEN_OWNER, _REOPEN_TOOL_ID, token=self._reopen_token
        )

    def closeEvent(self, event: qt.QCloseEvent) -> None:
        """close時に、遅延削除より先に編集とMaya監視を終了する。"""
        self._unregister_reopen()
        self.widget.dispose()
        super().closeEvent(event)


# Mayaの保存配置とuiScriptが参照する固定ID・復元先を定義する
_controller = MayaDockableWindowController(
    ChannelBoxWindow,
    control_id=CHANNEL_BOX_CONTROL_ID,
    restore=DockRestoreSpec(module="bd_tools.bd_channel_box.ui"),
    dock_options=DockOptions(
        area=DockArea.RIGHT,
        allowed_area=DockArea.ALL,
        floating=False,
        initial_width=_INITIAL_WIDTH,
        initial_height=360,
        minimum_width=_MINIMUM_WIDTH,
        retain=False,
    ),
)
WORKSPACE_CONTROL_NAME: str = _controller.workspace_control_name


def show() -> ChannelBoxWindow:
    """選択ノードの値を変更せず、単一のbdChannelBoxを表示する。"""
    window = _controller.window
    if (
        window is not None
        and qt.isValid(window)
        and window.widget.controller.is_disposed
    ):
        _controller.dispose()
    window = _controller.show()
    window.register_reopen()
    return window


def restore() -> ChannelBoxWindow:
    """MayaのuiScriptから、復元中のworkspaceControlへ内容を接続する。"""
    window = _controller.restore()
    window.register_reopen()
    return window


def close() -> None:
    """配置を残してworkspaceControlを閉じ、入力とMaya監視を終了する。"""
    _controller.close()


def reset_layout() -> ChannelBoxWindow:
    """utilの統合APIで保存配置をリセットし、右側へ再表示する。"""
    return reset_and_show_ui_layout(
        _controller,
        "bd_channel_box/windows/main",
        clear_widget_state=False,
    )


def dispose() -> None:
    """Window、入力Binding、callbackを即座に終了する。"""
    _controller.dispose()


register_reload_disposer(dispose)

__all__ = [
    "ChannelBoxWindow",
    "WORKSPACE_CONTROL_NAME",
    "close",
    "dispose",
    "reset_layout",
    "restore",
    "show",
]
