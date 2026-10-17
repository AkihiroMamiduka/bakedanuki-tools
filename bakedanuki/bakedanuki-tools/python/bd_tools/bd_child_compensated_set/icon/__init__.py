"""子を維持する変換値設定ツールの同梱アイコン。"""

from pathlib import Path
from typing import Final

from bd_util.py.path import resolve_relative_path

MENU: Final[Path] = resolve_relative_path(
    __file__, "bd_child_compensated_set.png"
)

__all__ = ["MENU"]
