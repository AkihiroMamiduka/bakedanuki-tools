# coding: utf-8
"""カスタムフィルター設定の右クリック対象と、下書きの除外を検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt

from bd_tools.bd_channel_box.controller import ChannelBoxMode
from bd_tools.bd_channel_box.custom_filter_setup import CustomFilterSetupPanel
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


def _events() -> None:
    """メニューと検索の遅延通知を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _new_scene() -> None:
    """各テスト専用のsceneを作り、選択とUndo履歴を分離する。"""
    cast(Callable[..., str], cmds.file)(new=True, force=True)


@pytest.fixture
def context_editor(
    qt_application: qt.QApplication, tmp_path: Path
) -> Iterator[tuple[ChannelBoxWidget, Path, str]]:
    """既存・欠落pathと別型の定義を持つ設定画面を作り、確実に破棄する。"""
    assert qt_application is not None
    _new_scene()
    node = cmds.createNode("transform", name="contextFilterBase")
    for path in ("rigA", "rigB", "rigC"):
        cmds.addAttr(node, longName=path, attributeType="double")
    cmds.select(node, replace=True)
    source = tmp_path / "context-rig.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Context Rig",
                "node_types": {
                    "transform": ["rigA", "legacyMissing", "rigB", "rigC"],
                    "joint": ["visibility"],
                    "network": [],
                },
            }
        ),
        encoding="utf-8",
    )
    editor = ChannelBoxWidget()
    editor.custom_filter_registry.add_paths((source,))
    editor.controller.set_mode("custom_filter_setup")
    editor.setup_panel.set_target(str(source))
    editor.setup_panel.tool_box.setCurrentWidget(editor.setup_panel.order_page)
    editor.resize(640, 720)
    editor.show()
    _events()
    cmds.flushUndo()
    try:
        yield editor, source, node
    finally:
        editor.dispose()
        editor.close()
        editor.deleteLater()
        _events()
        _new_scene()


def _right_click(
    target: qt.QWidget, position: qt.QPoint | None = None
) -> None:
    """右ボタンの押下・解放・メニュー通知を通常のQt入力経路へ送る。"""
    if position is None:
        position = target.rect().center()
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(position),
            qt.QPointF(target.mapToGlobal(position)),
            qt.Qt.MouseButton.RightButton,
            (
                qt.Qt.MouseButton.RightButton
                if kind == qt.QEvent.Type.MouseButtonPress
                else qt.Qt.MouseButton.NoButton
            ),
            qt.Qt.KeyboardModifier.NoModifier,
        )
        qt.QApplication.sendEvent(target, event)
    context = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        target.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(target, context)
    assert context.isAccepted()
    _events()


def _selected_paths(panel: CustomFilterSetupPanel) -> tuple[str, ...]:
    """一覧で選択中の正式pathを表示順に返す。"""
    return tuple(
        path
        for index in range(panel.order_list.count())
        if panel.order_list.item(index).isSelected()
        if isinstance(
            path := panel.order_list.item(index).data(
                qt.Qt.ItemDataRole.UserRole
            ),
            str,
        )
    )


def _active_popup() -> qt.QWidget | None:
    """標準メニューを含む現在のQt popupを取得する。"""
    return cast(
        Callable[[], qt.QWidget | None],
        getattr(qt.QApplication, "activePopupWidget"),
    )()


def _key(target: qt.QWidget, key: int) -> None:
    """Ctrl付きの標準編集ショートカットを入力欄へ送る。"""
    target.setFocus()
    for kind in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
        qt.QApplication.sendEvent(
            target,
            qt.QtGui.QKeyEvent(
                kind, key, qt.Qt.KeyboardModifier.ControlModifier
            ),
        )
    _events()


@pytest.mark.parametrize("clicked", (0, 2))
def test_order_context_removes_selected_paths_and_uses_draft_save_discard(
    context_editor: tuple[ChannelBoxWidget, Path, str], clicked: int
) -> None:
    """選択内の右クリックで集合を保持し、除外・破棄・保存を既存操作へつなぐ。"""
    editor, source, node = context_editor
    panel = editor.setup_panel
    order = panel.order_list
    before = source.read_bytes()
    node_names = cmds.ls(long=True)
    order.setCurrentRow(0)
    order.item(2).setSelected(True)
    _right_click(
        order.viewport(), order.visualItemRect(order.item(clicked)).center()
    )
    assert _selected_paths(panel) == ("rigA", "rigB")
    assert panel.order_context_menu.isVisible()
    assert [
        action.text() for action in panel.order_context_menu.actions()
    ] == ["除外する"]
    assert panel.remove_order_action.isEnabled()
    assert not editor.context_menu.isVisible()
    panel.remove_order_action.trigger()
    _events()
    assert panel.draft is not None
    assert panel.draft.paths("transform") == ("legacyMissing", "rigC")
    assert panel.draft.paths("joint") == ("visibility",)
    assert panel.draft.paths("network") == ()
    assert not panel.order_context_menu.isVisible()
    assert panel.target_combo.currentText() == "Context Rig *"
    assert source.read_bytes() == before
    assert cmds.getAttr(f"{node}.rigA") == 0.0
    assert cmds.ls(long=True) == node_names
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 破棄後に同じ経路で除外し直し、保存後だけ共有JSONを更新する
    panel.discard_button.click()
    assert panel.target_combo.currentText() == "Context Rig"
    order.setCurrentRow(0)
    order.item(2).setSelected(True)
    _right_click(
        order.viewport(), order.visualItemRect(order.item(clicked)).center()
    )
    panel.remove_order_action.trigger()
    panel.save_button.click()
    saved = json.loads(source.read_text(encoding="utf-8"))["node_types"]
    assert saved == {
        "transform": ["legacyMissing", "rigC"],
        "joint": ["visibility"],
        "network": [],
    }
    assert not panel.save_button.isEnabled()
    assert panel.target_combo.currentText() == "Context Rig"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_order_context_on_unselected_missing_path_targets_only_that_row(
    context_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """選択外の欠落pathを右クリックすると、その一行だけを除外できる。"""
    editor, source, _node = context_editor
    panel = editor.setup_panel
    order = panel.order_list
    before = source.read_bytes()
    order.setCurrentRow(0)
    order.item(2).setSelected(True)
    _right_click(
        order.viewport(), order.visualItemRect(order.item(1)).center()
    )
    assert _selected_paths(panel) == ("legacyMissing",)
    panel.remove_order_action.trigger()
    assert panel.draft is not None
    assert panel.draft.paths("transform") == ("rigA", "rigB", "rigC")
    assert source.read_bytes() == before


@pytest.mark.parametrize("empty", (False, True))
def test_order_context_on_blank_keeps_selection_and_does_not_open_menu(
    context_editor: tuple[ChannelBoxWidget, Path, str], empty: bool
) -> None:
    """余白と空一覧ではメニューを開かず、既存の選択・空配列を保持する。"""
    editor, _source, _node = context_editor
    panel = editor.setup_panel
    order = panel.order_list
    order.setCurrentRow(0)
    if empty:
        for index in range(order.count()):
            order.item(index).setSelected(True)
        panel.remove_button.click()
    else:
        order.item(2).setSelected(True)
    before = _selected_paths(panel)
    position = order.viewport().rect().bottomRight() - qt.QPoint(3, 3)
    assert order.itemAt(position) is None
    _right_click(order.viewport(), position)
    assert _selected_paths(panel) == before
    assert _active_popup() is None
    assert not editor.context_menu.isVisible()
    if empty:
        assert panel.draft is not None and panel.draft.has_node_type(
            "transform"
        )
        assert panel.draft.paths("transform") == ()


@pytest.mark.parametrize("surface", ("widget", "label", "candidates"))
def test_setup_surfaces_do_not_open_step_settings(
    context_editor: tuple[ChannelBoxWidget, Path, str], surface: str
) -> None:
    """設定モードでは余白や子Widgetから伝わる右クリックでStepを開かない。"""
    editor, source, _node = context_editor
    before = source.read_bytes()
    editor.setup_panel.tool_box.setCurrentWidget(
        editor.setup_panel.candidate_page
    )
    _events()
    targets = {
        "widget": editor,
        "label": editor.setup_panel.node_label,
        "candidates": editor.setup_panel.candidate_scroll.viewport(),
    }
    _right_click(targets[surface])
    assert _active_popup() is None
    assert not editor.context_menu.isVisible()
    assert source.read_bytes() == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("mode", ("values", "states"))
def test_other_modes_keep_step_menu_and_close_it_on_entering_setup(
    context_editor: tuple[ChannelBoxWidget, Path, str], mode: ChannelBoxMode
) -> None:
    """ほかのモードの余白メニューを維持し、設定へ入ると開いていたStepも閉じる。"""
    editor, _source, _node = context_editor
    editor.controller.set_mode(mode)
    _right_click(editor)
    assert editor.context_menu.isVisible()
    assert [action.text() for action in editor.context_menu.actions()] == [
        "Step設定"
    ]
    editor.controller.set_mode("custom_filter_setup")
    _events()
    assert _active_popup() is None


def test_search_context_is_suppressed_while_copy_cut_paste_undo_still_work(
    context_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """検索の右クリックだけを消費し、標準編集キーと入力内容は維持する。"""
    editor, source, _node = context_editor
    editor.setup_panel.tool_box.setCurrentWidget(
        editor.setup_panel.candidate_page
    )
    _events()
    field = editor.setup_panel.search_edit
    clipboard = qt.QApplication.clipboard()
    assert clipboard is not None
    previous_clipboard = qt.QtCore.QMimeData()
    original_data = cast(qt.QtCore.QMimeData | None, clipboard.mimeData())
    if original_data is not None:
        for name in original_data.formats():
            previous_clipboard.setData(name, original_data.data(name))
    before = source.read_bytes()
    try:
        field.setText("rigA")
        field.selectAll()
        _key(field, qt.Qt.Key.Key_C)
        assert clipboard.text() == "rigA"
        _right_click(field)
        assert _active_popup() is None
        assert field.text() == "rigA"
        field.selectAll()
        _key(field, qt.Qt.Key.Key_X)
        assert field.text() == ""
        _key(field, qt.Qt.Key.Key_V)
        assert field.text() == "rigA"
        _key(field, qt.Qt.Key.Key_Z)
        assert field.text() == ""
        _key(field, qt.Qt.Key.Key_Z)
        assert field.text() == "rigA"
        assert source.read_bytes() == before
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    finally:
        clipboard.setMimeData(previous_clipboard)


@pytest.mark.parametrize("operation", ("refresh", "mode", "dispose", "page"))
def test_open_order_menu_closes_when_the_editing_context_ends(
    context_editor: tuple[ChannelBoxWidget, Path, str], operation: str
) -> None:
    """再構築・モード切替・破棄でメニューを閉じ、旧対象への操作を持ち越さない。"""
    editor, source, _node = context_editor
    panel = editor.setup_panel
    order = panel.order_list
    before = source.read_bytes()
    _right_click(
        order.viewport(), order.visualItemRect(order.item(0)).center()
    )
    assert panel.order_context_menu.isVisible()
    if operation == "refresh":
        editor.controller.refresh()
    elif operation == "mode":
        editor.controller.set_mode("values")
    elif operation == "page":
        panel.tool_box.setCurrentWidget(panel.candidate_page)
    else:
        editor.dispose()
    _events()
    assert not panel.order_context_menu.isVisible()
    assert source.read_bytes() == before


def test_order_keyboard_menu_keeps_the_selected_rows(
    context_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """キーボードからも現在の選択範囲へ同じ除外メニューを開く。"""
    editor, _source, _node = context_editor
    panel = editor.setup_panel
    order = panel.order_list
    order.setCurrentRow(0)
    order.item(2).setSelected(True)
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Keyboard,
        qt.QPoint(-1, -1),
        order.mapToGlobal(qt.QPoint()),
    )
    qt.QApplication.sendEvent(order, event)
    _events()
    assert panel.order_context_menu.isVisible()
    assert _selected_paths(panel) == ("rigA", "rigB")
