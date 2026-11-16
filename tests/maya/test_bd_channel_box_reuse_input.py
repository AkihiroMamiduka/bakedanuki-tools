# coding: utf-8
"""操作途中で入力部品を別ノードへ再利用しても、旧入力を持ち越さない。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal, cast

import pytest
from maya import cmds

from bd_util.ui import (
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    IntSliderSpinBox,
    qt,
)
from bd_tools.bd_channel_box.widget import (
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelBoxWidget,
)


def _events() -> None:
    """選択同期と旧Binding・一時入力欄の遅延破棄を完了する。"""
    for _ in range(4):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set(path: str, value: int | float) -> None:
    """Mayaコマンドの数値入力だけを動的境界へ閉じる。"""
    cast(Callable[[str, int | float], None], cmds.setAttr)(path, value)


def _row(editor: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """属性名に一致する値入力行を返す。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeRowWidget)
    return row


def _state_row(editor: ChannelBoxWidget, name: str) -> AttributeStateRowWidget:
    """属性名に一致する表示・ロック行を返す。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row


def _mouse(
    origin: qt.QWidget,
    kind: qt.QEvent.Type,
    target: qt.QWidget,
) -> qt.QtGui.QMouseEvent:
    """旧押下元へ、指定部品の位置に対応するマウス通知を作る。"""
    position = target.mapToGlobal(target.rect().center())
    return qt.QtGui.QMouseEvent(
        kind,
        qt.QPointF(origin.mapFromGlobal(position)),
        qt.QPointF(position),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseMove
            else qt.Qt.MouseButton.LeftButton
        ),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseButtonRelease
            else qt.Qt.MouseButton.LeftButton
        ),
        qt.Qt.KeyboardModifier.NoModifier,
    )


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """値が異なり入力形式が同じ、三属性だけの二つのnetworkを表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    auto_key = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    cmds.undoInfo(state=True)
    for index, node in enumerate(("reuseInputA", "reuseInputB")):
        cmds.createNode("network", name=node, skipSelect=True)
        cmds.addAttr(
            node,
            longName="gain",
            attributeType="double",
            minValue=0,
            maxValue=10,
            keyable=True,
        )
        cmds.addAttr(
            node,
            longName="count",
            attributeType="long",
            minValue=0,
            maxValue=100,
            keyable=True,
        )
        cmds.addAttr(
            node, longName="stepValue", attributeType="double", keyable=True
        )
        _set(node + ".gain", 2 + index * 2)
        _set(node + ".count", 20 + index * 20)
        _set(node + ".stepValue", 3 + index * 3)
    cmds.select("reuseInputA", replace=True)
    widget = ChannelBoxWidget()
    widget.resize(420, 600)
    widget.show()
    _events()
    cmds.flushUndo()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        _events()
        cmds.autoKeyframe(state=auto_key)
        cast(Callable[..., str], cmds.file)(new=True, force=True)


@pytest.mark.parametrize("kind", ["display", "lock"])
def test_sweep_old_release_cannot_edit_reused_buttons_on_new_selection(
    editor: ChannelBoxWidget, kind: Literal["display", "lock"]
) -> None:
    """なぞり中の選択変更で旧押下を終了し、同じボタンの次のクリックを許可する。"""
    editor.controller.set_mode("states")
    editor.controller.set_attribute_filter("all")
    _events()
    row, last_row = _state_row(editor, "gain"), _state_row(editor, "count")
    first = (
        row.display_buttons["hidden"]
        if kind == "display"
        else row.lock_check_box
    )
    last = (
        last_row.display_buttons["hidden"]
        if kind == "display"
        else last_row.lock_check_box
    )
    old_binding = row.row.state_binding
    qt.QApplication.sendEvent(
        first, _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    )
    qt.QApplication.sendEvent(
        first, _mouse(first, qt.QEvent.Type.MouseMove, last)
    )
    sweep = editor.state_sweep if kind == "display" else editor.lock_sweep
    assert sweep.is_active
    assert editor.controller.state_edit_session.is_editing
    cmds.select("reuseInputB", replace=True)
    assert old_binding.is_disposed
    _events()
    assert _state_row(editor, "gain") is row
    assert not sweep.is_active
    assert not first.isDown()
    assert not editor.controller.state_edit_session.is_editing

    qt.QApplication.sendEvent(
        first, _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    )
    _events()
    for name in ("gain", "count"):
        assert cmds.getAttr(f"reuseInputB.{name}", keyable=True)
        assert not cmds.getAttr(f"reuseInputB.{name}", lock=True)
        if kind == "display":
            assert not cmds.getAttr(f"reuseInputA.{name}", keyable=True)
        else:
            assert cmds.getAttr(f"reuseInputA.{name}", lock=True)

    # 中断した部品でも、新しい押下は現在の対象だけを変更する
    first.click()
    _events()
    if kind == "display":
        assert not cmds.getAttr("reuseInputB.gain", keyable=True)
    else:
        assert cmds.getAttr("reuseInputB.gain", lock=True)
    assert cmds.getAttr("reuseInputB.count", keyable=True)
    assert not cmds.getAttr("reuseInputB.count", lock=True)


@pytest.mark.parametrize("name", ["gain", "count"])
def test_slider_old_release_and_queued_move_cannot_edit_new_selection(
    editor: ChannelBoxWidget, name: Literal["gain", "count"]
) -> None:
    """ドラッグを中断し、旧移動・releaseを再利用したSliderへ持ち越さない。"""
    row = _row(editor, name)
    view = row.editor
    assert isinstance(view, (FloatSliderSpinBox, IntSliderSpinBox))
    old_binding = row.row.binding
    view.slider.setSliderDown(True)
    view.slider.setValue(view.slider.maximum() // 2)
    changed = cmds.getAttr(f"reuseInputA.{name}")
    expected = 4 if name == "gain" else 40
    assert editor.controller.value_edit_session.is_editing
    cmds.select("reuseInputB", replace=True)
    assert old_binding.is_disposed
    # 選択同期と前後して配送される旧gestureの通知を、Qtのqueueへ残す
    qt.QApplication.postEvent(
        view.slider,
        _mouse(view.slider, qt.QEvent.Type.MouseMove, view.slider),
    )
    qt.QApplication.postEvent(
        view.slider,
        _mouse(view.slider, qt.QEvent.Type.MouseButtonRelease, view.slider),
    )
    _events()
    assert _row(editor, name) is row
    assert not view.slider.isSliderDown()
    assert not editor.controller.value_edit_session.is_editing
    assert cmds.getAttr(f"reuseInputA.{name}") == changed
    assert cmds.getAttr(f"reuseInputB.{name}") == expected
    view.spin_box.setValue(7)
    assert cmds.getAttr(f"reuseInputA.{name}") == changed
    assert cmds.getAttr(f"reuseInputB.{name}") == 7
    cmds.undo()
    _events()
    assert cmds.getAttr(f"reuseInputB.{name}") == expected


def test_numeric_overlay_is_discarded_before_reusing_value_field(
    editor: ChannelBoxWidget,
) -> None:
    """旧ノード向けの数値下書きを捨て、再利用後の新しい明示入力だけを適用する。"""
    row = _row(editor, "stepValue")
    view = row.editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setFocus()
    qt.QApplication.sendEvent(
        view.spin_box,
        qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_9,
            qt.Qt.KeyboardModifier.NoModifier,
            "9",
        ),
    )
    pending = editor.findChild(qt.QLineEdit, "channel_batch_numeric_editor")
    assert isinstance(pending, qt.QLineEdit)
    assert pending.isVisible()
    pending.setText("9")
    pending.setModified(True)
    cmds.select("reuseInputB", replace=True)
    _events()
    assert _row(editor, "stepValue") is row
    assert not qt.isValid(pending) or not pending.isVisible()
    editor.mode_combo.setFocus()
    _events()
    assert cmds.getAttr("reuseInputA.stepValue") == 3
    assert cmds.getAttr("reuseInputB.stepValue") == 6
    view.spin_box.setValue(8)
    assert cmds.getAttr("reuseInputA.stepValue") == 3
    assert cmds.getAttr("reuseInputB.stepValue") == 8


def test_step_draft_is_discarded_without_changing_saved_increment(
    editor: ChannelBoxWidget,
) -> None:
    """Stepの未確定文字を新ノードへ持ち越さず、確定済み増減量を利用する。"""
    row = _row(editor, "stepValue")
    view = row.editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.setSingleStep(0.25)
    step = view.step_spin_box
    step.setFocus()
    _events()
    pending = step.findChild(qt.QLineEdit)
    assert isinstance(pending, qt.QLineEdit)
    pending.setText("9")
    pending.setModified(True)
    assert step.value() == 0.25
    cmds.select("reuseInputB", replace=True)
    _events()
    editor.mode_combo.setFocus()
    _events()
    assert _row(editor, "stepValue") is row
    assert step.value() == view.singleStep() == 0.25
    assert cmds.getAttr("reuseInputA.stepValue") == 3
    assert cmds.getAttr("reuseInputB.stepValue") == 6
    view.spin_box.stepUp()
    assert cmds.getAttr("reuseInputA.stepValue") == 3
    assert cmds.getAttr("reuseInputB.stepValue") == 6.25
