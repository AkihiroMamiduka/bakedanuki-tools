# coding: utf-8
"""指定位置を基準に浮動Windowを画面内へ配置する。"""

from __future__ import annotations

from bd_util.ui import qt

__all__ = ["centered_position_within_screen"]


def centered_position_within_screen(
    anchor: qt.QPoint, frame_size: qt.QSize, available: qt.QRect
) -> qt.QPoint:
    """指定位置を中心にし、画面の作業領域へ収まる左上座標を返す。"""
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
