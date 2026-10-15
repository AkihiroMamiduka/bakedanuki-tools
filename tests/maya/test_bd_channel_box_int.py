# coding: utf-8
"""bdChannelBoxの整数行、選択入力、Copy／Pasteと状態編集を確認する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaIntPlugsBinding
from bd_util.ui import IntSpinBox, qt
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


def _events() -> None:
    """Maya通知とQtの遅延破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _row(widget: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """正式名で整数の入力行を取得する。"""
    row = next(
        row for row in widget.row_widgets if row.row.attribute.name == name
    )
    assert isinstance(row, AttributeRowWidget)
    return row


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """二ノードへ同じ整数属性と型固有の範囲を設定する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    set_attr = cast(Callable[[str, int], None], cmds.setAttr)
    for node, byte, short, long in (
        ("intA", 255, 5, 2147483647),
        ("intB", 4, 6, 4),
    ):
        cmds.createNode("transform", name=node)
        cmds.addAttr(
            node, longName="byteValue", attributeType="byte", keyable=True
        )
        cmds.addAttr(
            node,
            longName="shortValue",
            attributeType="short",
            minValue=-20,
            maxValue=20,
            keyable=True,
        )
        cmds.addAttr(
            node, longName="longValue", attributeType="long", keyable=True
        )
        for path, value in (
            ("byteValue", byte),
            ("shortValue", short),
            ("longValue", long),
        ):
            set_attr(node + "." + path, value)
    cmds.select("intB", "intA", replace=True)
    widget = ChannelBoxWidget()
    widget.resize(380, 650)
    widget.show()
    _events()
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def test_integer_rows_edit_align_and_respect_limits(
    editor: ChannelBoxWidget,
) -> None:
    """byte・short・longの整数欄と複数ノード入力を確認する。"""
    byte_row = _row(editor, "byteValue")
    short_row = _row(editor, "shortValue")
    long_row = _row(editor, "longValue")
    assert all(
        isinstance(row.editor, IntSpinBox)
        and isinstance(row.row.binding, MayaIntPlugsBinding)
        for row in (byte_row, short_row, long_row)
    )
    byte_spin = cast(IntSpinBox, byte_row.editor)
    short_spin = cast(IntSpinBox, short_row.editor)
    long_spin = cast(IntSpinBox, long_row.editor)
    assert (byte_spin.minimum(), byte_spin.maximum(), byte_spin.value()) == (
        0,
        255,
        255,
    )
    assert (
        short_spin.minimum(),
        short_spin.maximum(),
        short_spin.value(),
    ) == (-20, 20, 5)
    assert long_spin.value() == 2147483647
    assert byte_row.row.binding.is_mixed

    byte_spin.setValue(200)
    assert [
        cmds.getAttr(node + ".byteValue") for node in ("intA", "intB")
    ] == [200, 200]
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".byteValue") for node in ("intA", "intB")
    ] == [255, 4]

    key = (byte_row.row.attribute.path, byte_row.row.attribute.kind)
    short_key = (short_row.row.attribute.path, short_row.row.attribute.kind)
    editor.table_view.select_keys((key, short_key))
    selected_byte_spin = _row(editor, "byteValue").editor
    assert isinstance(selected_byte_spin, IntSpinBox)
    selected_byte_spin.setValue(10)
    assert [
        cmds.getAttr(node + "." + path)
        for path in ("byteValue", "shortValue")
        for node in ("intA", "intB")
    ] == [10, 10, 10, 10]
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]

    assert editor.controller.align_selected_values((key,))
    assert cmds.getAttr("intB.byteValue") == 255
    cmds.undo()
    _events()
    assert cmds.getAttr("intB.byteValue") == 4

    with pytest.raises(ValueError):
        editor.controller.apply_numeric_values((short_key,), 21.0)
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]
    assert editor.controller.offset_numeric_values((short_key,), 1)
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [6, 7]
    cmds.undo()
    _events()
    assert [
        cmds.getAttr(node + ".shortValue") for node in ("intA", "intB")
    ] == [5, 6]


def test_integer_copy_paste_and_state_mode(editor: ChannelBoxWidget) -> None:
    """整数値の同path貼付けと表示／ロック行の生成を確認する。"""
    clipboard = qt.QApplication.clipboard()
    previous = cast(qt.QtCore.QMimeData | None, clipboard.mimeData())
    saved = qt.QtCore.QMimeData()
    if previous is not None:
        for mime_type in previous.formats():
            saved.setData(mime_type, previous.data(mime_type))
    try:
        long_row = _row(editor, "longValue")
        key = (long_row.row.attribute.path, long_row.row.attribute.kind)
        assert editor.controller.copy_selected_values((key,)) == 1
        set_attr = cast(Callable[[str, int], None], cmds.setAttr)
        set_attr("intA.longValue", 1)
        set_attr("intB.longValue", 2)
        cmds.flushUndo()
        assert editor.controller.paste_copied_values()
        assert [
            cmds.getAttr(node + ".longValue") for node in ("intA", "intB")
        ] == [2147483647] * 2
        cmds.undo()
        _events()
        assert [
            cmds.getAttr(node + ".longValue") for node in ("intA", "intB")
        ] == [1, 2]

        editor.controller.set_mode("states")
        _events()
        assert any(
            row.attribute.name == "byteValue" for row in editor.controller.rows
        )
        editor.controller.set_selected_locked((("byteValue", "byte"),), True)
        assert cmds.getAttr("intA.byteValue", lock=True)
    finally:
        clipboard.setMimeData(saved)


def test_compound_child_and_connected_integer(
    editor: ChannelBoxWidget,
) -> None:
    """compound子を表示し、接続中の整数を読取り専用にする。"""
    for node in ("intA", "intB"):
        cmds.addAttr(
            node,
            longName="integerGroup",
            attributeType="compound",
            numberOfChildren=1,
        )
        cmds.addAttr(
            node,
            longName="childCount",
            attributeType="short",
            parent="integerGroup",
            keyable=True,
        )
    editor.refresh()
    _events()
    child = _row(editor, "childCount")
    assert child.row.attribute.path == "integerGroup.childCount"
    assert isinstance(child.editor, IntSpinBox)
    driver = cmds.createNode("transform")
    cmds.addAttr(
        driver, longName="driverCount", attributeType="short", keyable=True
    )
    for node in ("intA", "intB"):
        cmds.connectAttr(driver + ".driverCount", node + ".shortValue")
    cmds.select("intB", "intA", replace=True)
    editor.refresh()
    _events()
    short_row = _row(editor, "shortValue")
    assert isinstance(short_row.row.binding, MayaIntPlugsBinding)
    assert short_row.row.binding.writable_count == 0
    assert isinstance(short_row.editor, IntSpinBox)
    assert not short_row.editor.isEnabled()
