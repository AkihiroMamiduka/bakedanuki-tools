# coding: utf-8
"""目のない上位一覧の名前先頭でも、標準の行選択を行えることを確認する。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from bd_util.ui import dialog as ui_dialog
from bd_util.ui import qt

from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


@pytest.fixture
def editor(
    qt_application: qt.QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ChannelBoxWidget]:
    """実マウス入力を送る画面を作り、監視とQt objectを解放する。"""
    assert qt_application is not None

    def reject_dialog(*args: object) -> qt.QMessageBox.StandardButton:
        """保存済みの選択変更で確認が発生した場合は失敗として示す。"""
        raise AssertionError(f"予期しない確認: {args[1:]}")

    monkeypatch.setattr(ui_dialog, "warning_near", reject_dialog)
    widget = ChannelBoxWidget()
    widget.resize(760, 800)
    widget.show()
    qt.QApplication.processEvents()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _click_name_start(tree: qt.QTreeWidget, item: qt.QTreeWidgetItem) -> None:
    """目のある一覧なら切替領域になる名前先頭へ押下と解放を送る。"""
    tree.scrollToItem(item)
    qt.QApplication.processEvents()
    rect = tree.visualItemRect(item)
    position = qt.QPoint(rect.left() + 6, rect.center().y())
    assert tree.itemAt(position) is item
    viewport = tree.viewport()
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(position),
            qt.QPointF(viewport.mapToGlobal(position)),
            qt.Qt.MouseButton.LeftButton,
            (
                qt.Qt.MouseButton.LeftButton
                if kind == qt.QEvent.Type.MouseButtonPress
                else qt.Qt.MouseButton.NoButton
            ),
            qt.Qt.KeyboardModifier.NoModifier,
        )
        qt.QApplication.sendEvent(viewport, event)
    qt.QApplication.processEvents()


@pytest.mark.parametrize("level", ("preset_group", "preset"))
def test_upper_tree_name_start_selects_row_and_updates_children(
    editor: ChannelBoxWidget, tmp_path: Path, level: str
) -> None:
    """上2段の先頭20pxも行選択と下段連動に使い、目の処理で消費しない。"""
    registry = editor.custom_filter_registry
    first_group = registry.create_group(tmp_path / "Group A.json")
    first_preset = registry.create_preset(tmp_path / "Preset A.json")
    first_filter = tmp_path / "Filter A.json"
    create_custom_filter(first_filter, first_filter.stem)
    registry.add_paths((first_filter,))
    registry.save()
    second_preset = registry.create_preset(tmp_path / "Preset B.json")
    second_filter = tmp_path / "Filter B.json"
    create_custom_filter(second_filter, second_filter.stem)
    registry.add_paths((second_filter,))
    registry.save()
    registry.create_group(tmp_path / "Group B.json")
    registry.create_preset(tmp_path / "Preset C.json")
    registry.save()
    if level == "preset":
        registry.select_group(first_group)
        registry.select_preset(second_preset)
    editor.manage_custom_filters_action.trigger()
    qt.QApplication.processEvents()
    manager = editor.custom_filter_dialog
    assert manager is not None and manager.isVisible()
    tree = (
        manager.group_tree_widget
        if level == "preset_group"
        else manager.preset_tree_widget
    )
    path = first_group if level == "preset_group" else first_preset
    item = next(
        tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index).data(0, qt.Qt.ItemDataRole.UserRole)
        == path
    )
    assert tree.currentItem() is not item
    assert not item.isSelected()
    _click_name_start(tree, item)
    assert tree.currentItem() is item
    assert tree.selectedItems() == [item]
    if level == "preset_group":
        assert registry.active_group == first_group
        assert manager.preset_tree_widget.topLevelItemCount() == 2
    else:
        assert registry.active_preset == first_preset
        assert manager.tree_widget.topLevelItemCount() == 1
        assert manager.tree_widget.topLevelItem(0).text(0) == "Filter A"
    assert not registry.is_dirty


def test_current_fallback_keeps_a_partially_selected_row(
    editor: ChannelBoxWidget,
    tmp_path: Path,
) -> None:
    """名前列だけを選択した行も、現在行を外した後の移動先に含める。"""
    registry = editor.custom_filter_registry
    registry.create_group(tmp_path / "Group.json")
    first_path = registry.create_preset(tmp_path / "First.json")
    second_path = registry.create_preset(tmp_path / "Second.json")
    registry.save()
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None
    tree = manager.preset_tree_widget
    first = tree.topLevelItem(0)
    second = tree.topLevelItem(1)
    tree.setCurrentItem(
        first, 0, qt.QItemSelectionModel.SelectionFlag.ClearAndSelect
    )
    assert not tree.selectionModel().isRowSelected(0, qt.QModelIndex())
    second.setSelected(True)
    tree.setCurrentItem(
        second, 0, qt.QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert registry.active_preset == second_path

    second.setSelected(False)
    assert tree.selectedItems() == [first]
    assert tree.currentItem() is first
    assert registry.active_preset == first_path
    assert manager.preset_remove_button.isEnabled()
    assert manager.preset_move_down_button.isEnabled()


def test_manager_selection_follows_rename_saved_by_leave_confirmation(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """切替の保存確認で選択先が改名されても、保存後の識別パスへ移る。"""
    registry = editor.custom_filter_registry
    registry.create_group(tmp_path / "Group.json")
    first_path = registry.create_preset(tmp_path / "First.json")
    registry.create_preset(tmp_path / "Second.json")
    registry.save()
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None
    tree = manager.preset_tree_widget
    first = tree.topLevelItem(0)
    registry.rename_preset(first_path, "Renamed")
    confirmations: list[str] = []

    def save(*args: object) -> qt.QMessageBox.StandardButton:
        """切替時に一度だけ共通保存を選択する。"""
        confirmations.append(str(args[2]))
        return qt.QMessageBox.StandardButton.Save

    monkeypatch.setattr(ui_dialog, "warning_near", save)
    tree.setCurrentItem(
        first, 0, qt.QItemSelectionModel.SelectionFlag.ClearAndSelect
    )
    assert len(confirmations) == 1
    assert not registry.is_dirty
    assert registry.active_preset == registry.presets[0].path
    assert registry.active_preset != first_path
    assert tree.currentItem() is first
    assert first.text(0) == "Renamed"
    assert (tmp_path / "Renamed.json").is_file()
    assert not (tmp_path / "First.json").exists()
