# coding: utf-8
"""子を維持する変換値設定の対象属性。"""

from typing import Literal, TypeAlias

ChildSetTarget: TypeAlias = Literal[
    "translate", "rotate", "rotateAxis", "jointOrient"
]

__all__ = ["ChildSetTarget"]
