# coding: utf-8
"""子・姿勢を維持するモデルレスWindowの即時入力を検証する。"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.bd_channel_box import (
    child_rotation_ui,
    child_translate_ui,
    rotation_set_ui,
)
from bd_tools.bd_channel_box.child_compensated_set_window import (
    ChildCompensatedSetWindow,
)
from bd_tools.bd_channel_box.rotation_set_window import RotationSetWindow


@pytest.fixture
def clean_scene(qt_application: qt.QApplication) -> Iterator[None]:
    """表示単位を固定した空sceneを用意してテスト後に復旧する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    linear = cast(str, cmds.currentUnit(query=True, linear=True))
    angle = cast(str, cmds.currentUnit(query=True, angle=True))
    cmds.currentUnit(linear="cm", angle="deg")
    try:
        yield
    finally:
        cmds.flushUndo()
        cmds.currentUnit(linear=linear, angle=angle)
        cast(Callable[..., str], cmds.file)(new=True, force=True)


def _xyz(node: str, attribute: str) -> tuple[float, float, float]:
    """Maya表示単位でXYZ属性の実値を返す。"""
    return cast(
        tuple[float, float, float], cmds.getAttr(f"{node}.{attribute}")[0]
    )


def _set_xyz(
    node: str, attribute: str, values: tuple[float, float, float]
) -> None:
    """型付きMaya facade越しにXYZ複合属性を設定する。"""
    cast(Callable[..., None], cmds.setAttr)(
        f"{node}.{attribute}", *values, type="double3"
    )


def _matrix(node: str, *, world: bool = False) -> tuple[float, ...]:
    """補償前後を比較するためノードの行列を返す。"""
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
    """変換値をMayaの計算誤差内で比較する。"""
    assert len(actual) == len(expected)
    assert all(
        math.isclose(left, right, rel_tol=1.0e-8, abs_tol=1.0e-8)
        for left, right in zip(actual, expected)
    )


def _process_events(application: qt.QApplication) -> None:
    """選択callbackから予約された画面更新まで処理する。"""
    application.processEvents()
    application.processEvents()


def _assert_step_fields_visible(
    window: ChildCompensatedSetWindow | RotationSetWindow,
) -> None:
    """各軸のStep欄がWindowの表示領域内に収まることを確かめる。"""
    for editor in window.xyz_editor.value_editors:
        step = editor.step_spin_box
        assert step.isVisible()
        assert step.width() > 0
        assert editor.rect().contains(
            step.mapTo(editor, step.rect().bottomRight())
        )
        assert window.rect().contains(
            step.mapTo(window, step.rect().bottomRight())
        )


def _xyz_vertical_gaps(
    window: ChildCompensatedSetWindow | RotationSetWindow,
) -> tuple[int, int]:
    """XYZ入力行の間にある空白の高さを返す。"""
    editors = window.xyz_editor.value_editors
    return (
        editors[1].geometry().top() - editors[0].geometry().bottom() - 1,
        editors[2].geometry().top() - editors[1].geometry().bottom() - 1,
    )


def test_translation_window_follows_selection_and_steps_with_one_undo(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """基準ノードだけを即時変更し、子のworld位置とUndoを維持する。"""
    del clean_scene
    first = cmds.createNode("transform", name="firstTarget")
    second = cmds.createNode("transform", name="secondTarget")
    child = cmds.createNode("transform", name="childTarget", parent=second)
    _set_xyz(first, "translate", (1.0, 2.0, 3.0))
    _set_xyz(second, "translate", (4.0, 5.0, 6.0))
    _set_xyz(child, "translate", (2.0, 3.0, 4.0))
    child_before = _matrix(child, world=True)
    cmds.select(first, replace=True)
    window = ChildCompensatedSetWindow(initial_target="translate")
    try:
        window.show()
        _process_events(qt_application)
        assert first in window.target_label.text()
        assert window.xyz_editor.value_spins[0].isEnabled()

        # 未確定の文字入力を次に選択したノードへ持ち越さない
        line_edit = window.xyz_editor.value_spins[0].lineEdit()
        line_edit.setText("99")
        line_edit.setModified(True)
        cmds.select(first, second, replace=True)
        _process_events(qt_application)
        assert second in window.target_label.text()
        _assert_close(_xyz(first, "translate"), (1.0, 2.0, 3.0))
        _assert_close(
            tuple(spin.value() for spin in window.xyz_editor.value_spins),
            (4.0, 5.0, 6.0),
        )

        window.xyz_editor.step_spins[0].setValue(2.0)
        assert window.xyz_editor.value_editors[0].singleStep() == 2.0
        assert window.xyz_editor.value_editors[1].singleStep() == 1.0
        _assert_close(_xyz(second, "translate"), (4.0, 5.0, 6.0))
        cmds.flushUndo()
        window.xyz_editor.value_spins[0].stepBy(1)
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (6.0, 5.0, 6.0))
        _assert_close(_xyz(first, "translate"), (1.0, 2.0, 3.0))
        _assert_close(_matrix(child, world=True), child_before)
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (4.0, 5.0, 6.0))
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)

        # 文字入力の確定も上下操作と同じコマンドへ即時に渡す
        value_spin = window.xyz_editor.value_spins[0]
        committed_edit = value_spin.lineEdit()
        committed_edit.setText("7")
        for kind in (
            qt.QEvent.Type.ShortcutOverride,
            qt.QEvent.Type.KeyPress,
            qt.QEvent.Type.KeyRelease,
        ):
            key_event = qt.QtGui.QKeyEvent(
                kind,
                qt.Qt.Key.Key_Return,
                qt.Qt.KeyboardModifier.NoModifier,
            )
            key_event.setAccepted(False)
            qt.QApplication.sendEvent(value_spin, key_event)
            assert key_event.isAccepted()
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (7.0, 5.0, 6.0))
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (4.0, 5.0, 6.0))

        cmds.select(clear=True)
        _process_events(qt_application)
        assert not window.xyz_editor.value_spins[0].isEnabled()
    finally:
        window.close()
        window.deleteLater()


def test_child_rotation_window_applies_active_target_and_keeps_child(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """子を維持する回転値の確定を現在ノードへ即時適用する。"""
    del clean_scene
    joint = cmds.createNode("joint", name="rotateTarget")
    child = cmds.createNode("joint", name="rotateChild", parent=joint)
    _set_xyz(joint, "rotate", (3.0, 4.0, 5.0))
    _set_xyz(child, "translate", (2.0, 3.0, 4.0))
    child_before = _matrix(child, world=True)
    cmds.select(joint, replace=True)
    window = ChildCompensatedSetWindow(initial_target="rotate")
    try:
        window.show()
        _process_events(qt_application)
        window.xyz_editor.value_spins[1].setValue(14.0)
        _process_events(qt_application)
        _assert_close(_xyz(joint, "rotate"), (3.0, 14.0, 5.0))
        _assert_close(_matrix(child, world=True), child_before)
        assert window.xyz_editor.value_spins[1].value() == 14.0

        assert window.target_combo is not None
        assert window.joint_child_combo is not None
        window.target_combo.setCurrentIndex(
            window.target_combo.findData("jointOrient")
        )
        window.joint_child_combo.setCurrentIndex(
            window.joint_child_combo.findData("jointOrient")
        )
        window.xyz_editor.value_spins[0].setValue(11.0)
        _process_events(qt_application)
        _assert_close(_xyz(joint, "jointOrient"), (11.0, 0.0, 0.0))
        _assert_close(_matrix(child, world=True), child_before)
    finally:
        window.close()
        window.deleteLater()


def test_translation_world_field_tracks_selection_and_preserves_child(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """World欄は現在選択の位置を表示し、入力は子の位置を保つ。"""
    del clean_scene
    parent = cmds.createNode("transform", name="worldParent")
    node = cmds.createNode("transform", name="worldTarget", parent=parent)
    child = cmds.createNode("transform", name="worldChild", parent=node)
    other = cmds.createNode("transform", name="otherWorldTarget")
    _set_xyz(parent, "translate", (10.0, 0.0, 0.0))
    _set_xyz(node, "translate", (4.0, 0.0, 0.0))
    _set_xyz(child, "translate", (2.0, 0.0, 0.0))
    _set_xyz(other, "translate", (30.0, 0.0, 0.0))
    child_before = _matrix(child, world=True)
    cmds.select(node, replace=True)
    window = ChildCompensatedSetWindow(initial_target="translate")
    try:
        window.show()
        window.space_combo.setCurrentIndex(
            window.space_combo.findData("world")
        )
        _process_events(qt_application)
        assert math.isclose(window.xyz_editor.value_spins[0].value(), 14.0)

        cmds.flushUndo()
        window.xyz_editor.value_spins[0].setValue(18.0)
        _process_events(qt_application)
        _assert_close(_xyz(node, "translate"), (8.0, 0.0, 0.0))
        _assert_close(_matrix(child, world=True), child_before)
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(node, "translate"), (4.0, 0.0, 0.0))

        cmds.select(other, replace=True)
        _process_events(qt_application)
        assert math.isclose(window.xyz_editor.value_spins[0].value(), 30.0)
    finally:
        window.close()
        window.deleteLater()


def test_pose_window_updates_options_when_selected_type_changes(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """Joint固有属性からTransformへ移ると有効な設定先へ切り替える。"""
    del clean_scene
    joint = cmds.createNode("joint", name="poseJoint")
    transform = cmds.createNode("transform", name="poseTransform")
    cmds.select(joint, replace=True)
    window = RotationSetWindow()
    try:
        window.show()
        window.set_initial_target("jointOrient")
        _process_events(qt_application)
        assert window.target() == "jointOrient"
        assert window.compensate_with() == "rotate"

        cmds.select(transform, replace=True)
        _process_events(qt_application)
        assert window.target() == "rotate"
        assert window.compensate_with() == "rotateAxis"
        original_matrix = _matrix(transform)
        cmds.flushUndo()
        window.xyz_editor.value_spins[0].setValue(25.0)
        _process_events(qt_application)
        _assert_close(_xyz(transform, "rotate"), (25.0, 0.0, 0.0))
        _assert_close(_matrix(transform), original_matrix)
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(transform, "rotate"), (0.0, 0.0, 0.0))
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)

        cmds.select(joint, replace=True)
        _process_events(qt_application)
        assert window.target() == "rotate"
        assert window.compensate_with() == "jointOrient"
    finally:
        window.close()
        window.deleteLater()


def test_pose_window_uses_current_maya_angle_unit(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """Window表示中に角度単位が変わっても現単位で入力する。"""
    del clean_scene
    node = cmds.createNode("transform", name="angleUnitTarget")
    _set_xyz(node, "rotate", (90.0, 0.0, 0.0))
    original_matrix = _matrix(node)
    cmds.select(node, replace=True)
    window = RotationSetWindow()
    try:
        window.show()
        _process_events(qt_application)
        cmds.currentUnit(angle="rad")
        _process_events(qt_application)
        assert math.isclose(
            window.xyz_editor.value_spins[0].value(),
            math.pi / 2.0,
            abs_tol=1.0e-10,
        )
        window.xyz_editor.value_spins[0].setValue(math.pi / 3.0)
        _process_events(qt_application)
        cmds.currentUnit(angle="deg")
        _process_events(qt_application)
        assert math.isclose(_xyz(node, "rotate")[0], 60.0, abs_tol=1.0e-8)
        _assert_close(_matrix(node), original_matrix)
    finally:
        window.close()
        window.deleteLater()


def test_modeless_window_controllers_reuse_and_dispose(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """3画面の配置と再利用を確認し、終了時に監視を解除する。"""
    del clean_scene
    node = cmds.createNode("transform", name="liveControllerTarget")
    cmds.select(node, replace=True)
    translate = child_translate_ui.show()
    try:
        _process_events(qt_application)
        _assert_step_fields_visible(translate)
        assert _xyz_vertical_gaps(translate) == (2, 2)
        translate.resize(translate.width(), translate.height() + 60)
        _process_events(qt_application)
        assert _xyz_vertical_gaps(translate) == (2, 2)
        assert [
            translate.space_combo.itemText(index)
            for index in range(translate.space_combo.count())
        ] == ["World", "Local"]
        assert translate.space() == "local"
        assert child_translate_ui.show() is translate
        assert translate.windowFlags() & qt.Qt.WindowType.Window
        screen = qt_application.primaryScreen()
        assert screen is not None
        available = screen.availableGeometry()
        translate.set_anchor_position(available.bottomRight())
        _process_events(qt_application)
        assert available.contains(translate.frameGeometry())
    finally:
        child_translate_ui.close()
    assert translate.is_disposed

    rotation = child_rotation_ui.show("rotateAxis")
    try:
        _process_events(qt_application)
        _assert_step_fields_visible(rotation)
        assert _xyz_vertical_gaps(rotation) == (2, 2)
        assert [
            rotation.space_combo.itemText(index)
            for index in range(rotation.space_combo.count())
        ] == ["World", "Local"]
        assert rotation.space() == "local"
        assert child_rotation_ui.show("rotate") is rotation
        assert rotation.target() == "rotate"
    finally:
        child_rotation_ui.close()
    assert rotation.is_disposed

    pose = rotation_set_ui.show("rotateAxis")
    try:
        _process_events(qt_application)
        _assert_step_fields_visible(pose)
        assert _xyz_vertical_gaps(pose) == (2, 2)
        set_label = pose.target_attribute_label
        absorb_label = pose.compensation_attribute_label
        assert set_label.geometry().left() == absorb_label.geometry().left()
        assert pose.target_combo.geometry().left() == (
            pose.compensation_combo.geometry().left()
        )
        assert (
            set_label.geometry().center().y()
            < absorb_label.geometry().center().y()
        )
        for label, combo in (
            (set_label, pose.target_combo),
            (absorb_label, pose.compensation_combo),
        ):
            assert label.geometry().right() < combo.geometry().left()
            assert (
                abs(
                    label.geometry().center().y()
                    - combo.geometry().center().y()
                )
                <= 1
            )
        separator = pose.target_separator
        assert separator.frameShape() == qt.QFrame.Shape.HLine
        assert pose.target_label.geometry().bottom() < (
            separator.geometry().center().y()
        )
        assert separator.geometry().bottom() < set_label.geometry().top()
        assert rotation_set_ui.show("rotate") is pose
        assert pose.target() == "rotate"
    finally:
        rotation_set_ui.close()
    assert pose.is_disposed
    _process_events(qt_application)
