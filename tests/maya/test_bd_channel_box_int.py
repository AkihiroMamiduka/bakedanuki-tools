# coding: utf-8
"""bdChannelBoxの整数行、選択入力、Copy／Pasteと状態編集を確認する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaIntPlugsBinding
from bd_util.ui import (
    FloatValueStepSpinBox,
    IntValueStepSpinBox,
    IntSliderSpinBox,
    qt,
)
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


def _events() -> None:
    """Maya通知とQtの遅延破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _row(widget: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """正式名で整数の入力行を取得する。"""
    row = next(
        row for row in widget.row_widgets if row.row.attribute.name == name
    )
    assert isinstance(row, AttributeRowWidget)
    return row


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """二ノードへ同じ整数属性と型固有の範囲を設定する。"""
    del qt_application
    auto = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    set_attr = cast(Callable[[str, int], None], cmds.setAttr)
    for node, byte, short, long in (
        ("intA", 255, 5, 2147483647),
        ("intB", 4, 6, 4),
    ):
        cmds.createNode("transform", name=node)
        cmds.addAttr(
            node, longName="byteValue", attributeType="byte", keyable=True
        )
        cmds.addAttr(
            node,
            longName="shortValue",
            attributeType="short",
            minValue=-20,
            maxValue=20,
            keyable=True,
        )
        cmds.addAttr(
            node, longName="longValue", attributeType="long", keyable=True
        )
        for path, value in (
            ("byteValue", byte),
            ("shortValue", short),
            ("longValue", long),
        ):
            set_attr(node + "." + path, value)
    cmds.select("intB", "intA", replace=True)
    widget = ChannelBoxWidget()
    widget.resize(380, 650)
    widget.show()
    _events()
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    cmds.autoKeyframe(state=auto)
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def test_integer_rows_edit_align_and_respect_limits(
    editor: ChannelBoxWidget,
) -> None:
    """byte・short・longの整数欄と複数ノード入力を確認する。"""
    byte_row = _row(editor, "byteValue")
    short_row = _row(editor, "shortValue")
    long_row = _row(editor, "longValue")
    assert all(
        isinstance(row.editor, (IntValueStepSpinBox, IntSliderSpinBox))
        and isinstance(row.row.binding, MayaIntPlugsBinding)
        for row in (byte_row, short_row, long_row)
    )
    for row in (byte_row, short_row, long_row):
        assert row.name_label.toolTip() == ""
        assert row.input_indicator.toolTip() == ""
        assert row.editor.toolTip() == ""
        if isinstance(row.editor, IntValueStepSpinBox):
            assert row.editor.step_spin_box.toolTip() == ""
    byte_spin = cast(IntValueStepSpinBox, byte_row.editor).spin_box
    assert isinstance(short_row.editor, IntSliderSpinBox)
    short_spin = short_row.editor.spin_box
    long_spin = cast(IntValueStepSpinBox, long_row.editor).spin_box
    assert (byte_spin.minimum(), byte_spin.maximum(), byte_spin.value()) == (
        0,
        255,
        255,
    )
    assert (
        short_spin.minimum(),
        short_spin.maximum(),
        short_spin.value(),
    ) == (-20, 20, 5)
    assert long_spin.value() == 2147483647
    assert not byte_row.row.binding.is_mixed
    assert byte_spin.select_all_on_mouse_focus()

    byte_spin.setValue(200)
    assert [
        cmds.getAttr(node + ".byteValue") for node in ("intA", "intB")
    ] == [200, 200]
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".byteValue") for node in ("intA", "intB")
    ] == [255, 4]

    key = (byte_row.row.attribute.path, byte_row.row.attribute.kind)
    short_key = (short_row.row.attribute.path, short_row.row.attribute.kind)
    editor.table_view.select_keys((key, short_key))
    selected_byte_editor = _row(editor, "byteValue").editor
    assert isinstance(selected_byte_editor, IntValueStepSpinBox)
    selected_byte_spin = selected_byte_editor.spin_box
    selected_byte_spin.setValue(10)
    assert [
        cmds.getAttr(node + "." + path)
        for path in ("byteValue", "shortValue")
        for node in ("intA", "intB")
    ] == [10, 10, 10, 10]
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]

    assert editor.controller.align_selected_values((key,))
    assert cmds.getAttr("intB.byteValue") == 255
    cmds.undo()
    _events()
    assert cmds.getAttr("intB.byteValue") == 4

    with pytest.raises(ValueError):
        editor.controller.apply_numeric_values((short_key,), 21.0)
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]
    assert editor.controller.offset_numeric_values((short_key,), 1)
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [6, 7]
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]


def test_integer_copy_paste_and_state_mode(editor: ChannelBoxWidget) -> None:
    """整数値の同path貼付けと表示／ロック行の生成を確認する。"""
    clipboard = qt.QApplication.clipboard()
    previous = cast(qt.QtCore.QMimeData | None, clipboard.mimeData())
    saved = qt.QtCore.QMimeData()
    if previous is not None:
        for mime_type in previous.formats():
            saved.setData(mime_type, previous.data(mime_type))
    try:
        long_row = _row(editor, "longValue")
        key = (long_row.row.attribute.path, long_row.row.attribute.kind)
        assert editor.controller.copy_selected_values((key,)) == 1
        set_attr = cast(Callable[[str, int], None], cmds.setAttr)
        set_attr("intA.longValue", 1)
        set_attr("intB.longValue", 2)
        cmds.flushUndo()
        assert editor.controller.paste_copied_values()
        assert [
            cmds.getAttr(node + ".longValue") for node in ("intA", "intB")
        ] == [2147483647] * 2
        cmds.undo()
        _events()
        assert [
            cmds.getAttr(node + ".longValue") for node in ("intA", "intB")
        ] == [1, 2]

        editor.controller.set_mode("states")
        _events()
        assert any(
            row.attribute.name == "byteValue" for row in editor.controller.rows
        )
        editor.controller.set_selected_locked((("byteValue", "byte"),), True)
        assert cmds.getAttr("intA.byteValue", lock=True)
    finally:
        clipboard.setMimeData(saved)


def test_compound_child_and_connected_integer(
    editor: ChannelBoxWidget,
) -> None:
    """compound子を表示し、一般の入力接続は読取り専用にする。"""
    for node in ("intA", "intB"):
        cmds.addAttr(
            node,
            longName="integerGroup",
            attributeType="compound",
            numberOfChildren=1,
        )
        cmds.addAttr(
            node,
            longName="childCount",
            attributeType="short",
            parent="integerGroup",
            keyable=True,
        )
    editor.refresh()
    _events()
    child = _row(editor, "childCount")
    assert child.row.attribute.path == "integerGroup.childCount"
    assert isinstance(child.editor, IntValueStepSpinBox)
    driver = cmds.createNode("transform")
    cmds.addAttr(
        driver, longName="driverCount", attributeType="short", keyable=True
    )
    for node in ("intA", "intB"):
        cmds.connectAttr(driver + ".driverCount", node + ".shortValue")
    cmds.select("intB", "intA", replace=True)
    editor.refresh()
    _events()
    short_row = _row(editor, "shortValue")
    assert isinstance(short_row.row.binding, MayaIntPlugsBinding)
    assert short_row.row.binding.writable_count == 0
    assert isinstance(short_row.editor, IntSliderSpinBox)
    assert not short_row.editor.spin_box.isEnabled()
    assert not short_row.editor.slider.isEnabled()


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize(
    "attribute,mode",
    [
        ("byteValue", "time"),
        ("byteValue", "driven"),
        ("shortValue", "time"),
        ("shortValue", "driven"),
        ("shortValue", "layer"),
        ("longValue", "time"),
        ("longValue", "driven"),
        ("longValue", "layer"),
    ],
)
def test_connected_integer_value_and_undo(
    editor: ChannelBoxWidget, auto: bool, attribute: str, mode: str
) -> None:
    """整数欄の確定と上下操作を接続先と通常属性へ一括適用する。"""
    path = "intA." + attribute
    if mode == "driven":
        for value in (2, 8):
            cmds.setDrivenKeyframe(
                path, currentDriver="intB.tx", driverValue=value, value=value
            )
    else:
        cmds.setKeyframe(path, time=1, value=2.25)
        cmds.setKeyframe(path, time=10, value=8.75)
        if mode == "layer":
            layer = cast(str, cmds.animLayer("integerLayer", attribute=path))
            cmds.animLayer(layer, edit=True, selected=True, preferred=True)
            cmds.setKeyframe(path, animLayer=layer, time=1, value=1)
            cmds.setKeyframe(path, animLayer=layer, time=10, value=3)
    cmds.currentTime(5)
    cmds.select("intB", "intA", replace=True)
    editor.refresh()
    _events()
    row = _row(editor, attribute)
    value_editor = row.editor
    assert isinstance(value_editor, (IntValueStepSpinBox, IntSliderSpinBox))
    spin = value_editor.spin_box
    assert spin.isEnabled()
    initial = cmds.getAttr(path)
    other = cmds.getAttr("intB." + attribute)
    cmds.autoKeyframe(state=auto)
    cmds.flushUndo()
    spin.setValue(12)
    _events()
    assert cmds.getAttr(path) == 12
    assert cmds.getAttr("intB." + attribute) == 12
    assert editor.message_label.text().startswith("適用候補: 2属性")
    cmds.undo()
    _events()
    assert cmds.getAttr(path) == initial
    assert cmds.getAttr("intB." + attribute) == other
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    value_editor = _row(editor, attribute).editor
    assert isinstance(value_editor, (IntValueStepSpinBox, IntSliderSpinBox))
    spin = value_editor.spin_box
    spin.stepBy(1)
    _events()
    assert cmds.getAttr(path) == initial + 1
    assert cmds.getAttr("intB." + attribute) == other + 1
    cmds.undo()
    _events()
    assert cmds.getAttr(path) == initial
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_integer_animation_actions(editor: ChannelBoxWidget) -> None:
    """キー、ミュート、曲線のコピー・貼付け・削除にも整数行を使用する。"""
    cmds.select("intA", replace=True)
    editor.refresh()
    _events()
    controller = editor.controller
    key = (("longValue", "long"),)
    cmds.currentTime(1)
    assert controller.set_keyframes_selected(key) == 1
    cmds.currentTime(10)
    assert controller.set_keyframes_selected(key, breakdown=True) == 1
    assert cmds.keyframe(
        "intA.longValue", query=True, time=(10, 10), breakdown=True
    ) == [10]
    cmds.flushUndo()
    assert controller.set_muted_selected(key, muted=True) == 1
    assert cmds.mute("intA.longValue", query=True)
    cmds.undo()
    _events()
    assert not cmds.mute("intA.longValue", query=True)
    assert controller.copy_animation_curves_selected(key) == 1
    cmds.currentTime(20)
    assert (
        controller.paste_animation_curves_to_selected(
            (("shortValue", "short"),)
        )
        == 1
    )
    assert cmds.keyframe("intA.shortValue", query=True, timeChange=True) == [
        20,
        29,
    ]
    cmds.undo()
    _events()
    assert not cmds.keyframe("intA.shortValue", query=True, keyframeCount=True)
    assert controller.delete_animation_curves_selected(key) == 1
    assert not cmds.keyframe("intA.longValue", query=True, keyframeCount=True)
    cmds.undo()
    _events()
    assert cmds.keyframe("intA.longValue", query=True, keyframeCount=True) == 2
    assert controller.cut_animation_curves_selected(key) == 1
    assert not cmds.keyframe("intA.longValue", query=True, keyframeCount=True)
    cmds.undo()
    _events()
    assert cmds.keyframe("intA.longValue", query=True, keyframeCount=True) == 2


@pytest.fixture
def step_editor(editor: ChannelBoxWidget) -> ChannelBoxWidget:
    """Step欄同士の操作確認には両側hard limitを外した整数行を使う。"""
    for node in ("intA", "intB"):
        cmds.addAttr(
            node + ".shortValue",
            edit=True,
            hasMinValue=False,
            hasMaxValue=False,
        )
    editor.refresh()
    _events()
    cmds.flushUndo()
    return editor


def test_step_modes_multi_selection_reset_and_wheel_policy(
    step_editor: ChannelBoxWidget,
) -> None:
    """整数Stepを選択行へ共有し、リセットとホイール方針を維持する。"""
    editor = step_editor
    byte = _row(editor, "byteValue").editor
    short = _row(editor, "shortValue").editor
    assert isinstance(byte, IntValueStepSpinBox)
    assert isinstance(short, IntValueStepSpinBox)
    assert (
        byte.step_spin_box.stepMode()
        == short.step_spin_box.stepMode()
        == "multiplicative"
    )
    editor.table_view.select_keys(
        (("byteValue", "byte"), ("shortValue", "short"))
    )
    byte.step_spin_box.stepUp()
    assert byte.singleStep() == short.singleStep() == 10
    assert cmds.getAttr("intA.byteValue") == 255
    assert cmds.getAttr("intA.shortValue") == 5
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    byte.step_spin_box.setValue(15)
    byte.step_spin_box.stepDown()
    assert byte.singleStep() == short.singleStep() == 1
    assert editor.int_step_profile.entries == ()
    assert byte.step_spin_box.wheel_requires_focus()
    editor.wheel_editing_action.setChecked(True)
    assert not byte.step_spin_box.wheel_requires_focus()
    assert not byte.spin_box.wheel_requires_focus()
    short.setSingleStep(5)
    editor.int_step_profile.set_single_step("long:offscreenCount", 100)
    editor.context_menu.aboutToShow.emit()
    assert editor.reset_selected_steps_action.isEnabled()
    editor.reset_selected_steps_action.trigger()
    assert byte.singleStep() == short.singleStep() == 1
    assert tuple(entry.key for entry in editor.int_step_profile.entries) == (
        "long:offscreenCount",
    )
    editor.reset_all_steps_action.trigger()
    assert editor.int_step_profile.entries == ()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("invalid", [0.5, 2147483648.0])
def test_mixed_step_validation_is_atomic(
    step_editor: ChannelBoxWidget, invalid: float
) -> None:
    """小数や上限超過の混在一括Stepを拒否し、操作元も元へ戻す。"""
    editor = step_editor
    integer = _row(editor, "shortValue").editor
    floating = _row(editor, "translateX").editor
    assert isinstance(integer, IntValueStepSpinBox)
    assert isinstance(floating, FloatValueStepSpinBox)
    editor.table_view.select_keys(
        (("shortValue", "short"), ("translate.translateX", "distance"))
    )
    floating.step_spin_box.setValue(5.0)
    assert floating.singleStep() == integer.singleStep() == 5
    assert type(integer.singleStep()) is int
    integer_before = editor.int_step_profile.entries
    float_before = editor.step_profile.entries
    floating.step_spin_box.setValue(invalid)
    assert floating.singleStep() == integer.singleStep() == 5
    assert editor.int_step_profile.entries == integer_before
    assert editor.step_profile.entries == float_before
    assert editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_saved_step_is_shared_by_path_and_kind_but_not_changed_type(
    editor: ChannelBoxWidget,
) -> None:
    """同じ正式path・型ではStepを共有し、属性型の変更後には流用しない。"""
    value_editor = _row(editor, "longValue").editor
    assert isinstance(value_editor, IntValueStepSpinBox)
    value_editor.setSingleStep(15)
    assert editor.int_step_profile.single_step("long:longValue") == 15
    cmds.select("intB", replace=True)
    editor.refresh()
    _events()
    value_editor = _row(editor, "longValue").editor
    assert isinstance(value_editor, IntValueStepSpinBox)
    assert value_editor.singleStep() == 15
    other = cmds.createNode("transform")
    cmds.addAttr(
        other, longName="longValue", attributeType="short", keyable=True
    )
    cmds.select(other, replace=True)
    editor.refresh()
    _events()
    value_editor = _row(editor, "longValue").editor
    assert isinstance(value_editor, IntValueStepSpinBox)
    assert value_editor.singleStep() == 1


def test_step_offsets_keep_differences_and_refuse_whole_operation_on_limits(
    editor: ChannelBoxWidget,
) -> None:
    """値の上下へ設定Stepを適用し、全ノードの差・Undo・範囲検証を維持する。"""
    value_editor = _row(editor, "shortValue").editor
    assert isinstance(value_editor, IntSliderSpinBox)
    value_editor.spin_box.setSingleStep(10)
    value_editor.spin_box.stepUp()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [15, 16]
    value_editor.spin_box.stepUp()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [15, 16]
    assert editor.message_label.isVisible()
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
