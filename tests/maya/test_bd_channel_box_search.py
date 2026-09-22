# coding: utf-8
"""bdChannelBoxの属性検索と検索欄の表示方針を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt

from bd_tools.bd_channel_box.widget import ChannelBoxWidget


def _new_scene() -> None:
    """一時sceneを初期化し、前のテストの選択とUndoを破棄する。"""
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)


def _events() -> None:
    """検索タイマーとMayaの遅延同期を最新状態へ進める。"""
    for _ in range(4):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set_filter(editor: ChannelBoxWidget, value: str) -> None:
    """上部ComboBoxから指定したAttribute Filterを選択する。"""
    index = editor.filter_combo.findData(value)
    assert index >= 0
    editor.filter_combo.setCurrentIndex(index)
    _events()


def _visible_paths(editor: ChannelBoxWidget) -> tuple[str, ...]:
    """検索後も画面に表示されている正式属性pathを返す。"""
    return tuple(
        row.key[0]
        for index, row in enumerate(editor.table_view.rows)
        if not editor.table_view.isRowHidden(index)
    )


def _key(editor: ChannelBoxWidget, path: str) -> tuple[str, str]:
    """正式pathに対応するTable行の識別子を返す。"""
    return next(
        row.key for row in editor.table_view.rows if row.key[0] == path
    )


def _click(
    widget: qt.QWidget,
    modifiers: qt.Qt.KeyboardModifier = qt.Qt.KeyboardModifier.NoModifier,
) -> None:
    """修飾キー付きのクリックを既存の属性名欄へ送る。"""
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
            modifiers,
        )
        qt.QApplication.sendEvent(widget, event)


@pytest.fixture
def search_editor(
    qt_application: qt.QApplication,
) -> Iterator[ChannelBoxWidget]:
    """Nice Nameと表示状態が異なる検索用属性を持つノードを表示する。"""
    assert qt_application is not None
    _new_scene()
    node = cmds.createNode("transform", name="searchNode")
    cmds.addAttr(
        node,
        longName="heroWeight",
        niceName="Hero Weight",
        attributeType="double",
        keyable=True,
    )
    cmds.addAttr(
        node,
        longName="secretWeight",
        niceName="Secret Weight",
        attributeType="double",
    )
    cmds.select(node, replace=True)
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


def test_search_visibility_has_three_exclusive_modes(
    search_editor: ChannelBoxWidget,
) -> None:
    """初期値・全て連動・常時表示・非表示を排他的に切り替える。"""
    editor = search_editor
    actions = editor.search_visibility_actions
    assert tuple(actions) == ("never", "all_only", "always")
    assert tuple(action.text() for action in actions.values()) == (
        "非表示",
        "「全て」の場合のみ表示",
        "常に表示",
    )
    assert editor.search_visibility_menu.menuAction() in (
        editor.settings_menu.actions()
    )
    assert editor.search_visibility == "all_only"
    assert sum(action.isChecked() for action in actions.values()) == 1
    assert not editor.search_edit.isVisible()

    _set_filter(editor, "all")
    assert editor.search_edit.isVisible()
    assert editor.search_label.isVisible()

    _set_filter(editor, "keyable")
    assert not editor.search_edit.isVisible()
    actions["always"].setChecked(True)
    _events()
    assert editor.search_visibility == "always"
    assert editor.search_edit.isVisible()
    assert sum(action.isChecked() for action in actions.values()) == 1

    actions["never"].setChecked(True)
    _events()
    assert editor.search_visibility == "never"
    assert not editor.search_edit.isVisible()
    assert not editor.search_label.isVisible()
    assert sum(action.isChecked() for action in actions.values()) == 1


@pytest.mark.parametrize(
    ("query", "expected"),
    (
        ("HERO wei", ("heroWeight",)),
        ("TRANSLATE.TRANSLATEX", ("translate.translateX",)),
        ("secretweight", ("secretWeight",)),
        ("hero missing", ()),
    ),
)
def test_search_matches_nice_name_attribute_and_path_without_rebuild(
    search_editor: ChannelBoxWidget,
    query: str,
    expected: tuple[str, ...],
) -> None:
    """大小文字を無視したAND検索を既存行へ適用し、Bindingを再生成しない。"""
    editor = search_editor
    _set_filter(editor, "all")
    before = editor.row_widgets
    cmds.flushUndo()

    editor.search_edit.setText(query)
    _events()

    assert _visible_paths(editor) == expected
    assert editor.row_widgets == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert editor.empty_label.isVisible() == (not expected)
    if not expected:
        assert (
            editor.empty_label.text() == "検索条件に一致する属性がありません。"
        )


def test_hidden_search_is_inactive_and_keeps_window_text(
    search_editor: ChannelBoxWidget,
) -> None:
    """検索欄を隠した間は絞り込まず、Window内の文字列だけを保持する。"""
    editor = search_editor
    _set_filter(editor, "all")
    editor.search_edit.setText("heroWeight")
    _events()
    assert _visible_paths(editor) == ("heroWeight",)

    editor.search_visibility_actions["never"].setChecked(True)
    _events()
    assert editor.search_edit.text() == "heroWeight"
    assert not editor.search_edit.isVisible()
    assert len(_visible_paths(editor)) == len(editor.table_view.rows)
    assert not editor.empty_label.isVisible()

    editor.search_visibility_actions["always"].setChecked(True)
    _events()
    assert editor.search_edit.isVisible()
    assert _visible_paths(editor) == ("heroWeight",)


def test_all_only_search_is_suspended_for_other_attribute_filters(
    search_editor: ChannelBoxWidget,
) -> None:
    """全て以外では検索を停止し、常時表示へ切り替えた場合だけAND適用する。"""
    editor = search_editor
    _set_filter(editor, "all")
    editor.search_edit.setText("secretWeight")
    _events()
    assert _visible_paths(editor) == ("secretWeight",)

    _set_filter(editor, "keyable")
    assert not editor.search_edit.isVisible()
    assert len(_visible_paths(editor)) == len(editor.table_view.rows)
    assert "heroWeight" in _visible_paths(editor)

    editor.search_visibility_actions["always"].setChecked(True)
    _events()
    assert editor.search_edit.isVisible()
    assert not _visible_paths(editor)
    assert editor.empty_label.text() == "検索条件に一致する属性がありません。"


def test_search_removes_hidden_selection_without_restoring_it(
    search_editor: ChannelBoxWidget,
) -> None:
    """検索で見えなくなった属性を選択から外し、解除後も復元しない。"""
    editor = search_editor
    _set_filter(editor, "all")
    translate_x = _key(editor, "translate.translateX")
    translate_y = _key(editor, "translate.translateY")
    editor.table_view.select_keys((translate_x, translate_y))

    editor.search_edit.setText("translate.translateX")
    _events()
    assert editor.table_view.selected_keys() == (translate_x,)

    editor.search_edit.clear()
    _events()
    assert translate_x in editor.table_view.selected_keys()
    assert translate_y not in editor.table_view.selected_keys()


def test_search_moves_hidden_selection_anchor_to_a_visible_row(
    search_editor: ChannelBoxWidget,
) -> None:
    """検索で隠れたShift選択の起点を、最初の表示行へ移す。"""
    editor = search_editor
    _set_filter(editor, "all")
    hero_weight = _key(editor, "heroWeight")
    translate_x = _key(editor, "translate.translateX")
    translate_y = _key(editor, "translate.translateY")
    editor.table_view.select_keys((hero_weight,))
    editor.table_view.selectionModel().clearSelection()

    editor.search_edit.setText("translate")
    _events()

    translate_y_label = next(
        row.name_label
        for row in editor.row_widgets
        if row.row.attribute.path == "translate.translateY"
    )
    _click(translate_y_label, qt.Qt.KeyboardModifier.ShiftModifier)
    assert editor.table_view.selected_keys() == (translate_x, translate_y)


def test_search_text_survives_mode_and_node_refresh(
    search_editor: ChannelBoxWidget,
) -> None:
    """検索文字列をモードとノードの変更後も再構築された行へ適用する。"""
    editor = search_editor
    editor.search_visibility_actions["always"].setChecked(True)
    editor.search_edit.setText("heroWeight")
    _events()
    assert _visible_paths(editor) == ("heroWeight",)

    editor.mode_combo.setCurrentIndex(1)
    _events()
    assert editor.search_edit.text() == "heroWeight"
    assert _visible_paths(editor) == ("heroWeight",)

    other = cmds.createNode("transform", name="otherSearchNode")
    cmds.select(other, replace=True)
    _events()
    assert editor.search_edit.text() == "heroWeight"
    assert not _visible_paths(editor)
    assert editor.empty_label.text() == "検索条件に一致する属性がありません。"
