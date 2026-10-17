# coding: utf-8
"""多数ノードモードの基準表示と、操作時だけの全対象編集を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Literal, cast

import pytest
from maya import cmds

from bd_util.maya.node.inspection import ScalarAttributeInfo
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
    _row(editor, "free").copy_selected_values_action.trigger()
    copied = memory.read()
    assert len(copied.nodes) == 1
    assert copied.nodes[0].values[0].value == 3
    _set("bulkReference.free", 6)
    _events()
    row = _row(editor, "free")
    row.context_menu.aboutToShow.emit()
    assert row.paste_selected_values_action.isEnabled()
    row.paste_selected_values_action.trigger()
    _events()
    assert _values("free") == [3, 3]


def test_align_lock_and_keyframe_menus_keep_all_targets(
    editor: ChannelBoxWidget,
) -> None:
    """混在を常時計測しなくても整列・lock・キー設定を全対象へ実行できる。"""
    row = _row(editor, "free")
    editor.table_view.select_keys(_keys(editor, "free"))
    row.context_menu.aboutToShow.emit()
    assert row.align_action.isEnabled()
    row.align_action.trigger()
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
    editor: ChannelBoxWidget, operation: str
) -> None:
    """千対象のlock・表示変更が値を変えず、一回のUndo/Redoで復元する。"""
    nodes = tuple(
        cmds.createNode("transform", name=f"bulkState{index}")
        for index in range(1000)
    )
    cmds.select(*nodes, replace=True)
    _events()
    keys = _keys(editor, "translateX")
    cmds.flushUndo()

    if operation == "lock":
        assert editor.controller.set_selected_locked(keys, True)
    else:
        assert editor.controller.set_selected_display(keys, "channel_box")

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
