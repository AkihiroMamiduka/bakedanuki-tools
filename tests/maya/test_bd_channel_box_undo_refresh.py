# coding: utf-8
"""Undoの値同期と、構成が変わる場合だけの入力行再構築を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal, cast

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from bd_util.maya.ui import MayaCallbackRegistry
from bd_util.ui import (
    EnumComboBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    IntSliderSpinBox,
    IntValueStepSpinBox,
    StringLineEdit,
    qt,
)
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget

_NODES = ("undoOther", "undoReference")


def _events() -> None:
    """遅延した値同期、構成確認と旧入力欄の削除を完了する。"""
    for _ in range(4):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set(path: str, value: float | int | bool | str) -> None:
    """動的なMayaコマンド境界で型を限定してscalar値を設定する。"""
    if isinstance(value, str):
        cmds.setAttr(path, value, type="string")
    else:
        cast(Callable[[str, float | int | bool], None], cmds.setAttr)(
            path, value
        )


def _values(name: str) -> tuple[object, ...]:
    """操作対象二ノードの実値を取得する。"""
    return tuple(cmds.getAttr(f"{node}.{name}") for node in _NODES)


def _row(editor: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """属性の正式名に対応する値入力行を取得する。"""
    result = next(
        widget
        for widget in editor.row_widgets
        if widget.row.attribute.name == name
    )
    assert isinstance(result, AttributeRowWidget)
    return result


def _names(editor: ChannelBoxWidget) -> set[str]:
    """現在の入力行にある属性名を返す。"""
    return {widget.row.attribute.name for widget in editor.row_widgets}


def _record_rebuilds(editor: ChannelBoxWidget) -> list[None]:
    """構成再構築の完了通知だけを記録する。"""
    rebuilt: list[None] = []

    def changed() -> None:
        """全行の再配置要求が発生したことを記録する。"""
        rebuilt.append(None)

    editor.controller.rows_changed.connect(changed)
    return rebuilt


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """値が異なる二ノードと、接続・無関係Undo用ノードを表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    auto_key = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    cmds.undoInfo(state=True)
    for index, node in enumerate(_NODES):
        cmds.createNode("transform", name=node)
        cmds.addAttr(
            node, longName="gain", attributeType="double", keyable=True
        )
        cmds.addAttr(
            node,
            longName="limited",
            attributeType="double",
            minValue=0,
            maxValue=100,
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
            node, longName="enabled", attributeType="bool", keyable=True
        )
        cmds.addAttr(
            node,
            longName="mode",
            attributeType="enum",
            enumName="First:Second:Third",
            keyable=True,
        )
        cmds.addAttr(node, longName="caption", dataType="string")
        cmds.setAttr(f"{node}.caption", channelBox=True)
        cmds.addAttr(node, longName="hiddenValue", attributeType="double")
        for path in ("gain", "limited", "count"):
            _set(f"{node}.{path}", 1 + index * 2)
        _set(f"{node}.enabled", bool(index))
        _set(f"{node}.mode", index)
        _set(f"{node}.caption", f"初期{index}")
    cmds.createNode("network", name="undoMarker", skipSelect=True)
    cmds.addAttr("undoMarker", longName="value", attributeType="double")
    cmds.select(*_NODES, replace=True)
    widget = ChannelBoxWidget()
    widget.resize(420, 650)
    widget.show()
    _events()
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    cmds.autoKeyframe(state=auto_key)
    cast(Callable[..., str], cmds.file)(new=True, force=True)


@pytest.mark.parametrize(
    "name,value",
    [
        ("gain", 7.5),
        ("count", 7),
        ("enabled", False),
        ("mode", 2),
        ("caption", "確定値"),
    ],
)
def test_value_undo_redo_keeps_rows_and_never_writes_back(
    editor: ChannelBoxWidget, name: str, value: float | int | bool | str
) -> None:
    """全scalar型のUndoでは行と選択を維持し、同期がRedo履歴を消さない。"""
    row = _row(editor, name)
    key = (row.row.attribute.path, row.row.attribute.kind)
    editor.table_view.select_keys((key,))
    before = editor.row_widgets
    bindings = editor.controller.rows
    initial = _values(name)
    rebuilt = _record_rebuilds(editor)
    if name == "gain":
        assert isinstance(value, float)
        editor.controller.apply_numeric_values((key,), value)
    elif name == "count":
        assert isinstance(value, int)
        editor.controller.apply_numeric_values((key,), value)
    elif name == "enabled":
        assert isinstance(value, bool)
        editor.controller.apply_bool_values((key,), value)
    elif name == "mode":
        assert isinstance(value, int)
        editor.controller.apply_enum_values((key,), key, value)
    else:
        assert isinstance(value, str)
        editor.controller.apply_string_values((key,), value)
    _events()
    assert _values(name) == (value, value)

    cmds.undo()
    _events()
    assert _values(name) == initial
    assert editor.row_widgets == before
    assert editor.controller.rows == bindings
    assert editor.table_view.selected_keys() == (key,)
    assert not rebuilt
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert not cmds.undoInfo(query=True, redoQueueEmpty=True)

    cmds.redo()
    _events()
    assert _values(name) == (value, value)
    assert editor.row_widgets == before
    assert editor.controller.rows == bindings
    assert not rebuilt
    assert cmds.undoInfo(query=True, redoQueueEmpty=True)


def test_unrelated_undo_keeps_existing_input_rows(
    editor: ChannelBoxWidget,
) -> None:
    """非選択ノードだけのUndoでも入力行を破棄せず、値を書き込まない。"""
    before = editor.row_widgets
    initial = _values("gain")
    rebuilt = _record_rebuilds(editor)
    _set("undoMarker.value", 9)
    cmds.undo()
    _events()
    assert cmds.getAttr("undoMarker.value") == 0
    assert _values("gain") == initial
    assert editor.row_widgets == before
    assert not rebuilt
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert cmds.getAttr("undoMarker.value") == 9
    assert editor.row_widgets == before
    assert not rebuilt


def test_undo_keeps_pending_attribute_search_and_existing_rows(
    editor: ChannelBoxWidget,
) -> None:
    """検索の適用前にUndoしても、保持した行へ最新の検索文字を反映する。"""
    editor.search_visibility_actions["always"].setChecked(True)
    _events()
    _set("undoMarker.value", 7)
    before = editor.row_widgets
    rebuilt = _record_rebuilds(editor)
    assert (
        sum(
            not editor.table_view.isRowHidden(index)
            for index in range(len(editor.table_view.rows))
        )
        > 1
    )

    # 検索timerへQtイベントを渡す前に、別ノードの変更を戻す
    editor.search_edit.setText("gain")
    cmds.undo()
    _events()
    visible = tuple(
        row.key[0]
        for index, row in enumerate(editor.table_view.rows)
        if not editor.table_view.isRowHidden(index)
    )
    assert visible == ("gain",)
    assert editor.search_edit.text() == "gain"
    assert editor.row_widgets == before
    assert not rebuilt
    assert _values("gain") == (1, 3)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert cmds.getAttr("undoMarker.value") == 7
    assert editor.row_widgets == before
    assert not rebuilt


def test_slider_drag_undo_keeps_rows_and_finishes_edit_session(
    editor: ChannelBoxWidget,
) -> None:
    """連続ドラッグのUndoを一回に保ち、保持した行を次の操作にも利用する。"""
    row = _row(editor, "count")
    view = row.editor
    assert isinstance(view, IntSliderSpinBox)
    before = editor.row_widgets
    rebuilt = _record_rebuilds(editor)
    view.slider.setSliderDown(True)
    view.slider.setValue(10)
    view.slider.setValue(20)
    view.slider.setSliderDown(False)
    _events()
    assert _values("count") == (20, 20)
    cmds.undo()
    _events()
    assert _values("count") == (1, 3)
    assert editor.row_widgets == before
    assert not view.slider.isSliderDown()
    assert not editor.controller.value_edit_session.is_editing
    assert not rebuilt
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert _values("count") == (20, 20)
    assert editor.row_widgets == before
    view.spin_box.setValue(30)
    assert _values("count") == (30, 30)
    cmds.undo()
    _events()
    assert _values("count") == (20, 20)
    assert editor.row_widgets == before


@pytest.mark.parametrize("operation", ["add", "delete", "rename"])
def test_attribute_structure_undo_redo_rebuilds_rows(
    editor: ChannelBoxWidget, operation: str
) -> None:
    """追加・削除・改名のUndoとRedoは、新しい属性実体へ接続し直す。"""
    if operation == "add":
        cmds.addAttr(
            "undoReference",
            longName="addedValue",
            attributeType="double",
            keyable=True,
        )
        changed, restored = "addedValue", "gain"
    elif operation == "delete":
        cmds.deleteAttr("undoReference.gain")
        changed, restored = "count", "gain"
    else:
        cmds.renameAttr("undoReference.gain", "renamedGain")
        changed, restored = "renamedGain", "gain"
    _events()
    assert changed in _names(editor)
    after = editor.row_widgets
    rebuilt = _record_rebuilds(editor)

    cmds.undo()
    _events()
    assert restored in _names(editor)
    assert "addedValue" not in _names(editor)
    assert "renamedGain" not in _names(editor)
    assert editor.row_widgets != after
    assert rebuilt
    assert _row(editor, "gain").row.binding.value == 3
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    cmds.redo()
    _events()
    assert changed in _names(editor)
    if operation in ("delete", "rename"):
        assert "gain" not in _names(editor)


def test_structure_undo_defers_rebuild_during_reentrant_qt_events(
    editor: ChannelBoxWidget,
) -> None:
    """属性復元callbackがQtへ再入しても、復元完了後だけ行を構築する。"""
    cmds.deleteAttr("undoReference.gain")
    _events()
    assert "gain" not in _names(editor)
    observed: list[bool] = []
    reentered: list[bool] = []
    changes_during_callback: list[int] = []

    def rows_changed() -> None:
        """行の再構築通知がMayaのUndoまたはRedo途中だったか記録する。"""
        observed.append(om.MGlobal.isUndoing() or om.MGlobal.isRedoing())

    def attribute_changed(
        message: int,
        _plug: om.MPlug,
        _other: om.MPlug,
        *_args: object,
    ) -> None:
        """構成復元中に外部ツールがQtイベントを処理する状況を再現する。"""
        structural = (
            om.MNodeMessage.kAttributeAdded | om.MNodeMessage.kAttributeRemoved
        )
        in_history = om.MGlobal.isUndoing() or om.MGlobal.isRedoing()
        if not message & structural or not in_history:
            return
        before = len(observed)
        reentered.append(in_history)
        qt.QApplication.processEvents()
        changes_during_callback.append(len(observed) - before)

    selection = om.MSelectionList()
    selection.add("undoReference")
    registry = MayaCallbackRegistry(editor)
    registry.register(
        om.MNodeMessage.addAttributeChangedCallback(
            selection.getDependNode(0), attribute_changed
        )
    )
    editor.controller.rows_changed.connect(rows_changed)
    try:
        cmds.undo()
        _events()
        assert reentered
        assert not any(changes_during_callback)
        assert observed and not any(observed)
        assert _row(editor, "gain").row.binding.value == 3
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)

        observed.clear()
        reentered.clear()
        changes_during_callback.clear()
        cmds.redo()
        _events()
        assert reentered
        assert not any(changes_during_callback)
        assert observed and not any(observed)
        assert "gain" not in _names(editor)
        assert cmds.undoInfo(query=True, redoQueueEmpty=True)
    finally:
        registry.dispose()
        registry.deleteLater()


def test_deleted_reference_undo_restores_node_and_live_rows(
    editor: ChannelBoxWidget,
) -> None:
    """基準ノード削除後のUndoは、復元した選択実体の値編集へ再接続する。"""
    old = _row(editor, "gain").row.binding
    cmds.delete("undoReference")
    _events()
    assert old.is_disposed
    assert not cmds.objExists("undoReference")
    cmds.undo()
    _events()
    assert cmds.objExists("undoReference")
    assert editor.controller.representative_node_name == "|undoReference"
    restored = _row(editor, "gain")
    assert restored.row.binding.value == 3
    assert restored.row.binding is not old
    key = (restored.row.attribute.path, restored.row.attribute.kind)
    assert editor.controller.apply_numeric_values((key,), 8)
    assert _values("gain") == (8, 8)


@pytest.mark.parametrize("display_filter", ["keyable", "channel_box"])
def test_display_flag_undo_redo_rechecks_filtered_rows(
    editor: ChannelBoxWidget,
    display_filter: Literal["keyable", "channel_box"],
) -> None:
    """表示条件を変えるUndoでは行を増減し、Redoでも元の条件へ追従する。"""
    editor.controller.set_attribute_filter(display_filter)
    _events()
    cmds.flushUndo()
    name = "gain" if display_filter == "keyable" else "hiddenValue"
    if display_filter == "keyable":
        cmds.setAttr("undoReference.gain", keyable=False, channelBox=False)
    else:
        cmds.setAttr("undoReference.hiddenValue", channelBox=True)
    _events()
    after = name in _names(editor)
    cmds.undo()
    _events()
    assert (name in _names(editor)) is not after
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert (name in _names(editor)) is after


@pytest.mark.parametrize("name", ["limited", "count"])
@pytest.mark.parametrize("change", ["maximum", "replace_without_maximum"])
def test_hard_limit_undo_recreates_slider_or_step_with_current_range(
    editor: ChannelBoxWidget, name: str, change: str
) -> None:
    """範囲定義のUndoとRedoで、Sliderの範囲とStepへの切替を復元する。"""
    if change == "maximum":
        cmds.addAttr(f"undoReference.{name}", edit=True, maxValue=200)
    else:
        # 上限有無のeditはMaya自身がUndoしないため、復元可能な属性置換で確認する
        cmds.undoInfo(openChunk=True, chunkName="ReplaceRangeAttribute")
        try:
            cmds.deleteAttr(f"undoReference.{name}")
            cmds.addAttr(
                "undoReference",
                longName=name,
                attributeType="double" if name == "limited" else "long",
                minValue=0,
                keyable=True,
            )
            _set(f"undoReference.{name}", 3)
        finally:
            cmds.undoInfo(closeChunk=True)
    # 定義編集後に開き直した状態からも、Undoによる元の範囲へ追従する
    editor.refresh()
    _events()
    changed = _row(editor, name)
    if change == "replace_without_maximum":
        assert isinstance(
            changed.editor, (FloatValueStepSpinBox, IntValueStepSpinBox)
        )
    cmds.undo()
    _events()
    assert cmds.attributeQuery(name, node="undoReference", maxExists=True)
    restored = _row(editor, name)
    assert restored is not changed
    assert isinstance(restored.editor, (FloatSliderSpinBox, IntSliderSpinBox))
    assert restored.editor.spin_box.maximum() == 100
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    result = _row(editor, name).editor
    if change == "maximum":
        assert isinstance(result, (FloatSliderSpinBox, IntSliderSpinBox))
        assert result.spin_box.maximum() == 200
    else:
        assert isinstance(result, (FloatValueStepSpinBox, IntValueStepSpinBox))


def test_enum_definition_undo_updates_choices_without_losing_redo(
    editor: ChannelBoxWidget,
) -> None:
    """enum定義のUndoでは値が同じでも候補名を更新し、追加書込みをしない。"""
    cmds.addAttr(
        "undoReference.mode", edit=True, enumName="First:Changed:Last"
    )
    editor.refresh()
    _events()
    changed = _row(editor, "mode").editor
    assert isinstance(changed, EnumComboBox)
    assert changed.currentText() == "Changed"
    cmds.undo()
    _events()
    restored = _row(editor, "mode").editor
    assert isinstance(restored, EnumComboBox)
    assert restored.currentText() == "Second"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    result = _row(editor, "mode").editor
    assert isinstance(result, EnumComboBox)
    assert result.currentText() == "Changed"


@pytest.mark.parametrize("operation", ["lock", "connection", "key"])
def test_state_only_undo_updates_input_state_without_rebuilding(
    editor: ChannelBoxWidget, operation: str
) -> None:
    """値が同じlock・接続・キーのUndoでも、編集可否と色帯を更新する。"""
    before = editor.row_widgets
    row = _row(editor, "gain")
    if operation == "lock":
        cmds.setAttr("undoReference.gain", lock=True)
    elif operation == "connection":
        _set("undoMarker.value", 3)
        cmds.flushUndo()
        cmds.connectAttr("undoMarker.value", "undoReference.gain")
    else:
        cmds.setKeyframe("undoReference.gain", value=3)
    _events()
    state = {"lock": "locked", "connection": "connected", "key": "keyed"}[
        operation
    ]
    assert row.input_indicator.input_state == state
    rebuilt = _record_rebuilds(editor)
    cmds.undo()
    _events()
    assert _row(editor, "gain") is row
    assert editor.row_widgets == before
    assert row.input_indicator.input_state == "unconnected"
    assert row.row.binding.view_model.set_value_command.can_execute
    assert not rebuilt
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert _row(editor, "gain") is row
    assert row.input_indicator.input_state == state
    assert not rebuilt


def test_undo_discards_pending_numeric_input_before_focus_confirmation(
    editor: ChannelBoxWidget,
) -> None:
    """Undo中に未確定数値を破棄し、後のフォーカス移動で再適用しない。"""
    _set("undoReference.gain", 5)
    _events()
    row = _row(editor, "gain")
    assert isinstance(row.editor, FloatValueStepSpinBox)
    before = editor.row_widgets
    row.editor.spin_box.setFocus()
    qt.QApplication.sendEvent(
        row.editor.spin_box,
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
    cmds.undo()
    _events()
    assert editor.row_widgets == before
    assert not qt.isValid(pending) or not pending.isVisible()
    editor.mode_combo.setFocus()
    _events()
    assert _values("gain") == (1, 3)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert _values("gain") == (1, 5)


def test_undo_discards_step_text_and_keeps_saved_increment(
    editor: ChannelBoxWidget,
) -> None:
    """Undo後のフォーカス移動でStep下書きを確定せず、保存済み増減量を保つ。"""
    row = _row(editor, "gain")
    view = row.editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.setSingleStep(0.25)
    _set("undoMarker.value", 7)
    before = editor.row_widgets
    step = view.step_spin_box
    step.setFocus()
    _events()
    pending = step.findChild(qt.QLineEdit)
    assert isinstance(pending, qt.QLineEdit)
    pending.setText("9")
    pending.setModified(True)
    assert step.value() == 0.25
    cmds.undo()
    _events()
    editor.mode_combo.setFocus()
    _events()
    assert editor.row_widgets == before
    assert step.value() == view.singleStep() == 0.25
    assert _values("gain") == (1, 3)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert cmds.getAttr("undoMarker.value") == 7
    assert step.value() == view.singleStep() == 0.25


def test_undo_discards_string_draft_and_closes_enum_popup(
    editor: ChannelBoxWidget,
) -> None:
    """Undoで文字列下書きと開いた候補を終了し、旧入力でRedoを消さない。"""
    _set("undoMarker.value", 7)
    row = _row(editor, "caption")
    assert isinstance(row.editor, StringLineEdit)
    row.editor.setText("未確定入力")
    row.editor.textEdited.emit("未確定入力")
    combo = _row(editor, "mode").editor
    assert isinstance(combo, EnumComboBox)
    combo.showPopup()
    before = editor.row_widgets
    cmds.undo()
    _events()
    assert editor.row_widgets == before
    assert row.editor.text() == "初期1"
    assert not combo.view().isVisible()
    row.editor.editingFinished.emit()
    _events()
    assert _values("caption") == ("初期0", "初期1")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert cmds.getAttr("undoMarker.value") == 7
