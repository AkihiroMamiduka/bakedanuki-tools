# coding: utf-8
"""選択変更で共通入力行を保持し、構成の差分だけを更新することを検証する。"""

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.ui import (
    BoolCheckBox,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    StringLineEdit,
    qt,
)
from bd_tools.bd_channel_box.widget import (
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelBoxWidget,
)


def _events() -> None:
    """選択同期と旧Binding・削除行の遅延破棄を完了する。"""
    for _ in range(4):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set_value(path: str, value: float) -> None:
    """Maya commandの可変引数を数値書込みの境界へ閉じる。"""
    cast(Callable[[str, float], None], cmds.setAttr)(path, value)


def _row(editor: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """指定した属性名の値入力行を返す。"""
    row = next(r for r in editor.row_widgets if r.row.attribute.name == name)
    assert isinstance(row, AttributeRowWidget)
    return row


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """値とenum定義が異なる、同構成の二つのtransformを表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    auto_key = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    for index, name in enumerate(("reuseA", "reuseB")):
        cmds.createNode("transform", name=name)
        _set_value(name + ".translateX", 2.0 + index)
        cmds.addAttr(
            name,
            longName="gain",
            attributeType="double",
            minValue=0,
            maxValue=10,
            keyable=True,
        )
        _set_value(name + ".gain", 1.0 + index)
        cmds.addAttr(
            name,
            longName="mode",
            attributeType="enum",
            enumName="Off:On" if index == 0 else "Low:Middle:High",
            keyable=True,
        )
        cmds.addAttr(name, longName="note", dataType="string", keyable=True)
        cast(Callable[..., None], cmds.setAttr)(
            name + ".note", f"note{index}", type="string"
        )
    cmds.select("reuseA", replace=True)
    widget = ChannelBoxWidget()
    widget.controller.set_attribute_filter("all")
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


def test_selection_reuses_views_with_new_bindings(
    editor: ChannelBoxWidget,
) -> None:
    """全行の部品を保持し、旧入力を即停止して新しい対象だけへ書き込む。"""
    before = editor.row_widgets
    old = _row(editor, "translateX").row.binding
    assert isinstance(old, MayaFloatPlugsBinding)
    key = ("translate.translateX", "distance")
    editor.table_view.select_keys((key,))
    cmds.select("reuseB", replace=True)
    assert old.is_disposed
    with pytest.raises(RuntimeError):
        old.set_value(99.0)
    _events()
    assert editor.row_widgets == before
    assert editor.table_view.selected_keys() == ()
    row = _row(editor, "translateX")
    assert isinstance(row.editor, FloatValueStepSpinBox)
    assert isinstance(row.row.binding, MayaFloatPlugsBinding)
    assert row.row.binding.value == 3.0
    row.editor.spin_box.setValue(8.0)
    assert cmds.getAttr("reuseA.translateX") == 2.0
    assert cmds.getAttr("reuseB.translateX") == 8.0
    cmds.undo()
    _events()
    assert row.row.binding.value == 3.0
    assert editor.row_widgets == before


def test_attribute_difference_replaces_only_affected_rows(
    editor: ChannelBoxWidget,
) -> None:
    """属性増減と数値範囲の変化では、その属性だけを追加・破棄する。"""
    cmds.addAttr("reuseA", longName="onlyA", attributeType="double")
    cmds.addAttr("reuseB", longName="onlyB", attributeType="double")
    cmds.addAttr("reuseB.gain", edit=True, maxValue=20)
    _events()
    kept = _row(editor, "translateX")
    removed = _row(editor, "onlyA")
    changed = _row(editor, "gain")
    cmds.select("reuseB", replace=True)
    _events()
    assert _row(editor, "translateX") is kept
    assert _row(editor, "gain") is not changed
    assert not qt.isValid(changed)
    assert not qt.isValid(removed)
    assert _row(editor, "onlyB")
    gain = _row(editor, "gain").editor
    assert isinstance(gain, FloatSliderSpinBox)
    gain.spin_box.setValue(15.0)
    assert cmds.getAttr("reuseB.gain") == 15.0
    assert cmds.getAttr("reuseA.gain") == 1.0


def test_enum_definition_and_string_draft_follow_new_selection(
    editor: ChannelBoxWidget,
) -> None:
    """再利用するenumの項目を差し替え、旧文字列の下書きを持ち越さない。"""
    enum_row = _row(editor, "mode")
    string_row = _row(editor, "note")
    assert isinstance(enum_row.editor, EnumComboBox)
    assert isinstance(string_row.editor, StringLineEdit)
    string_row.editor.setFocus()
    string_row.editor.selectAll()
    string_row.editor.insert("old draft")
    cmds.select("reuseB", replace=True)
    _events()
    assert _row(editor, "mode") is enum_row
    assert _row(editor, "note") is string_row
    assert [
        enum_row.editor.itemText(i) for i in range(enum_row.editor.count())
    ] == ["Low", "Middle", "High"]
    assert string_row.editor.text() == "note1"
    qt.QApplication.sendEvent(
        string_row.editor,
        qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_Return,
            qt.Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert cmds.getAttr("reuseA.note") == "note0"
    assert cmds.getAttr("reuseB.note") == "note1"


def test_repeated_switch_does_not_duplicate_slider_session_signals(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """複数回の再利用後もslider開始は一回だけ通知し、Boolも新対象へ入力する。"""
    slider_row = _row(editor, "gain")
    for name in ("reuseB", "reuseA", "reuseB", "reuseA", "reuseB"):
        cmds.select(name, replace=True)
        _events()
    starts: list[bool] = []

    def begin(*, reuse_targets: bool = False) -> None:
        """signalの接続数だけを記録し、Mayaへ操作を書き込まない。"""
        starts.append(reuse_targets)

    monkeypatch.setattr(editor.controller, "begin_value_edit", begin)
    assert _row(editor, "gain") is slider_row
    assert isinstance(slider_row.editor, FloatSliderSpinBox)
    slider_row.editor.slider.editStarted.emit()
    assert starts == [True]
    visibility = _row(editor, "visibility").editor
    assert isinstance(visibility, BoolCheckBox)
    visibility.click()
    assert cmds.getAttr("reuseB.visibility") is False
    assert cmds.getAttr("reuseA.visibility") is True


def test_state_views_reuse_controls_and_switch_write_targets(
    editor: ChannelBoxWidget,
) -> None:
    """設定モードの共通部品を保持し、新しい対象のlockだけを切り替える。"""
    editor.controller.set_mode("states")
    _events()
    before = editor.row_widgets
    row = next(r for r in before if r.row.attribute.name == "translateX")
    assert isinstance(row, AttributeStateRowWidget)
    old = row.row.state_binding
    cmds.select("reuseB", replace=True)
    assert old.is_disposed
    _events()
    assert editor.row_widgets == before
    row.lock_check_box.click()
    assert cmds.getAttr("reuseB.translateX", lock=True)
    assert not cmds.getAttr("reuseA.translateX", lock=True)


def test_empty_and_coalesced_selection_do_not_keep_old_targets(
    editor: ChannelBoxWidget,
) -> None:
    """同期前の連続選択と選択解除でも、最後の対象と部品寿命が一致する。"""
    before = editor.row_widgets
    cmds.select("reuseB", replace=True)
    cmds.select("reuseA", replace=True)
    _events()
    assert editor.row_widgets == before
    assert _row(editor, "translateX").row.binding.value == 2.0
    cmds.select(clear=True)
    _events()
    assert not editor.row_widgets
    assert all(not qt.isValid(row) for row in before)
    cmds.select("reuseB", replace=True)
    _events()
    assert _row(editor, "translateX").row.binding.value == 3.0
