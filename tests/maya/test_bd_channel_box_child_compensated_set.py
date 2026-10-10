# coding: utf-8
"""子を維持する値設定ダイアログと基準ノードのコマンド接続を検証する。"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.bd_channel_box.child_compensated_set_dialog import (
    ChildCompensatedSetDialog,
    ROTATION_INITIAL_HEIGHT,
    ROTATION_INITIAL_WIDTH,
    TRANSLATE_INITIAL_HEIGHT,
    TRANSLATE_INITIAL_WIDTH,
)
from bd_tools.bd_channel_box.controller import (
    ChannelBoxController,
    RoundTransformKind,
)


@pytest.fixture
def controller(
    qt_application: qt.QApplication,
) -> Iterator[ChannelBoxController]:
    """新しいsceneで制御層を作り、単位とUndo状態を復旧する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    previous_linear = cast(str, cmds.currentUnit(query=True, linear=True))
    previous_angle = cast(str, cmds.currentUnit(query=True, angle=True))
    cmds.currentUnit(linear="cm", angle="deg")
    owner = qt.QObject()
    instance = ChannelBoxController(owner)
    try:
        yield instance
    finally:
        instance.dispose()
        owner.deleteLater()
        cmds.flushUndo()
        cmds.currentUnit(linear=previous_linear, angle=previous_angle)
        cast(Callable[..., str], cmds.file)(new=True, force=True)


def _set_xyz(node: str, attribute: str, values: Sequence[float]) -> None:
    """三成分の移動・回転属性を現在のMaya表示単位で設定する。"""
    cast(Callable[..., None], cmds.setAttr)(
        f"{node}.{attribute}", *values, type="double3"
    )


def _xyz(node: str, attribute: str) -> tuple[float, float, float]:
    """三成分属性を現在のMaya表示単位で取得する。"""
    return cast(
        tuple[float, float, float], cmds.getAttr(f"{node}.{attribute}")[0]
    )


def _world_matrix(node: str) -> tuple[float, ...]:
    """直接の子のworld行列を確認するため取得する。"""
    return cast(
        tuple[float, ...],
        cmds.xform(node, query=True, matrix=True, worldSpace=True),
    )


def _assert_close(actual: Sequence[float], expected: Sequence[float]) -> None:
    """XYZまたは行列の値を丸め誤差内で照合する。"""
    assert len(actual) == len(expected)
    assert all(
        math.isclose(left, right, rel_tol=1.0e-8, abs_tol=1.0e-8)
        for left, right in zip(actual, expected)
    )


def test_dialog_converts_edited_world_translation_without_scene_change(
    qt_application: qt.QApplication,
    controller: ChannelBoxController,
) -> None:
    """空間切替は編集中のworld位置をlocalへ換算しsceneを変更しない。"""
    parent = cmds.createNode("transform", name="previewParent")
    target = cmds.createNode("transform", name="previewTarget", parent=parent)
    _set_xyz(parent, "translate", (10.0, 20.0, 30.0))
    _set_xyz(target, "translate", (1.0, 2.0, 3.0))
    controller.node_names = (target,)
    context = controller.capture_child_set_context()
    scene_before = _world_matrix(target)
    dialog = ChildCompensatedSetDialog(
        "translate",
        context.representative_name,
        context.representative_type,
        dict(context.values_canonical),
    )
    try:
        screen = qt_application.primaryScreen()
        assert screen is not None
        dialog.set_anchor_position(screen.availableGeometry().center())
        dialog.show()
        qt_application.processEvents()
        assert "基準ノードのみ" in dialog.target_label.text()
        assert target in dialog.target_label.text()
        assert dialog.child_label.text().startswith("子のworld座標")
        assert dialog.target_combo is None
        assert dialog.preservation_combo is None
        assert dialog.joint_child_combo is None
        assert dialog.space_combo.itemText(0) == "Local"
        assert dialog.space_combo.itemText(1) == "World"
        assert dialog.target() == "translate"
        assert dialog.compensate_child_translate()
        assert dialog.joint_child_compensation_attr() == "rotate"
        assert dialog.space() == "local"
        _assert_close(dialog.values_canonical(), (1.0, 2.0, 3.0))

        dialog.space_combo.setCurrentIndex(
            dialog.space_combo.findData("world")
        )
        assert dialog.space() == "world"
        _assert_close(dialog.values_canonical(), (11.0, 22.0, 33.0))
        dialog.value_spins[0].setValue(13.0)
        _assert_close(dialog.values_canonical(), (13.0, 22.0, 33.0))

        dialog.space_combo.setCurrentIndex(
            dialog.space_combo.findData("local")
        )
        _assert_close(dialog.values_canonical(), (3.0, 2.0, 3.0))
        _assert_close(_xyz(target, "translate"), (1.0, 2.0, 3.0))
        _assert_close(_world_matrix(target), scene_before)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_rotation_dialog_keeps_target_drafts_and_default_compensation(
    qt_application: qt.QApplication,
    controller: ChannelBoxController,
) -> None:
    """Jointの設定先切替とworld往復は編集中の値と既定の補償先を保つ。"""
    parent = cmds.createNode("transform", name="rotationPreviewParent")
    joint = cmds.createNode("joint", name="rotationPreview", parent=parent)
    _set_xyz(parent, "rotate", (9.0, -12.0, 25.0))
    _set_xyz(joint, "rotateAxis", (2.0, 4.0, 6.0))
    _set_xyz(joint, "jointOrient", (3.0, 5.0, 7.0))
    cast(Callable[..., None], cmds.setAttr)(f"{joint}.rotateOrder", 3)
    controller.node_names = (joint,)
    context = controller.capture_child_set_context()
    scene_before = _world_matrix(joint)
    dialog = ChildCompensatedSetDialog(
        "rotateAxis",
        context.representative_name,
        context.representative_type,
        dict(context.values_canonical),
    )
    try:
        screen = qt_application.primaryScreen()
        assert screen is not None
        dialog.set_anchor_position(screen.availableGeometry().center())
        dialog.show()
        qt_application.processEvents()
        assert dialog.child_label.text().startswith("子のworld姿勢")
        assert dialog.target_combo is not None
        assert dialog.preservation_combo is not None
        assert dialog.joint_child_combo is not None
        assert dialog.preservation_combo.itemText(0) == "座標と姿勢"
        assert dialog.preservation_combo.itemText(1) == "姿勢"
        assert tuple(label.text() for label in dialog.selector_labels) == (
            "値をセットする属性",
            "入力空間",
            "子の維持範囲",
            "子Jointの補償属性",
        )
        assert len({label.width() for label in dialog.selector_labels}) == 1
        assert (
            dialog.target_combo.y()
            < dialog.space_combo.y()
            < dialog.preservation_combo.y()
            < dialog.joint_child_combo.y()
        )
        assert dialog.target() == "rotateAxis"
        assert dialog.compensate_child_translate()
        assert dialog.joint_child_compensation_attr() == "rotate"
        dialog.value_spins[0].setValue(17.0)
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("jointOrient")
        )
        _assert_close(dialog.values_canonical(), (3.0, 5.0, 7.0))
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("rotateAxis")
        )
        _assert_close(dialog.values_canonical(), (17.0, 4.0, 6.0))
        dialog.space_combo.setCurrentIndex(
            dialog.space_combo.findData("world")
        )
        assert dialog.space() == "world"
        world_target = dialog.values_canonical()
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("jointOrient")
        )
        _assert_close(dialog.values_canonical(), world_target)
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData("rotateAxis")
        )
        dialog.space_combo.setCurrentIndex(
            dialog.space_combo.findData("local")
        )
        _assert_close(dialog.values_canonical(), (17.0, 4.0, 6.0))
        _assert_close(_world_matrix(joint), scene_before)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_child_set_dialog_opens_at_configured_size(
    qt_application: qt.QApplication,
    controller: ChannelBoxController,
) -> None:
    """移動と回転のダイアログを指定寸法でクリック位置付近へ開く。"""
    target = cmds.createNode("transform", name="compactDialogTarget")
    controller.node_names = (target,)
    context = controller.capture_child_set_context()
    screen = qt_application.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    initial_targets: tuple[tuple[RoundTransformKind, qt.QSize], ...] = (
        (
            "translate",
            qt.QSize(TRANSLATE_INITIAL_WIDTH, TRANSLATE_INITIAL_HEIGHT),
        ),
        (
            "rotate",
            qt.QSize(ROTATION_INITIAL_WIDTH, ROTATION_INITIAL_HEIGHT),
        ),
    )
    for initial_target, expected_size in initial_targets:
        parent = qt.QWidget()
        parent.show()
        dialog = ChildCompensatedSetDialog(
            initial_target,
            context.representative_name,
            context.representative_type,
            dict(context.values_canonical),
            parent,
        )
        observed_sizes: list[qt.QSize] = []
        observed_frames: list[qt.QRect] = []
        observed_bottom_gaps: list[int] = []

        def inspect_and_reject() -> None:
            """表示中の寸法・位置・下部余白を記録して閉じる。"""
            observed_sizes.append(dialog.size())
            observed_frames.append(dialog.frameGeometry())
            observed_bottom_gaps.append(
                dialog.height() - dialog.buttons.geometry().bottom() - 1
            )
            dialog.reject()

        try:
            dialog.set_anchor_position(available.center())
            inspection_timer = qt.QTimer(dialog)
            inspection_timer.setSingleShot(True)
            inspection_timer.timeout.connect(inspect_and_reject)
            inspection_timer.start(100)
            assert dialog.exec() == qt.QDialog.DialogCode.Rejected
            assert observed_sizes == [expected_size]
            dialog_layout = dialog.layout()
            assert dialog_layout is not None
            assert observed_bottom_gaps[0] <= (
                dialog_layout.contentsMargins().bottom() + 2
            )
            assert available.contains(observed_frames[0])
            frame_center = observed_frames[0].center()
            assert abs(frame_center.x() - available.center().x()) <= 1
            assert abs(frame_center.y() - available.center().y()) <= 1
        finally:
            dialog.close()
            dialog.deleteLater()
            parent.close()
            parent.deleteLater()


def test_translation_dialog_shows_meters_without_rounding_cm_source(
    controller: ChannelBoxController,
) -> None:
    """移動の表示単位がmでも未編集のcm正本を丸めず返す。"""
    target = cmds.createNode("transform", name="unitPreview")
    _set_xyz(target, "translate", (123.456789012345, 2.0, 3.0))
    controller.node_names = (target,)
    context = controller.capture_child_set_context()
    cmds.currentUnit(linear="m")
    dialog = ChildCompensatedSetDialog(
        "translate",
        context.representative_name,
        context.representative_type,
        dict(context.values_canonical),
    )
    try:
        assert math.isclose(
            dialog.value_spins[0].value(),
            1.23456789012345,
            rel_tol=0.0,
            abs_tol=1.0e-14,
        )
        assert math.isclose(
            dialog.values_canonical()[0],
            123.456789012345,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
    finally:
        dialog.close()
        dialog.deleteLater()


def test_controller_sets_only_representative_node_and_undoes_once(
    controller: ChannelBoxController,
) -> None:
    """複数選択でも基準ノードのみ変更し、子のworld行列とUndoを保つ。"""
    other = cmds.createNode("transform", name="untouchedTransform")
    target = cmds.createNode("transform", name="setTargetTransform")
    child = cmds.createNode("transform", name="setChild", parent=target)
    _set_xyz(other, "translate", (8.0, 9.0, 10.0))
    _set_xyz(target, "translate", (2.0, 3.0, 4.0))
    _set_xyz(child, "translate", (5.0, 6.0, 7.0))
    child_before = _world_matrix(child)
    controller.node_names = (other, target)
    context = controller.capture_child_set_context()
    assert context.representative_name == target
    cmds.flushUndo()

    assert (
        controller.set_child_compensated_value(
            context,
            (12.0, 13.0, 14.0),
            target="translate",
            space="local",
        )
        == 1
    )
    _assert_close(_xyz(target, "translate"), (12.0, 13.0, 14.0))
    _assert_close(_xyz(other, "translate"), (8.0, 9.0, 10.0))
    _assert_close(_world_matrix(child), child_before)

    cmds.undo()
    _assert_close(_xyz(target, "translate"), (2.0, 3.0, 4.0))
    _assert_close(_world_matrix(child), child_before)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
