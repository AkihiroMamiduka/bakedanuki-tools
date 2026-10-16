"""姿勢を維持する回転値設定ツールの同梱アイコン。"""

from pathlib import Path
from typing import Final

from bd_util.py.path import resolve_relative_path

MENU: Final[Path] = resolve_relative_path(
    __file__, "bd_rotation_preserving_pose.png"
)

__all__ = ["MENU"]
