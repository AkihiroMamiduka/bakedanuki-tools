# coding: utf-8
"""クリック位置を基準に画面内へ配置するダイアログ。"""

from __future__ import annotations

from typing import cast

from bd_util.ui import qt

__all__ = ["AnchoredDialog"]


def _centered_position_within_screen(
    anchor: qt.QPoint, frame_size: qt.QSize, available: qt.QRect
) -> qt.QPoint:
    """クリック位置を中心にし、画面の作業領域へ収まる左上座標を返す。"""
    maximum_x = max(
        available.left(), available.right() - frame_size.width() + 1
    )
    maximum_y = max(
        available.top(), available.bottom() - frame_size.height() + 1
    )
    return qt.QPoint(
        min(
            max(anchor.x() - frame_size.width() // 2, available.left()),
            maximum_x,
        ),
        min(
            max(anchor.y() - frame_size.height() // 2, available.top()),
            maximum_y,
        ),
    )


class AnchoredDialog(qt.QDialog):
    """表示時のウィンドウ枠をクリック位置の画面内へ収める。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """親ウィジェットと配置基準を初期化する。"""
        super().__init__(parent)
        self._anchor_position: qt.QPoint | None = None

    def set_anchor_position(self, position: qt.QPoint) -> None:
        """ダイアログの中心にしたいメニュークリック位置を保存する。"""
        self._anchor_position = qt.QPoint(position.x(), position.y())
        self.adjustSize()
        self._position_near_anchor()

    def showEvent(self, arg__1: qt.QtGui.QShowEvent) -> None:
        """表示時に確定したウィンドウ枠寸法で配置を補正する。"""
        super().showEvent(arg__1)
        self._position_near_anchor()

    def _position_near_anchor(self) -> None:
        """クリック位置のモニターを選び、枠ごと画面内へ移動する。"""
        anchor = self._anchor_position
        if anchor is None:
            return
        application = qt.QtGui.QGuiApplication.instance()
        if not isinstance(application, qt.QtGui.QGuiApplication):
            return
        screen = cast(
            qt.QtGui.QScreen | None,
            qt.QtGui.QGuiApplication.screenAt(anchor),
        )
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, self.screen())
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, application.primaryScreen())
        if screen is None:
            return
        available = screen.availableGeometry()
        if available.isEmpty():
            return
        frame_size = self.frameGeometry().size()
        self.move(
            _centered_position_within_screen(anchor, frame_size, available)
        )
