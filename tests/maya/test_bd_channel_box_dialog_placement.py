# coding: utf-8
"""確認と追加画面で、操作位置と入力方法が引き継がれることを検証する。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest

from bd_util.ui import qt
from bd_util.ui import dialog as ui_dialog
from bd_tools.bd_channel_box import custom_filter_manager as manager_module
from bd_tools.bd_channel_box.custom_filter_dialogs import (
    create_registered_filter,
)
from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """操作位置を共有する画面を作り、入力監視とMaya監視を解除する。"""
    assert qt_application is not None
    widget = ChannelBoxWidget()
    try:
        yield widget
    finally:
        widget.setup_panel.discard()
        widget.dispose()
        widget.close()
        widget.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
def test_addition_keeps_its_origin_after_unsaved_confirmation(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["preset_group", "preset", "filter"],
) -> None:
    """確認中にカーソルを動かしても、全段の追加画面へ元の起点を渡す。"""
    source = create_custom_filter(tmp_path / "Filter.json")
    registry = editor.custom_filter_registry
    registry.add_paths((source,))
    registry.save()
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None
    registry.set_enabled(registry.entries[0].path, False)
    origin = qt.QPoint(123, 234)
    cursor = [qt.QPoint(origin)]
    confirmations: list[qt.QPoint] = []
    selections: list[qt.QPoint] = []

    def position() -> qt.QPoint:
        """確認画面の操作によるカーソル移動を再現する。"""
        return qt.QPoint(cursor[0])

    def discard(*args: object) -> qt.QMessageBox.StandardButton:
        """確認の起点を記録し、カーソルを移動してから破棄を選ぶ。"""
        anchor = args[3]
        assert isinstance(anchor, qt.QPoint)
        confirmations.append(qt.QPoint(anchor))
        cursor[0] = qt.QPoint(678, 789)
        return qt.QMessageBox.StandardButton.Discard

    def select(*args: object) -> tuple[list[str], str]:
        """追加画面の起点を記録して取り消す。"""
        anchor = args[4]
        assert isinstance(anchor, qt.QPoint)
        selections.append(qt.QPoint(anchor))
        return [], ""

    monkeypatch.setattr(qt.QCursor, "pos", position)
    monkeypatch.setattr(ui_dialog, "warning_near", discard)
    monkeypatch.setattr(manager_module, "get_open_file_names_near", select)
    button = {
        "preset_group": manager.group_add_button,
        "preset": manager.preset_add_button,
        "filter": manager.add_button,
    }[kind]
    button.click()
    assert confirmations == [origin]
    assert selections == [origin]
    assert cursor[0] != origin
    assert not editor.setup_panel.is_dirty


def test_keyboard_creation_uses_its_focused_button(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """カーソルが離れていても、キーボード操作元の近くで未保存確認を開く。"""
    source = create_custom_filter(tmp_path / "Filter.json")
    registry = editor.custom_filter_registry
    registry.add_paths((source,))
    registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(source)
    registry.set_enabled(registry.entries[0].path, False)
    editor.show()
    button = panel.preset_new_button
    button.setFocus()
    qt.QApplication.processEvents()
    captured: list[qt.QPoint] = []

    def cancel(*args: object) -> qt.QMessageBox.StandardButton:
        """起点だけを記録し、保存先画面を開かずに中止する。"""
        anchor = args[3]
        assert isinstance(anchor, qt.QPoint)
        captured.append(qt.QPoint(anchor))
        return qt.QMessageBox.StandardButton.Cancel

    def distant_cursor() -> qt.QPoint:
        """操作元とは離れたカーソル位置を返す。"""
        return qt.QPoint(-4000, -3000)

    monkeypatch.setattr(qt.QCursor, "pos", distant_cursor)
    monkeypatch.setattr(ui_dialog, "warning_near", cancel)
    event = qt.QtGui.QKeyEvent(
        qt.QEvent.Type.KeyPress,
        qt.Qt.Key.Key_F6,
        qt.Qt.KeyboardModifier.NoModifier,
    )
    qt.QApplication.sendEvent(button, event)
    button.click()
    assert captured == [button.mapToGlobal(button.rect().center())]
    assert panel.is_dirty


def test_duplicate_failure_uses_the_original_operation_position(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """複製元の消失も、通知時のカーソルではなく明示した起点で伝える。"""
    origin = qt.QPoint(123, 234)
    captured: list[qt.QPoint] = []

    def close_warning(*args: object) -> qt.QMessageBox.StandardButton:
        """複製失敗の通知を記録して閉じる。"""
        anchor = args[3]
        assert isinstance(anchor, qt.QPoint)
        captured.append(qt.QPoint(anchor))
        return qt.QMessageBox.StandardButton.Ok

    monkeypatch.setattr(ui_dialog, "warning_near", close_warning)
    assert (
        create_registered_filter(
            editor,
            editor.custom_filter_registry,
            source=str(tmp_path / "missing.json"),
            position=origin,
        )
        is None
    )
    assert captured == [origin]
