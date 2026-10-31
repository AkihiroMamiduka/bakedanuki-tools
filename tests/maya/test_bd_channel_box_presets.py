# coding: utf-8
"""共有プリセットの切替と、管理画面・属性編集の共通保存を検証する。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from bd_util.ui import dialog as ui_dialog
from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_dialogs as dialog_module

from bd_tools.bd_channel_box.custom_filter_dialogs import (
    create_registered_preset,
    default_filter_directory,
)
from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.custom_filter_presets import (
    create_preset_document,
)
from bd_tools.bd_channel_box.custom_filter_registry import CustomFilterRegistry
from bd_tools.bd_channel_box.custom_filters import (
    load_custom_filter,
    normalize_filter_path,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


@pytest.fixture
def editor(
    qt_application: qt.QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ChannelBoxWidget]:
    """一つの共有編集セッションを持つ画面を作成し、監視を解放する。"""
    assert qt_application is not None

    def unexpected_dialog(*args: object) -> qt.QMessageBox.StandardButton:
        """意図しないモーダル画面で検証を停止せず、内容を失敗として示す。"""
        raise AssertionError(f"予期しない確認: {args[1:]}")

    monkeypatch.setattr(ui_dialog, "warning_near", unexpected_dialog)
    widget = ChannelBoxWidget()
    widget.resize(700, 800)
    widget.show()
    qt.QApplication.processEvents()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _presets(
    editor: ChannelBoxWidget, tmp_path: Path
) -> tuple[str, str, tuple[str, ...]]:
    """同じフィルターを異なる順序・表示状態で参照する二つのプリセットを作る。"""
    registry = editor.custom_filter_registry
    registry.create_group(str(tmp_path / "Group.json"))
    files = tuple(tmp_path / f"{name}.json" for name in ("First", "Second"))
    for file in files:
        create_custom_filter(file, file.stem)
    first = registry.create_preset(str(tmp_path / "Modeling.json"))
    paths = registry.add_paths(files)
    registry.save()
    second = registry.create_preset(str(tmp_path / "Rigging.json"))
    registry.add_paths(reversed(files))
    registry.set_enabled(paths[0], False)
    registry.save()
    registry.select_preset(first)
    return first, second, paths


def test_preset_row_is_shared_by_all_modes_and_changes_custom_candidates(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """同じ選択行でプリセットを切り替え、通常と設定の候補を同期する。"""
    first, second, paths = _presets(editor, tmp_path)
    combo = editor.preset_combo
    assert combo is editor.setup_panel.preset_combo
    assert combo.currentData() == first
    assert editor.filter_combo.count() == 7
    assert not editor.setup_panel.global_controls.isVisible()
    assert not editor.setup_panel.preset_new_button.isVisible()
    combo.setCurrentIndex(combo.findData(second))
    assert editor.custom_filter_registry.active_preset == second
    assert tuple(
        entry.path for entry in editor.custom_filter_registry.entries
    ) == (
        paths[1],
        paths[0],
    )
    assert editor.filter_combo.count() == 6
    assert editor.filter_combo.itemText(5) == "Custom: Second"
    editor.controller.set_mode("states")
    assert combo.isVisible() and combo.currentData() == second
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    assert panel.global_controls.isVisible()
    assert panel.preset_new_button.isVisible()
    assert panel.preset_rename_button.isVisible()
    assert panel.target_combo.count() == 3
    assert panel.target_combo.findData(paths[0]) > 0
    assert editor.filter_combo.count() == 5
    assert not editor.custom_filter_registry.is_dirty


def test_common_save_and_discard_cover_structure_and_filter_contents(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """目の状態と属性編集を一緒に保存し、次の変更も一緒に破棄する。"""
    _first, _second, paths = _presets(editor, tmp_path)
    registry = editor.custom_filter_registry
    panel = editor.setup_panel
    editor.controller.set_mode("custom_filter_setup")
    panel.set_target(paths[0])
    draft = panel.draft
    assert draft is not None
    draft.set_included("transform", "visibility", True)
    registry.set_enabled(paths[1], False)
    panel.refresh_entries()
    assert panel.is_dirty and panel.save_button.isEnabled()
    panel.save_button.click()
    assert not panel.is_dirty
    assert load_custom_filter(paths[0]).node_types == {
        "transform": ("visibility",)
    }
    restored = CustomFilterRegistry()
    assert tuple(entry.enabled for entry in restored.entries) == (True, False)
    draft = panel.draft
    assert draft is not None
    draft.set_included("transform", "translate.translateX", True)
    registry.set_enabled(paths[0], False)
    panel.refresh_entries()
    panel.discard_button.click()
    assert not panel.is_dirty
    assert tuple(entry.enabled for entry in registry.entries) == (True, False)
    assert panel.draft is not None
    assert panel.draft.paths("transform") == ("visibility",)


@pytest.mark.parametrize("save", (False, True))
def test_preset_switch_confirms_pending_filter_and_keeps_cancelled_selection(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    save: bool,
) -> None:
    """切替の取消は元の対象を保ち、保存を選ぶと内容を確定して切り替える。"""
    first, second, paths = _presets(editor, tmp_path)
    panel = editor.setup_panel
    editor.controller.set_mode("custom_filter_setup")
    panel.set_target(paths[0])
    assert panel.draft is not None
    panel.draft.set_included("transform", "visibility", True)
    panel.refresh_entries()
    choices: list[str] = []

    def choose(*args: object) -> qt.QMessageBox.StandardButton:
        """共通保存の確認を記録し、検証対象の応答を返す。"""
        choices.append(str(args[2]))
        return (
            qt.QMessageBox.StandardButton.Save
            if save
            else qt.QMessageBox.StandardButton.Cancel
        )

    monkeypatch.setattr(ui_dialog, "warning_near", choose)
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData(second))
    expected = second if save else first
    assert len(choices) == 1
    assert editor.custom_filter_registry.active_preset == expected
    assert editor.preset_combo.currentData() == expected
    assert panel.draft is not None
    assert panel.draft.paths("transform") == ("visibility",)
    assert panel.draft.is_dirty is not save


@pytest.mark.parametrize("target_kind", ("filter", "preset"))
def test_discarded_target_registration_is_not_loaded_after_confirmation(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    """切替確認の破棄で消えた登録へ移らず、物理JSONだけは残す。"""
    first, _second, paths = _presets(editor, tmp_path)
    registry = editor.custom_filter_registry
    panel = editor.setup_panel
    editor.controller.set_mode("custom_filter_setup")
    panel.set_target(paths[0])
    assert panel.draft is not None
    panel.draft.set_included("transform", "visibility", True)
    source_content = Path(paths[0]).read_bytes()

    # 保存済みの親に追加した登録だけを下書きにし、切替先として表示する
    destination = tmp_path / "Ephemeral.json"
    if target_kind == "filter":
        create_custom_filter(destination)
        (target,) = registry.add_paths((destination,))
        combo = panel.target_combo
    else:
        document = create_preset_document(destination, "preset")
        (target,) = registry.add_preset_paths((document.path,))
        combo = editor.preset_combo
    assert registry.is_dirty and panel.draft.is_dirty
    index = combo.findData(target)
    assert index > 0
    choices: list[str] = []

    def discard(*args: object) -> qt.QMessageBox.StandardButton:
        """属性編集と未保存の追加登録をまとめて破棄する。"""
        choices.append(str(args[2]))
        return qt.QMessageBox.StandardButton.Discard

    monkeypatch.setattr(ui_dialog, "warning_near", discard)
    combo.setCurrentIndex(index)
    assert len(choices) == 1
    assert not panel.is_dirty
    assert Path(paths[0]).read_bytes() == source_content
    assert destination.is_file()
    assert combo.findData(target) == -1
    assert registry.active_preset == first
    if target_kind == "filter":
        assert target not in {entry.path for entry in registry.entries}
        assert panel.draft is None
        assert panel.target_combo.currentData() is None
    else:
        assert target not in {entry.path for entry in registry.presets}
        assert editor.preset_combo.currentData() == first
        assert panel.draft is not None and panel.draft.path == paths[0]
        assert panel.draft.paths("transform") == ()


def test_save_resolves_renamed_target_preset_before_switching(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """確認中に保存で改名された切替先を、新しい識別パスへ引き継ぐ。"""
    first, second, paths = _presets(editor, tmp_path)
    registry = editor.custom_filter_registry
    panel = editor.setup_panel
    editor.controller.set_mode("custom_filter_setup")
    panel.set_target(paths[0])
    assert panel.draft is not None
    panel.draft.set_included("transform", "visibility", True)
    registry.rename_preset(second, "Renamed Rigging")
    destination = tmp_path / "Renamed Rigging.json"
    assert registry.active_preset == first
    assert Path(second).is_file() and not destination.exists()
    assert panel.is_dirty
    choices: list[str] = []

    def save(*args: object) -> qt.QMessageBox.StandardButton:
        """切替を続ける前に、保留した改名と属性編集を一緒に確定する。"""
        choices.append(str(args[2]))
        return qt.QMessageBox.StandardButton.Save

    monkeypatch.setattr(ui_dialog, "warning_near", save)
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData(second))
    renamed = normalize_filter_path(destination)
    assert len(choices) == 1
    assert not Path(second).exists() and destination.is_file()
    assert registry.active_preset == renamed
    assert editor.preset_combo.currentData() == renamed
    assert editor.preset_combo.findData(second) == -1
    assert not panel.is_dirty
    assert panel.draft is not None and panel.draft.path == paths[0]
    assert panel.draft.paths("transform") == ("visibility",)
    restored = CustomFilterRegistry()
    assert restored.active_preset == renamed
    assert renamed in {entry.path for entry in restored.presets}
    assert second not in {entry.path for entry in restored.presets}


def test_manager_current_preset_controls_lower_list_with_multiselection(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """複数選択を残しながら現在行の所属だけを下段とメインへ表示する。"""
    first, second, paths = _presets(editor, tmp_path)
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None and manager.isVisible()
    tree = manager.preset_tree_widget
    assert tree.selectionMode() == (
        qt.QAbstractItemView.SelectionMode.ExtendedSelection
    )
    assert tree.topLevelItemCount() == 2
    first_item = tree.topLevelItem(0)
    second_item = tree.topLevelItem(1)
    tree.setCurrentItem(first_item)
    second_item.setSelected(True)
    tree.setCurrentItem(
        second_item, 0, qt.QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert len(tree.selectedItems()) == 2
    assert editor.custom_filter_registry.active_preset == second
    assert editor.preset_combo.currentData() == second
    assert tuple(
        manager.tree_widget.topLevelItem(index).data(
            0, qt.Qt.ItemDataRole.UserRole
        )
        for index in range(manager.tree_widget.topLevelItemCount())
    ) == (paths[1], paths[0])
    second_item.setSelected(False)
    assert editor.custom_filter_registry.active_preset == first
    assert tree.currentItem() is first_item
    assert len(tree.selectedItems()) == 1
    tree.clearSelection()
    assert editor.custom_filter_registry.active_preset is None
    assert manager.tree_widget.topLevelItemCount() == 0
    assert first != second


def test_unreadable_parent_keeps_error_row_and_disables_child_creation(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """読込不能な親を選んでも、新規ファイルだけ作られる操作を有効にしない。"""
    registry = editor.custom_filter_registry
    (broken_group,) = registry.add_group_paths(
        (tmp_path / "Missing Group.json",)
    )
    registry.select_group(broken_group)
    editor.controller.set_mode("custom_filter_setup")
    assert not editor.setup_panel.preset_new_button.isEnabled()
    assert not editor.setup_panel.new_button.isEnabled()
    registry.create_group(str(tmp_path / "Valid Group.json"))
    (broken_preset,) = registry.add_preset_paths(
        (tmp_path / "Missing Preset.json",)
    )
    registry.select_preset(broken_preset)
    assert editor.setup_panel.preset_new_button.isEnabled()
    assert not editor.setup_panel.new_button.isEnabled()
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None
    assert manager.preset_tree_widget.topLevelItem(0).text(2) == "読込エラー"
    assert not manager.new_button.isEnabled()
    assert not manager.add_button.isEnabled()


@pytest.mark.parametrize("kind", ("preset_group", "preset"))
def test_new_preset_document_uses_version_prefs_type_directory(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """種類別の初期フォルダーから空JSONを作り、ファイル名で登録する。"""
    destination = tmp_path / "Selected.json"
    calls: list[Path] = []

    def choose(*args: object) -> tuple[str, str]:
        """初期ディレクトリの作成を確認し、別の保存先を選ぶ。"""
        initial = Path(str(args[2]))
        calls.append(initial)
        assert initial.is_dir()
        return str(destination), ""

    monkeypatch.setattr(dialog_module, "get_save_file_name_near", choose)
    if kind == "preset_group":
        created = create_registered_preset(
            editor, editor.custom_filter_registry, "preset_group"
        )
        expected_directory = default_filter_directory("preset_group")
        entries = editor.custom_filter_registry.groups
    else:
        created = create_registered_preset(
            editor, editor.custom_filter_registry, "preset"
        )
        expected_directory = default_filter_directory("preset")
        entries = editor.custom_filter_registry.presets
    assert calls == [expected_directory]
    assert created == normalize_filter_path(destination)
    assert destination.is_file()
    assert entries[-1].name == "Selected"
    assert "name" not in json.loads(destination.read_text(encoding="utf-8"))
    assert editor.custom_filter_registry.is_dirty
