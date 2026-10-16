"""各ツールのアイコン定数の公開型を固定する。"""

from pathlib import Path
from typing import assert_type

from bd_tools import (
    bd_channel_box,
    bd_child_compensated_set,
    bd_rotation_preserving_pose,
)

assert_type(bd_channel_box.icon.MENU, Path)
assert_type(bd_child_compensated_set.icon.MENU, Path)
assert_type(bd_rotation_preserving_pose.icon.MENU, Path)
