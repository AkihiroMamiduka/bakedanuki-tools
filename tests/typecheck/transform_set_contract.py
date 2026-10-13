# coding: utf-8
"""独立した変換値設定ツールの公開API型を固定する。"""

from typing import assert_type

from bd_tools import bd_child_compensated_set, bd_rotation_preserving_pose
from bd_tools.bd_child_compensated_set import ChildSetDockWindow
from bd_tools.bd_child_compensated_set.window import ChildCompensatedSetWindow
from bd_tools.bd_rotation_preserving_pose import RotationSetDockWindow
from bd_tools.bd_rotation_preserving_pose.window import RotationSetWindow

assert_type(
    bd_child_compensated_set.show("translate", "translate"),
    ChildSetDockWindow,
)
assert_type(
    bd_child_compensated_set.show("rotation", "jointOrient"),
    ChildSetDockWindow,
)
assert_type(bd_child_compensated_set.restore(), ChildSetDockWindow)
assert_type(
    bd_child_compensated_set.show().translate_page,
    ChildCompensatedSetWindow,
)
assert_type(
    bd_rotation_preserving_pose.show("rotateAxis"), RotationSetDockWindow
)
assert_type(bd_rotation_preserving_pose.restore(), RotationSetDockWindow)
assert_type(
    bd_rotation_preserving_pose.show().rotation_page, RotationSetWindow
)
