# coding: utf-8
"""Channel Editorのenum入力・定義差・表示同期・寿命を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaEnumPlugsBinding
from bd_util.ui import EnumComboBox, EnumItem, qt

from bd_tools.channel_editor.widget import (
    AttributeRowWidget,
    ChannelEditorWidget,
)

_NODES = ("enumA", "enumB", "enumC")
_DEFINITION = "Negative=-2:Off=0:Preview=5:Final=10"


def _events() -> None:
    """遅延同期とQtの破棄を進め、選択変更後の行を確定する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set(name: str, value: int) -> None:
    """enum用の整数引数だけをMaya commandの型境界で補正する。"""
    cast(Callable[[str, int], None], cmds.setAttr)(name, value)


def _values() -> list[int]:
    """一括編集対象の現在値を選択順で読む。"""
    return [cast(int, cmds.getAttr(name + ".mode")) for name in _NODES]


def _row(
    editor: ChannelEditorWidget, path: str = "mode"
) -> AttributeRowWidget:
    """正式pathに対応する、再構築後の最新の行を取得する。"""
    return next(w for w in editor.row_widgets if w.row.attribute.path == path)


def _combo(editor: ChannelEditorWidget) -> EnumComboBox:
    """enum行が専用Viewへ接続されていることを確認する。"""
    row = _row(editor)
    assert isinstance(row.editor, EnumComboBox)
    assert isinstance(row.row.binding, MayaEnumPlugsBinding)
    return row.editor


@pytest.fixture
def enum_editor(
    qt_application: qt.QApplication,
) -> Iterator[ChannelEditorWidget]:
    """同じ定義で異なる現在値を持つ3ノードを表示する。"""
    assert qt_application is not None
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)
    for name, value in zip(_NODES, (5, 0, -2)):
        cmds.createNode("transform", name=name)
        cmds.addAttr(
            name,
            longName="mode",
            attributeType="enum",
            enumName=_DEFINITION,
            keyable=True,
        )
        _set(name + ".mode", value)
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


def test_enum_initial_refresh_and_same_index_only_read(
    enum_editor: ChannelEditorWidget,
) -> None:
    """表示・更新・同一index選択は、混在したsceneとUndoを維持する。"""
    combo = _combo(enum_editor)
    assert combo.currentText() == "Preview"
    assert combo.currentIndex() == 2
    assert combo.width() == 156
    item = combo.currentData()
    assert isinstance(item, EnumItem) and item.value == 5
    assert _row(enum_editor).name_label.text().startswith("• ")
    assert "3/3" in combo.toolTip()
    combo.setCurrentIndex(combo.currentIndex())
    enum_editor.refresh()
    _events()
    assert _values() == [5, 0, -2]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_enum_selection_writes_sparse_value_and_undo_restores_each_target(
    enum_editor: ChannelEditorWidget,
) -> None:
    """項目位置ではなく実整数を一括適用し、一回のUndoで混在へ戻す。"""
    _combo(enum_editor).setCurrentIndex(3)
    assert _values() == [10, 10, 10]
    cmds.undo()
    _events()
    assert _values() == [5, 0, -2]
    assert _combo(enum_editor).currentText() == "Preview"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert _values() == [10, 10, 10]
    assert _combo(enum_editor).currentText() == "Final"


def test_enum_explicit_alignment_and_noop_do_not_duplicate_undo(
    enum_editor: ChannelEditorWidget,
) -> None:
    """代表と同じ値への明示入力だけを適用し、同値入力は履歴を増やさない。"""
    _row(enum_editor).align_action.trigger()
    assert _values() == [5, 5, 5]
    assert not _row(enum_editor).align_action.isEnabled()
    assert not _row(enum_editor).row.binding.apply_representative_value()
    cmds.undo()
    _events()
    assert _values() == [5, 0, -2]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_enum_external_value_changes_do_not_rebuild_or_propagate(
    enum_editor: ChannelEditorWidget,
) -> None:
    """外部の値変更ではViewを保ち、他対象へ書き戻さない。"""
    combo = _combo(enum_editor)
    _set("enumA.mode", -2)
    _events()
    assert _combo(enum_editor) is combo
    assert combo.currentText() == "Negative"
    assert _values() == [-2, 0, -2]
    _set("enumB.mode", -2)
    _events()
    assert not _row(enum_editor).row.binding.is_mixed


@pytest.mark.parametrize(
    "definition",
    [
        "Negative=-2:Off=0:Other=5:Final=10",
        "Negative=-2:Off=0:Preview=6:Final=10",
    ],
)
def test_enum_mismatched_definitions_are_excluded_before_binding(
    enum_editor: ChannelEditorWidget, definition: str
) -> None:
    """名前や整数対応が異なる対象を除外し、他の入力行も維持する。"""
    cmds.addAttr("enumB.mode", edit=True, enumName=definition)
    cmds.setAttr("enumB.mode", lock=True)
    enum_editor.refresh()
    _events()
    assert _row(enum_editor, "translate.translateX")
    assert not enum_editor.message_label.isVisible()
    assert "enumB: enum定義" in _combo(enum_editor).toolTip()
    assert "2/3" in _combo(enum_editor).toolTip()
    _combo(enum_editor).setCurrentIndex(3)
    assert _values() == [10, 0, 10]


def test_enum_definition_changes_block_until_regrouped_without_writing(
    enum_editor: ChannelEditorWidget,
) -> None:
    """使用中の不一致で入力を止め、更新時に対象を再判定する。"""
    combo = _combo(enum_editor)
    cmds.addAttr("enumB.mode", edit=True, enumName="Off=0:Other=5:Final=10")
    _events()
    assert _combo(enum_editor) is combo
    assert not combo.isEnabled()
    assert "0/3" in combo.toolTip()
    assert "enum定義" in combo.toolTip()
    assert not _row(enum_editor).align_action.isEnabled()
    cmds.flushUndo()
    enum_editor.refresh()
    _events()
    assert _combo(enum_editor).isEnabled()
    assert _row(enum_editor).row.binding.target_count == 2
    assert _values() == [5, 0, -2]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.addAttr("enumB.mode", edit=True, enumName=_DEFINITION)
    enum_editor.refresh()
    _events()
    assert _row(enum_editor).row.binding.target_count == 3


def test_enum_undefined_representative_can_be_replaced_but_not_aligned(
    enum_editor: ChannelEditorWidget,
) -> None:
    """未定義整数を表示したまま保持し、有効項目の入力とUndoを許可する。"""
    _set("enumA.mode", 2)
    _events()
    combo = _combo(enum_editor)
    assert combo.currentIndex() == -1
    assert combo.placeholderText() == "未定義 (2)"
    assert combo.isEnabled()
    assert not _row(enum_editor).align_action.isEnabled()
    assert "未定義 (2)" in combo.toolTip()
    cmds.flushUndo()
    combo.setCurrentIndex(0)
    assert _values() == [-2, -2, -2]
    cmds.undo()
    _events()
    assert _values() == [2, 0, -2]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_enum_lock_and_animation_respect_representative_policy(
    enum_editor: ChannelEditorWidget,
) -> None:
    """後続lockを除外し、基準へのアニメーション接続で行を停止する。"""
    cmds.setAttr("enumB.mode", lock=True)
    _events()
    assert "2/3" in _combo(enum_editor).toolTip()
    _combo(enum_editor).setCurrentIndex(3)
    assert _values() == [10, 0, 10]
    cmds.setKeyframe("enumA.mode")
    _events()
    assert not _combo(enum_editor).isEnabled()
    assert not _row(enum_editor).align_action.isEnabled()
    assert "0/3" in _combo(enum_editor).toolTip()


def test_enum_display_flags_builtin_compound_and_array_scope(
    enum_editor: ChannelEditorWidget,
) -> None:
    """標準enumと表示対象のcompound子を返し、非表示と配列を除く。"""
    cmds.setAttr("enumA.rotateOrder", channelBox=True)
    cmds.setAttr("enumA.mode", keyable=False, channelBox=True)
    for name, multi in (("group", False), ("records", True)):
        cmds.addAttr(
            "enumA",
            longName=name,
            attributeType="compound",
            numberOfChildren=1,
            multi=multi,
        )
        cmds.addAttr(
            "enumA",
            longName=name + "Mode",
            parent=name,
            attributeType="enum",
            enumName="A:B",
            keyable=True,
        )
    cmds.addAttr(
        "enumA", longName="hiddenMode", attributeType="enum", enumName="A:B"
    )
    enum_editor.refresh()
    _events()
    assert isinstance(_row(enum_editor, "rotateOrder").editor, EnumComboBox)
    assert isinstance(
        _row(enum_editor, "group.groupMode").editor, EnumComboBox
    )
    assert _combo(enum_editor).isEnabled()
    paths = {w.row.attribute.path for w in enum_editor.row_widgets}
    assert {"hiddenMode", "records.recordsMode"}.isdisjoint(paths)


def test_enum_selection_and_dispose_close_popup_and_stop_old_input(
    enum_editor: ChannelEditorWidget,
) -> None:
    """選択変更と終了は開いた選択肢と古いBindingからの入力を終了する。"""
    combo = _combo(enum_editor)
    binding = _row(enum_editor).row.binding
    assert isinstance(binding, MayaEnumPlugsBinding)
    combo.showPopup()
    cmds.select("enumB", replace=True)
    _events()
    assert binding.is_disposed
    with pytest.raises(RuntimeError):
        binding.set_value(10)
    assert _values() == [5, 0, -2]
    current = _combo(enum_editor)
    current.showPopup()
    enum_editor.dispose()
    _events()
    assert not current.isEnabled()
    assert not current.view().isVisible()
