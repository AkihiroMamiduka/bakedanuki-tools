# coding: utf-8
"""整数Sliderの選別・選択入力・中断・Step保持を実際のMaya属性で確認する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import (
    FloatSliderSpinBox,
    IntSliderSpinBox,
    IntValueStepSpinBox,
    qt,
)
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


def events() -> None:
    """Maya通知とQtの表示・遅延破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def row(widget: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """正式名で入力行を取得する。"""
    result = next(
        w for w in widget.row_widgets if w.row.attribute.name == name
    )
    assert isinstance(result, AttributeRowWidget)
    return result


def slider(
    widget: ChannelBoxWidget, name: str = "longValue"
) -> IntSliderSpinBox:
    """整数Sliderを持つ行を取得する。"""
    result = row(widget, name).editor
    assert isinstance(result, IntSliderSpinBox)
    return result


def values(path: str) -> list[object]:
    """二ノードの確定値を取得する。"""
    return [cmds.getAttr(node + "." + path) for node in ("sliderA", "sliderB")]


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """制限の種類が異なる整数と比較用floatを二ノードへ用意する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    auto = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    cmds.undoInfo(state=True)
    for node, offset in (("sliderA", 0), ("sliderB", 1)):
        cmds.createNode("transform", name=node)
        for name, kind, limits, initial in (
            ("byteFree", "byte", {}, 128),
            ("byteValue", "byte", {"minValue": 10, "maxValue": 200}, 30),
            ("shortFree", "short", {}, 3),
            ("shortValue", "short", {"minValue": -20, "maxValue": 20}, 5),
            ("longValue", "long", {"minValue": 0, "maxValue": 100}, 20),
            (
                "fullValue",
                "long",
                {"minValue": -(2**31), "maxValue": 2**31 - 1},
                7,
            ),
            ("minOnly", "long", {"minValue": 0}, 1),
            ("maxOnly", "long", {"maxValue": 100}, 1),
            (
                "equalValue",
                "long",
                {"minValue": 5, "maxValue": 5, "defaultValue": 5},
                5,
            ),
            ("softOnly", "long", {"softMinValue": -10, "softMaxValue": 10}, 1),
            ("gain", "double", {"minValue": 0, "maxValue": 100}, 2.5),
        ):
            cast(Callable[..., None], cmds.addAttr)(
                node, longName=name, attributeType=kind, keyable=True, **limits
            )
            if name == "byteValue":
                # byteは生成時の範囲指定をMayaが上書きするため、定義後に設定する
                cmds.addAttr(
                    node + "." + name, edit=True, minValue=10, maxValue=200
                )
            cast(Callable[[str, float | int], None], cmds.setAttr)(
                node + "." + name,
                initial + (0 if name == "equalValue" else offset),
            )
        cmds.addAttr(
            node,
            longName="counts",
            attributeType="compound",
            numberOfChildren=1,
        )
        cmds.addAttr(
            node,
            longName="childValue",
            attributeType="short",
            parent="counts",
            minValue=-5,
            maxValue=5,
            keyable=True,
        )
    cmds.select("sliderB", "sliderA", replace=True)
    widget = ChannelBoxWidget()
    widget.resize(420, 650)
    widget.show()
    events()
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    events()
    assert not widget.controller.value_edit_session.is_editing
    cmds.autoKeyframe(state=auto)
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def test_explicit_limits_select_slider_and_all_fields_align(
    editor: ChannelBoxWidget,
) -> None:
    """型既定・片側・soft・同値制限はStep、両側hard制限とcompound子はSliderになる。"""
    for name in (
        "byteFree",
        "shortFree",
        "minOnly",
        "maxOnly",
        "equalValue",
        "softOnly",
    ):
        assert isinstance(row(editor, name).editor, IntValueStepSpinBox)
    for name, limits in (
        ("byteValue", (10, 200)),
        ("shortValue", (-20, 20)),
        ("longValue", (0, 100)),
        ("fullValue", (-(2**31), 2**31 - 1)),
        ("childValue", (-5, 5)),
    ):
        view = slider(editor, name)
        assert view.slider.intRange() == limits
        assert view.layoutOrder() == "value_slider"
        assert view.spin_box.width() == 156
        assert view.slider.width() == 60
        assert view.width() == 222
        layout = view.layout()
        assert isinstance(layout, qt.QHBoxLayout)
        assert layout.spacing() == 6
        assert layout.itemAt(0).widget() is view.spin_box
        assert layout.itemAt(1).widget() is view.slider
        assert view.spin_box.select_all_on_mouse_focus()
        assert view.rect().contains(view.spin_box.geometry())
        assert view.rect().contains(view.slider.geometry())
    floating = row(editor, "gain").editor
    assert isinstance(floating, FloatSliderSpinBox)
    assert floating.width() == slider(editor).width()
    assert values("fullValue") == [7, 8]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    editor.wheel_editing_action.setChecked(True)
    assert not slider(editor).spin_box.wheel_requires_focus()


@pytest.mark.parametrize(
    "attribute,maximum", [("objectColor", 7), ("overrideColor", 31)]
)
def test_transform_standard_color_slider_preserves_limits_and_undo(
    editor: ChannelBoxWidget, attribute: str, maximum: int
) -> None:
    """標準色属性をSliderで一括編集し、両側の入力範囲と一回Undoを保つ。"""
    for node, value in (("sliderA", 1), ("sliderB", 2)):
        cast(Callable[[str, int], None], cmds.setAttr)(
            node + "." + attribute, value
        )
    editor.controller.set_attribute_filter("all")
    events()
    view = slider(editor, attribute)
    assert view.slider.intRange() == (0, maximum)
    assert (view.spin_box.minimum(), view.spin_box.maximum()) == (0, maximum)
    cmds.flushUndo()
    view.slider.setSliderDown(True)
    for value in (3, 6):
        view.slider.setValue(value)
        assert values(attribute) == [value, value]
        assert view.spin_box.value() == value
    view.slider.setSliderDown(False)
    cmds.undo()
    events()
    assert values(attribute) == [1, 2]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    events()
    assert values(attribute) == [6, 6]


def test_integer_drag_aligns_selected_int_and_float_with_one_undo(
    editor: ChannelBoxWidget,
) -> None:
    """異なる整数型とfloatの全ノードへ同じ整数をライブ反映し、一Undoで戻す。"""
    editor.table_view.select_keys(
        (("longValue", "long"), ("shortValue", "short"), ("gain", "number"))
    )
    view = slider(editor)
    view.slider.setSliderDown(True)
    for value in (10, 15, 18):
        view.slider.setValue(value)
        assert (
            values("longValue")
            == values("shortValue")
            == values("gain")
            == [value, value]
        )
    view.slider.setSliderDown(False)
    assert not editor.controller.value_edit_session.is_editing
    cmds.undo()
    events()
    assert values("longValue") == [20, 21]
    assert values("shortValue") == [5, 6]
    assert values("gain") == [2.5, 3.5]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    events()
    assert values("longValue") == values("shortValue") == [18, 18]


def test_failed_update_keeps_prior_success_and_finishes_keyboard_gesture(
    editor: ChannelBoxWidget,
) -> None:
    """後続の不正値ではその更新全体を拒否し、矢印操作のUndoも閉じる。"""
    editor.table_view.select_keys(
        (("longValue", "long"), ("shortValue", "short"))
    )
    view = slider(editor)
    view.slider.setSliderDown(True)
    view.slider.setValue(10)
    assert values("longValue") == values("shortValue") == [10, 10]
    view.slider.setValue(30)
    assert values("longValue") == values("shortValue") == [10, 10]
    assert not view.slider.isSliderDown()
    assert not editor.controller.value_edit_session.is_editing
    assert editor.message_label.isVisible()
    cmds.undo()
    events()
    assert values("longValue") == [20, 21]
    assert values("shortValue") == [5, 6]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    # つまみ押下を伴わないキー操作でも拒否時に操作単位を残さない
    view = slider(editor)
    view.slider.keyPressEvent(
        qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_End,
            qt.Qt.KeyboardModifier.NoModifier,
        )
    )
    assert not editor.controller.value_edit_session.is_editing
    assert not view.slider.isSliderDown()


def test_representative_range_does_not_silently_clamp_other_targets(
    editor: ChannelBoxWidget,
) -> None:
    """別ノードの狭い制限へ合わせて値を補正せず、全対象の更新を拒否する。"""
    cmds.addAttr("sliderB.longValue", edit=True, maxValue=25)
    editor.refresh()
    events()
    view = slider(editor)
    assert view.slider.intRange() == (0, 100)
    cmds.flushUndo()
    view.slider.setSliderDown(True)
    view.slider.setValue(50)
    assert values("longValue") == [20, 21]
    assert not editor.controller.value_edit_session.is_editing
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_full_int32_endpoints_and_separate_value_input_undo(
    editor: ChannelBoxWidget,
) -> None:
    """全32-bit範囲を整数のまま扱い、ドラッグと後続の数値入力を別Undoにする。"""
    view = slider(editor, "fullValue")
    view.slider.setSliderDown(True)
    view.slider.setValue(0)
    assert values("fullValue") == [-(2**31), -(2**31)]
    view.slider.setValue(view.slider.maximum())
    view.slider.setSliderDown(False)
    assert values("fullValue") == [2**31 - 1, 2**31 - 1]
    view.spin_box.setValue(123456789)
    cmds.undo()
    events()
    assert values("fullValue") == [2**31 - 1, 2**31 - 1]
    cmds.undo()
    events()
    assert values("fullValue") == [7, 8]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize(
    "reason", ["time", "lock", "selection", "filter", "hide", "close"]
)
def test_interruption_closes_integer_drag(
    editor: ChannelBoxWidget, reason: str
) -> None:
    """時刻・ロック・選択・フィルター・非表示・終了で旧操作を残さない。"""
    view = slider(editor)
    view.slider.setSliderDown(True)
    view.slider.setValue(60)
    assert editor.controller.value_edit_session.is_editing
    if reason == "time":
        cmds.currentTime(cmds.currentTime(query=True) + 1)
    elif reason == "lock":
        cmds.setAttr("sliderA.longValue", lock=True)
    elif reason == "selection":
        cmds.select("sliderB", replace=True)
    elif reason == "filter":
        editor.controller.set_attribute_filter("hidden")
    elif reason == "hide":
        editor.hide()
    else:
        editor.close()
    events()
    assert not editor.controller.value_edit_session.is_editing
    if qt.isValid(view):
        assert not view.slider.isSliderDown()


@pytest.mark.parametrize("auto_key", [False, True])
@pytest.mark.parametrize("mode", ["time", "driven", "layer"])
def test_connected_slider_keeps_existing_animation_edit_rules(
    editor: ChannelBoxWidget, auto_key: bool, mode: str
) -> None:
    """整数Sliderも時間カーブ・SDK・Layerの既存入力規則と一操作Undoを使う。"""
    path = "sliderA.longValue"
    if mode == "driven":
        for value in (2, 8):
            cmds.setDrivenKeyframe(
                path,
                currentDriver="sliderB.tx",
                driverValue=value,
                value=value,
            )
    else:
        cmds.setKeyframe(path, time=1, value=2)
        cmds.setKeyframe(path, time=10, value=8)
        if mode == "layer":
            layer = cast(
                str, cmds.animLayer("integerSliderLayer", attribute=path)
            )
            cmds.animLayer(layer, edit=True, selected=True, preferred=True)
            cmds.setKeyframe(path, animLayer=layer, time=1, value=1)
            cmds.setKeyframe(path, animLayer=layer, time=10, value=3)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    editor.refresh()
    events()
    initial = values("longValue")
    view = slider(editor)
    cmds.flushUndo()
    view.slider.setSliderDown(True)
    for value in (40, 50, 60):
        view.slider.setValue(value)
        assert values("longValue") == [value, value]
    view.slider.setSliderDown(False)
    cmds.undo()
    events()
    assert values("longValue") == initial
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_hidden_step_setting_returns_after_limits_removed_and_all_reset(
    editor: ChannelBoxWidget,
) -> None:
    """Step設定をSlider表示中も保持し、選択リセット対象と全リセットを区別する。"""
    editor.int_step_profile.set_single_step("long:longValue", 15)
    editor.table_view.select_keys((("longValue", "long"),))
    editor.context_menu.aboutToShow.emit()
    assert not editor.reset_selected_steps_action.isEnabled()
    assert editor.reset_all_steps_action.isEnabled()
    for node in ("sliderA", "sliderB"):
        cmds.addAttr(node + ".longValue", edit=True, hasMaxValue=False)
    editor.refresh()
    events()
    step = row(editor, "longValue").editor
    assert isinstance(step, IntValueStepSpinBox)
    assert step.singleStep() == 15
    for node in ("sliderA", "sliderB"):
        cmds.addAttr(node + ".longValue", edit=True, maxValue=100)
    editor.refresh()
    events()
    assert isinstance(row(editor, "longValue").editor, IntSliderSpinBox)
    editor.reset_all_steps_action.trigger()
    assert editor.int_step_profile.single_step("long:longValue") is None


def test_step_sharing_skips_slider_and_keeps_its_saved_step(
    editor: ChannelBoxWidget,
) -> None:
    """選択Stepの共有はStep欄がある行だけに適用し、Slider行の保存値を保持する。"""
    editor.int_step_profile.set_single_step("long:longValue", 15)
    editor.table_view.select_keys(
        (("longValue", "long"), ("shortFree", "short"))
    )
    step = row(editor, "shortFree").editor
    assert isinstance(step, IntValueStepSpinBox)
    cmds.flushUndo()
    step.step_spin_box.stepUp()
    assert step.singleStep() == 10
    assert editor.int_step_profile.single_step("long:longValue") == 15
    assert values("longValue") == [20, 21]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_time_change_discards_pending_integer_slider_value(
    editor: ChannelBoxWidget,
) -> None:
    """整数Slider付き値欄の未確定文字を、時刻変更後の属性へ持ち越さない。"""
    cmds.setKeyframe("sliderA.longValue", time=1, value=10)
    cmds.setKeyframe("sliderA.longValue", time=10, value=20)
    cmds.currentTime(1)
    cmds.autoKeyframe(state=True)
    editor.refresh()
    events()
    view = slider(editor)
    view.spin_box.setFocus()
    line = view.spin_box.lineEdit()
    assert line is not None
    line.setText("99")
    line.setModified(True)
    cmds.currentTime(2)
    events()
    expected = cmds.getAttr("sliderA.longValue")
    assert view.spin_box.value() == expected
    assert line.text() != "99"
    qt.QApplication.sendEvent(
        view.spin_box,
        qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_Return,
            qt.Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert cmds.getAttr("sliderA.longValue") == expected
    assert cmds.keyframe("sliderA.longValue", query=True, timeChange=True) == [
        1,
        10,
    ]
