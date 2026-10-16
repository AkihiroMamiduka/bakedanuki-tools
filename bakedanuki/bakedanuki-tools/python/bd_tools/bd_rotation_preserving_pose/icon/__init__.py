"""姿勢を維持する回転値設定ツールの同梱アイコン。"""

from pathlib import Path
from typing import Final

from bd_util.py.path import icon_path

MENU: Final[Path] = icon_path(__file__, "bd_rotation_preserving_pose.png")

__all__ = ["MENU"]
