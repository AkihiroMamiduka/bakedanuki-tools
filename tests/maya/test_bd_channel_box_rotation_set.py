# coding: utf-8
"""姿勢を維持する回転設定ダイアログとコマンド接続を検証する。"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.bd_channel_box.controller import ChannelBoxController
from bd_tools.bd_channel_box.rotation_set_dialog import RotationSetDialog


@pytest.fixture
def controller(
    qt_application: qt.QApplication,
) -> Iterator[ChannelBoxController]:
    """新しいシーンと制御層を作り、操作後に破棄する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    previous_angle = cast(str, cmds.currentUnit(query=True, angle=True))
    cmds.currentUnit(angle="deg")
    parent = qt.QObject()
    instance = ChannelBoxController(parent)
    try:
        yield instance
    finally:
        instance.dispose()
        parent.deleteLater()
        cmds.flushUndo()
        cmds.currentUnit(angle=previous_angle)
        cast(Callable[..., str], cmds.file)(new=True, force=True)


def _set_xyz(node: str, attribute: str, values: Sequence[float]) -> None:
    """回転属性の三成分をMaya表示角度単位で設定する。"""
    cast(Callable[..., None], cmds.setAttr)(
        f"{node}.{attribute}", *values, type="double3"
    )


def _xyz(node: str, attribute: str) -> tuple[float, float, float]:
    """回転属性の三成分をMaya表示角度単位で取得する。"""
    return cast(
        tuple[float, float, float], cmds.getAttr(f"{node}.{attribute}")[0]
    )


def _matrix(node: str, *, world: bool = False) -> tuple[float, ...]:
    """ノードのlocalまたはworld行列を取得する。"""
    return cast(
        tuple[float, ...],
        cmds.xform(
            node,
            query=True,
            matrix=True,
            worldSpace=world,
            objectSpace=not world,
        ),
    )


def _assert_close(actual: Sequence[float], expected: Sequence[float]) -> None:
    """回転値または行列の各成分が許容誤差内か検証する。"""
    assert len(actual) == len(expected)
    assert all(
        math.isclose(left, right, rel_tol=1.0e-8, abs_tol=1.0e-8)
        for left, right in zip(actual, expected)
    )


def test_dialog_defaults_and_preserves_values_when_target_changes(
    controller: ChannelBoxController,
) -> None:
    """Jointの補償先初期値と、設定先ごとの未丸め入力を確認する。"""
    joint = cmds.createNode("joint", name="dialogJoint")
    _set_xyz(joint, "rotate", (12.345678901234567, 20.0, 30.0))
    _set_xyz(joint, "rotateAxis", (4.0, 5.0, 6.0))
    _set_xyz(joint, "jointOrient", (7.0, 8.0, 9.0))
    controller.node_names = (joint,)
    context = controller.capture_rotation_set_context()
    original = dict(context.values_degrees)
    dialog = RotationSetDialog(
        "rotate",
        context.representative_name,
        context.representative_type,
        original,
        ("transform", "joint"),
    )
    try:
        assert dialog.target() == "rotate"
        assert dialog.compensate_with() == "jointOrient"
        assert joint in dialog.target_count_label.text()
        assert "対象外 1 ノード" in dialog.target_count_label.text()
        assert dialog.values_degrees() == original["rotate"]
        dialog.value_spins[0].setValue(37.0)
        dialog.compensation_combo.setCurrentIndex(
            dialog.compensation_combo.findData("rotateAxis")
        )
        assert "対象 2 ノード" in dialog.target_count_label.text()
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("rotateAxis")
        )
        assert dialog.compensate_with() == "rotate"
        assert dialog.values_degrees() == original["rotateAxis"]
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("jointOrient")
        )
        assert dialog.compensate_with() == "rotate"
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("rotate")
        )
        assert dialog.compensate_with() == "rotateAxis"
        assert math.isclose(dialog.values_degrees()[0], 37.0)
        _assert_close(_xyz(joint, "rotate"), original["rotate"])
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_transform_options_and_display_unit_conversion(
    controller: ChannelBoxController,
) -> None:
    """Transformでは二属性だけを選び、rad入力をdegreeへ戻す。"""
    transform = cmds.createNode("transform", name="dialogTransform")
    controller.node_names = (transform,)
    context = controller.capture_rotation_set_context()
    cmds.currentUnit(angle="rad")
    dialog = RotationSetDialog(
        "rotateAxis",
        context.representative_name,
        context.representative_type,
        dict(context.values_degrees),
        context.node_types,
    )
    try:
        assert dialog.target_combo.count() == 2
        assert dialog.target() == "rotateAxis"
        assert dialog.compensate_with() == "rotate"
        assert dialog.compensation_combo.count() == 1
        dialog.value_spins[1].setValue(1.0)
        assert math.isclose(
            dialog.values_degrees()[1], math.degrees(1.0), rel_tol=1.0e-12
        )
    finally:
        dialog.close()
        dialog.deleteLater()


def test_controller_sets_joint_rotate_with_one_undo_and_reports_excluded(
    controller: ChannelBoxController,
) -> None:
    """混合選択でJointのみ変更し、localと子world行列を保つ。"""
    transform = cmds.createNode("transform", name="otherTransform")
    joint = cmds.createNode("joint", name="targetJoint")
    child = cmds.createNode("joint", name="childJoint", parent=joint)
    _set_xyz(joint, "rotate", (20.0, -15.0, 8.0))
    _set_xyz(joint, "rotateAxis", (5.0, 6.0, 7.0))
    _set_xyz(joint, "jointOrient", (2.0, 3.0, 4.0))
    _set_xyz(transform, "rotate", (1.0, 2.0, 3.0))
    original_rotate = _xyz(joint, "rotate")
    original_local = _matrix(joint)
    original_child_world = _matrix(child, world=True)
    controller.node_names = (transform, joint)
    context = controller.capture_rotation_set_context()
    reports: list[str] = []
    controller.operation_reported.connect(reports.append)
    cmds.flushUndo()

    assert (
        controller.set_rotation_preserving_pose(
            context,
            (30.0, 40.0, 50.0),
            target="rotate",
            compensate_with="jointOrient",
        )
        == 1
    )
    _assert_close(_xyz(joint, "rotate"), (30.0, 40.0, 50.0))
    _assert_close(_xyz(transform, "rotate"), (1.0, 2.0, 3.0))
    _assert_close(_matrix(joint), original_local)
    _assert_close(_matrix(child, world=True), original_child_world)
    assert reports and transform in reports[-1]

    cmds.undo()
    _assert_close(_xyz(joint, "rotate"), original_rotate)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
