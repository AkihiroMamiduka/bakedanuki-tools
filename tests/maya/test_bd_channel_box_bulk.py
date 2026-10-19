# coding: utf-8
"""多数ノードモードの基準表示と、操作時だけの全対象編集を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from math import isclose
from typing import Literal, cast

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from bd_util.maya.node.inspection import (
    ScalarAttributeInfo,
    ScalarAttributeTypeInfo,
)
from bd_util.maya.ui import (
    MayaEditSession,
    MayaEnumPlugsBinding,
    MayaEnumValueEdit,
    MayaNodeValueSnapshot,
    MayaPlugsValueEdit,
    MayaScalarPasteResult,
    MayaScalarValueSnapshot,
    MayaScalarValueTransfer,
)
from bd_util.maya.ui.binding._enum_plug_value import EnumPlugValue
from bd_util.ui import (
    EnumComboBox,
    EnumDefinition,
    FloatValueStepSpinBox,
    FloatViewModel,
    IntSliderSpinBox,
    StringLineEdit,
    qt,
)
import bd_tools.bd_channel_box.controller as controller_module
from bd_tools.bd_channel_box.controller import ChannelBoxMode
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


def _events() -> None:
    """通知の同期と、旧入力部品の遅延削除を完了する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set(path: str, value: float | int | bool) -> None:
    """Mayaの数値設定の型境界を閉じる。"""
    cast(Callable[[str, float | int | bool], None], cmds.setAttr)(path, value)


def _row(editor: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """属性の正式名に対応する値編集行を取得する。"""
    result = next(
        widget
        for widget in editor.row_widgets
        if widget.row.attribute.name == name
    )
    assert isinstance(result, AttributeRowWidget)
    return result


def test_menus_stay_uncreated_during_input_undo_and_rebuild(
    editor: ChannelBoxWidget,
) -> None:
    """表示・値同期・Undo/Redo・終了で未使用の行メニューを作らない。"""
    assert all(
        not widget.has_context_menu
        for widget in editor.row_widgets
        if isinstance(widget, AttributeRowWidget)
    )
    key = (_row(editor, "free").row.attribute.path, "number")
    cmds.flushUndo()
    assert editor.controller.offset_numeric_values((key,), 1.0)
    editor.controller.finish_value_edit()
    _events()
    for operation in (cmds.undo, cmds.redo, editor.refresh):
        operation()
        _events()
        assert all(
            not widget.has_context_menu
            for widget in editor.row_widgets
            if isinstance(widget, AttributeRowWidget)
        )
    rows = editor.row_widgets
    editor.dispose()
    assert all(
        not widget.has_context_menu
        for widget in rows
        if isinstance(widget, AttributeRowWidget)
    )


def test_row_menu_is_created_and_connected_only_once(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """初回利用時だけ対象行のメニューを作り、操作の接続を重複させない。"""
    row = _row(editor, "free")
    calls: list[tuple[str, tuple[str, str]]] = []

    def record(action: str, key: tuple[str, str]) -> None:
        """選択属性の操作が一回だけ呼ばれることを記録する。"""
        calls.append((action, key))

    monkeypatch.setattr(editor, "_run_selected_action", record)
    menu = row.context_menu
    assert row.context_menu is menu
    menu.aboutToShow.emit()
    menu.aboutToShow.emit()
    menu.set_key_selected_action.trigger()
    assert calls == [("key_selected", (row.row.attribute.path, "number"))]
    assert all(
        not widget.has_context_menu
        for widget in editor.row_widgets
        if isinstance(widget, AttributeRowWidget) and widget is not row
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def _keys(
    editor: ChannelBoxWidget, *names: str
) -> tuple[tuple[str, str], ...]:
    """表示行の正式pathと型を操作対象の識別子として返す。"""
    return tuple(
        (
            _row(editor, name).row.attribute.path,
            _row(editor, name).row.attribute.kind,
        )
        for name in names
    )


def _values(name: str) -> list[object]:
    """後続ノード、基準ノードの順に現在の値を返す。"""
    return [
        cmds.getAttr(node + "." + name)
        for node in ("bulkOther", "bulkReference")
    ]


def _key(widget: qt.QWidget, key: qt.Qt.Key, text: str = "") -> None:
    """実際のキーイベントで文字入力と確定を行う。"""
    for kind in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
        qt.QApplication.sendEvent(
            widget,
            qt.QtGui.QKeyEvent(
                kind, key, qt.Qt.KeyboardModifier.NoModifier, text
            ),
        )


class _MemoryClipboard:
    """OS clipboardへ影響を与えず、コピー元と貼付け先を確認する。"""

    def __init__(self) -> None:
        """未コピー状態を作る。"""
        self.transfer: MayaScalarValueTransfer | None = None

    def contains(self) -> bool:
        """値が保存されているか返す。"""
        return self.transfer is not None

    def read(self) -> MayaScalarValueTransfer:
        """保存済みの属性値を返す。"""
        assert self.transfer is not None
        return self.transfer

    def write(self, transfer: MayaScalarValueTransfer) -> None:
        """コピー結果を保持する。"""
        self.transfer = transfer


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """異なる値を持つ二ノードを多数ノードモードへ接続する。"""
    del qt_application
    auto_key = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    cmds.undoInfo(state=True)
    cmds.currentUnit(linear="cm", angle="deg")
    for node, initial in (("bulkOther", 1), ("bulkReference", 3)):
        cmds.createNode("transform", name=node)
        cmds.addAttr(
            node, longName="free", attributeType="double", keyable=True
        )
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
            node, longName="enabled", attributeType="bool", keyable=True
        )
        cmds.addAttr(
            node,
            longName="mode",
            attributeType="enum",
            enumName="First:Second:Third",
            keyable=True,
        )
        cmds.addAttr(node, longName="label", dataType="string", keyable=True)
        for attribute in ("free", "gain", "count"):
            _set(node + "." + attribute, initial)
        _set(node + ".enabled", node == "bulkReference")
        _set(node + ".mode", int(node == "bulkReference"))
        cmds.setAttr(node + ".label", node, type="string")
    cmds.select("bulkOther", "bulkReference", replace=True)
    widget = ChannelBoxWidget()
    widget.controller.set_mode("bulk_values")
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


def test_thousand_nodes_inspect_and_bind_only_the_reference(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """千ノード選択でも、表示用の属性取得とBindingは基準一個に限定する。"""
    nodes = tuple(
        cmds.createNode("network", name=f"bulkThousand{index}")
        for index in range(999)
    ) + ("bulkReference",)
    original = controller_module.inspect_scalar_attributes
    inspected: list[str] = []

    def record(name: str) -> tuple[ScalarAttributeInfo, ...]:
        """属性情報を取得したノードを記録する。"""
        inspected.append(name)
        return original(name)

    monkeypatch.setattr(controller_module, "inspect_scalar_attributes", record)
    cmds.select(*nodes, replace=True)
    _events()
    assert len(editor.controller.node_names) == 1000
    assert not editor.controller.selection_limit_exceeded
    assert inspected and set(inspected) == {"|bulkReference"}
    assert editor.selection_count_label.text() == "1000 ノード"
    assert editor.row_widgets
    for widget in editor.row_widgets:
        assert isinstance(widget, AttributeRowWidget)
        assert len(widget.row.binding.target_states) == 1
        assert not widget.row.binding.is_mixed
    assert isinstance(_row(editor, "free").editor, FloatValueStepSpinBox)
    assert isinstance(_row(editor, "count").editor, IntSliderSpinBox)


@pytest.mark.parametrize("mode", ["values", "states", "custom_filter_setup"])
def test_existing_modes_keep_the_selection_limit(
    editor: ChannelBoxWidget, mode: ChannelBoxMode
) -> None:
    """通常三モードの上限を維持し、多数ノードモードへ戻れば表示する。"""
    nodes = tuple(
        cmds.createNode("network", name=f"bulkLimit{index}")
        for index in range(50)
    ) + ("bulkReference",)
    cmds.select(*nodes, replace=True)
    _events()
    assert len(editor.controller.node_names) == 51
    editor.controller.set_mode(mode)
    _events()
    assert editor.controller.selection_limit_exceeded
    assert not editor.row_widgets
    editor.controller.set_mode("bulk_values")
    _events()
    assert not editor.controller.selection_limit_exceeded
    assert len(editor.controller.node_names) == 51
    assert _row(editor, "free").row.binding.value == 3


def test_reference_display_does_not_propagate_external_changes(
    editor: ChannelBoxWidget,
) -> None:
    """基準の表示更新と他ノードの外部変更は一括入力を発生させない。"""
    original = editor.row_widgets
    _set("bulkOther.free", 8)
    _events()
    assert _row(editor, "free").row.binding.value == 3
    assert not _row(editor, "free").row.binding.is_mixed
    _set("bulkReference.free", 5)
    _events()
    assert editor.row_widgets == original
    assert _row(editor, "free").row.binding.value == 5
    assert _values("free") == [8, 5]


@pytest.mark.parametrize("attribute", ["free", "count"])
def test_explicit_same_numeric_value_edits_other_nodes_and_undoes(
    editor: ChannelBoxWidget, attribute: str
) -> None:
    """基準と同じ数値の明示確定でも他ノードを揃え、一度のUndoで戻す。"""
    view = _row(editor, attribute).editor
    assert isinstance(view, (FloatValueStepSpinBox, IntSliderSpinBox))
    view.spin_box.setFocus()
    view.spin_box.selectAll()
    _key(view.spin_box, qt.Qt.Key.Key_3, "3")
    focused = qt.QApplication.focusWidget()
    assert isinstance(focused, qt.QLineEdit)
    _key(focused, qt.Qt.Key.Key_Return)
    _events()
    assert _values(attribute) == [3, 3]
    cmds.undo()
    _events()
    assert _values(attribute) == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert _values(attribute) == [3, 3]
    assert _row(editor, attribute).row.binding.value == 3


@pytest.mark.parametrize("selected", [False, True])
def test_single_numeric_input_preserves_caret_and_selection(
    editor: ChannelBoxWidget, selected: bool
) -> None:
    """単一属性の部分編集は元のカーソル・選択範囲を維持して全対象へ適用する。"""
    editor.controller.apply_numeric_values(_keys(editor, "free"), 123)
    view = _row(editor, "free").editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setFocus()
    source = view.spin_box.findChild(qt.QLineEdit)
    assert isinstance(source, qt.QLineEdit)
    source.deselect()
    source.setCursorPosition(3)
    if selected:
        source.setSelection(1, 1)
    _key(source, qt.Qt.Key.Key_4, "4")
    focused = qt.QApplication.focusWidget()
    assert isinstance(focused, qt.QLineEdit)
    _key(focused, qt.Qt.Key.Key_Return)
    assert _values("free") == ([143, 143] if selected else [1234, 1234])


def test_pasted_same_numeric_value_edits_other_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """値欄への同値のキーボード貼付けも明示確定として全対象へ適用する。"""
    clipboard = qt.QApplication.clipboard()
    assert clipboard is not None
    saved = qt.QtCore.QMimeData()
    previous = cast(qt.QtCore.QMimeData | None, clipboard.mimeData())
    if previous is not None:
        for format_name in previous.formats():
            saved.setData(format_name, previous.data(format_name))
    try:
        clipboard.setText("3")
        view = _row(editor, "free").editor
        assert isinstance(view, FloatValueStepSpinBox)
        view.spin_box.setFocus()
        view.spin_box.selectAll()
        event = qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_V,
            qt.Qt.KeyboardModifier.ControlModifier,
            "v",
        )
        qt.QApplication.sendEvent(view.spin_box, event)
        focused = qt.QApplication.focusWidget()
        assert isinstance(focused, qt.QLineEdit)
        _key(focused, qt.Qt.Key.Key_Return)
        assert _values("free") == [3, 3]
    finally:
        clipboard.setMimeData(saved)


def test_explicit_same_string_value_edits_other_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """基準と同じ文字列の再確定も、入力handlerを通して他ノードへ適用する。"""
    view = _row(editor, "label").editor
    assert isinstance(view, StringLineEdit)
    view.setFocus()
    view.selectAll()
    _key(view, qt.Qt.Key.Key_B, "bulkReference")
    _key(view, qt.Qt.Key.Key_Return)
    assert _values("label") == ["bulkReference", "bulkReference"]


def test_same_enum_item_activation_edits_other_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """同じenum項目の明示選択だけを全対象へ適用し、表示更新では適用しない。"""
    view = _row(editor, "mode").editor
    assert isinstance(view, EnumComboBox)
    view.setCurrentIndex(view.currentIndex())
    assert _values("mode") == [0, 1]
    view.activated.emit(view.currentIndex())
    assert _values("mode") == [1, 1]
    cmds.undo()
    _events()
    assert _values("mode") == [0, 1]


@pytest.mark.parametrize("attribute", ["drawStyle", "probeEnum"])
def test_thousand_joint_enums_apply_once_with_linear_definition_reads(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
) -> None:
    """千jointの標準・動的enumを一回で編集し、定義取得と一時Bindingを抑える。"""
    nodes = tuple(
        cmds.createNode("joint", name=f"bulkDrawStyle{index}")
        for index in range(1000)
    )
    if attribute == "probeEnum":
        for node in nodes:
            cmds.addAttr(
                node,
                longName=attribute,
                attributeType="enum",
                enumName="A:B:C",
            )
    cmds.setAttr(nodes[-1] + "." + attribute, channelBox=True)
    cmds.select(*nodes, replace=True)
    _events()
    row = _row(editor, attribute)
    view = row.editor
    assert isinstance(view, EnumComboBox)
    assert len(row.row.binding.target_states) == 1
    assert view.currentIndex() == 0
    view.setFocus()
    _events()
    cmds.flushUndo()

    # 時間制限に頼らず、実際のMaya定義問い合わせの二乗増加を早期に検出する
    original_definition = EnumPlugValue.read_definition
    definition_reads = 0
    definition_budget = 40 * len(nodes)

    def query_definition(
        value: EnumPlugValue, *, refresh: bool = False
    ) -> EnumDefinition:
        """定義の実読取りを数え、全件走査の繰り返しを上限で止める。"""
        nonlocal definition_reads
        definition_reads += 1
        assert definition_reads <= definition_budget
        return original_definition(value, refresh=refresh)

    original_create = cast(
        Callable[..., MayaEnumPlugsBinding],
        getattr(editor.controller, "_create_enum_binding"),
    )
    temporary: list[tuple[MayaEnumPlugsBinding, bool, int]] = []

    def create_binding(
        path: str,
        targets: list[str],
        excluded: list[str],
        *,
        monitor: bool = True,
    ) -> MayaEnumPlugsBinding:
        """実際の一時Bindingを保持し、適用回数・対象数・監視指定を確認する。"""
        binding = original_create(path, targets, excluded, monitor=monitor)
        temporary.append((binding, monitor, len(binding.target_states)))
        return binding

    monkeypatch.setattr(EnumPlugValue, "read_definition", query_definition)
    monkeypatch.setattr(
        editor.controller, "_create_enum_binding", create_binding
    )

    # 下キー一回で次項目へ移し、signalの重複適用も検出する
    _key(view, qt.Qt.Key.Key_Down)
    assert len(temporary) == 1
    binding, monitored, target_count = temporary[0]
    assert not monitored
    assert target_count == len(nodes)
    assert binding.is_disposed
    assert 0 < definition_reads <= definition_budget
    assert all(cmds.getAttr(node + "." + attribute) == 1 for node in nodes)
    assert len(row.row.binding.target_states) == 1
    assert not row.row.binding.is_disposed
    _events()

    # 一操作のUndo/Redoで全件を復元し、UI同期が再適用を起こさないことを確認する
    cmds.undo()
    _events()
    assert all(cmds.getAttr(node + "." + attribute) == 0 for node in nodes)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert all(cmds.getAttr(node + "." + attribute) == 1 for node in nodes)
    assert sum(not monitored for _, monitored, _ in temporary) == 1


@pytest.mark.parametrize("mode", ["values", "bulk_values"])
@pytest.mark.parametrize(
    "operation",
    [
        "enum",
        "align_selected",
        "align_filtered",
        "paste_all",
        "paste_filtered",
        "paste_selected_single",
        "paste_selected_multi",
    ],
)
def test_enum_edit_paths_use_operation_validation_only_in_bulk_mode(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    mode: ChannelBoxMode,
    operation: str,
) -> None:
    """enum入力・混合行揃え・各Paste経路の検証方針を表示モードごとに保つ。"""
    editor.controller.set_mode(mode)
    _events()
    memory = _MemoryClipboard()
    monkeypatch.setattr(editor.controller, "_value_clipboard", memory)
    original_apply = controller_module.apply_plugs_values
    policies: list[Literal["per_write", "operation"]] = []

    def apply_and_record(
        edits: Sequence[MayaPlugsValueEdit],
        *,
        edit_session: MayaEditSession | None = None,
        enum_validation: Literal["per_write", "operation"] = "per_write",
    ) -> bool:
        """実適用を維持し、enumを含む要求へ渡した検証方針を記録する。"""
        assert any(isinstance(edit, MayaEnumValueEdit) for edit in edits)
        policies.append(enum_validation)
        return original_apply(
            edits,
            edit_session=edit_session,
            enum_validation=enum_validation,
        )

    monkeypatch.setattr(
        controller_module, "apply_plugs_values", apply_and_record
    )
    paste_name = (
        "apply_scalar_value_transfer"
        if operation == "paste_all"
        else (
            "apply_scalar_value_to_paths"
            if operation == "paste_selected_single"
            else "apply_scalar_value_transfer_to_paths"
        )
    )
    original_paste = cast(
        Callable[..., MayaScalarPasteResult],
        getattr(controller_module, paste_name),
    )

    def paste_and_record(
        *args: object, **kwargs: object
    ) -> MayaScalarPasteResult:
        """公開Paste入口の検証方針を記録し、実際の値適用も行う。"""
        policy = kwargs.get("enum_validation", "per_write")
        if policy == "operation":
            policies.append("operation")
        else:
            assert policy == "per_write"
            policies.append("per_write")
        return original_paste(*args, **kwargs)

    monkeypatch.setattr(controller_module, paste_name, paste_and_record)
    keys = _keys(editor, "free", "mode")
    if operation == "enum":
        enum_keys = _keys(editor, "mode")
        assert editor.controller.apply_enum_values(enum_keys, enum_keys[0], 2)
    elif operation == "align_selected":
        assert editor.controller.align_selected_values(keys)
    elif operation == "align_filtered":
        assert editor.controller.align_filtered_values("keyable")
    else:
        copy_keys = (
            _keys(editor, "mode")
            if operation == "paste_selected_single"
            else keys
        )
        editor.controller.copy_selected_values(copy_keys)
        if operation == "paste_all":
            assert editor.controller.paste_copied_values()
        elif operation == "paste_filtered":
            assert editor.controller.paste_copied_values("keyable")
        else:
            assert editor.controller.paste_copied_values_to_selected(copy_keys)
    assert policies == ["operation" if mode == "bulk_values" else "per_write"]
    assert _values("mode") == ([2, 2] if operation == "enum" else [1, 1])


def test_scalar_types_edit_all_nodes_and_skip_changed_enum_definition(
    editor: ChannelBoxWidget,
) -> None:
    """bool・整数・文字列も全対象へ適用し、後続enumの定義差は操作時に除外する。"""
    assert editor.controller.apply_bool_values(_keys(editor, "enabled"), True)
    assert _values("enabled") == [True, True]
    assert editor.controller.apply_numeric_values(_keys(editor, "count"), 12)
    assert _values("count") == [12, 12]
    assert editor.controller.apply_string_values(
        _keys(editor, "label"), "same"
    )
    assert _values("label") == ["same", "same"]
    cmds.addAttr("bulkOther.mode", edit=True, enumName="First:Different:Third")
    keys = _keys(editor, "mode")
    assert editor.controller.apply_enum_values(keys, keys[0], 2)
    assert _values("mode") == [0, 2]


@pytest.mark.parametrize("kind", ["doubleLinear", "doubleAngle"])
def test_numeric_unit_mismatch_is_excluded_at_operation_time(
    editor: ChannelBoxWidget, kind: str
) -> None:
    """同じ数値pathでも無単位と距離・角度を混同して適用しない。"""
    cmds.deleteAttr("bulkOther.free")
    cmds.addAttr(
        "bulkOther", longName="free", attributeType=kind, keyable=True
    )
    _set("bulkOther.free", 2)
    assert editor.controller.apply_numeric_values(_keys(editor, "free"), 7)
    assert _values("free") == [2, 7]


def test_operation_rechecks_missing_wrong_type_and_locked_targets(
    editor: ChannelBoxWidget,
) -> None:
    """表示後の属性削除・型違い・lockを操作時に判定し、対応対象だけ編集する。"""
    missing = cmds.createNode("network", name="bulkMissing")
    wrong = cmds.createNode("network", name="bulkWrongType")
    cmds.addAttr(wrong, longName="free", attributeType="long", keyable=True)
    cmds.select(missing, wrong, "bulkOther", "bulkReference", replace=True)
    _events()
    cmds.setAttr("bulkOther.free", lock=True)
    assert editor.controller.apply_numeric_values(_keys(editor, "free"), 7)
    assert _values("free") == [1, 7]
    assert cmds.getAttr(wrong + ".free") == 0
    cmds.setAttr("bulkOther.free", lock=False)
    cmds.deleteAttr("bulkOther.free")
    assert editor.controller.apply_numeric_values(_keys(editor, "free"), 8)
    assert cmds.getAttr("bulkReference.free") == 8
    assert not cmds.objExists("bulkOther.free")


def test_secondary_range_violation_rejects_the_whole_multirow_edit(
    editor: ChannelBoxWidget,
) -> None:
    """基準にない後続の範囲制限も検証し、他の行へ部分適用を残さない。"""
    cmds.addAttr("bulkOther.free", edit=True, minValue=0, maxValue=5)
    cmds.flushUndo()
    with pytest.raises((ValueError, RuntimeError)):
        editor.controller.apply_numeric_values(
            _keys(editor, "gain", "free"), 8
        )
    assert _values("free") == [1, 3]
    assert _values("gain") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_renamed_secondary_node_remains_an_edit_target(
    editor: ChannelBoxWidget,
) -> None:
    """常時監視しない後続ノードが改名されても、現在の同じ対象へ適用する。"""
    renamed = cmds.rename("bulkOther", "bulkRenamed")
    _events()
    assert editor.controller.apply_numeric_values(_keys(editor, "free"), 7)
    assert cmds.getAttr(renamed + ".free") == 7
    assert cmds.getAttr("bulkReference.free") == 7


def test_selected_instance_path_survives_operations_and_parent_rename(
    editor: ChannelBoxWidget,
) -> None:
    """同じDAG実体の先頭pathへ置き換えず、選択したinstance経路を保つ。"""
    first_parent = cmds.createNode("transform", name="bulkFirstParent")
    second_parent = cmds.createNode("transform", name="bulkSecondParent")
    cmds.parent("bulkOther", first_parent)
    cmds.parent("|bulkFirstParent|bulkOther", second_parent, addObject=True)
    selected = "|bulkSecondParent|bulkOther"
    cmds.select(selected, "bulkReference", replace=True)
    _events()
    assert editor.controller.node_names[0] == selected
    assert editor.controller.apply_numeric_values(_keys(editor, "free"), 7)
    assert editor.controller.node_names[0] == selected
    cmds.rename(second_parent, "bulkRenamedParent")
    _events()
    assert editor.controller.apply_numeric_values(_keys(editor, "free"), 8)
    assert editor.controller.node_names[0] == "|bulkRenamedParent|bulkOther"
    assert cmds.getAttr("|bulkFirstParent|bulkOther.free") == 8


@pytest.mark.parametrize("interruption", ["selection", "close"])
@pytest.mark.parametrize(
    "operation", ["numeric", "align_filtered", "round_filtered"]
)
def test_interruption_during_bulk_write_restores_all_old_targets(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
    operation: str,
) -> None:
    """書込み途中の選択変更・closeで一時Bindingも終了し、部分適用を復旧する。"""
    original = cast(Callable[..., None], cmds.setAttr)
    interrupted = False
    if operation == "round_filtered":
        _set("bulkOther.free", 1.25)
        _set("bulkReference.free", 3.75)
        _events()
    initial = _values("free")

    def set_and_interrupt(*args: object, **kwargs: object) -> None:
        """最初の実書込み直後に、入力を無効化する外部操作を挟む。"""
        nonlocal interrupted
        original(*args, **kwargs)
        if not interrupted:
            interrupted = True
            if interruption == "selection":
                cmds.select("bulkOther", replace=True)
            else:
                editor.controller.dispose()

    monkeypatch.setattr(cmds, "setAttr", set_and_interrupt)
    with pytest.raises((RuntimeError, ExceptionGroup)):
        if operation == "align_filtered":
            editor.controller.align_filtered_values("visible")
        elif operation == "round_filtered":
            editor.controller.round_filtered_values("visible", 1)
        else:
            editor.controller.apply_numeric_values(
                _keys(editor, "free", "gain"), 7
            )
    assert interrupted
    assert _values("free") == initial
    assert _values("gain") == [1, 3]


def test_slider_keeps_live_updates_and_one_undo_for_all_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """Sliderの複数更新を全対象へ反映し、一操作を一回のUndoへまとめる。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    view.slider.setSliderDown(True)
    for value in (20, 30, 40):
        view.slider.setValue(value)
        assert _values("count") == [value, value]
    view.slider.setSliderDown(False)
    _events()
    assert not editor.controller.value_edit_session.is_editing
    cmds.undo()
    _events()
    assert _values("count") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert _values("count") == [40, 40]


@pytest.mark.parametrize("auto_key", [False, True])
def test_connected_slider_keeps_animation_and_undo_rules(
    editor: ChannelBoxWidget, auto_key: bool
) -> None:
    """一時Bindingでも時間カーブの連続編集とAuto Keyの一操作Undoを維持する。"""
    for node in ("bulkOther", "bulkReference"):
        cmds.setKeyframe(node + ".count", time=1, value=10)
        cmds.setKeyframe(node + ".count", time=10, value=20)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    editor.refresh()
    _events()
    initial = _values("count")
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    cmds.flushUndo()
    view.slider.setSliderDown(True)
    for value in (30, 40, 50):
        view.slider.setValue(value)
        assert _values("count") == [value, value]
    view.slider.setSliderDown(False)
    cmds.undo()
    _events()
    assert _values("count") == initial
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert all(
        cmds.keyframe(node + ".count", query=True, keyframeCount=True) == 2
        for node in ("bulkOther", "bulkReference")
    )


def test_selection_change_discards_old_numeric_draft(
    editor: ChannelBoxWidget,
) -> None:
    """選択変更時は未確定値を旧対象にも新対象にも適用しない。"""
    view = _row(editor, "free").editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setFocus()
    view.spin_box.selectAll()
    _key(view.spin_box, qt.Qt.Key.Key_9, "9")
    cmds.select("bulkOther", replace=True)
    _events()
    assert _values("free") == [1, 3]
    assert _row(editor, "free").row.binding.value == 1
    assert editor.controller.representative_node_name == "|bulkOther"


def test_copy_uses_reference_and_paste_menu_edits_all_targets(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """値Copyの基準一個と、値Pasteの全対象というメニューの対象範囲を維持する。"""
    memory = _MemoryClipboard()
    monkeypatch.setattr(editor.controller, "_value_clipboard", memory)
    editor.table_view.select_keys(_keys(editor, "free"))
    _row(editor, "free").context_menu.copy_selected_values_action.trigger()
    copied = memory.read()
    assert len(copied.nodes) == 1
    assert copied.nodes[0].values[0].value == 3
    _set("bulkReference.free", 6)
    _events()
    row = _row(editor, "free")
    row.context_menu.aboutToShow.emit()
    assert row.context_menu.paste_selected_values_action.isEnabled()
    row.context_menu.paste_selected_values_action.trigger()
    _events()
    assert _values("free") == [3, 3]


def test_align_lock_and_keyframe_menus_keep_all_targets(
    editor: ChannelBoxWidget,
) -> None:
    """混在を常時計測しなくても整列・lock・キー設定を全対象へ実行できる。"""
    row = _row(editor, "free")
    editor.table_view.select_keys(_keys(editor, "free"))
    row.context_menu.aboutToShow.emit()
    assert row.context_menu.align_action.isEnabled()
    row.context_menu.align_action.trigger()
    assert _values("free") == [3, 3]
    editor.controller.set_selected_locked(_keys(editor, "free"), True)
    assert all(
        cmds.getAttr(node + ".free", lock=True)
        for node in ("bulkOther", "bulkReference")
    )
    editor.controller.set_selected_locked(_keys(editor, "free"), False)
    _events()
    assert editor.controller.set_keyframes_selected(_keys(editor, "free")) == 2
    assert all(
        cmds.keyframe(node + ".free", query=True, keyframeCount=True) == 1
        for node in ("bulkOther", "bulkReference")
    )


@pytest.mark.parametrize("operation", ["lock", "display"])
def test_thousand_node_state_operations_keep_flags_and_one_undo(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """千対象のlock・表示変更が値を変えず、一回のUndo/Redoで復元する。"""
    nodes = tuple(
        cmds.createNode("transform", name=f"bulkState{index}")
        for index in range(1000)
    )
    cmds.select(*nodes, replace=True)
    _events()
    keys = _keys(editor, "translateX")
    created = _record_bulk_drag_rows(editor, monkeypatch)
    cmds.flushUndo()

    if operation == "lock":
        assert editor.controller.set_selected_locked(keys, True)
    else:
        assert editor.controller.set_selected_display(keys, "channel_box")
    assert not created

    def flags() -> tuple[tuple[bool, bool, bool], ...]:
        """全対象の自身のlock・keyable・channelBox状態を取得する。"""
        return tuple(
            (
                bool(cmds.getAttr(node + ".translateX", lock=True)),
                bool(cmds.getAttr(node + ".translateX", keyable=True)),
                bool(cmds.getAttr(node + ".translateX", channelBox=True)),
            )
            for node in nodes
        )

    applied = (
        (True, True, False) if operation == "lock" else (False, False, True)
    )
    assert flags() == (applied,) * len(nodes)
    assert all(cmds.getAttr(node + ".translateX") == 0 for node in nodes)
    cmds.undo()
    assert flags() == ((False, True, False),) * len(nodes)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    assert flags() == (applied,) * len(nodes)
    _events()


@pytest.mark.parametrize(
    "operation", ["lock", "display", "key", "layer", "mute"]
)
def test_bulk_menu_operations_keep_different_enum_definitions_without_value_bindings(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """定義が別のenumも従来どおり操作し、値Bindingを作らず一回でUndoする。"""
    cmds.addAttr("bulkOther.mode", edit=True, enumName="Other:Second:Third")
    names = ("bulkOther.mode", "bulkReference.mode")
    layer = ""
    if operation == "mute":
        cmds.setKeyframe(*names, time=1)
    elif operation == "layer":
        layer = cast(str, cmds.animLayer("bulkMenuLayer"))
        root = cast(str, cmds.animLayer(query=True, root=True))
        cmds.animLayer(root, edit=True, selected=False)
        cmds.animLayer(layer, edit=True, selected=True)
    _events()
    keys = _keys(editor, "mode")
    created = _record_bulk_drag_rows(editor, monkeypatch)
    reports: list[str] = []
    editor.controller.operation_reported.connect(reports.append)
    cmds.flushUndo()
    controller = editor.controller
    if operation == "lock":
        assert controller.set_selected_locked(keys, True)
        assert all(cmds.getAttr(name, lock=True) for name in names)
        assert reports[-1] == "適用候補: 2属性 / 対象外: 0件"
    elif operation == "display":
        assert controller.set_selected_display(keys, "channel_box")
        assert all(cmds.getAttr(name, channelBox=True) for name in names)
        assert reports[-1] == "適用候補: 2属性 / 対象外: 0件"
    elif operation == "key":
        assert controller.set_keyframes_selected(keys) == 2
        assert all(
            cmds.keyframe(name, query=True, keyframeCount=True) == 1
            for name in names
        )
    elif operation == "layer":
        assert controller.edit_animation_layers_selected(keys, add=True) == 2
        assert (
            len(
                cast(
                    list[str],
                    cmds.animLayer(layer, query=True, attribute=True),
                )
            )
            == 2
        )
    else:
        assert controller.set_muted_selected(keys, muted=True) == 2
        assert all(cmds.mute(name, query=True) for name in names)
    assert not created
    assert _values("mode") == [0, 1]
    cmds.undo()
    _events()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    if operation == "lock":
        assert not any(cmds.getAttr(name, lock=True) for name in names)
    elif operation == "display":
        assert all(cmds.getAttr(name, keyable=True) for name in names)
    elif operation == "key":
        assert not any(
            cmds.keyframe(name, query=True, keyframeCount=True)
            for name in names
        )
    elif operation == "layer":
        assert not cmds.animLayer(layer, query=True, attribute=True)
    else:
        assert not any(cmds.mute(name, query=True) for name in names)


@pytest.mark.parametrize("operation", ["lock", "display"])
@pytest.mark.parametrize("missing", [False, True])
def test_bulk_state_targets_report_missing_and_wrong_types(
    editor: ChannelBoxWidget, operation: str, missing: bool
) -> None:
    """対応先の欠損と型違いを除外し、状態操作の候補件数を通知する。"""
    cmds.deleteAttr("bulkOther.free")
    if not missing:
        cmds.addAttr(
            "bulkOther", longName="free", attributeType="long", keyable=True
        )
    keys = _keys(editor, "free")
    reports: list[str] = []
    editor.controller.operation_reported.connect(reports.append)
    cmds.flushUndo()
    if operation == "lock":
        assert editor.controller.set_selected_locked(keys, True)
        assert cmds.getAttr("bulkReference.free", lock=True)
        if not missing:
            assert not cmds.getAttr("bulkOther.free", lock=True)
    else:
        assert editor.controller.set_selected_display(keys, "hidden")
        assert not cmds.getAttr("bulkReference.free", keyable=True)
        if not missing:
            assert cmds.getAttr("bulkOther.free", keyable=True)
    assert reports[-1].startswith("適用候補: 1属性 / 対象外: 1件")
    assert ("対応する属性なし" if missing else "型・単位が異なる") in reports[
        -1
    ]
    cmds.undo()
    _events()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("operation", ["lock", "display"])
def test_bulk_state_targets_keep_each_rows_reference_constraint(
    editor: ChannelBoxWidget, operation: str
) -> None:
    """基準で状態変更不可の行全体を除外し、他の行だけを一括変更する。"""
    keys = _keys(editor, "translateX", "free")
    if operation == "lock":
        cmds.setAttr("bulkReference.translate", lock=True)
    else:
        # 定義由来の両Trueは、setAttrでは作れない表示編集不可の状態になる
        cmds.deleteAttr("bulkReference.free")
        definition = om.MFnNumericAttribute()
        attribute = definition.create(
            "free", "free", om.MFnNumericData.kDouble
        )
        definition.keyable = True
        definition.channelBox = True
        selection = om.MSelectionList()
        selection.add("bulkReference")
        om.MFnDependencyNode(selection.getDependNode(0)).addAttribute(
            attribute
        )
    _events()
    reports: list[str] = []
    editor.controller.operation_reported.connect(reports.append)
    cmds.flushUndo()
    if operation == "lock":
        assert editor.controller.set_selected_locked(keys, True)
        assert not cmds.getAttr("bulkOther.tx", lock=True)
        assert all(
            cmds.getAttr(node + ".free", lock=True)
            for node in ("bulkOther", "bulkReference")
        )
    else:
        assert editor.controller.set_selected_display(keys, "hidden")
        assert cmds.getAttr("bulkOther.free", keyable=True)
        assert not any(
            cmds.getAttr(node + ".tx", keyable=True)
            for node in ("bulkOther", "bulkReference")
        )
    assert reports[-1].startswith("適用候補: 2属性 / 対象外: 1件")
    assert "状態を変更できません" in reports[-1]
    cmds.undo()
    _events()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_thousand_node_nine_attribute_paste_avoids_temporary_view_models(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """九千属性のPasteで入力用ViewModelを作らず全件とUndo/Redoを維持する。"""
    nodes = tuple(
        cmds.createNode("transform", name=f"bulkPaste{index}")
        for index in range(1000)
    )
    paths = tuple(
        f"{group}.{group}{axis}"
        for group in ("translate", "rotate", "scale")
        for axis in ("X", "Y", "Z")
    )
    snapshots = tuple(
        MayaScalarValueSnapshot(
            path,
            (
                "distance"
                if path.startswith("translate")
                else ("angle" if path.startswith("rotate") else "number")
            ),
            2.0,
        )
        for path in paths
    )
    memory = _MemoryClipboard()
    memory.write(MayaScalarValueTransfer((MayaNodeValueSnapshot(snapshots),)))
    monkeypatch.setattr(editor.controller, "_value_clipboard", memory)
    cmds.select(*nodes, replace=True)
    _events()
    before = tuple(
        tuple(cmds.getAttr(node + "." + path) for path in paths)
        for node in nodes
    )
    cmds.flushUndo()
    created_models = 0
    original_init = cast(Callable[..., None], FloatViewModel.__init__)

    def initialize_model(
        model: FloatViewModel, *args: object, **kwargs: object
    ) -> None:
        """処理時間に依存せず、属性ごとのUI用オブジェクト生成を検出する。"""
        nonlocal created_models
        created_models += 1
        assert created_models <= 64
        original_init(model, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(FloatViewModel, "__init__", initialize_model)
        assert editor.controller.paste_copied_values()
        assert created_models == 0
    assert all(
        cmds.getAttr(node + "." + path) == 2
        for node in nodes
        for path in paths
    )
    cmds.undo()
    assert (
        tuple(
            tuple(cmds.getAttr(node + "." + path) for path in paths)
            for node in nodes
        )
        == before
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    assert all(
        cmds.getAttr(node + "." + path) == 2
        for node in nodes
        for path in paths
    )
    _events()


def _record_bulk_drag_rows(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> list[controller_module.ChannelRow]:
    """一時行だけを記録し、常設行の再生成と区別する。"""
    original = cast(
        Callable[..., controller_module.ChannelRow],
        getattr(editor.controller, "_create_value_row"),
    )
    created: list[controller_module.ChannelRow] = []

    def create(
        attribute: ScalarAttributeInfo,
        targets: list[str],
        excluded: list[str],
        *,
        monitor: bool = True,
    ) -> controller_module.ChannelRow:
        """本来の生成を行い、全対象を持つ一時行だけを保持する。"""
        row = original(attribute, targets, excluded, monitor=monitor)
        if not monitor:
            created.append(row)
        return row

    monkeypatch.setattr(editor.controller, "_create_value_row", create)
    return created


@pytest.mark.parametrize("name", ["free", "count"])
@pytest.mark.parametrize("offset", [False, True])
def test_bulk_numeric_refreshes_all_targets_only_after_input(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    offset: bool,
) -> None:
    """再利用中の全体同期を一回に保ち、各入力で対象全体を更新する。"""
    created = _record_bulk_drag_rows(editor, monkeypatch)
    keys = _keys(editor, name)
    apply = (
        editor.controller.offset_numeric_values
        if offset
        else editor.controller.apply_numeric_values
    )
    assert apply(keys, 1)
    assert apply(keys, 2)
    binding = created[-1].binding
    store = binding.store
    original_refresh = store.refresh
    calls: list[bool] = []

    def refresh() -> bool:
        """一時Bindingだけの全対象同期を記録する。"""
        calls.append(True)
        return original_refresh()

    monkeypatch.setattr(store, "refresh", refresh)
    assert apply(keys, 3)
    assert len(calls) == 1
    assert _values(name) == ([7, 9] if offset else [3, 3])


@pytest.mark.parametrize("name", ["free", "count"])
def test_bulk_numeric_rechecks_reference_lock_and_reports_current_reason(
    editor: ChannelBoxWidget, name: str
) -> None:
    """基準のlock変更をQt同期前に検出し、解除後は同じ対象へ再入力できる。"""
    controller = editor.controller
    keys = _keys(editor, name)
    assert controller.apply_numeric_values(keys, 4)
    assert controller.apply_numeric_values(keys, 5)
    reports: list[str] = []
    controller.operation_reported.connect(reports.append)
    cmds.setAttr("bulkReference." + name, lock=True)
    assert not controller.apply_numeric_values(keys, 6)
    assert _values(name) == [5, 5]
    assert "ロック" in reports[-1]
    assert not _row(
        editor, name
    ).row.binding.view_model.set_value_command.can_execute
    cmds.setAttr("bulkReference." + name, lock=False)
    assert controller.apply_numeric_values(keys, 7)
    assert _values(name) == [7, 7]
    assert _row(
        editor, name
    ).row.binding.view_model.set_value_command.can_execute


def _assert_bulk_drag_rows_disposed(
    rows: Sequence[controller_module.ChannelRow],
) -> None:
    """Qtの即時・遅延破棄のどちらでも旧行が入力不能か確認する。"""
    assert rows
    assert all(
        not qt.isValid(row.binding) or row.binding.is_disposed for row in rows
    )


def test_bulk_drag_reuses_resolution_and_releases_between_gestures(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ドラッグ内だけ全対象を一度解決し、表示監視とUndoの区切りを保つ。"""
    widget = _row(editor, "count")
    view = widget.editor
    assert isinstance(view, IntSliderSpinBox)
    assert widget.row.binding.target_states[0].input_state is not None
    created = _record_bulk_drag_rows(editor, monkeypatch)
    original = controller_module.inspect_scalar_attribute_types
    inspected: list[str] = []

    def inspect(
        name: str, *, paths: Sequence[str] | None = None
    ) -> tuple[ScalarAttributeTypeInfo, ...]:
        """実際の属性解決だけを数え、キャッシュ利用との違いを固定する。"""
        inspected.append(name)
        return original(name, paths=paths)

    monkeypatch.setattr(
        controller_module, "inspect_scalar_attribute_types", inspect
    )
    view.slider.setSliderDown(True)
    for value in (20, 30, 40):
        view.slider.setValue(value)
        assert _values("count") == [value, value]
        assert len(created) == 1 and len(inspected) == 2
        assert not created[0].binding.is_disposed
        assert all(
            target.input_state is None
            for target in created[0].binding.target_states
        )
    view.slider.setSliderDown(False)
    _assert_bulk_drag_rows_disposed(created)
    assert not editor.controller.value_edit_session.is_editing
    assert widget.row.binding.target_states[0].input_state is not None
    view.slider.setSliderDown(True)
    view.slider.setValue(50)
    assert len(created) == 2 and len(inspected) == 4
    assert created[0].binding is not created[1].binding
    view.slider.setSliderDown(False)
    _assert_bulk_drag_rows_disposed(created)
    cmds.undo()
    _events()
    assert _values("count") == [40, 40]
    cmds.undo()
    _events()
    assert _values("count") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bulk_drag_rejects_recreated_secondary_attribute(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ドラッグ中の属性再作成へ旧対象を接続せず、先行入力を維持する。"""
    created = _record_bulk_drag_rows(editor, monkeypatch)
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    view.slider.setSliderDown(True)
    view.slider.setValue(20)
    cmds.deleteAttr("bulkOther.count")
    cmds.addAttr(
        "bulkOther",
        longName="count",
        attributeType="long",
        minValue=0,
        maxValue=100,
        keyable=True,
    )
    _set("bulkOther.count", 99)
    view.slider.setValue(30)
    assert _values("count") == [99, 20]
    assert len(created) == 1
    _assert_bulk_drag_rows_disposed(created)
    assert not editor.controller.value_edit_session.is_editing
    assert not view.slider.isSliderDown()
    assert editor.message_label.isVisible()


@pytest.mark.parametrize(
    "reason",
    ["mode", "time", "selection", "filter", "close", "hide", "dispose"],
)
def test_bulk_drag_interruption_releases_cached_targets(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    """画面や操作対象の切替で一時行を破棄し、後続Undoへ操作を混ぜない。"""
    marker = cmds.createNode(
        "network", name="bulkDragUndoMarker", skipSelect=True
    )
    cmds.addAttr(marker, longName="value", attributeType="double")
    cmds.flushUndo()
    created = _record_bulk_drag_rows(editor, monkeypatch)
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    view.slider.setSliderDown(True)
    view.slider.setValue(20)
    assert editor.controller.value_edit_session.is_editing
    if reason == "mode":
        editor.controller.set_mode("states")
    elif reason == "time":
        cmds.currentTime(cmds.currentTime(query=True) + 1)
    elif reason == "selection":
        cmds.select("bulkOther", replace=True)
    elif reason == "filter":
        editor.controller.set_attribute_filter("hidden")
    elif reason == "close":
        editor.close()
    elif reason == "dispose":
        editor.controller.dispose()
    else:
        editor.hide()
    _events()
    _assert_bulk_drag_rows_disposed(created)
    assert not editor.controller.value_edit_session.is_editing
    if qt.isValid(view):
        assert not view.slider.isSliderDown()
    _set(marker + ".value", 7)
    cmds.undo()
    _events()
    assert cmds.getAttr(marker + ".value") == 0
    assert _values("count") == [20, 20]


@pytest.mark.parametrize("direct", [False, True])
def test_bulk_drag_rechecks_secondary_lock_and_new_range(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    direct: bool,
) -> None:
    """対象を再利用してもlockと新しい範囲を読み、失敗前の確定値を保つ。"""
    created = _record_bulk_drag_rows(editor, monkeypatch)
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    view.slider.setSliderDown(True)
    view.slider.setValue(20)
    cmds.setAttr("bulkOther.count", lock=True)
    view.slider.setValue(30)
    assert _values("count") == [20, 30]
    cmds.setAttr("bulkOther.count", lock=False)
    view.slider.setValue(40)
    assert _values("count") == [40, 40]
    assert len(created) == 1
    cmds.addAttr("bulkOther.count", edit=True, maxValue=45)
    if direct:
        with pytest.raises(ValueError):
            editor.controller.apply_numeric_values(_keys(editor, "count"), 50)
    else:
        view.slider.setValue(50)
        assert not view.slider.isSliderDown()
        assert editor.message_label.isVisible()
    assert _values("count") == [40, 40]
    _assert_bulk_drag_rows_disposed(created)
    assert not editor.controller.value_edit_session.is_editing
    cmds.undo()
    _events()
    assert _values("count") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bulk_slider_wheel_reuses_targets_and_keeps_separate_undo(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """wheel三イベントの対象は二回だけ準備し、Undoは個別に維持する。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    view.slider.setFocus()
    _events()
    assert view.slider.hasFocus()
    created = _record_bulk_drag_rows(editor, monkeypatch)
    snapshots: list[list[object]] = []
    for index in range(3):
        event = qt.QtGui.QWheelEvent(
            qt.QPointF(5, 5),
            qt.QPointF(5, 5),
            qt.QPoint(),
            qt.QPoint(0, 120),
            qt.Qt.MouseButton.NoButton,
            qt.Qt.KeyboardModifier.NoModifier,
            qt.Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        qt.QApplication.sendEvent(view.slider, event)
        snapshots.append(_values("count"))
        assert snapshots[-1][0] == snapshots[-1][1]
        assert len(created) == min(index + 1, 2)
        _assert_bulk_drag_rows_disposed(created[:1])
        if index:
            assert not created[-1].binding.is_disposed
        assert not editor.controller.value_edit_session.is_editing
    assert snapshots[0] != [1, 3] and snapshots[1] != snapshots[0]
    for expected in reversed(snapshots[:-1]):
        cmds.undo()
        _events()
        assert _values("count") == expected
    cmds.undo()
    _events()
    assert _values("count") == [1, 3]
    _assert_bulk_drag_rows_disposed(created)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_other_numeric_operation_finishes_cached_drag_before_undo(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """別の増減入力はドラッグのcacheとUndoを閉じてから独立して適用する。"""
    created = _record_bulk_drag_rows(editor, monkeypatch)
    keys = _keys(editor, "count")
    editor.controller.begin_value_edit()
    editor.controller.apply_numeric_values(keys, 20)
    assert editor.controller.offset_numeric_values(keys, 1)
    _assert_bulk_drag_rows_disposed(created)
    assert not editor.controller.value_edit_session.is_editing
    assert _values("count") == [21, 21]
    cmds.undo()
    _events()
    assert _values("count") == [20, 20]
    cmds.undo()
    _events()
    assert _values("count") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bulk_drag_start_failure_closes_edit_session(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """対象監視の初期登録に失敗しても、未書込みの連続編集を終了する。"""

    def fail_register(
        _registry: controller_module.MayaCallbackRegistry, callback_id: int
    ) -> int:
        """作成済みの実callbackを除いてから登録失敗を再現する。"""
        controller_module.om.MMessage.removeCallback(callback_id)
        raise RuntimeError("test callback registration")

    monkeypatch.setattr(
        controller_module.MayaCallbackRegistry, "register", fail_register
    )
    editor.controller.begin_value_edit()
    with pytest.raises(RuntimeError, match="test callback registration"):
        editor.controller.apply_numeric_values(_keys(editor, "count"), 20)
    assert not editor.controller.value_edit_session.is_editing
    assert _values("count") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bulk_drag_key_change_never_resolves_replacement_at_old_ancestor_path(
    editor: ChannelBoxWidget,
) -> None:
    """祖先改名後に行を切り替えても、旧pathへ作られた別nodeを編集しない。"""
    parent = cmds.createNode(
        "transform", name="bulkDragParent", skipSelect=True
    )
    cmds.parent("bulkOther", parent)
    cmds.select("|bulkDragParent|bulkOther", "bulkReference", replace=True)
    editor.refresh()
    _events()
    count_keys = _keys(editor, "count")
    gain_keys = _keys(editor, "gain")
    editor.controller.begin_value_edit()
    editor.controller.apply_numeric_values(count_keys, 20)
    cmds.rename(parent, "bulkDragRenamedParent")
    old_parent = cmds.createNode(
        "transform", name="bulkDragParent", skipSelect=True
    )
    replacement = cmds.createNode(
        "transform", name="bulkOther", parent=old_parent, skipSelect=True
    )
    cmds.addAttr(
        replacement, longName="gain", attributeType="double", keyable=True
    )
    _set("|bulkDragParent|bulkOther.gain", 99)
    try:
        editor.controller.apply_numeric_values(gain_keys, 7)
    except RuntimeError:
        # Mayaが選択変更も通知した場合は、旧行を終了して入力を拒否する
        pass
    finally:
        editor.controller.finish_value_edit()
    assert cmds.getAttr("|bulkDragParent|bulkOther.gain") == 99


def _wheel(target: qt.QWidget, *, require_accepted: bool = True) -> None:
    """同じ入力先へフォーカス付きの実wheelイベントを一刻み送る。"""
    target.setFocus()
    assert target.hasFocus()
    event = qt.QtGui.QWheelEvent(
        qt.QPointF(5, 5),
        qt.QPointF(5, 5),
        qt.QPoint(),
        qt.QPoint(0, 120),
        qt.Qt.MouseButton.NoButton,
        qt.Qt.KeyboardModifier.NoModifier,
        qt.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    qt.QApplication.sendEvent(target, event)
    if require_accepted:
        assert event.isAccepted()


def _assert_numeric_values(name: str, expected: Sequence[float | int]) -> None:
    """数値属性の全対象を、浮動小数点の丸めだけ許容して比較する。"""
    assert all(
        isclose(cast(float, actual), value, abs_tol=1e-9)
        for actual, value in zip(_values(name), expected, strict=True)
    )


def _wheel_targets(editor: ChannelBoxWidget) -> object | None:
    """非公開の保持対象を、不透明な寿命確認用objectとして参照する。"""
    return cast(object | None, getattr(editor.controller, "_bulk_value_cache"))


def _wheel_pending_keys(editor: ChannelBoxWidget) -> object | None:
    """初回入力の候補が中断後に残っていないか確認する。"""
    return cast(
        object | None, getattr(editor.controller, "_bulk_numeric_keys")
    )


def _wheel_timer(editor: ChannelBoxWidget) -> qt.QTimer:
    """保持期限の非公開timerを、Qtの型境界で取り出す。"""
    return cast(qt.QTimer, getattr(editor.controller, "_bulk_value_timer"))


@pytest.mark.parametrize("name", ["free", "count"])
def test_bulk_value_wheel_reuses_targets_and_preserves_relative_undo(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """floatと整数の値欄で差を保ち、三入力を別Undo・Redoで戻す。"""
    view = _row(editor, name).editor
    assert isinstance(view, (FloatValueStepSpinBox, IntSliderSpinBox))
    delta = view.spin_box.singleStep()
    created = _record_bulk_drag_rows(editor, monkeypatch)
    inspected: list[str] = []
    original = controller_module.inspect_scalar_attribute_types

    def inspect(
        node: str, *, paths: Sequence[str] | None = None
    ) -> tuple[ScalarAttributeTypeInfo, ...]:
        """操作対象の照合が三入力目に再実行されないことを数える。"""
        inspected.append(node)
        return original(node, paths=paths)

    monkeypatch.setattr(
        controller_module, "inspect_scalar_attribute_types", inspect
    )
    for index in range(1, 4):
        _wheel(view.spin_box)
        _assert_numeric_values(name, [1 + index * delta, 3 + index * delta])
        assert not editor.controller.value_edit_session.is_editing
    assert len(created) == 2
    assert len(inspected) == 4
    assert not created[-1].binding.is_disposed
    for index in range(2, -1, -1):
        cmds.undo()
        _assert_numeric_values(name, [1 + index * delta, 3 + index * delta])
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    for index in range(1, 4):
        cmds.redo()
        _assert_numeric_values(name, [1 + index * delta, 3 + index * delta])
    _events()
    _assert_bulk_drag_rows_disposed(created)


def test_bulk_wheel_reads_current_value_step_and_lock_each_event(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """対象再利用中も外部値・Step・後続lockの変更を次の入力へ反映する。"""
    view = _row(editor, "free").editor
    assert isinstance(view, FloatValueStepSpinBox)
    created = _record_bulk_drag_rows(editor, monkeypatch)
    _wheel(view.spin_box)
    _wheel(view.spin_box)
    view.spin_box.setSingleStep(2)
    _set("bulkOther.free", 37)
    _wheel(view.spin_box)
    assert cmds.getAttr("bulkOther.free") == 39
    cmds.setAttr("bulkOther.free", lock=True)
    _wheel(view.spin_box)
    assert cmds.getAttr("bulkOther.free") == 39
    cmds.setAttr("bulkOther.free", lock=False)
    _wheel(view.spin_box)
    assert cmds.getAttr("bulkOther.free") == 41
    assert len(created) == 2


@pytest.mark.parametrize("name", ["gain", "count"])
def test_bulk_wheel_revalidates_secondary_range_and_clears_on_failure(
    editor: ChannelBoxWidget, name: str
) -> None:
    """後続だけの範囲違反を毎回検証し、失敗時に全対象と保持期限を解放する。"""
    keys = _keys(editor, name)
    for _ in range(2):
        assert editor.controller.offset_numeric_values(keys, 1)
    before = _values(name)
    cmds.addAttr(f"bulkOther.{name}", edit=True, maxValue=3)
    with pytest.raises(ValueError):
        editor.controller.offset_numeric_values(keys, 1)
    assert _values(name) == before
    assert _wheel_targets(editor) is None
    assert _wheel_pending_keys(editor) is None
    assert not _wheel_timer(editor).isActive()


def test_bulk_wheel_multiple_rows_read_changed_display_units(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """複数型と単位の行でも、保持中の単位変更後に同じ表示差分を加える。"""
    view = _row(editor, "free").editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setSingleStep(1)
    editor.table_view.select_keys(
        _keys(editor, "free", "count", "translateX", "rotateX")
    )
    created = _record_bulk_drag_rows(editor, monkeypatch)
    for _ in range(2):
        _wheel(view.spin_box)
    assert len(created) == 8
    cmds.currentUnit(linear="m", angle="rad")
    before_tx = cast(list[float], _values("translateX"))
    before_rx = cast(list[float], _values("rotateX"))
    _wheel(view.spin_box)
    _assert_numeric_values("translateX", [value + 1 for value in before_tx])
    _assert_numeric_values("rotateX", [value + 1 for value in before_rx])
    _assert_numeric_values("count", [4, 6])
    assert len(created) == 8


def test_bulk_wheel_cache_registration_failure_releases_and_keeps_prior_undo(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """二入力目の監視開始失敗でも、前の単発Undoと対象解放を保つ。"""
    keys = _keys(editor, "count")
    assert editor.controller.offset_numeric_values(keys, 1)

    def fail_register(
        _registry: controller_module.MayaCallbackRegistry, callback_id: int
    ) -> int:
        """実際に作成されたcallbackを解放してから登録失敗を再現する。"""
        controller_module.om.MMessage.removeCallback(callback_id)
        raise RuntimeError("test wheel callback registration")

    monkeypatch.setattr(
        controller_module.MayaCallbackRegistry, "register", fail_register
    )
    with pytest.raises(RuntimeError, match="test wheel callback registration"):
        editor.controller.offset_numeric_values(keys, 1)
    assert _wheel_targets(editor) is None
    assert _wheel_pending_keys(editor) is None
    assert not _wheel_timer(editor).isActive()
    assert _values("count") == [2, 4]
    cmds.undo()
    assert _values("count") == [1, 3]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bulk_wheel_expiry_during_write_defers_target_disposal(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """書込み中に期限通知が再入しても対象を先に破棄せず、独立Undoを保つ。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    created = _record_bulk_drag_rows(editor, monkeypatch)
    _wheel(view.spin_box)
    _wheel(view.spin_box)
    triggered = False

    def expire(message: int, *_args: object) -> None:
        """基準の変更時に、Qt待機処理へ再入した期限通知を再現する。"""
        nonlocal triggered
        if (
            triggered
            or not message & controller_module.om.MNodeMessage.kAttributeSet
        ):
            return
        triggered = True
        _wheel_timer(editor).timeout.emit()
        assert not created[-1].binding.is_disposed

    selection = controller_module.om.MSelectionList()
    selection.add("bulkReference")
    callback = controller_module.om.MNodeMessage.addAttributeChangedCallback(
        selection.getDependNode(0), expire
    )
    try:
        _wheel(view.spin_box)
    finally:
        controller_module.om.MMessage.removeCallback(callback)
    assert triggered
    assert _values("count") == [4, 6]
    _assert_bulk_drag_rows_disposed(created)
    assert _wheel_pending_keys(editor) is None
    cmds.undo()
    assert _values("count") == [3, 5]


def test_bulk_wheel_expires_targets_and_starts_with_single_input_again(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """実timerの期限で監視を解放し、次の単発入力には対象を持ち越さない。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    created = _record_bulk_drag_rows(editor, monkeypatch)
    _wheel(view.spin_box)
    _wheel(view.spin_box)
    _wheel_timer(editor).setInterval(5)
    _wheel_timer(editor).start()
    loop = qt.QtCore.QEventLoop()
    stop = qt.QTimer()
    stop.setSingleShot(True)
    stop.timeout.connect(loop.quit)
    stop.start(25)
    loop.exec()
    assert _wheel_targets(editor) is None
    assert _wheel_pending_keys(editor) is None
    _assert_bulk_drag_rows_disposed(created)
    _wheel_timer(editor).setInterval(500)
    _wheel(view.spin_box)
    assert len(created) == 3
    assert _wheel_targets(editor) is None
    _assert_bulk_drag_rows_disposed(created)
    _wheel(view.spin_box)
    assert len(created) == 4
    assert _wheel_targets(editor) is not None


@pytest.mark.parametrize(
    "reason",
    [
        "rows",
        "nodes",
        "mode",
        "filter",
        "time",
        "undo",
        "hide",
        "close",
        "dispose",
        "refresh",
        "other",
        "scene",
    ],
)
def test_bulk_wheel_idle_targets_release_on_interruption(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    """Undoを開いていない待機中にも、操作条件と画面の切替で監視を解放する。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    created = _record_bulk_drag_rows(editor, monkeypatch)
    _wheel(view.spin_box)
    _wheel(view.spin_box)
    assert _wheel_targets(editor) is not None
    if reason == "rows":
        editor.table_view.select_keys(_keys(editor, "free"))
    elif reason == "nodes":
        cmds.select("bulkOther", replace=True)
    elif reason == "mode":
        editor.controller.set_mode("values")
    elif reason == "filter":
        editor.controller.set_attribute_filter("all")
    elif reason == "time":
        cmds.currentTime(cmds.currentTime(query=True) + 1)
    elif reason == "undo":
        cmds.undo()
    elif reason == "hide":
        editor.hide()
    elif reason == "close":
        editor.close()
    elif reason == "dispose":
        editor.controller.dispose()
    elif reason == "refresh":
        editor.refresh()
    elif reason == "other":
        editor.controller.apply_bool_values(_keys(editor, "enabled"), True)
    else:
        cast(Callable[..., str], cmds.file)(new=True, force=True)
    _events()
    _assert_bulk_drag_rows_disposed(created)
    assert _wheel_targets(editor) is None
    assert _wheel_pending_keys(editor) is None
    assert not _wheel_timer(editor).isActive()
    assert not editor.controller.value_edit_session.is_editing


def test_bulk_wheel_re_resolves_recreated_attribute_between_events(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """イベント間の同名再作成は旧Bindingを捨て、新しい現在値から加算する。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    created = _record_bulk_drag_rows(editor, monkeypatch)
    _wheel(view.spin_box)
    _wheel(view.spin_box)
    cmds.deleteAttr("bulkOther.count")
    cmds.addAttr(
        "bulkOther",
        longName="count",
        attributeType="long",
        minValue=0,
        maxValue=100,
        defaultValue=50,
        keyable=True,
    )
    _wheel(view.spin_box)
    assert _values("count") == [51, 6]
    assert len(created) == 3
    _assert_bulk_drag_rows_disposed(created)
    assert _wheel_targets(editor) is None


@pytest.mark.parametrize("prior_inputs", [0, 1, 2])
@pytest.mark.parametrize("part", ["slider", "spin_box"])
def test_bulk_wheel_recreation_during_write_rolls_back_surviving_targets(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    prior_inputs: int,
    part: str,
) -> None:
    """保持した対象の書込み中に同名再作成が起きても、別実体を書き換えない。"""
    view = _row(editor, "count").editor
    assert isinstance(view, IntSliderSpinBox)
    created = _record_bulk_drag_rows(editor, monkeypatch)
    target = view.slider if part == "slider" else view.spin_box
    for _ in range(prior_inputs):
        _wheel(target)
    before = _values("count")
    triggered = False

    def replace(message: int, *_args: object) -> None:
        """基準値の書込み直後に、後続の属性を別実体へ置き換える。"""
        nonlocal triggered
        if (
            triggered
            or not message & controller_module.om.MNodeMessage.kAttributeSet
        ):
            return
        triggered = True
        cmds.deleteAttr("bulkOther.count")
        cmds.addAttr(
            "bulkOther",
            longName="count",
            attributeType="long",
            minValue=0,
            maxValue=100,
            defaultValue=77,
            keyable=True,
        )

    selection = controller_module.om.MSelectionList()
    selection.add("bulkReference")
    node = selection.getDependNode(0)
    callback = controller_module.om.MNodeMessage.addAttributeChangedCallback(
        node, replace
    )
    try:
        _wheel(target, require_accepted=False)
    finally:
        controller_module.om.MMessage.removeCallback(callback)
    assert triggered
    assert _values("count") == [77, before[-1]]
    assert editor.message_label.isVisible()
    _assert_bulk_drag_rows_disposed(created)
    assert _wheel_targets(editor) is None
    assert not _wheel_timer(editor).isActive()
