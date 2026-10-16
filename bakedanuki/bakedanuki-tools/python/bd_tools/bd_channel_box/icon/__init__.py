"""bdChannelBoxの同梱アイコン。"""

from pathlib import Path
from typing import Final

from bd_util.py.path import icon_path

MENU: Final[Path] = icon_path(__file__, "bd_channel_box.png")

__all__ = ["MENU"]
