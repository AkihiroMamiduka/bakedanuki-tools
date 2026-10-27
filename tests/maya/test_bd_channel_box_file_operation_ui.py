# coding: utf-8
"""実ファイル操作の選択・保存確認・状態色を管理画面から検証する。"""

from pathlib import Path
from typing import cast
from collections.abc import Iterator

import pytest

from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_manager as manager_module
from bd_tools.bd_channel_box import custom_filter_dialogs as dialogs
from bd_tools.bd_channel_box.custom_filter_files import FileKind
from bd_tools.bd_channel_box.custom_filter_presets import (
    FilterReference,
    create_preset_document,
)
from bd_tools.bd_channel_box.custom_filters import normalize_filter_path
from bd_tools.bd_channel_box.custom_filter_setup import CustomFilterSetupPanel
from test_bd_channel_box_file_operations import create_file_library


@pytest.fixture(autouse=True)
def reject_unexpected_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """想定外の警告でモーダル待機せず、テストの失敗として通知する。"""
    errors: list[str] = []

    def warning(
        _parent: object, _title: str, message: str, _position: object
    ) -> qt.QMessageBox.StandardButton:
        """予期せぬ警告を記録して閉じる。"""
        errors.append(message)
        return qt.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(manager_module.ui_dialog, "warning_near", warning)
    yield
    assert not errors


def _tree(
    dialog: manager_module.CustomFilterManagerDialog, kind: FileKind
) -> qt.QTreeWidget:
    """対象階層の一覧を返す。"""
    return (
        dialog.group_tree_widget
        if kind == "preset_group"
        else (
            dialog.preset_tree_widget
            if kind == "preset"
            else dialog.tree_widget
        )
    )


def _select(tree: qt.QTreeWidget, count: int) -> None:
    """現在行を維持したまま先頭から指定件数を選択する。"""
    for index in range(tree.topLevelItemCount()):
        tree.topLevelItem(index).setSelected(index < count)


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
def test_manager_bulk_move_then_delete_and_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: FileKind,
) -> None:
    """3一覧で複数選択・移動後の選択維持・削除取消・実削除を操作する。"""
    registry, paths = create_file_library(tmp_path)
    parent = qt.QWidget()
    dialog = manager_module.CustomFilterManagerDialog(registry, parent)
    tree = _tree(dialog, kind)
    _select(tree, 2)
    folder = tmp_path / "Moved"
    folder.mkdir()

    def choose(*_args: object, **_kwargs: object) -> str:
        """Mayaの保存先選択結果を返す。"""
        return str(folder)

    monkeypatch.setattr(manager_module, "get_existing_directory_near", choose)
    try:
        move = (
            dialog.group_move_file_button
            if kind == "preset_group"
            else (
                dialog.preset_move_file_button
                if kind == "preset"
                else dialog.move_file_button
            )
        )
        delete = (
            dialog.group_delete_file_button
            if kind == "preset_group"
            else (
                dialog.preset_delete_file_button
                if kind == "preset"
                else dialog.delete_file_button
            )
        )
        assert move.isEnabled() and delete.isEnabled()
        move.click()
        assert len(tree.selectedItems()) == 2
        moved = tuple(folder.iterdir())
        assert len(moved) == 2

        def cancel(*_args: object) -> bool:
            """実削除の確認を取り消す。"""
            return False

        monkeypatch.setattr(manager_module, "confirm_file_delete", cancel)
        delete.click()
        assert all(path.exists() for path in moved)

        def accept(*_args: object) -> bool:
            """実削除の確認を受け入れる。"""
            return True

        monkeypatch.setattr(manager_module, "confirm_file_delete", accept)
        delete.click()
        assert not any(path.exists() for path in moved)
        assert paths["f1"].exists() == (kind != "filter")
        assert not delete.isEnabled()
    finally:
        dialog.deleteLater()
        parent.deleteLater()


@pytest.mark.parametrize(
    "outcome", ("cancel", "save_failed", "still_dirty", "saved")
)
def test_manager_requires_save_and_tracks_original_selection_after_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    """保存取消・失敗・残存を中止し、保存成功時は同じファイルを改名後も追跡する。"""
    registry, paths = create_file_library(tmp_path)
    parent = qt.QWidget()
    folder = tmp_path / "Moved"
    folder.mkdir()
    save_calls: list[bool] = []

    def save() -> bool:
        """成功時に改名を確定し、見かけの選択を別の行へ切り替える。"""
        save_calls.append(True)
        if outcome == "save_failed":
            return False
        if outcome == "saved":
            registry.save()
            dialog.preset_tree_widget.clearSelection()
            dialog.preset_tree_widget.topLevelItem(1).setSelected(True)
        return True

    dialog = manager_module.CustomFilterManagerDialog(
        registry, parent, save_changes=save
    )
    tree = dialog.preset_tree_widget
    _select(tree, 1)
    registry.rename_preset(normalize_filter_path(paths["p1"]), "Renamed")

    def confirm_save(*_args: object) -> bool:
        """指定した結果に応じて保存前確認を取り消す。"""
        return outcome != "cancel"

    def choose(*_args: object, **_kwargs: object) -> str:
        """移動先を返す。"""
        return str(folder)

    monkeypatch.setattr(
        manager_module, "confirm_file_operation_save", confirm_save
    )
    monkeypatch.setattr(
        manager_module,
        "get_existing_directory_near",
        choose,
    )
    try:
        dialog.preset_move_file_button.click()
        assert bool(save_calls) == (outcome != "cancel")
        assert (folder / "Renamed.json").exists() == (outcome == "saved")
        assert paths["p2"].exists()
        assert paths["p1"].exists() == (outcome != "saved")
    finally:
        dialog.deleteLater()
        parent.deleteLater()


def test_status_error_color_survives_selection_and_resets_after_reload(
    tmp_path: Path,
) -> None:
    """済と読込エラーを区別し、状態列だけを選択中も赤くして回復時に解除する。"""
    registry, paths = create_file_library(tmp_path)
    paths["f1"].write_bytes(b"{")
    registry.reload_all()
    parent = qt.QWidget()
    dialog = manager_module.CustomFilterManagerDialog(registry, parent)
    tree = dialog.tree_widget
    try:
        item = tree.topLevelItem(0)
        assert item.text(2) == "読込エラー"
        assert item.foreground(2).color() == qt.QColor(255, 96, 96)
        assert item.foreground(0).style() == qt.Qt.BrushStyle.NoBrush
        option = qt.QtWidgets.QStyleOptionViewItem()
        delegate = cast(qt.QStyledItemDelegate, tree.itemDelegateForColumn(2))
        delegate.initStyleOption(option, tree.model().index(0, 2))
        palette = cast(qt.QPalette, getattr(option, "palette"))
        assert palette.color(
            qt.QPalette.ColorRole.HighlightedText
        ) == qt.QColor(255, 96, 96)
        paths["f1"].write_bytes(paths["f2"].read_bytes())
        registry.reload_all()
        assert item.text(2) == "済"
        assert item.foreground(2).style() == qt.Qt.BrushStyle.NoBrush
    finally:
        dialog.deleteLater()
        parent.deleteLater()


def _delete_preview_widgets(
    dialog: qt.QDialog,
) -> tuple[qt.QComboBox, qt.QListWidget, qt.QLabel]:
    """削除対象と更新する参照元を確認する部品を取得する。"""
    combo = dialog.findChild(qt.QComboBox, "deleteFileCombo")
    references = dialog.findChild(qt.QListWidget, "deleteReferenceList")
    label = dialog.findChild(qt.QLabel, "deleteReferenceLabel")
    assert isinstance(combo, qt.QComboBox)
    assert isinstance(references, qt.QListWidget)
    assert isinstance(label, qt.QLabel)
    assert dialog.findChild(qt.QLabel, "deleteReferenceEmpty") is None
    return combo, references, label


def _reference_paths(references: qt.QListWidget) -> tuple[str, ...]:
    """一覧に表示されている参照元のフルパスを取得する。"""
    return tuple(
        references.item(index).text() for index in range(references.count())
    )


@pytest.mark.parametrize(
    ("kind", "prefix", "reference_prefix"),
    (
        ("preset_group", "g", None),
        ("preset", "p", "g"),
        ("filter", "f", "p"),
    ),
)
def test_delete_confirmation_defaults_to_cancel_and_lists_full_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: FileKind,
    prefix: str,
    reference_prefix: str | None,
) -> None:
    """各階層の削除対象と共有参照元を表示し、既定の取消でファイルを保護する。"""
    registry, paths = create_file_library(tmp_path)
    selected = tuple(paths[f"{prefix}{index}"] for index in (1, 2))
    plan = registry.prepare_file_delete(kind, (str(path) for path in selected))
    before = {key: path.read_bytes() for key, path in paths.items()}
    parent = qt.QWidget()

    def inspect(dialog: qt.QDialog, anchor: qt.QPoint) -> int:
        """確認画面を実行せず、表示内容と既定ボタンを調べる。"""
        assert anchor == qt.QPoint(10, 20)
        combo, references, label = _delete_preview_widgets(dialog)
        assert not combo.isEditable()
        assert combo.count() == 2
        assert combo.currentIndex() == 0
        expected: set[str] = (
            set()
            if reference_prefix is None
            else {
                str(paths[f"{reference_prefix}{index}"].resolve())
                for index in (1, 2)
            }
        )
        for index, path in enumerate(selected):
            combo.setCurrentIndex(index)
            full_path = str(path.resolve())
            assert combo.currentText() == full_path
            assert combo.itemData(index, qt.Qt.ItemDataRole.ToolTipRole) == (
                full_path
            )
            assert combo.toolTip() == full_path
            assert set(_reference_paths(references)) == expected
            assert references.count() == len(expected)
            assert label.text() == (
                f"更新する参照元ファイル（{len(expected)}件）"
            )
            assert not references.isHidden()
            for row in range(references.count()):
                item = references.item(row)
                assert item.toolTip() == item.text()
        buttons = dialog.findChild(qt.QDialogButtonBox)
        assert isinstance(buttons, qt.QDialogButtonBox)
        assert buttons.button(
            qt.QDialogButtonBox.StandardButton.Ok
        ).text() == ("2件のファイルを削除")
        assert buttons.button(
            qt.QDialogButtonBox.StandardButton.Cancel
        ).isDefault()
        buttons.button(qt.QDialogButtonBox.StandardButton.Cancel).click()
        return dialog.result()

    monkeypatch.setattr(dialogs, "exec_dialog_near", inspect)
    try:
        assert not dialogs.confirm_file_delete(parent, plan, qt.QPoint(10, 20))
        assert before == {
            key: path.read_bytes() for key, path in paths.items()
        }
        assert not registry.is_dirty
    finally:
        parent.deleteLater()


def test_delete_preview_switches_only_the_selected_files_reference_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """共通の親と異なる親を持つ2件で、切替時に該当する参照元だけを表示する。"""
    registry, paths = create_file_library(tmp_path)
    registry.select_preset(str(paths["p2"]))
    registry.remove(normalize_filter_path(paths["f2"]))
    registry.save()
    third_preset = tmp_path / "p3.json"
    create_preset_document(
        third_preset,
        "preset",
        (FilterReference(normalize_filter_path(paths["f2"])),),
    )
    registry.select_group(str(paths["g2"]))
    registry.add_preset_paths((third_preset,))
    registry.save()
    registry.select_group(str(paths["g1"]))
    registry.select_preset(str(paths["p1"]))
    plan = registry.prepare_file_delete(
        "filter", (str(paths["f1"]), str(paths["f2"]))
    )
    before = {key: path.read_bytes() for key, path in paths.items()}
    parent = qt.QWidget()

    def inspect(dialog: qt.QDialog, _anchor: qt.QPoint) -> int:
        """対象を往復して切り替え、ほかの対象専用の親が混ざらないことを調べる。"""
        combo, references, label = _delete_preview_widgets(dialog)
        for index in (0, 1, 0):
            combo.setCurrentIndex(index)
            assert set(_reference_paths(references)) == {
                str(paths["p1"].resolve()),
                str((paths["p2"] if index == 0 else third_preset).resolve()),
            }
            assert references.count() == 2
            assert label.text() == "更新する参照元ファイル（2件）"
            assert not references.isHidden()
        assert before == {
            key: path.read_bytes() for key, path in paths.items()
        }
        return int(qt.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(dialogs, "exec_dialog_near", inspect)
    try:
        assert not dialogs.confirm_file_delete(parent, plan, qt.QPoint())
    finally:
        parent.deleteLater()


def test_delete_preview_updates_count_with_empty_reference_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """対象ごとに参照件数を更新し、未参照の対象では0件と空の一覧を示す。"""
    registry, paths = create_file_library(tmp_path)
    registry.select_group(str(paths["g2"]))
    registry.remove_presets((normalize_filter_path(paths["p2"]),))
    registry.save()
    registry.select_group(str(paths["g1"]))
    plan = registry.prepare_file_delete(
        "preset", (str(paths["p1"]), str(paths["p2"]))
    )
    # 確認対象は現在一覧の登録に限られるため、0件は保存済み計画を使って確認する
    unreferenced_plan = registry.prepare_file_delete(
        "preset_group", (str(paths["g1"]),)
    )
    parent = qt.QWidget()
    checked: list[bool] = []

    def inspect(dialog: qt.QDialog, _anchor: qt.QPoint) -> int:
        """参照元が2件・1件・0件の場合の件数と一覧の切替を調べる。"""
        combo, references, label = _delete_preview_widgets(dialog)
        if combo.count() == 2:
            for index, count in ((0, 2), (1, 1), (0, 2)):
                combo.setCurrentIndex(index)
                assert references.count() == count
                assert label.text() == f"更新する参照元ファイル（{count}件）"
                assert not references.isHidden()
        else:
            assert references.count() == 0
            assert label.text() == "更新する参照元ファイル（0件）"
            assert not references.isHidden()
        checked.append(True)
        return int(qt.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(dialogs, "exec_dialog_near", inspect)
    try:
        assert not dialogs.confirm_file_delete(parent, plan, qt.QPoint())
        assert not dialogs.confirm_file_delete(
            parent, unreferenced_plan, qt.QPoint()
        )
        assert len(checked) == 2
    finally:
        parent.deleteLater()


def test_delete_preview_keeps_full_long_paths_in_tooltips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """長い削除対象・参照元を省略せず保持し、ツールチップから全文を確認できる。"""
    folder = tmp_path / ("long_directory_" * 3)
    folder.mkdir()
    registry, paths = create_file_library(folder)
    plan = registry.prepare_file_delete(
        "filter", (str(paths["f1"]), str(paths["f2"]))
    )
    parent = qt.QWidget()

    def inspect(dialog: qt.QDialog, _anchor: qt.QPoint) -> int:
        """コンボの両項目と各参照元のツールチップをフルパスと照合する。"""
        combo, references, _label = _delete_preview_widgets(dialog)
        for index, key in enumerate(("f1", "f2")):
            combo.setCurrentIndex(index)
            expected = str(paths[key].resolve())
            assert combo.itemText(index) == expected
            assert combo.itemData(index, qt.Qt.ItemDataRole.ToolTipRole) == (
                expected
            )
            assert combo.toolTip() == expected
            assert set(_reference_paths(references)) == {
                str(paths[item].resolve()) for item in ("p1", "p2")
            }
            for row in range(references.count()):
                item = references.item(row)
                assert item.toolTip() == item.text()
        return int(qt.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(dialogs, "exec_dialog_near", inspect)
    try:
        assert not dialogs.confirm_file_delete(parent, plan, qt.QPoint())
    finally:
        parent.deleteLater()


@pytest.mark.parametrize("accepted", (False, True))
def test_delete_confirmation_switching_keeps_all_original_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    """表示対象を切り替えた後も確定は全件を削除し、取消は一件も変更しない。"""
    registry, paths = create_file_library(tmp_path)
    parent = qt.QWidget()
    manager = manager_module.CustomFilterManagerDialog(registry, parent)
    _select(manager.tree_widget, 2)
    before = {key: path.read_bytes() for key, path in paths.items()}
    checked: list[bool] = []

    def inspect(dialog: qt.QDialog, _anchor: qt.QPoint) -> int:
        """2件目の表示へ切り替え、利用者が選んだ確定または取消を操作する。"""
        combo, _references, _label = _delete_preview_widgets(dialog)
        combo.setCurrentIndex(1)
        assert combo.currentText() == str(paths["f2"].resolve())
        buttons = dialog.findChild(qt.QDialogButtonBox)
        assert isinstance(buttons, qt.QDialogButtonBox)
        button = (
            qt.QDialogButtonBox.StandardButton.Ok
            if accepted
            else qt.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(button).click()
        checked.append(True)
        return dialog.result()

    monkeypatch.setattr(dialogs, "exec_dialog_near", inspect)
    try:
        manager.delete_file_button.click()
        assert checked == [True]
        assert paths["f1"].exists() == (not accepted)
        assert paths["f2"].exists() == (not accepted)
        assert all(paths[key].exists() for key in ("p1", "p2", "g1", "g2"))
        if not accepted:
            assert before == {
                key: path.read_bytes() for key, path in paths.items()
            }
        assert not registry.is_dirty
    finally:
        manager.deleteLater()
        parent.deleteLater()


def test_physical_filter_delete_clears_the_setup_draft(tmp_path: Path) -> None:
    """実削除したフィルターを未登録の編集対象として残さない。"""
    registry, paths = create_file_library(tmp_path)
    parent = qt.QWidget()
    panel = CustomFilterSetupPanel(registry, parent)
    path = normalize_filter_path(paths["f1"])
    try:
        panel.set_target(path)
        assert panel.draft is not None and panel.draft.path == path
        registry.delete_files(registry.prepare_file_delete("filter", (path,)))
        assert panel.draft is None
    finally:
        panel.deleteLater()
        parent.deleteLater()
