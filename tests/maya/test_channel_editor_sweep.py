# coding: utf-8
"""なぞり入力とフィルター、複数ノード、Undo、操作中断を統合検証する。"""

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.channel_editor.widget import (
    AttributeStateRowWidget,
    ChannelEditorWidget,
)


def _events() -> None:
    """遅延再構築とQt破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelEditorWidget]:
    """複数transformのKeyable属性を、上位の行が見える大きさで表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    for name in ("sweepA", "sweepB"):
        cmds.createNode("transform", name=name)
    cmds.select("sweepA", "sweepB", replace=True)
    widget = ChannelEditorWidget()
    widget.resize(380, 460)
    widget.mode_combo.setCurrentIndex(1)
    widget.filter_combo.setCurrentIndex(
        widget.filter_combo.findData("keyable")
    )
    widget.show()
    _events()
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def _button(editor: ChannelEditorWidget, name: str) -> qt.QRadioButton:
    """対象行のHideボタンを取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row.display_buttons["hidden"]


def _mouse(
    origin: qt.QRadioButton, kind: qt.QEvent.Type, target: qt.QRadioButton
) -> None:
    """押下元へ別行のグローバル座標を持つマウスイベントを送る。"""
    position = target.mapToGlobal(qt.QPoint(8, target.height() // 2))
    event = qt.QtGui.QMouseEvent(
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
    qt.QApplication.sendEvent(origin, event)


def _start(
    editor: ChannelEditorWidget,
) -> tuple[qt.QRadioButton, qt.QRadioButton]:
    """Translate XからZまで高速になぞり、Yを含む三行を変更する。"""
    first, last = _button(editor, "translateX"), _button(editor, "translateZ")
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    assert editor.state_sweep.is_active
    return first, last


def _assert_keyable(value: bool) -> None:
    """両選択ノードの三軸が同じ状態で、値とlockを維持するか確認する。"""
    for node in ("sweepA", "sweepB"):
        for attribute in ("translateX", "translateY", "translateZ"):
            path = f"{node}.{attribute}"
            assert bool(cmds.getAttr(path, keyable=True)) is value
            assert not cmds.getAttr(path, channelBox=True)
            assert not cmds.getAttr(path, lock=True)
            assert cmds.getAttr(path) == 0.0


def test_sweep_freezes_filtered_rows_and_groups_undo(
    editor: ChannelEditorWidget,
) -> None:
    """変更は即時に反映し、絞り込みはrelease後、Undoは全行一回にする。"""
    before = editor.row_widgets
    first, last = _start(editor)
    _events()
    _assert_keyable(False)
    assert editor.row_widgets == before
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    assert not editor.state_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    assert not any(
        row.row.attribute.name.startswith("translate")
        for row in editor.row_widgets
    )
    cmds.undo()
    _events()
    _assert_keyable(True)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    _assert_keyable(False)


@pytest.mark.parametrize(
    "action",
    ["escape", "hide", "mode", "filter", "refresh", "selection", "dispose"],
)
def test_interruption_commits_and_closes_undo(
    editor: ChannelEditorWidget, action: str
) -> None:
    """各中断経路で入力を終了し、後続の値変更を同じUndoへ混ぜない。"""
    first, last = _start(editor)
    if action == "escape":
        qt.QApplication.sendEvent(
            first,
            qt.QtGui.QKeyEvent(
                qt.QEvent.Type.KeyPress,
                qt.Qt.Key.Key_Escape,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )
    elif action == "hide":
        editor.hide()
    elif action == "mode":
        editor.controller.set_mode("values")
    elif action == "filter":
        editor.controller.set_attribute_filter("all")
    elif action == "refresh":
        editor.controller.refresh()
    elif action == "selection":
        cmds.select(clear=True)
    else:
        editor.dispose()
    assert not editor.state_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    if qt.isValid(first) and qt.isValid(last):
        _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    _assert_keyable(False)
    cast(Callable[[str, float], None], cmds.setAttr)("sweepA.rotateX", 20.0)
    cmds.undo()
    assert cmds.getAttr("sweepA.rotateX") == 0.0
    _assert_keyable(False)


def test_attribute_removal_interrupts_without_deferring_structure(
    editor: ChannelEditorWidget,
) -> None:
    """属性構成の変更はなぞりを中断し、古いBindingへの入力を止める。"""
    cmds.addAttr("sweepA", longName="temporary", attributeType="double")
    _events()
    _start(editor)
    cmds.deleteAttr("sweepA.temporary")
    assert not editor.state_sweep.is_active
    _events()
    assert not editor.controller.state_edit_session.is_editing
    _assert_keyable(False)
