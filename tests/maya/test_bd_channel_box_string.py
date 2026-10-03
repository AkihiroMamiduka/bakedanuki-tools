# coding: utf-8
"""bdChannelBoxの汎用typed string行と一括操作を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaScalarValueClipboard, MayaScalarValueTransfer
from bd_util.ui import StringLineEdit, qt

from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


def _events() -> None:
    """MayaとQtの予約済み表示同期を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _new_scene() -> None:
    """一時sceneへ切り替えてテストのノードを隔離する。"""
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)


def _row(widget: ChannelBoxWidget, path: str) -> AttributeRowWidget:
    """正式pathに対応する値入力行を返す。"""
    row = next(
        item for item in widget.row_widgets if item.row.attribute.path == path
    )
    assert isinstance(row, AttributeRowWidget)
    return row


def _click(widget: qt.QWidget) -> None:
    """実際のマウス通知で文字欄の選択挙動を確認する。"""
    position = widget.rect().center()
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(position),
            qt.QPointF(widget.mapToGlobal(position)),
            qt.Qt.MouseButton.LeftButton,
            (
                qt.Qt.MouseButton.LeftButton
                if kind == qt.QEvent.Type.MouseButtonPress
                else qt.Qt.MouseButton.NoButton
            ),
            qt.Qt.KeyboardModifier.NoModifier,
        )
        qt.QApplication.sendEvent(widget, event)


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """二つの独立したstring属性を持つノードを選択する。"""
    assert qt_application is not None
    _new_scene()
    for name, caption, alternate in (
        ("channelStringA", "先頭", "左"),
        ("channelStringB", "後続", "右"),
    ):
        cmds.createNode("transform", name=name)
        for path, value in (("caption", caption), ("alternate", alternate)):
            cmds.addAttr(name, longName=path, dataType="string")
            cmds.setAttr(f"{name}.{path}", value, type="string")
            cmds.setAttr(f"{name}.{path}", channelBox=True)
    cmds.select("channelStringB", "channelStringA", replace=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    widget = ChannelBoxWidget()
    widget.show()
    _events()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    _new_scene()


def test_string_rows_show_mixed_and_edit_selected_paths_once(
    editor: ChannelBoxWidget,
) -> None:
    """表示は無変更で、選択した複数string行を一回で編集・Undoする。"""
    first = _row(editor, "caption")
    second = _row(editor, "alternate")
    assert isinstance(first.editor, StringLineEdit)
    assert isinstance(second.editor, StringLineEdit)
    assert first.row.binding.is_mixed
    assert first.editor.text() == "先頭"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    editor.table_view.select_keys(
        (("caption", "string"), ("alternate", "string"))
    )
    _click(first.editor)
    assert editor.table_view.selected_keys() == (
        ("caption", "string"),
        ("alternate", "string"),
    )
    first.editor.setText(" 共通 😀 ")
    first.editor.textEdited.emit(" 共通 😀 ")
    first.editor.returnPressed.emit()
    for node in ("channelStringA", "channelStringB"):
        assert cmds.getAttr(node + ".caption") == " 共通 😀 "
        assert cmds.getAttr(node + ".alternate") == " 共通 😀 "
    cmds.undo()
    _events()
    assert cmds.getAttr("channelStringA.caption") == "先頭"
    assert cmds.getAttr("channelStringB.caption") == "後続"
    assert cmds.getAttr("channelStringA.alternate") == "左"
    assert cmds.getAttr("channelStringB.alternate") == "右"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_string_copy_follows_last_selected_node(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """選択順だけを変えるとstring表示と属性値Copyの基準も変わる。"""
    copied: list[MayaScalarValueTransfer] = []

    def capture_copy(
        _clipboard: MayaScalarValueClipboard, transfer: MayaScalarValueTransfer
    ) -> None:
        """OS clipboardを変更せず、コピーされる搬送値を記録する。"""
        copied.append(transfer)

    monkeypatch.setattr(MayaScalarValueClipboard, "write", capture_copy)
    assert editor.controller.representative_node_name == "|channelStringA"
    cmds.select("channelStringA", "channelStringB", replace=True)
    _events()
    assert editor.controller.node_names == (
        "|channelStringA",
        "|channelStringB",
    )
    assert editor.controller.representative_node_name == "|channelStringB"
    assert editor.header_label.text() == "channelStringB"
    row = _row(editor, "caption")
    assert isinstance(row.editor, StringLineEdit)
    assert row.editor.text() == "後続"
    assert row.row.target_names == (
        "|channelStringB",
        "|channelStringA",
    )
    assert (
        editor.controller.copy_selected_values((("caption", "string"),)) == 1
    )
    transfer = copied[0]
    assert transfer.nodes[0].values[0].value == "後続"


def test_string_field_opens_attribute_context_menu(
    editor: ChannelBoxWidget,
) -> None:
    """文字列欄の右クリックは属性操作を開き、値を書き込まない。"""
    row = _row(editor, "caption")
    assert isinstance(row.editor, StringLineEdit)
    position = row.editor.rect().center()
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        row.editor.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(row.editor, event)
    _events()
    assert row.context_menu.isVisible()
    assert cmds.getAttr("channelStringA.caption") == "先頭"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    row.context_menu.close()


def test_string_copy_paste_and_filter_follow_existing_rules(
    editor: ChannelBoxWidget,
) -> None:
    """単一string値を別pathと全選択ノードへ複写し、Undoする。"""
    editor.table_view.select_keys((("caption", "string"),))
    assert (
        editor.controller.copy_selected_values((("caption", "string"),)) == 1
    )
    editor.table_view.select_keys((("alternate", "string"),))
    cmds.flushUndo()
    assert editor.controller.paste_copied_values_to_selected(
        (("alternate", "string"),)
    )
    assert cmds.getAttr("channelStringA.alternate") == "先頭"
    assert cmds.getAttr("channelStringB.alternate") == "先頭"
    cmds.undo()
    assert cmds.getAttr("channelStringA.alternate") == "左"
    assert cmds.getAttr("channelStringB.alternate") == "右"

    editor.controller.set_attribute_filter("hidden")
    _events()
    assert "caption" not in {
        item.row.attribute.path for item in editor.row_widgets
    }
    editor.controller.set_attribute_filter("all")
    _events()
    assert isinstance(_row(editor, "caption").editor, StringLineEdit)


def test_copy_all_includes_visible_and_hidden_string_values(
    editor: ChannelBoxWidget,
) -> None:
    """全属性Copyは表示フィルターに依存せずstring実値も保持する。"""
    cmds.addAttr("channelStringA", longName="hiddenCaption", dataType="string")
    cmds.setAttr("channelStringA.hiddenCaption", "非表示", type="string")
    editor.refresh()
    assert editor.controller.copy_all_values() >= 3
    transfer = MayaScalarValueClipboard().read()
    copied = {item.path: item for item in transfer.nodes[0].values}
    assert copied["caption"].kind == "string"
    assert copied["caption"].value == "先頭"
    assert copied["hiddenCaption"].value == "非表示"


def test_same_representative_text_aligns_mixed_followers(
    editor: ChannelBoxWidget,
) -> None:
    """代表と同じ文字列の明示入力でも混在した後続ノードを揃える。"""
    row = _row(editor, "caption")
    assert isinstance(row.editor, StringLineEdit)
    row.editor.setText("先頭")
    row.editor.textEdited.emit("先頭")
    row.editor.returnPressed.emit()
    assert cmds.getAttr("channelStringB.caption") == "先頭"


def test_string_edit_follows_external_values_without_recommitting_draft(
    editor: ChannelBoxWidget,
) -> None:
    """後続・代表の値変更で未確定入力を破棄し、状態通知だけでは保つ。"""
    row = _row(editor, "caption")
    assert isinstance(row.editor, StringLineEdit)
    row.editor.setText("入力中")
    row.editor.textEdited.emit("入力中")
    cmds.setAttr("channelStringB.caption", lock=True)
    _events()
    assert row.editor.text() == "入力中"
    cmds.setAttr("channelStringB.caption", lock=False)
    _events()
    assert row.editor.text() == "入力中"

    cmds.setAttr("channelStringB.caption", "外部値", type="string")
    _events()
    assert row.editor.text() == "先頭"
    assert not row.editor.hasConflict()
    row.editor.editingFinished.emit()
    assert cmds.getAttr("channelStringB.caption") == "外部値"

    row.editor.setText("もう一度入力中")
    row.editor.textEdited.emit("もう一度入力中")
    cmds.setAttr("channelStringA.caption", "代表の外部値", type="string")
    _events()
    assert row.editor.text() == "代表の外部値"
    row.editor.editingFinished.emit()
    assert cmds.getAttr("channelStringA.caption") == "代表の外部値"
    assert cmds.getAttr("channelStringB.caption") == "外部値"


def test_string_state_mode_changes_display_and_lock(
    editor: ChannelBoxWidget,
) -> None:
    """string行の表示状態とlockも既存の状態モードで編集する。"""
    editor.controller.set_mode("states")
    _events()
    keys = (("caption", "string"),)
    assert editor.controller.set_selected_display(keys, "hidden")
    _events()
    for node in ("channelStringA", "channelStringB"):
        assert not cmds.getAttr(node + ".caption", channelBox=True)
    assert editor.controller.set_selected_display(keys, "keyable")
    for node in ("channelStringA", "channelStringB"):
        assert cmds.getAttr(node + ".caption", keyable=True)
    assert editor.controller.set_selected_locked(keys, True)
    for node in ("channelStringA", "channelStringB"):
        assert cmds.getAttr(node + ".caption", lock=True)
    cmds.undo()
    assert all(
        not cmds.getAttr(node + ".caption", lock=True)
        for node in ("channelStringA", "channelStringB")
    )


def test_joint_other_type_uses_normal_hidden_filter(
    qt_application: qt.QApplication,
) -> None:
    """既存jointのotherTypeも特例なしで通常のstring行として扱う。"""
    assert qt_application is not None
    _new_scene()
    joint = cmds.createNode("joint")
    cmds.select(joint)
    cmds.flushUndo()
    widget = ChannelBoxWidget()
    widget.show()
    try:
        _events()
        assert "otherType" not in {
            item.row.attribute.path for item in widget.row_widgets
        }
        widget.controller.set_attribute_filter("hidden")
        _events()
        assert isinstance(_row(widget, "otherType").editor, StringLineEdit)
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
        assert not cmds.getAttr(joint + ".otherType", keyable=True)
        assert not cmds.getAttr(joint + ".otherType", channelBox=True)
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        _events()
        _new_scene()
