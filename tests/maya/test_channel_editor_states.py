# coding: utf-8
"""Channel Editorの表示・ロック操作とモード切替のMaya統合検証。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal, cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.ui import FloatValueStepSpinBox, qt

from bd_tools.channel_editor.widget import (
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelEditorWidget,
)

_NODES = ("stateA", "stateB")
_Display = Literal["keyable", "channel_box", "hidden"]


def _events() -> None:
    """遅延同期とWidget破棄を処理し、最新の行へ進める。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set_value(name: str, value: float) -> None:
    """Maya commandの可変引数境界だけを補正して数値を設定する。"""
    cast(Callable[[str, float], None], cmds.setAttr)(name, value)


def _flags(path: str) -> tuple[bool, bool, bool]:
    """属性のkeyable・channelBox・自身のlockを順に取得する。"""
    return (
        bool(cmds.getAttr(path, keyable=True)),
        bool(cmds.getAttr(path, channelBox=True)),
        bool(cmds.getAttr(path, lock=True)),
    )


def _row_names(editor: ChannelEditorWidget) -> set[str]:
    """現在のモードで表示される正式属性名を返す。"""
    return {row.row.attribute.name for row in editor.row_widgets}


def _value_row(
    editor: ChannelEditorWidget, name: str = "weight"
) -> AttributeRowWidget:
    """正式属性名から最新の値入力行を取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeRowWidget)
    return row


def _state_row(
    editor: ChannelEditorWidget, name: str = "weight"
) -> AttributeStateRowWidget:
    """正式属性名から最新の表示・ロック行を取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row


def _states(editor: ChannelEditorWidget) -> None:
    """上部ComboBoxから表示・ロックモードへ切り替える。"""
    editor.mode_combo.setCurrentIndex(1)
    _events()
    assert editor.controller.mode == "states"


def _values(editor: ChannelEditorWidget) -> None:
    """上部ComboBoxから値編集モードへ切り替える。"""
    editor.mode_combo.setCurrentIndex(0)
    _events()
    assert editor.controller.mode == "values"


def _choose_display(
    editor: ChannelEditorWidget, display: _Display, name: str = "weight"
) -> None:
    """表示状態の項目を明示選択し、同じ項目の選び直しも通知する。"""
    combo = _state_row(editor, name).display_combo
    index = combo.findData(display)
    assert index >= 0
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    _events()


@pytest.fixture
def state_editor(
    qt_application: qt.QApplication,
) -> Iterator[ChannelEditorWidget]:
    """既存のHide属性と異なる値を持つ2ノードを値モードで表示する。"""
    assert qt_application is not None
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)
    for name, value in zip(_NODES, (0.25, 0.75)):
        cmds.createNode("transform", name=name)
        cmds.addAttr(
            name,
            longName="weight",
            attributeType="double",
            minValue=0,
            maxValue=1,
            keyable=True,
        )
        _set_value(f"{name}.weight", value)
        cmds.addAttr(name, longName="hiddenValue", attributeType="double")
        cmds.addAttr(
            name,
            longName="longHiddenValue",
            niceName="Hidden attribute with a very long display name",
            attributeType="double",
        )
        cmds.addAttr(
            name,
            longName="mode",
            attributeType="enum",
            enumName="Off:Preview:Final",
            keyable=True,
        )
    cmds.select(*_NODES, replace=True)
    cmds.flushUndo()
    widget = ChannelEditorWidget()
    widget.show()
    _events()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    file_command(new=True, force=True)


def test_mode_switch_only_reads_and_preserves_value_step(
    state_editor: ChannelEditorWidget,
) -> None:
    """モード切替・表示更新は値とフラグとUndoを維持し、stepも失わない。"""
    editor = state_editor
    assert editor.controller.mode == "values"
    assert editor.mode_combo.currentIndex() == 0
    assert "hiddenValue" not in _row_names(editor)
    step = _value_row(editor, "translateX").editor
    assert isinstance(step, FloatValueStepSpinBox)
    step.setSingleStep(0.01)
    before = [_flags(name + ".weight") for name in _NODES]

    # 設定行の初期描画や再構築から一括変更を発生させない
    _states(editor)
    assert "hiddenValue" in _row_names(editor)
    editor.refresh()
    _events()
    _values(editor)
    restored = _value_row(editor, "translateX").editor
    assert isinstance(restored, FloatValueStepSpinBox)
    assert restored.singleStep() == 0.01
    assert [_flags(name + ".weight") for name in _NODES] == before
    assert [cmds.getAttr(name + ".weight") for name in _NODES] == [0.25, 0.75]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("width", [280, 360, 520])
def test_mode_switch_preserves_width_with_long_hidden_name(
    state_editor: ChannelEditorWidget, width: int
) -> None:
    """長いHide属性が増えても、Window幅と共通行の名前列・入力列を維持する。"""
    editor = state_editor
    editor.resize(width, 360)
    _events()
    value_row = _value_row(editor)
    before = (
        editor.width(),
        value_row.name_label.width(),
        value_row.editor.x(),
    )
    _states(editor)
    row = _state_row(editor)
    assert (editor.width(), row.name_label.width(), row.editor.x()) == before
    assert editor.scroll_area.horizontalScrollBar().maximum() == 0
    for current in editor.row_widgets:
        assert isinstance(current, AttributeStateRowWidget)
        assert current.editor.width() == 156
        assert current.editor.x() + current.editor.width() == current.width()
    _values(editor)
    restored = _value_row(editor)
    assert (
        editor.width(),
        restored.name_label.width(),
        restored.editor.x(),
    ) == before


def test_hidden_attribute_can_be_restored_and_hidden_row_stays_available(
    state_editor: ChannelEditorWidget,
) -> None:
    """既存Hideを復帰でき、Hideへ変更した行も設定中と再選択後に操作できる。"""
    editor = state_editor
    _states(editor)
    _choose_display(editor, "channel_box", "hiddenValue")
    assert [_flags(name + ".hiddenValue") for name in _NODES] == [
        (False, True, False),
        (False, True, False),
    ]
    _values(editor)
    assert "hiddenValue" in _row_names(editor)
    _states(editor)
    _choose_display(editor, "hidden", "hiddenValue")
    assert "hiddenValue" in _row_names(editor)
    assert (
        _state_row(editor, "hiddenValue").display_combo.currentData()
        == "hidden"
    )
    cmds.select(clear=True)
    _events()
    cmds.select(*_NODES, replace=True)
    _events()
    assert "hiddenValue" in _row_names(editor)
    _choose_display(editor, "keyable", "hiddenValue")
    _values(editor)
    assert "hiddenValue" in _row_names(editor)


@pytest.mark.parametrize("display", ["channel_box", "hidden"])
def test_display_change_has_one_undo_and_redo(
    state_editor: ChannelEditorWidget, display: _Display
) -> None:
    """表示変更を一回のUndoで両対象の元フラグへ戻し、Redoで再適用する。"""
    editor = state_editor
    _states(editor)
    before = [_flags(name + ".weight") for name in _NODES]
    _choose_display(editor, display)
    expected = (False, display == "channel_box", False)
    assert [_flags(name + ".weight") for name in _NODES] == [
        expected,
        expected,
    ]
    cmds.undo()
    _events()
    assert [_flags(name + ".weight") for name in _NODES] == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert [_flags(name + ".weight") for name in _NODES] == [
        expected,
        expected,
    ]
    assert _state_row(editor).display_combo.currentData() == display


def test_mixed_display_is_explicit_and_undo_restores_each_node(
    state_editor: ChannelEditorWidget,
) -> None:
    """表示状態の混在を示し、同じ代表状態の選択でも全対象へ揃えられる。"""
    cmds.setAttr("stateB.weight", keyable=False, channelBox=True)
    _events()
    _states(state_editor)
    row = _state_row(state_editor)
    assert "混在" in row.display_combo.currentText()
    assert row.name_label.text().startswith("• ")
    before = [_flags(name + ".weight") for name in _NODES]
    cmds.flushUndo()
    _choose_display(state_editor, "keyable")
    assert all(_flags(name + ".weight")[0] for name in _NODES)
    cmds.undo()
    _events()
    assert [_flags(name + ".weight") for name in _NODES] == before
    assert "混在" in _state_row(state_editor).display_combo.currentText()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_value_mixed_marker_does_not_leak_into_state_mode(
    state_editor: ChannelEditorWidget,
) -> None:
    """値だけが混在している行を、表示・ロックの混在として示さない。"""
    assert _value_row(state_editor).name_label.text().startswith("• ")
    _states(state_editor)
    assert not _state_row(state_editor).name_label.text().startswith("• ")
    assert "混在" not in _state_row(state_editor).display_combo.currentText()


def test_lock_and_unlock_representative_do_not_depend_on_value_writability(
    state_editor: ChannelEditorWidget,
) -> None:
    """代表がロック中でも解除でき、値入力へ戻ると編集可能状態を反映する。"""
    editor = state_editor
    _states(editor)
    _state_row(editor).lock_check_box.click()
    _events()
    assert all(_flags(name + ".weight")[2] for name in _NODES)
    _values(editor)
    binding = _value_row(editor).row.binding
    assert not binding.view_model.set_value_command.can_execute
    _states(editor)
    assert _state_row(editor).lock_check_box.isEnabled()
    assert _state_row(editor).lock_check_box.isChecked()
    cmds.flushUndo()
    _state_row(editor).lock_check_box.click()
    _events()
    assert not any(_flags(name + ".weight")[2] for name in _NODES)
    cmds.undo()
    _events()
    assert all(_flags(name + ".weight")[2] for name in _NODES)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mixed_lock_user_clicks_only_choose_locked_or_unlocked(
    state_editor: ChannelEditorWidget,
) -> None:
    """混在lockは三状態で表示し、ユーザー操作ではTrueとFalseだけへ揃える。"""
    cmds.setAttr("stateB.weight", lock=True)
    _events()
    _states(state_editor)
    check = _state_row(state_editor).lock_check_box
    assert check.checkState() == qt.Qt.CheckState.PartiallyChecked
    cmds.flushUndo()
    check.click()
    _events()
    first = [_flags(name + ".weight")[2] for name in _NODES]
    assert first[0] == first[1]
    assert _state_row(state_editor).lock_check_box.checkState() != (
        qt.Qt.CheckState.PartiallyChecked
    )
    cmds.undo()
    _events()
    assert [_flags(name + ".weight")[2] for name in _NODES] == [False, True]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_enum_definition_difference_does_not_exclude_state_editing(
    state_editor: ChannelEditorWidget,
) -> None:
    """値入力から除外されるenum定義違いも表示・ロック操作には含める。"""
    cmds.addAttr("stateB.mode", edit=True, enumName="Other=5:Different=10")
    state_editor.refresh()
    assert _value_row(state_editor, "mode").row.binding.target_count == 1
    _states(state_editor)
    _choose_display(state_editor, "hidden", "mode")
    assert [_flags(name + ".mode") for name in _NODES] == [
        (False, False, False),
        (False, False, False),
    ]
    _state_row(state_editor, "mode").lock_check_box.click()
    _events()
    assert all(_flags(name + ".mode")[2] for name in _NODES)


def test_external_state_change_does_not_propagate(
    state_editor: ChannelEditorWidget,
) -> None:
    """外部で変更した状態は混在表示へ同期し、別ノードへ転送しない。"""
    _states(state_editor)
    cmds.setAttr("stateA.weight", keyable=False, channelBox=True)
    cmds.setAttr("stateA.weight", lock=True)
    _events()
    row = _state_row(state_editor)
    assert "混在" in row.display_combo.currentText()
    assert row.lock_check_box.checkState() == qt.Qt.CheckState.PartiallyChecked
    assert _flags("stateB.weight") == (True, False, False)


def test_mode_switch_finishes_drag_before_lock_undo(
    state_editor: ChannelEditorWidget,
) -> None:
    """モード切替でSliderの連続Undoを閉じ、続くlock操作と分離する。"""
    binding = _value_row(state_editor).row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    owner = qt.QObject(state_editor)
    assert binding.view_model.begin_edit(owner)
    binding.set_value(0.4)
    binding.set_value(0.6)
    _states(state_editor)
    assert binding.is_disposed
    _state_row(state_editor).lock_check_box.click()
    _events()
    cmds.undo()
    _events()
    assert not any(_flags(name + ".weight")[2] for name in _NODES)
    assert [cmds.getAttr(name + ".weight") for name in _NODES] == [0.6, 0.6]
    cmds.undo()
    _events()
    assert [cmds.getAttr(name + ".weight") for name in _NODES] == [0.25, 0.75]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_parent_lock_is_never_implicitly_removed(
    state_editor: ChannelEditorWidget,
) -> None:
    """子行のlock操作と表示変更でcompound親のlockを勝手に解除しない。"""
    cmds.setAttr("stateA.translate", lock=True)
    _events()
    _states(state_editor)
    row = _state_row(state_editor, "translateX")
    if row.lock_check_box.isEnabled():
        row.lock_check_box.click()
        _events()
    assert bool(cmds.getAttr("stateA.translate", lock=True))
    row = _state_row(state_editor, "translateX")
    if row.display_combo.isEnabled():
        _choose_display(state_editor, "hidden", "translateX")
    assert bool(cmds.getAttr("stateA.translate", lock=True))


def test_state_binding_stops_on_selection_and_dispose(
    state_editor: ChannelEditorWidget,
) -> None:
    """選択切替と終了で古い状態Bindingを破棄し、監視を再生成しない。"""
    _states(state_editor)
    old = _state_row(state_editor).row.state_binding
    cmds.select("stateB", replace=True)
    _events()
    assert old.is_disposed
    current = _state_row(state_editor).row.state_binding
    state_editor.dispose()
    assert current.is_disposed
    cmds.select("stateA", replace=True)
    _events()
    assert state_editor.controller.is_disposed
    assert not state_editor.controller.rows


def test_display_noop_does_not_add_undo(
    state_editor: ChannelEditorWidget,
) -> None:
    """同じ表示状態の明示選択はUndo履歴を増やさない。"""
    _states(state_editor)
    _choose_display(state_editor, "keyable")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mode_combo_keeps_keyboard_focus_for_round_trip(
    state_editor: ChannelEditorWidget,
) -> None:
    """上部ComboBoxの上下キーだけで両モードを往復できる。"""
    combo = state_editor.mode_combo
    combo.setFocus()
    _events()
    for key, expected in (
        (qt.Qt.Key.Key_Down, "states"),
        (qt.Qt.Key.Key_Up, "values"),
    ):
        event = qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress, key, qt.Qt.KeyboardModifier.NoModifier
        )
        qt.QApplication.sendEvent(combo, event)
        _events()
        assert state_editor.controller.mode == expected
        assert combo.hasFocus()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mode_switch_commits_pending_numeric_text_as_value_edit(
    state_editor: ChannelEditorWidget,
) -> None:
    """未確定の数値は切替時のフォーカス移動で確定し、一回のUndoで戻る。"""
    view = _value_row(state_editor, "translateX").editor
    assert isinstance(view, FloatValueStepSpinBox)
    spin = view.spin_box
    spin.setFocus()
    spin.selectAll()
    _events()
    event = qt.QtGui.QKeyEvent(
        qt.QEvent.Type.KeyPress,
        qt.Qt.Key.Key_4,
        qt.Qt.KeyboardModifier.NoModifier,
        "4",
    )
    qt.QApplication.sendEvent(spin, event)
    assert [cmds.getAttr(name + ".tx") for name in _NODES] == [0, 0]
    _states(state_editor)
    assert [cmds.getAttr(name + ".tx") for name in _NODES] == [4, 4]
    cmds.undo()
    _events()
    assert [cmds.getAttr(name + ".tx") for name in _NODES] == [0, 0]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
