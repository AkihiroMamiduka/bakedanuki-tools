# coding: utf-8
"""管理画面の出力選択、保存前確認、改名追跡と対話位置を検証する。"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_manager as manager_module
from bd_tools.bd_channel_box import config
from bd_tools.bd_channel_box.custom_filter_editor import (
    CustomFilterDraft,
    create_custom_filter,
)
from bd_tools.bd_channel_box.custom_filter_export import ExportKind
from bd_tools.bd_channel_box.custom_filter_manager import (
    CustomFilterManagerDialog,
)
from bd_tools.bd_channel_box.custom_filter_registry import CustomFilterRegistry
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterError,
    normalize_filter_path,
)


@pytest.fixture
def manager(
    qt_application: qt.QApplication, tmp_path: Path
) -> Iterator[CustomFilterManagerDialog]:
    """各階層に複数の正常行を持つ管理画面を作り、Qt objectを解放する。"""
    assert qt_application is not None
    parent = qt.QWidget()
    registry = CustomFilterRegistry(parent)
    registry.remove_groups(tuple(entry.path for entry in registry.groups))
    group = registry.create_group(tmp_path / "Group A.json")
    preset = registry.create_preset(tmp_path / "Preset A.json")
    filters = tuple(
        create_custom_filter(tmp_path / f"Filter {name}.json")
        for name in ("A", "B")
    )
    registry.add_paths(filters)
    registry.create_preset(tmp_path / "Preset B.json")
    registry.add_paths(filters)
    registry.create_group(tmp_path / "Group B.json")
    registry.save()
    registry.select_group(group)
    registry.select_preset(preset)
    dialog = CustomFilterManagerDialog(registry, parent)
    try:
        yield dialog
    finally:
        dialog.close()
        parent.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _tree(
    manager: CustomFilterManagerDialog, kind: ExportKind
) -> qt.QTreeWidget:
    """出力階層に対応する公開一覧を返す。"""
    if kind == "preset_group":
        return manager.group_tree_widget
    if kind == "preset":
        return manager.preset_tree_widget
    return manager.tree_widget


def _button(
    manager: CustomFilterManagerDialog, kind: ExportKind
) -> qt.QToolButton:
    """出力階層に対応する公開ボタンを返す。"""
    if kind == "preset_group":
        return manager.group_export_button
    if kind == "preset":
        return manager.preset_export_button
    return manager.export_button


def _select(tree: qt.QTreeWidget, *indices: int) -> None:
    """指定した一覧行だけを順に選択する。"""
    tree.clearSelection()
    for index in indices:
        tree.topLevelItem(index).setSelected(True)


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
def test_export_requires_valid_selected_rows(
    manager: CustomFilterManagerDialog, tmp_path: Path, kind: ExportKind
) -> None:
    """上位は一件、定義は複数を許し、未選択や不正行混在は拒否する。"""
    tree = _tree(manager, kind)
    button = _button(manager, kind)
    _select(tree, 0)
    assert button.isEnabled()
    tree.topLevelItem(1).setSelected(True)
    assert button.isEnabled() is (kind == "filter")
    _select(tree)
    assert not button.isEnabled()
    tree.setCurrentItem(
        tree.topLevelItem(0),
        0,
        qt.QItemSelectionModel.SelectionFlag.NoUpdate,
    )
    assert not button.isEnabled()

    missing = str(tmp_path / "missing.json")
    registry = manager.registry
    if kind == "preset_group":
        registry.add_group_paths((missing,))
    elif kind == "preset":
        registry.add_preset_paths((missing,))
    else:
        registry.add_paths((missing,))
    invalid_index = tree.topLevelItemCount() - 1
    _select(tree, invalid_index)
    assert not button.isEnabled()
    tree.topLevelItem(0).setSelected(True)
    assert not button.isEnabled()


@pytest.mark.parametrize("outcome", ("cancel", "false", "error", "dirty"))
def test_standalone_export_keeps_edits_when_save_does_not_complete(
    manager: CustomFilterManagerDialog,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    """取消と保存失敗では編集を維持し、保存先選択へ進まない。"""
    registry = manager.registry
    source = registry.entries[0].path
    before = Path(source).read_bytes()
    registry.set_enabled(source, False)
    _select(manager.tree_widget, 0)
    calls: list[str] = []

    def confirm(_parent: qt.QWidget, _anchor: qt.QPoint) -> bool:
        """保存かキャンセルの確認応答を記録する。"""
        calls.append("confirm")
        return outcome != "cancel"

    def save() -> bool:
        """False、例外、未保存の残存という三種類の失敗を再現する。"""
        calls.append("save")
        if outcome == "error":
            raise CustomFilterError("保存先へ書き込めません")
        return outcome == "dirty"

    def refuse_folder(*_args: object) -> str:
        """保存が完了していない状態で保存先へ進むことを拒否する。"""
        raise AssertionError("未保存の変更が残っています")

    def warning(*_args: object) -> None:
        """保存例外を捕捉してモーダル表示を防ぐ。"""
        calls.append("warning")

    monkeypatch.setattr(manager_module, "confirm_export_save", confirm)
    monkeypatch.setattr(manager, "_save_changes", save)
    monkeypatch.setattr(
        manager_module, "get_existing_directory_near", refuse_folder
    )
    monkeypatch.setattr(manager_module.ui_dialog, "warning_near", warning)
    manager.export_button.click()
    assert calls[0] == "confirm"
    assert ("save" in calls) is (outcome != "cancel")
    assert ("warning" in calls) is (outcome == "error")
    assert registry.is_dirty
    assert not registry.entries[0].enabled
    assert Path(source).read_bytes() == before


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
def test_export_tracks_the_initial_target_after_save_rename(
    manager: CustomFilterManagerDialog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: ExportKind,
) -> None:
    """保存による改名と選択移動の後も、押下した対象と起点を保持する。"""
    registry = manager.registry
    tree = _tree(manager, kind)
    _select(tree, 0)
    original: object = tree.topLevelItem(0).data(
        0, qt.Qt.ItemDataRole.UserRole
    )
    assert isinstance(original, str)
    renamed = normalize_filter_path(tmp_path / "Renamed.json")
    origin = qt.QPoint(123, 234)
    events: list[str] = []
    anchors: list[qt.QPoint] = []
    output = tmp_path / "Export"

    def position() -> qt.QPoint:
        """一連の対話が一回の位置取得だけで始まることを記録する。"""
        events.append("position")
        return qt.QPoint(origin)

    def confirm(anchor: qt.QPoint) -> bool:
        """選択元を改名保存してから別の行へ選択を移す。"""
        events.append("confirm")
        anchors.append(qt.QPoint(anchor))
        if kind == "preset_group":
            registry.rename_group(original, "Renamed")
            registry.save()
        elif kind == "preset":
            registry.rename_preset(original, "Renamed")
            registry.save()
        else:
            draft = CustomFilterDraft(original)
            draft.rename("Renamed")
            registry.save(draft)
        blocked = tree.blockSignals(True)
        try:
            _select(tree, 1)
        finally:
            tree.blockSignals(blocked)
        return True

    def folder(
        _parent: qt.QWidget,
        _caption: str,
        directory: str,
        anchor: qt.QPoint,
        *,
        initial_size: qt.QSize,
    ) -> str:
        """保存後の親フォルダーと同じ位置で保存先が開くことを確認する。"""
        events.append("folder")
        anchors.append(qt.QPoint(anchor))
        assert Path(directory) == tmp_path
        assert initial_size == qt.QSize(
            config.EXPORT_DIRECTORY_DIALOG_WIDTH,
            config.EXPORT_DIRECTORY_DIALOG_HEIGHT,
        )
        return str(tmp_path)

    def export(
        actual_kind: ExportKind,
        paths: Sequence[str | Path],
        directory: str | Path,
    ) -> Path:
        """保存後に選択した別行ではなく、元対象の新しいパスを受け取る。"""
        events.append("export")
        assert actual_kind == kind
        assert tuple(paths) == (renamed,)
        assert Path(directory) == tmp_path
        return output

    def complete(dialog: qt.QDialog, anchor: qt.QPoint) -> int:
        """同じ位置の完了通知に出力先が表示されることを確認する。"""
        events.append("complete")
        anchors.append(qt.QPoint(anchor))
        assert isinstance(dialog, qt.QMessageBox)
        assert dialog.icon() == qt.QMessageBox.Icon.Information
        assert dialog.standardButtons() == qt.QMessageBox.StandardButton.Ok
        assert str(output) in dialog.informativeText()
        return qt.QMessageBox.StandardButton.Ok.value

    monkeypatch.setattr(manager, "_dialog_position", position)
    monkeypatch.setattr(manager, "_confirm_export", confirm)
    monkeypatch.setattr(manager_module, "get_existing_directory_near", folder)
    monkeypatch.setattr(manager_module, "export_custom_filter_files", export)
    monkeypatch.setattr(manager_module, "exec_dialog_near", complete)
    _button(manager, kind).click()
    assert events == ["position", "confirm", "folder", "export", "complete"]
    assert anchors == [origin, origin, origin]
    assert not registry.is_dirty


@pytest.mark.parametrize("approved", (False, True))
def test_shared_confirmation_must_leave_no_pending_edits(
    manager: CustomFilterManagerDialog,
    monkeypatch: pytest.MonkeyPatch,
    approved: bool,
) -> None:
    """共有確認の中止と、成功応答でも変更が残る場合は出力へ進まない。"""
    path = manager.registry.entries[0].path
    manager.registry.set_enabled(path, False)
    _select(manager.tree_widget, 0)
    calls: list[qt.QPoint] = []
    origin = qt.QPoint(234, 345)

    def position() -> qt.QPoint:
        """保存前確認へ渡す位置を固定する。"""
        return qt.QPoint(origin)

    def confirm(anchor: qt.QPoint) -> bool:
        """変更を保存せず、確認の応答だけを返す。"""
        calls.append(qt.QPoint(anchor))
        return approved

    def refuse_folder(*_args: object) -> str:
        """中止または未保存が残る場合の保存先表示を拒否する。"""
        raise AssertionError("保存先選択へ進めません")

    monkeypatch.setattr(manager, "_dialog_position", position)
    monkeypatch.setattr(manager, "_confirm_export", confirm)
    monkeypatch.setattr(
        manager_module, "get_existing_directory_near", refuse_folder
    )
    manager.export_button.click()
    assert calls == [origin]
    assert manager.registry.is_dirty


@pytest.mark.parametrize("outcome", ("cancel", "error", "success"))
def test_filter_export_preserves_multiple_paths_and_dialog_anchor(
    manager: CustomFilterManagerDialog,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    """複数定義を一覧順で渡し、フォルダー取消と失敗も同じ起点で扱う。"""
    _select(manager.tree_widget, 0, 1)
    expected = tuple(entry.path for entry in manager.registry.entries)
    origin = qt.QPoint(345, 456)
    events: list[str] = []
    anchors: list[qt.QPoint] = []

    def position() -> qt.QPoint:
        """複数選択の出力開始位置を固定する。"""
        events.append("position")
        return qt.QPoint(origin)

    def refuse_confirmation(*_args: object) -> bool:
        """保存済みの定義に不要な確認が出ないことを保証する。"""
        raise AssertionError("未保存変更はありません")

    def folder(
        _parent: qt.QWidget,
        _caption: str,
        _directory: str,
        anchor: qt.QPoint,
        *,
        initial_size: qt.QSize,
    ) -> str:
        """同じ起点で保存先選択か取消を返す。"""
        events.append("folder")
        anchors.append(qt.QPoint(anchor))
        assert initial_size == qt.QSize(1100, 620)
        return "" if outcome == "cancel" else str(tmp_path)

    def export(
        kind: ExportKind,
        paths: Sequence[str | Path],
        _directory: str | Path,
    ) -> Path:
        """一覧順を検証し、出力成功またはエラーを返す。"""
        events.append("export")
        assert kind == "filter"
        assert tuple(paths) == expected
        if outcome == "error":
            raise CustomFilterError("依存ファイルを読み込めません")
        return tmp_path / "Export"

    def warning(
        _parent: qt.QWidget,
        _title: str,
        message: str,
        anchor: qt.QPoint,
    ) -> None:
        """出力失敗も開始時の起点に通知する。"""
        events.append("warning")
        anchors.append(qt.QPoint(anchor))
        assert "依存ファイル" in message

    def complete(_dialog: qt.QDialog, anchor: qt.QPoint) -> int:
        """完了通知の起点を記録する。"""
        events.append("complete")
        anchors.append(qt.QPoint(anchor))
        return qt.QMessageBox.StandardButton.Ok.value

    monkeypatch.setattr(manager, "_dialog_position", position)
    monkeypatch.setattr(config, "EXPORT_DIRECTORY_DIALOG_WIDTH", 1100)
    monkeypatch.setattr(config, "EXPORT_DIRECTORY_DIALOG_HEIGHT", 620)
    monkeypatch.setattr(
        manager_module, "confirm_export_save", refuse_confirmation
    )
    monkeypatch.setattr(manager_module, "get_existing_directory_near", folder)
    monkeypatch.setattr(manager_module, "export_custom_filter_files", export)
    monkeypatch.setattr(manager_module.ui_dialog, "warning_near", warning)
    monkeypatch.setattr(manager_module, "exec_dialog_near", complete)
    manager.export_button.click()
    expected_events = ["position", "folder"]
    if outcome != "cancel":
        expected_events += [
            "export",
            "warning" if outcome == "error" else "complete",
        ]
    assert events == expected_events
    assert anchors == [origin] * (1 if outcome == "cancel" else 2)


@pytest.mark.parametrize(
    "error", (RuntimeError("Mayaの画面エラー"), ValueError("初期サイズ"))
)
def test_directory_dialog_failure_stops_export_with_a_nearby_warning(
    manager: CustomFilterManagerDialog,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Maya標準画面やサイズ設定の失敗を起点へ通知し、出力を作成しない。"""
    _select(manager.tree_widget, 0)
    origin = qt.QPoint(100, 200)
    warnings: list[str] = []

    def position() -> qt.QPoint:
        """失敗通知の起点を固定する。"""
        return qt.QPoint(origin)

    def fail(*_args: object, **_kwargs: object) -> str:
        """ダイアログ表示または設定値の失敗を再現する。"""
        raise error

    def refuse_export(*_args: object) -> Path:
        """保存先の選択に失敗した後のファイル出力を拒否する。"""
        raise AssertionError("出力へ進んではいけません")

    def warning(
        _parent: qt.QWidget, _title: str, message: str, anchor: qt.QPoint
    ) -> None:
        """開始位置と表示される失敗理由を記録する。"""
        assert anchor == origin
        warnings.append(message)

    monkeypatch.setattr(manager, "_dialog_position", position)
    monkeypatch.setattr(manager_module, "get_existing_directory_near", fail)
    monkeypatch.setattr(
        manager_module, "export_custom_filter_files", refuse_export
    )
    monkeypatch.setattr(manager_module.ui_dialog, "warning_near", warning)
    manager.export_button.click()
    assert warnings == [str(error)]
