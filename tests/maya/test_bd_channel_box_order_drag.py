# coding: utf-8
"""手動登録順の中ドラッグと伸縮ボタンをMayaの設定画面で検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt

from bd_tools.bd_channel_box.custom_filter_setup import CustomFilterSetupPanel
from bd_tools.bd_channel_box.custom_filters import load_custom_filter
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


def _events() -> None:
    """設定画面の更新と破棄待ちのQtイベントを処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _new_scene() -> None:
    """検証専用の空シーンを作り、他テストの選択を残さない。"""
    cast(Callable[..., str], cmds.file)(new=True, force=True)


@pytest.fixture
def order_editor(
    qt_application: qt.QApplication, tmp_path: Path
) -> Iterator[tuple[ChannelBoxWidget, Path]]:
    """欠落候補と別型を含む保存済みフィルターを持つ設定画面を作る。"""
    assert qt_application is not None
    _new_scene()
    node = cmds.createNode("transform", name="middleOrderBase")
    for name in ("orderA", "orderB", "orderD", "orderE"):
        cmds.addAttr(node, longName=name, attributeType="double")
    cmds.select(node, replace=True)
    source = tmp_path / "order.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Middle Order",
                "node_types": {
                    "transform": [
                        "orderA",
                        "orderB",
                        "orderC",
                        "orderD",
                        "orderE",
                    ],
                    "joint": ["visibility"],
                },
            }
        ),
        encoding="utf-8",
    )
    editor = ChannelBoxWidget()
    registry = editor.custom_filter_registry
    registry.create_group(tmp_path / "group.json")
    registry.create_preset(tmp_path / "preset.json")
    registry.add_paths((source,))
    registry.save()
    editor.controller.set_mode("custom_filter_setup")
    editor.setup_panel.set_target(str(source))
    editor.setup_panel.tool_box.setCurrentWidget(editor.setup_panel.order_page)
    editor.resize(640, 720)
    editor.show()
    _events()
    cmds.flushUndo()
    try:
        yield editor, source
    finally:
        editor.dispose()
        editor.close()
        editor.deleteLater()
        _events()
        _new_scene()


def _selected_paths(panel: CustomFilterSetupPanel) -> tuple[str, ...]:
    """正式pathを使い、表示順で選択中の属性を取得する。"""
    order = panel.order_list
    return tuple(
        path
        for row in range(order.count())
        if order.item(row).isSelected()
        if isinstance(
            path := order.item(row).data(qt.Qt.ItemDataRole.UserRole), str
        )
    )


def _select_rows(panel: CustomFilterSetupPanel, rows: tuple[int, ...]) -> None:
    """次の中ドラッグを開始する複数行を明示的に選択する。"""
    order = panel.order_list
    order.clearSelection()
    order.setCurrentRow(rows[0])
    for row in rows:
        order.item(row).setSelected(True)
    _events()


def _send_mouse(
    order: qt.QListWidget,
    kind: qt.QEvent.Type,
    position: qt.QPoint,
    button: qt.Qt.MouseButton,
) -> None:
    """一覧のviewportへ押下・移動・解放の実Qtマウスイベントを送る。"""
    viewport = order.viewport()
    event = qt.QtGui.QMouseEvent(
        kind,
        qt.QPointF(position),
        qt.QPointF(viewport.mapToGlobal(position)),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseMove
            else button
        ),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseButtonRelease
            else button
        ),
        qt.Qt.KeyboardModifier.NoModifier,
    )
    qt.QApplication.sendEvent(viewport, event)


def _drag_to_boundary(
    panel: CustomFilterSetupPanel, pressed_row: int, before_row: int
) -> None:
    """指定行から、並べ替え前の一覧にある指定行間へ中ドラッグする。"""
    order = panel.order_list
    start = order.visualItemRect(order.item(pressed_row)).center()
    last_rect = order.visualItemRect(order.item(order.count() - 1))
    end = qt.QPoint(
        start.x(),
        (
            last_rect.bottom() + 3
            if before_row == order.count()
            else order.visualItemRect(order.item(before_row)).top()
        ),
    )
    _send_mouse(
        order,
        qt.QEvent.Type.MouseButtonPress,
        start,
        qt.Qt.MouseButton.MiddleButton,
    )
    _send_mouse(
        order, qt.QEvent.Type.MouseMove, end, qt.Qt.MouseButton.MiddleButton
    )
    _send_mouse(
        order,
        qt.QEvent.Type.MouseButtonRelease,
        end,
        qt.Qt.MouseButton.MiddleButton,
    )
    _events()


@pytest.mark.parametrize(
    ("selected", "pressed", "expected", "expected_selection"),
    (
        ((1,), 1, ("A", "C", "D", "E", "B"), ("B",)),
        ((1, 2), 1, ("A", "D", "E", "B", "C"), ("B", "C")),
        ((1, 3), 3, ("A", "C", "E", "B", "D"), ("B", "D")),
        ((1, 3), 0, ("B", "C", "D", "E", "A"), ("A",)),
    ),
)
def test_middle_drag_updates_draft_and_keeps_selected_paths(
    order_editor: tuple[ChannelBoxWidget, Path],
    selected: tuple[int, ...],
    pressed: int,
    expected: tuple[str, ...],
    expected_selection: tuple[str, ...],
) -> None:
    """単行・連続・非連続・選択外からの移動を下書きへ一括反映する。"""
    editor, source = order_editor
    panel = editor.setup_panel
    before = source.read_bytes()
    _select_rows(panel, selected)
    _drag_to_boundary(panel, pressed, panel.order_list.count())
    assert panel.draft is not None
    expected_paths = tuple(f"order{name}" for name in expected)
    assert panel.draft.paths("transform") == expected_paths
    assert _selected_paths(panel) == tuple(
        f"order{name}" for name in expected_selection
    )
    assert panel.draft.paths("joint") == ("visibility",)
    assert panel.draft.is_dirty
    assert source.read_bytes() == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 保存と破棄の対象も新しい表示順に一致させる
    assert panel.save()
    assert load_custom_filter(source).node_types["transform"] == expected_paths
    saved = source.read_bytes()
    _select_rows(panel, (0,))
    _drag_to_boundary(panel, 0, panel.order_list.count())
    assert panel.draft.is_dirty
    panel.discard()
    _events()
    assert panel.draft is not None
    assert panel.draft.paths("transform") == expected_paths
    assert not panel.draft.is_dirty
    assert source.read_bytes() == saved
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_left_drag_selects_without_changing_draft_order(
    order_editor: tuple[ChannelBoxWidget, Path],
) -> None:
    """中ドラッグを追加しても、左ドラッグは候補外の属性を含む選択に使う。"""
    editor, source = order_editor
    panel = editor.setup_panel
    order = panel.order_list
    before = source.read_bytes()
    start = order.visualItemRect(order.item(0)).center()
    end = order.visualItemRect(order.item(3)).center()
    _send_mouse(
        order,
        qt.QEvent.Type.MouseButtonPress,
        start,
        qt.Qt.MouseButton.LeftButton,
    )
    _send_mouse(
        order, qt.QEvent.Type.MouseMove, end, qt.Qt.MouseButton.LeftButton
    )
    _send_mouse(
        order,
        qt.QEvent.Type.MouseButtonRelease,
        end,
        qt.Qt.MouseButton.LeftButton,
    )
    _events()
    assert _selected_paths(panel) == (
        "orderA",
        "orderB",
        "orderC",
        "orderD",
    )
    assert panel.draft is not None and not panel.draft.is_dirty
    assert source.read_bytes() == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_order_buttons_share_remaining_height_after_fixed_remove(
    order_editor: tuple[ChannelBoxWidget, Path],
) -> None:
    """除外・上・下の順で配置し、上下だけが一覧の高さへ均等に追従する。"""
    editor, _source = order_editor
    panel = editor.setup_panel
    previous_up_height = 0
    for height in (640, 820):
        editor.resize(640, height)
        _events()
        remove = panel.remove_button
        up = panel.up_button
        down = panel.down_button
        remove_position = remove.mapTo(panel.order_page, qt.QPoint())
        up_position = up.mapTo(panel.order_page, qt.QPoint())
        down_position = down.mapTo(panel.order_page, qt.QPoint())
        assert remove.size() == qt.QSize(20, 20)
        assert up.width() == down.width() == 20
        assert up.height() >= 20 and down.height() >= 20
        assert abs(up.height() - down.height()) <= 1
        assert up.height() > previous_up_height
        previous_up_height = up.height()
        assert remove_position.y() < up_position.y() < down_position.y()
        order_bottom = panel.order_list.mapTo(
            panel.order_page, panel.order_list.rect().bottomLeft()
        ).y()
        assert abs(down_position.y() + down.height() - 1 - order_bottom) <= 1
        assert all(
            button.iconSize() == qt.QSize(16, 16)
            for button in (remove, up, down)
        )
