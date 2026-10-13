# coding: utf-8
"""姿勢を維持する回転値設定の対象属性。"""

from typing import Literal, TypeAlias

RotationTarget: TypeAlias = Literal["rotate", "rotateAxis", "jointOrient"]

__all__ = ["RotationTarget"]
