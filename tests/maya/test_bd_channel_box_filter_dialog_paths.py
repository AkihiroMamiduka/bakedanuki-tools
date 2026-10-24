# coding: utf-8
"""現在行・編集対象を基準にしたファイルダイアログの初期フォルダーを検証する。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest

from bd_util.ui import dialog as ui_dialog
from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_dialogs as dialog_module
from bd_tools.bd_channel_box import custom_filter_manager as manager_module
from bd_tools.bd_channel_box import custom_filter_setup as setup_panel_module

from bd_tools.bd_channel_box.custom_filter_dialogs import (
    default_filter_directory,
)
from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.custom_filter_manager import (
    CustomFilterManagerDialog,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget

_Kind = Literal["preset_group", "preset", "filter"]


@pytest.fixture
def editor(
    qt_application: qt.QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ChannelBoxWidget]:
    """設定と管理を共有する画面を用意し、予期しない確認を記録する。"""
    assert qt_application is not None
    warnings: list[str] = []

    def cancel_warning(*args: object) -> qt.QMessageBox.StandardButton:
        """想定外の確認で停止せず、終了時に失敗として報告する。"""
        warnings.append(str(args[2]))
        return qt.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(ui_dialog, "warning_near", cancel_warning)
    widget = ChannelBoxWidget()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)
        assert not warnings, warnings


def _manager_tree(
    editor: ChannelBoxWidget, kind: _Kind
) -> tuple[CustomFilterManagerDialog, qt.QTreeWidget]:
    """管理画面の指定段を取得し、同じ編集セッションで操作する。"""
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None
    tree = {
        "preset_group": manager.group_tree_widget,
        "preset": manager.preset_tree_widget,
        "filter": manager.tree_widget,
    }[kind]
    return manager, tree


def _register(editor: ChannelBoxWidget, kind: _Kind, path: Path) -> None:
    """既存フォルダーに種類に応じた有効なJSONを作成して登録する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = editor.custom_filter_registry
    if kind == "preset_group":
        registry.create_group(path)
    elif kind == "preset":
        registry.create_preset(path)
    else:
        create_custom_filter(path)
        registry.add_paths((path,))


def _choose_current(tree: qt.QTreeWidget, path: Path) -> None:
    """ファイル名から行を選び、現在行と通常の行選択を一致させる。"""
    item = next(
        tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
        if Path(
            str(tree.topLevelItem(index).data(0, qt.Qt.ItemDataRole.UserRole))
        )
        == path
    )
    tree.setCurrentItem(
        item,
        0,
        qt.QItemSelectionModel.SelectionFlag.ClearAndSelect
        | qt.QItemSelectionModel.SelectionFlag.Rows,
    )


def _capture_dialogs(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """新規と追加の初期パスを記録し、ファイル操作はキャンセルする。"""
    calls: list[Path] = []

    def save(*args: object) -> tuple[str, str]:
        """新規作成の初期フォルダーだけを取得する。"""
        calls.append(Path(str(args[2])))
        return "", ""

    def open_files(*args: object) -> tuple[list[str], str]:
        """追加の初期フォルダーだけを取得する。"""
        calls.append(Path(str(args[2])))
        return [], ""

    monkeypatch.setattr(dialog_module, "get_save_file_name_near", save)
    monkeypatch.setattr(manager_module, "get_open_file_names_near", open_files)
    return calls


def _click(manager: CustomFilterManagerDialog, kind: _Kind, add: bool) -> None:
    """指定段の新規または追加ボタンを、利用者と同じ経路で押す。"""
    new_button, add_button = {
        "preset_group": (manager.group_new_button, manager.group_add_button),
        "preset": (manager.preset_new_button, manager.preset_add_button),
        "filter": (manager.new_button, manager.add_button),
    }[kind]
    button = add_button if add else new_button
    assert button.isEnabled()
    button.click()


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
@pytest.mark.parametrize("add", (False, True))
def test_manager_uses_current_row_folder_with_multiple_selection(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _Kind,
    add: bool,
) -> None:
    """複数選択の先頭や直近のダイアログに依存せず、現在行の親を開く。"""
    first = tmp_path / "first" / "First.json"
    second = tmp_path / "second" / "Second.json"
    for path in (first, second):
        _register(editor, kind, path)
    editor.custom_filter_registry.save()
    manager, tree = _manager_tree(editor, kind)
    _choose_current(tree, first)
    first_item = tree.currentItem()
    _choose_current(tree, second)
    first_item.setSelected(True)
    assert len(tree.selectedItems()) == 2
    calls = _capture_dialogs(monkeypatch)
    _click(manager, kind, add)
    assert calls == [second.parent]
    assert len(tree.selectedItems()) == 2
    assert not editor.custom_filter_registry.is_dirty


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
@pytest.mark.parametrize(
    "condition", ("unselected", "error", "missing_parent")
)
def test_manager_folder_fallback_keeps_unavailable_locations_absent(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _Kind,
    condition: str,
) -> None:
    """未選択と親消失はprefsへ戻し、読込エラーだけなら既存の親を利用する。"""
    path = tmp_path / "reference" / "Reference.json"
    registry = editor.custom_filter_registry
    if condition == "unselected":
        _register(editor, kind, path)
    else:
        if condition == "error":
            path.parent.mkdir()
            path.write_text("{", encoding="utf-8")
        if kind == "preset_group":
            registry.add_group_paths((path,))
        elif kind == "preset":
            registry.add_preset_paths((path,))
        else:
            registry.add_paths((path,))
    registry.save()
    manager, tree = _manager_tree(editor, kind)
    _choose_current(tree, path)
    if condition == "unselected":
        tree.clearSelection()
    calls = _capture_dialogs(monkeypatch)
    _click(manager, kind, True)
    expected = (
        path.parent if condition == "error" else default_filter_directory(kind)
    )
    assert calls == [expected]
    assert expected.is_dir()
    if condition == "missing_parent":
        assert not path.parent.exists()


@pytest.mark.parametrize("preset", (False, True))
def test_setup_creation_uses_the_current_edit_target_folder(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preset: bool,
) -> None:
    """設定画面の新規作成も、編集中の種類に対応する既存フォルダーを開く。"""
    kind: _Kind = "preset" if preset else "filter"
    path = tmp_path / "shared" / "Editing.json"
    _register(editor, kind, path)
    editor.custom_filter_registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    if not preset:
        panel.set_target(str(path))
    calls = _capture_dialogs(monkeypatch)
    button = panel.preset_new_button if preset else panel.new_button
    button.click()
    assert calls == [path.parent]


def test_manager_rechecks_current_row_after_discarding_unsaved_registration(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """破棄で消える登録の古い行を参照せず、残った現在行から初期位置を取る。"""
    saved = tmp_path / "saved" / "Saved.json"
    pending = tmp_path / "pending" / "Pending.json"
    _register(editor, "filter", saved)
    registry = editor.custom_filter_registry
    registry.save()
    manager, tree = _manager_tree(editor, "filter")
    _register(editor, "filter", pending)
    _choose_current(tree, pending)

    def discard(*_args: object) -> qt.QMessageBox.StandardButton:
        """新規作成を続ける前に、未保存の追加登録を破棄する。"""
        return qt.QMessageBox.StandardButton.Discard

    monkeypatch.setattr(ui_dialog, "warning_near", discard)
    calls = _capture_dialogs(monkeypatch)
    _click(manager, "filter", False)
    assert calls == [saved.parent]
    assert not registry.is_dirty
    assert pending.is_file()


@pytest.mark.parametrize("preset", (False, True))
def test_setup_creation_keeps_click_origin_across_confirmation(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preset: bool,
) -> None:
    """保存・破棄確認でカーソルが動いても、新規画面へ最初の起点を渡す。"""
    source = tmp_path / "Filter.json"
    _register(editor, "filter", source)
    registry = editor.custom_filter_registry
    registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    registry.set_enabled(registry.entries[0].path, False)
    origin = qt.QPoint(123, 234)
    cursor = [qt.QPoint(origin)]
    captured: list[qt.QPoint] = []

    def position() -> qt.QPoint:
        """操作中のカーソル移動を再現する。"""
        return qt.QPoint(cursor[0])

    def discard(*_args: object) -> qt.QMessageBox.StandardButton:
        """確認ボタン側へカーソルを移動してから破棄する。"""
        cursor[0] = qt.QPoint(678, 789)
        return qt.QMessageBox.StandardButton.Discard

    def save(*args: object) -> tuple[str, str]:
        """配置共通処理へ渡された起点だけを記録する。"""
        point = args[4]
        assert isinstance(point, qt.QPoint)
        captured.append(qt.QPoint(point))
        return "", ""

    monkeypatch.setattr(qt.QCursor, "pos", position)
    monkeypatch.setattr(ui_dialog, "warning_near", discard)
    monkeypatch.setattr(dialog_module, "get_save_file_name_near", save)
    button = panel.preset_new_button if preset else panel.new_button
    button.click()
    assert captured == [origin]
    assert cursor[0] != origin


@pytest.mark.parametrize("preset", (False, True))
def test_setup_rename_passes_its_click_position_to_modal_execution(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preset: bool,
) -> None:
    """両方の名前変更画面が同じ配置APIへ起点を渡し、取消で編集しない。"""
    source = tmp_path / "Filter.json"
    _register(editor, "filter", source)
    editor.custom_filter_registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    origin = qt.QPoint(123, 234)
    captured: list[qt.QPoint] = []

    def position() -> qt.QPoint:
        """ボタンの操作位置を固定する。"""
        return qt.QPoint(origin)

    def execute(_dialog: qt.QDialog, point: qt.QPoint) -> int:
        """名前入力の配置先を記録し、取消として戻る。"""
        captured.append(qt.QPoint(point))
        return int(qt.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(qt.QCursor, "pos", position)
    monkeypatch.setattr(dialog_module, "exec_dialog_near", execute)
    monkeypatch.setattr(setup_panel_module, "exec_dialog_near", execute)
    button = panel.preset_rename_button if preset else panel.rename_button
    button.click()
    assert captured == [origin]
    assert not panel.is_dirty


def test_manager_filter_rename_keeps_origin_across_confirmation(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理画面からの名前変更も、確認前の起点を共用の入力画面へ引き継ぐ。"""
    source = tmp_path / "Filter.json"
    _register(editor, "filter", source)
    registry = editor.custom_filter_registry
    registry.save()
    manager, tree = _manager_tree(editor, "filter")
    _choose_current(tree, source)
    registry.set_enabled(registry.entries[0].path, False)
    origin = qt.QPoint(123, 234)
    cursor = [qt.QPoint(origin)]
    captured: list[qt.QPoint] = []

    def position() -> qt.QPoint:
        """操作位置を確認画面の表示前後で切り替える。"""
        return qt.QPoint(cursor[0])

    def discard(*_args: object) -> qt.QMessageBox.StandardButton:
        """確認ボタンへカーソルを移して構成変更を破棄する。"""
        cursor[0] = qt.QPoint(678, 789)
        return qt.QMessageBox.StandardButton.Discard

    def execute(_dialog: qt.QDialog, point: qt.QPoint) -> int:
        """管理画面から設定画面へ渡された起点を記録する。"""
        captured.append(qt.QPoint(point))
        return int(qt.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(qt.QCursor, "pos", position)
    monkeypatch.setattr(ui_dialog, "warning_near", discard)
    monkeypatch.setattr(setup_panel_module, "exec_dialog_near", execute)
    manager.rename_button.click()
    assert captured == [origin]
    assert cursor[0] != origin
