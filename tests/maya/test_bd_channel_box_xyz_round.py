# coding: utf-8
"""bdChannelBox の XYZ 専用丸めと正式プラグインの接続を検証する。"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.bd_channel_box.controller import ChannelBoxController


@pytest.fixture
def controller(
    qt_application: qt.QApplication,
) -> Iterator[ChannelBoxController]:
    """新しいシーンと制御層を作り、テスト後に破棄する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    previous_linear = cast(str, cmds.currentUnit(query=True, linear=True))
    previous_angle = cast(str, cmds.currentUnit(query=True, angle=True))
    cmds.currentUnit(linear="cm", angle="deg")
    parent = qt.QObject()
    instance = ChannelBoxController(parent)
    try:
        yield instance
    finally:
        instance.dispose()
        parent.deleteLater()
        cmds.flushUndo()
        cmds.currentUnit(linear=previous_linear, angle=previous_angle)
        cast(Callable[..., str], cmds.file)(new=True, force=True)


def _set_value(plug: str, value: float) -> None:
    """Maya の単一数値属性へ検証値を設定する。"""
    cast(Callable[[str, float], None], cmds.setAttr)(plug, value)


def _get_value(plug: str) -> float:
    """Maya の単一数値属性から検証値を取得する。"""
    return cast(float, cmds.getAttr(plug))


def _assert_values_close(
    actual: Sequence[float], expected: Sequence[float]
) -> None:
    """座標または行列の各成分が許容誤差内か確認する。"""
    assert len(actual) == len(expected)
    assert all(
        math.isclose(a, b, rel_tol=1.0e-8, abs_tol=1.0e-8)
        for a, b in zip(actual, expected)
    )


def test_translate_xyz_uses_display_units_and_one_undo(
    controller: ChannelBoxController,
) -> None:
    """複数 Transform の XYZ 丸めと子の world 位置保持を確認する。"""
    cmds.currentUnit(linear="in")
    first = cmds.createNode("transform", name="first")
    second = cmds.createNode("transform", name="second")
    child = cmds.createNode("transform", name="child", parent=first)
    _set_value(first + ".translateX", 1.235)
    _set_value(second + ".translateX", -2.676)
    _set_value(child + ".translateX", 3.0)
    child_world_before = cast(
        list[float],
        cmds.xform(child, query=True, worldSpace=True, translation=True),
    )
    controller.node_names = (first, second)
    cmds.flushUndo()

    assert controller.round_transform_xyz("translate", 2) == 2
    assert math.isclose(_get_value(first + ".translateX"), 1.24)
    assert math.isclose(_get_value(second + ".translateX"), -2.68)
    _assert_values_close(
        cast(
            list[float],
            cmds.xform(child, query=True, worldSpace=True, translation=True),
        ),
        child_world_before,
    )

    cmds.undo()
    assert math.isclose(_get_value(first + ".translateX"), 1.235)
    assert math.isclose(_get_value(second + ".translateX"), -2.676)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_joint_orient_xyz_filters_mixed_selection_and_keeps_child_pose(
    controller: ChannelBoxController,
) -> None:
    """混合選択の Transform を報告し Joint だけを子補償付きで丸める。"""
    transform = cmds.createNode("transform", name="other")
    joint = cmds.createNode("joint", name="parentJoint")
    child = cmds.createNode("joint", name="childJoint", parent=joint)
    _set_value(joint + ".jointOrientZ", 12.345)
    _set_value(child + ".translateX", 3.0)
    child_world_before = cast(
        tuple[float, ...], cmds.getAttr(child + ".worldMatrix[0]")
    )
    reports: list[str] = []
    controller.operation_reported.connect(reports.append)
    controller.node_names = (transform, joint)
    cmds.flushUndo()

    assert (
        controller.round_transform_xyz(
            "jointOrient",
            2,
            compensate_child_translate=True,
            joint_child_compensation_attr="jointOrient",
        )
        == 1
    )
    assert math.isclose(_get_value(joint + ".jointOrientZ"), 12.35)
    _assert_values_close(
        cast(tuple[float, ...], cmds.getAttr(child + ".worldMatrix[0]")),
        child_world_before,
    )
    assert reports and "other" in reports[-1]

    cmds.undo()
    assert math.isclose(_get_value(joint + ".jointOrientZ"), 12.345)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
