# coding: utf-8
"""Channel Editorの公開Windowとlifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import (
    DockArea,
    DockOptions,
    DockRestoreSpec,
    MayaDockableWindow,
    MayaDockableWindowController,
    reset_and_show_ui_layout,
)
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .widget import ChannelEditorWidget

_MINIMUM_WIDTH = 360


class ChannelEditorWindow(MayaDockableWindow):
    """Mayaへドッキングできる値入力用Window。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """Windowを構成し、現在の選択を表示する。"""
        super().__init__(parent)
        self.setObjectName("bdToolsChannelEditorWindow")
        self.setWindowTitle("bakedanuki · Channel Editor")
        self.resize(420, 360)
        # 保存済みの狭いタブ幅で復元されても値欄とstep欄を確保する
        self.setMinimumWidth(_MINIMUM_WIDTH)
        self.widget = ChannelEditorWidget(self)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)

        # Maya側のcloseとcontroller破棄は子WidgetのcloseEventに依存しない
        self.dock_closed.connect(self.widget.dispose)
        self.dock_about_to_dispose.connect(self.widget.dispose)

    def closeEvent(self, event: qt.QCloseEvent) -> None:
        """close時に、遅延削除より先に編集とMaya監視を終了する。"""
        self.widget.dispose()
        super().closeEvent(event)


# Mayaの保存配置とuiScriptが参照する固定ID・復元先を維持する
_controller = MayaDockableWindowController(
    ChannelEditorWindow,
    control_id="bdToolsChannelEditorWindow",
    restore=DockRestoreSpec(module="bd_tools.channel_editor.ui"),
    dock_options=DockOptions(
        area=DockArea.RIGHT,
        allowed_area=DockArea.ALL,
        floating=False,
        initial_width=420,
        initial_height=360,
        minimum_width=_MINIMUM_WIDTH,
        retain=False,
    ),
)
WORKSPACE_CONTROL_NAME: str = _controller.workspace_control_name


def show() -> ChannelEditorWindow:
    """選択ノードの値を変更せず、単一のChannel Editorを表示する。"""
    window = _controller.window
    if (
        window is not None
        and qt.isValid(window)
        and window.widget.controller.is_disposed
    ):
        _controller.dispose()
    return _controller.show()


def restore() -> ChannelEditorWindow:
    """MayaのuiScriptから、復元中のworkspaceControlへ内容を接続する。"""
    return _controller.restore()


def close() -> None:
    """配置を残してworkspaceControlを閉じ、入力とMaya監視を終了する。"""
    _controller.close()


def reset_layout() -> ChannelEditorWindow:
    """utilの統合APIで保存配置をリセットし、右側へ再表示する。"""
    return reset_and_show_ui_layout(
        _controller,
        "channel_editor/windows/main",
        clear_widget_state=False,
    )


def dispose() -> None:
    """Window、入力Binding、callbackを即座に終了する。"""
    _controller.dispose()


register_reload_disposer(dispose)

__all__ = [
    "ChannelEditorWindow",
    "WORKSPACE_CONTROL_NAME",
    "close",
    "dispose",
    "reset_layout",
    "restore",
    "show",
]
