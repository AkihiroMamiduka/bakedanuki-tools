# coding: utf-8
"""Channel Editorの公開Windowとlifecycle。"""

from __future__ import annotations

from bd_util.maya.ui import MayaWindowController
from bd_util.ui import qt

from .._dev.lifecycle import register_reload_disposer
from .widget import ChannelEditorWidget


class ChannelEditorWindow(qt.QDialog):
    """値入力を支援する通常Window。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """Windowを構成し、現在の選択を表示する。"""
        super().__init__(parent)
        self.setObjectName("bdToolsChannelEditorWindow")
        self.setWindowTitle("bakedanuki · Channel Editor")
        self.resize(420, 360)
        self.widget = ChannelEditorWidget(self)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)

    def closeEvent(self, arg__1: qt.QCloseEvent) -> None:
        """close時に、遅延削除より先に編集とMaya監視を終了する。"""
        self.widget.dispose()
        super().closeEvent(arg__1)

    def reject(self) -> None:
        """Escapeでも入力と監視を終了して、Qt標準の終了処理へ渡す。"""
        self.widget.dispose()
        super().reject()


_controller: MayaWindowController[ChannelEditorWindow] | None = None


def show() -> ChannelEditorWindow:
    """選択ノードの値を変更せず、単一のChannel Editorを表示する。"""
    global _controller
    if _controller is not None:
        window = _controller.window
        if window is not None and window.widget.controller.is_disposed:
            _controller.dispose()
    if _controller is None:
        _controller = MayaWindowController(
            ChannelEditorWindow,
            settings_path="channel_editor/windows/main",
        )
    return _controller.show()


def dispose() -> None:
    """Window、入力Binding、callbackを即座に終了する。"""
    global _controller
    controller, _controller = _controller, None
    if controller is not None:
        window = controller.window
        if window is not None and qt.isValid(window):
            window.widget.dispose()
        controller.dispose()


register_reload_disposer(dispose)

__all__ = ["ChannelEditorWindow", "dispose", "show"]
