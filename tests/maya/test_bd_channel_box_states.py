# coding: utf-8
"""bdChannelBoxの表示・ロック操作とモード切替のMaya統合検証。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal, cast

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.ui import FloatValueStepSpinBox, qt

from bd_tools.bd_channel_box.controller import (
    ChannelAttributeFilter,
    ChannelBoxMode,
)
from bd_tools.bd_channel_box.widget import (
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelBoxWidget,
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


def _row_names(editor: ChannelBoxWidget) -> set[str]:
    """現在のモードで表示される正式属性名を返す。"""
    return {row.row.attribute.name for row in editor.row_widgets}


def _value_row(
    editor: ChannelBoxWidget, name: str = "weight"
) -> AttributeRowWidget:
    """正式属性名から最新の値入力行を取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeRowWidget)
    return row


def _state_row(
    editor: ChannelBoxWidget, name: str = "weight"
) -> AttributeStateRowWidget:
    """正式属性名から最新の表示・ロック行を取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row


def _state_keys(
    editor: ChannelBoxWidget, *names: str
) -> tuple[tuple[str, str], ...]:
    """表示・ロック行の正式pathと型を、表示順で返す。"""
    return tuple(
        (
            _state_row(editor, name).row.attribute.path,
            _state_row(editor, name).row.attribute.kind,
        )
        for name in names
    )


def _key(widget: qt.QWidget, key: qt.Qt.Key) -> None:
    """フォーカス中の入力部品へ、通常のキー操作を送る。"""
    widget.setFocus()
    for kind in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
        qt.QApplication.sendEvent(
            widget,
            qt.QtGui.QKeyEvent(
                kind,
                key,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )


def _states(editor: ChannelBoxWidget) -> None:
    """上部ComboBoxから表示・ロックモードへ切り替える。"""
    editor.mode_combo.setCurrentIndex(1)
    _events()
    assert editor.controller.mode == "states"


def _values(editor: ChannelBoxWidget) -> None:
    """上部ComboBoxから値編集モードへ切り替える。"""
    editor.mode_combo.setCurrentIndex(0)
    _events()
    assert editor.controller.mode == "values"


def _choose_display(
    editor: ChannelBoxWidget, display: _Display, name: str = "weight"
) -> None:
    """表示状態のラジオボタンをクリックして明示入力する。"""
    _state_row(editor, name).display_buttons[display].click()
    _events()


def _checked_display(
    editor: ChannelBoxWidget, name: str = "weight"
) -> tuple[_Display, ...]:
    """画面で選択中の表示状態を返し、混在時は空のtupleにする。"""
    return tuple(
        value
        for value, button in _state_row(editor, name).display_buttons.items()
        if button.isChecked()
    )


def _filter(editor: ChannelBoxWidget, value: ChannelAttributeFilter) -> None:
    """フィルターComboBoxを操作し、絞り込み後の行へ進める。"""
    index = editor.filter_combo.findData(value)
    assert index >= 0
    editor.filter_combo.setCurrentIndex(index)
    _events()
    assert editor.controller.attribute_filter == value


@pytest.fixture
def state_editor(
    qt_application: qt.QApplication,
) -> Iterator[ChannelBoxWidget]:
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
    widget = ChannelBoxWidget()
    widget.show()
    _events()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    file_command(new=True, force=True)


def test_mode_switch_only_reads_and_preserves_value_step(
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget, width: int
) -> None:
    """上部の説明と長いHide属性がある場合も、指定幅に収まる配置を維持する。"""
    editor = state_editor
    editor.resize(width, 600)
    _events()
    assert editor.width() == width
    assert editor.mode_combo.x() == editor.filter_combo.x()
    assert editor.mode_combo.width() == editor.filter_combo.width()
    for label, combo in (
        (editor.mode_label, editor.mode_combo),
        (editor.filter_label, editor.filter_combo),
    ):
        assert label.x() + label.width() < combo.x()
        assert label.width() >= label.fontMetrics().horizontalAdvance(
            label.text()
        )
        assert combo.width() >= combo.minimumSizeHint().width()
        assert combo.x() + combo.width() <= width
    value_row = _value_row(editor)
    before = (
        editor.width(),
        value_row.name_label.width(),
        value_row.editor.x(),
    )
    assert not editor.scroll_area.verticalScrollBar().isVisible()
    _states(editor)
    row = _state_row(editor)
    assert editor.width() == before[0]
    assert editor.scroll_area.verticalScrollBar().isVisible()
    assert row.name_label.width() < before[1]
    assert row.editor.x() < before[2]
    assert editor.scroll_area.horizontalScrollBar().maximum() == 0
    for current in editor.row_widgets:
        assert isinstance(current, AttributeStateRowWidget)
        assert current.editor.width() == 200
        assert current.editor.x() + current.editor.width() == current.width()
        buttons = (*current.display_buttons.values(), current.lock_check_box)
        for button in buttons:
            assert button.width() >= button.sizeHint().width()
            assert 0 <= button.x()
            assert button.x() + button.width() <= current.editor.width()
        for left, right in zip(buttons, buttons[1:]):
            assert left.x() + left.width() < right.x()
    _values(editor)
    assert not editor.scroll_area.verticalScrollBar().isVisible()
    restored = _value_row(editor)
    assert (
        editor.width(),
        restored.name_label.width(),
        restored.editor.x(),
    ) == before


@pytest.mark.parametrize("mode", ["values", "states"])
@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        ("all", {"weight", "mode", "hiddenValue", "longHiddenValue"}),
        ("visible", {"weight", "mode"}),
        ("keyable", {"weight"}),
        ("channel_box", {"mode"}),
        ("hidden", {"hiddenValue", "longHiddenValue"}),
    ],
)
def test_five_filters_in_both_modes_only_read_representative_state(
    state_editor: ChannelBoxWidget,
    mode: ChannelBoxMode,
    selected: ChannelAttributeFilter,
    expected: set[str],
) -> None:
    """両モードの五種類の絞り込みは、基準属性だけで判定してsceneを変えない。"""
    editor = state_editor
    cmds.setAttr("stateA.mode", keyable=False)
    cmds.setAttr("stateA.mode", channelBox=True)
    _events()
    editor.controller.set_mode(mode)
    attributes = ("weight", "mode", "hiddenValue", "longHiddenValue")
    before = {
        f"{node}.{name}": _flags(f"{node}.{name}")
        for node in _NODES
        for name in attributes
    }
    cmds.flushUndo()
    _filter(editor, selected)
    assert _row_names(editor).intersection(attributes) == expected
    assert {path: _flags(path) for path in before} == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_filters_remember_each_mode_through_refresh_and_selection(
    state_editor: ChannelBoxWidget,
) -> None:
    """初期値を維持しつつ、各モードの最終フィルターをWindow内だけに保持する。"""
    editor = state_editor
    assert editor.filter_combo.currentData() == "visible"
    _filter(editor, "keyable")
    _states(editor)
    assert editor.filter_combo.currentData() == "all"
    _filter(editor, "hidden")
    _values(editor)
    assert editor.filter_combo.currentData() == "keyable"
    _states(editor)
    assert editor.filter_combo.currentData() == "hidden"
    editor.refresh()
    cmds.select("stateB", replace=True)
    _events()
    assert editor.controller.attribute_filter == "hidden"
    assert editor.filter_combo.currentData() == "hidden"
    fresh = ChannelBoxWidget()
    try:
        assert fresh.controller.attribute_filter == "visible"
        fresh.controller.set_mode("states")
        assert fresh.controller.attribute_filter == "all"
    finally:
        fresh.dispose()
        fresh.deleteLater()
        _events()


def test_filtered_display_edit_completes_all_targets_before_row_removal(
    state_editor: ChannelBoxWidget,
) -> None:
    """状態の一括変更完了後に行を外し、UndoとRedoで該当行が出入りする。"""
    editor = state_editor
    _states(editor)
    _filter(editor, "keyable")
    binding = _state_row(editor).row.state_binding
    binding.set_display_state("hidden")
    assert not binding.is_disposed
    assert [_flags(name + ".weight") for name in _NODES] == [
        (False, False, False),
        (False, False, False),
    ]
    _events()
    assert binding.is_disposed
    assert "weight" not in _row_names(editor)
    cmds.undo()
    _events()
    assert "weight" in _row_names(editor)
    assert all(_flags(name + ".weight")[0] for name in _NODES)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert "weight" not in _row_names(editor)
    _filter(editor, "all")
    assert _checked_display(editor) == ("hidden",)


@pytest.mark.parametrize("mode", ["values", "states"])
def test_external_channel_box_flag_updates_filter_without_propagation(
    state_editor: ChannelBoxWidget, mode: ChannelBoxMode
) -> None:
    """keyableを変えない外部ChannelBox操作にも追従し、他ノードへ転送しない。"""
    editor = state_editor
    editor.controller.set_mode(mode)
    _filter(editor, "channel_box")
    assert "hiddenValue" not in _row_names(editor)
    cmds.setAttr("stateB.hiddenValue", channelBox=True)
    _events()
    assert "hiddenValue" not in _row_names(editor)
    cmds.setAttr("stateA.hiddenValue", channelBox=True)
    _events()
    assert "hiddenValue" in _row_names(editor)
    cmds.setAttr("stateA.hiddenValue", channelBox=False)
    _events()
    assert "hiddenValue" not in _row_names(editor)
    assert _flags("stateB.hiddenValue") == (False, True, False)


def test_hidden_value_edit_preserves_flags_and_respects_lock_and_connection(
    state_editor: ChannelBoxWidget,
) -> None:
    """Hide属性も一括で値編集でき、lockと入力接続による操作制限を維持する。"""
    editor = state_editor
    _filter(editor, "hidden")
    binding = _value_row(editor, "hiddenValue").row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    binding.set_value(0.5)
    _events()
    assert [cmds.getAttr(n + ".hiddenValue") for n in _NODES] == [0.5, 0.5]
    assert [_flags(n + ".hiddenValue") for n in _NODES] == [
        (False, False, False),
        (False, False, False),
    ]
    cmds.undo()
    _events()
    assert [cmds.getAttr(n + ".hiddenValue") for n in _NODES] == [0, 0]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.setAttr("stateA.hiddenValue", lock=True)
    _events()
    assert not _value_row(
        editor, "hiddenValue"
    ).row.binding.view_model.set_value_command.can_execute
    cmds.setAttr("stateA.hiddenValue", lock=False)
    cmds.connectAttr("stateA.weight", "stateA.hiddenValue")
    _events()
    assert not _value_row(
        editor, "hiddenValue"
    ).row.binding.view_model.set_value_command.can_execute


def test_filter_switch_finishes_drag_and_preserves_step(
    state_editor: ChannelBoxWidget,
) -> None:
    """絞り込みで連続編集のUndoを閉じ、非表示にした値行のstepを維持する。"""
    editor = state_editor
    step = _value_row(editor, "translateX").editor
    assert isinstance(step, FloatValueStepSpinBox)
    step.setSingleStep(0.01)
    binding = _value_row(editor).row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    assert binding.view_model.begin_edit(qt.QObject(editor))
    binding.set_value(0.4)
    binding.set_value(0.6)
    _filter(editor, "hidden")
    assert binding.is_disposed
    hidden_binding = _value_row(editor, "hiddenValue").row.binding
    assert isinstance(hidden_binding, MayaFloatPlugsBinding)
    hidden_binding.set_value(0.5)
    cmds.undo()
    _events()
    assert [cmds.getAttr(n + ".hiddenValue") for n in _NODES] == [0, 0]
    assert [cmds.getAttr(n + ".weight") for n in _NODES] == [0.6, 0.6]
    cmds.undo()
    _events()
    assert [cmds.getAttr(n + ".weight") for n in _NODES] == [0.25, 0.75]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    _filter(editor, "visible")
    restored = _value_row(editor, "translateX").editor
    assert isinstance(restored, FloatValueStepSpinBox)
    assert restored.singleStep() == 0.01


def test_filter_combo_keeps_keyboard_focus_and_empty_filter_is_recoverable(
    state_editor: ChannelBoxWidget,
) -> None:
    """上下キーで空の絞り込みからも戻れ、フォーカスと表示操作だけを維持する。"""
    editor = state_editor
    _filter(editor, "keyable")
    combo = editor.filter_combo
    combo.setFocus()
    _events()
    for key, expected in (
        (qt.Qt.Key.Key_Down, "channel_box"),
        (qt.Qt.Key.Key_Up, "keyable"),
    ):
        qt.QApplication.sendEvent(
            combo,
            qt.QtGui.QKeyEvent(
                qt.QEvent.Type.KeyPress,
                key,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )
        _events()
        assert editor.controller.attribute_filter == expected
        assert combo.hasFocus()
        assert editor.empty_label.isVisible() == (expected == "channel_box")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_filter_switch_commits_pending_numeric_text_as_value_edit(
    state_editor: ChannelBoxWidget,
) -> None:
    """数値の未確定文字をフィルター変更時に確定し、一回のUndoで戻す。"""
    view = _value_row(state_editor, "translateX").editor
    assert isinstance(view, FloatValueStepSpinBox)
    spin = view.spin_box
    spin.setFocus()
    spin.selectAll()
    _events()
    qt.QApplication.sendEvent(
        spin,
        qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_4,
            qt.Qt.KeyboardModifier.NoModifier,
            "4",
        ),
    )
    assert [cmds.getAttr(n + ".tx") for n in _NODES] == [0, 0]
    _filter(state_editor, "hidden")
    assert [cmds.getAttr(n + ".tx") for n in _NODES] == [4, 4]
    cmds.undo()
    _events()
    assert [cmds.getAttr(n + ".tx") for n in _NODES] == [0, 0]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_hidden_attribute_can_be_restored_and_hidden_row_stays_available(
    state_editor: ChannelBoxWidget,
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
    assert _checked_display(editor, "hiddenValue") == ("hidden",)
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
    state_editor: ChannelBoxWidget, display: _Display
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
    assert _checked_display(editor) == (display,)


def test_selected_display_control_aligns_rows_and_groups_undo(
    state_editor: ChannelBoxWidget,
) -> None:
    """選択行の選択済みradioを再操作し、他の選択行も同じ状態へ揃える。"""
    editor = state_editor
    _states(editor)
    _choose_display(editor, "hidden", "translateY")
    before = {
        f"{node}.{name}": _flags(f"{node}.{name}")
        for node in _NODES
        for name in ("translateX", "translateY")
    }
    selected = _state_keys(editor, "translateX", "translateY")
    editor.table_view.select_keys(selected)
    source = _state_row(editor, "translateX")
    assert source.display_buttons["keyable"].isChecked()
    cmds.flushUndo()

    source.display_buttons["keyable"].click()
    _events()
    for node in _NODES:
        for name in ("translateX", "translateY"):
            assert _flags(f"{node}.{name}") == (True, False, False)
    assert editor.table_view.selected_keys() == selected

    cmds.undo()
    _events()
    assert {path: _flags(path) for path in before} == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize(
    ("initial", "expected"),
    (("unlocked", True), ("locked", False), ("mixed", True)),
)
def test_selected_lock_control_uses_resulting_state_and_groups_undo(
    state_editor: ChannelBoxWidget,
    initial: str,
    expected: bool,
) -> None:
    """選択行のlockを、操作元の次状態へキー入力で一括変更する。"""
    editor = state_editor
    _states(editor)
    attributes = ("translateX", "translateY")
    if initial == "locked":
        for node in _NODES:
            for name in attributes:
                cmds.setAttr(f"{node}.{name}", lock=True)
    elif initial == "mixed":
        cmds.setAttr("stateA.translateX", lock=True)
        cmds.setAttr("stateB.translateY", lock=True)
    _events()
    before = {
        f"{node}.{name}": _flags(f"{node}.{name}")
        for node in _NODES
        for name in attributes
    }
    selected = _state_keys(editor, *attributes)
    editor.table_view.select_keys(selected)
    cmds.flushUndo()

    _key(_state_row(editor, "translateX").lock_check_box, qt.Qt.Key.Key_Space)
    _events()
    for node in _NODES:
        for name in attributes:
            assert bool(cmds.getAttr(f"{node}.{name}", lock=True)) is expected
    assert editor.table_view.selected_keys() == selected

    cmds.undo()
    _events()
    assert {path: _flags(path) for path in before} == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_unselected_state_control_changes_only_its_row(
    state_editor: ChannelBoxWidget,
) -> None:
    """既存選択の外にある操作部品は、その行だけを変更する。"""
    editor = state_editor
    _states(editor)
    selected = _state_keys(editor, "translateX", "translateY")
    editor.table_view.select_keys(selected)
    cmds.flushUndo()

    _state_row(editor, "translateZ").lock_check_box.click()
    _events()
    for node in _NODES:
        assert cmds.getAttr(f"{node}.translateZ", lock=True)
        assert not cmds.getAttr(f"{node}.translateX", lock=True)
        assert not cmds.getAttr(f"{node}.translateY", lock=True)
    assert editor.table_view.selected_keys() == selected

    cmds.undo()
    _events()
    assert all(
        not cmds.getAttr(f"{node}.translateZ", lock=True) for node in _NODES
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mixed_display_is_explicit_and_undo_restores_each_node(
    state_editor: ChannelBoxWidget,
) -> None:
    """表示状態の混在を示し、同じ代表状態の選択でも全対象へ揃えられる。"""
    cmds.setAttr("stateB.weight", keyable=False, channelBox=True)
    _events()
    _states(state_editor)
    row = _state_row(state_editor)
    assert _checked_display(state_editor) == ()
    assert all("混在" in b.toolTip() for b in row.display_buttons.values())
    assert row.name_label.text().startswith("• ")
    before = [_flags(name + ".weight") for name in _NODES]
    cmds.flushUndo()
    _choose_display(state_editor, "keyable")
    assert all(_flags(name + ".weight")[0] for name in _NODES)
    cmds.undo()
    _events()
    assert [_flags(name + ".weight") for name in _NODES] == before
    assert _checked_display(state_editor) == ()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_value_mixed_marker_does_not_leak_into_state_mode(
    state_editor: ChannelBoxWidget,
) -> None:
    """値だけが混在している行を、表示・ロックの混在として示さない。"""
    assert _value_row(state_editor).name_label.text().startswith("• ")
    _states(state_editor)
    assert not _state_row(state_editor).name_label.text().startswith("• ")
    assert _checked_display(state_editor) == ("keyable",)


def test_lock_and_unlock_representative_do_not_depend_on_value_writability(
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget,
) -> None:
    """外部で変更した状態は混在表示へ同期し、別ノードへ転送しない。"""
    _states(state_editor)
    cmds.setAttr("stateA.weight", keyable=False, channelBox=True)
    cmds.setAttr("stateA.weight", lock=True)
    _events()
    row = _state_row(state_editor)
    assert _checked_display(state_editor) == ()
    assert row.lock_check_box.checkState() == qt.Qt.CheckState.PartiallyChecked
    assert _flags("stateB.weight") == (True, False, False)


def test_mode_switch_finishes_drag_before_lock_undo(
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget,
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
    if row.display_buttons["hidden"].isEnabled():
        _choose_display(state_editor, "hidden", "translateX")
    assert bool(cmds.getAttr("stateA.translate", lock=True))


def test_state_binding_stops_on_selection_and_dispose(
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget,
) -> None:
    """同じ表示状態の明示選択はUndo履歴を増やさない。"""
    _states(state_editor)
    _choose_display(state_editor, "keyable")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_display_radio_keyboard_stays_independent_of_lock_and_other_rows(
    state_editor: ChannelBoxWidget,
) -> None:
    """矢印とSpaceで表示状態だけを変更し、ロックや別行の選択へ影響させない。"""
    editor = state_editor
    _states(editor)
    row = _state_row(editor)
    editor.scroll_area.ensureWidgetVisible(row)
    _events()
    row.display_buttons["keyable"].setFocus()
    for key, expected in (
        (qt.Qt.Key.Key_Right, "channel_box"),
        (qt.Qt.Key.Key_Right, "hidden"),
        (qt.Qt.Key.Key_Left, "channel_box"),
    ):
        focused = next(b for b in row.display_buttons.values() if b.hasFocus())
        cmds.flushUndo()
        for event_type in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
            qt.QApplication.sendEvent(
                focused,
                qt.QtGui.QKeyEvent(
                    event_type, key, qt.Qt.KeyboardModifier.NoModifier
                ),
            )
        _events()
        assert _checked_display(editor) == (expected,)
        assert [_flags(n + ".weight") for n in _NODES] == [
            (False, expected == "channel_box", False),
        ] * 2
        assert _checked_display(editor, "hiddenValue") == ("hidden",)
    row.display_buttons["keyable"].setFocus()
    for event_type in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
        qt.QApplication.sendEvent(
            row.display_buttons["keyable"],
            qt.QtGui.QKeyEvent(
                event_type,
                qt.Qt.Key.Key_Space,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )
    _events()
    assert _checked_display(editor) == ("keyable",)
    assert [_flags(n + ".weight") for n in _NODES] == [
        (True, False, False)
    ] * 2


def test_disabled_display_radios_do_not_write(
    state_editor: ChannelBoxWidget,
) -> None:
    """編集不可の行では3つとも無効にし、クリックで状態やUndoを変更しない。"""
    # 両フラグが属性定義で有効な状態は標準Undoで復元できず、表示変更だけ不可になる
    cmds.deleteAttr("stateA.weight")
    definition = om.MFnNumericAttribute()
    attribute = definition.create(
        "weight", "weight", om.MFnNumericData.kDouble
    )
    definition.keyable = True
    definition.channelBox = True
    selection = om.MSelectionList()
    selection.add("stateA")
    om.MFnDependencyNode(selection.getDependNode(0)).addAttribute(attribute)
    _events()
    _states(state_editor)
    row = _state_row(state_editor)
    before = [_flags(n + ".weight") for n in _NODES]
    assert row.lock_check_box.isEnabled()
    cmds.flushUndo()
    for button in row.display_buttons.values():
        assert not button.isEnabled()
        button.click()
    _events()
    assert [_flags(n + ".weight") for n in _NODES] == before
    assert _checked_display(state_editor) == ("keyable",)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mode_combo_keeps_keyboard_focus_for_round_trip(
    state_editor: ChannelBoxWidget,
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
    state_editor: ChannelBoxWidget,
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
