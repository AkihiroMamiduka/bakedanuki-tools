# coding: utf-8
"""共有プリセットの移行・下書き・選択・全参照改名を検証する。"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt
from bd_tools.bd_channel_box.custom_filter_editor import (
    CustomFilterDraft,
    create_custom_filter,
)
from bd_tools.bd_channel_box.custom_filter_presets import read_preset_document
from bd_tools.bd_channel_box.custom_filter_registry import CustomFilterRegistry
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterError,
    normalize_filter_path,
)


def _legacy_settings(files: list[dict[str, object]]) -> None:
    """旧登録設定を、通常の設定ファイルへ書き込む。"""
    path = get_ui_settings_file("bd_channel_box/preferences/custom_filters")
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = qt.QSettings(str(path), qt.QSettings.Format.IniFormat)
    settings.setValue(
        "preferences/custom_filters/registrations",
        json.dumps({"version": 1, "files": files}),
    )
    settings.sync()


def _shared_graph(
    tmp_path: Path,
) -> tuple[CustomFilterRegistry, str, str, str, str]:
    """二つのグループから同じプリセットを参照する構成を保存する。"""
    registry = CustomFilterRegistry()
    filter_path = create_custom_filter(tmp_path / "Filter.json", "Filter")
    preset = registry.create_preset(tmp_path / "Preset.json")
    registry.add_paths((filter_path,))
    group_a = registry.create_group(tmp_path / "GroupA.json")
    registry.add_preset_paths((preset,))
    group_b = registry.create_group(tmp_path / "GroupB.json")
    registry.add_preset_paths((preset,))
    registry.select_preset(preset)
    registry.save()
    return registry, filter_path, preset, group_a, group_b


def test_legacy_registration_migrates_without_moving_filters(
    tmp_path: Path,
) -> None:
    """旧順序・ON/OFF・エラー登録を既定JSONへ移し、元フィルターを保護する。"""
    first = Path(create_custom_filter(tmp_path / "Rigging.json", "Rigging"))
    broken = tmp_path / "Missing.json"
    before = first.read_bytes()
    _legacy_settings(
        [
            {"path": str(first), "enabled": False},
            {"path": str(broken), "enabled": True},
            {"path": str(first), "enabled": True},
        ]
    )
    registry = CustomFilterRegistry()
    assert registry.storage_error is None and not registry.is_dirty
    assert registry.groups[0].name == "Default"
    assert registry.presets[0].name == "Default"
    assert tuple(entry.path for entry in registry.entries) == (
        normalize_filter_path(first),
        normalize_filter_path(broken),
    )
    assert not registry.entries[0].enabled
    assert registry.entries[1].error is not None
    assert first.read_bytes() == before
    group = read_preset_document(registry.groups[0].path, "preset_group")
    preset = read_preset_document(group.references[0].path, "preset")
    assert preset.references[0].path == normalize_filter_path(first)
    assert CustomFilterRegistry().groups == registry.groups


def test_unsaved_roots_are_not_restored_and_created_files_remain(
    tmp_path: Path,
) -> None:
    """未保存グループ選択は登録を復活させず、破棄しても新規JSONを削除しない。"""
    registry = CustomFilterRegistry()
    original = registry.active_group
    created = registry.create_group(tmp_path / "DraftGroup.json")
    assert registry.active_group == created and registry.is_dirty
    restored = CustomFilterRegistry()
    assert tuple(item.path for item in restored.groups) == (original,)
    assert restored.active_group == original
    registry.discard()
    assert tuple(item.path for item in registry.groups) == (original,)
    assert Path(created).is_file() and not registry.is_dirty


def test_visibility_and_order_are_independent_between_presets(
    tmp_path: Path,
) -> None:
    """同じJSONの表示状態と並び順は各プリセットで独立し、選択を復元する。"""
    registry = CustomFilterRegistry()
    first = create_custom_filter(tmp_path / "First.json", "First")
    second = create_custom_filter(tmp_path / "Second.json", "Second")
    preset_a = registry.create_preset(tmp_path / "Modeling.json")
    registry.add_paths((first, second))
    preset_b = registry.create_preset(tmp_path / "Rigging.json")
    registry.add_paths((second, first))
    registry.set_enabled(first, False)
    registry.save()
    registry.select_preset(preset_a)
    assert tuple(item.path for item in registry.entries) == (first, second)
    assert all(item.enabled for item in registry.entries)
    registry.select_preset(preset_b)
    restored = CustomFilterRegistry()
    assert restored.active_preset == preset_b and not restored.is_dirty
    assert tuple(item.path for item in restored.entries) == (second, first)
    assert not restored.entries[1].enabled


def test_shared_preset_changes_are_visible_from_both_groups(
    tmp_path: Path,
) -> None:
    """同一プリセット参照の下書きはグループを切り替えても共有される。"""
    registry, filter_path, preset, group_a, group_b = _shared_graph(tmp_path)
    registry.set_enabled(filter_path, False)
    before = Path(preset).read_bytes()
    registry.select_group(group_a)
    assert registry.active_preset == preset and not registry.entries[0].enabled
    registry.select_group(group_b)
    assert not registry.entries[0].enabled
    assert Path(preset).read_bytes() == before
    registry.discard()
    assert registry.entries[0].enabled and not registry.is_dirty


def test_batch_rename_updates_all_known_references(tmp_path: Path) -> None:
    """プリセットとフィルターの同時改名を、全既知グループへ反映する。"""
    registry, filter_path, preset, group_a, group_b = _shared_graph(tmp_path)
    draft = CustomFilterDraft(filter_path)
    draft.rename("RenamedFilter")
    registry.rename_preset(preset, "RenamedPreset")
    registry.rename_group(group_a, "RenamedGroup")
    registry.save(draft)
    new_filter = normalize_filter_path(tmp_path / "RenamedFilter.json")
    new_preset = normalize_filter_path(tmp_path / "RenamedPreset.json")
    new_group = normalize_filter_path(tmp_path / "RenamedGroup.json")
    assert not Path(filter_path).exists() and not Path(preset).exists()
    assert not Path(group_a).exists()
    assert draft.path == new_filter and not draft.is_dirty
    for group in (new_group, group_b):
        document = read_preset_document(group, "preset_group")
        assert tuple(ref.path for ref in document.references) == (new_preset,)
    document = read_preset_document(new_preset, "preset")
    assert tuple(ref.path for ref in document.references) == (new_filter,)
    assert not registry.is_dirty
    restored = CustomFilterRegistry()
    assert restored.active_group == group_b
    assert restored.active_preset == new_preset
    assert restored.entries[0].path == new_filter


@pytest.mark.parametrize("kind", ("preset_group", "preset"))
def test_case_only_rename_preserves_input_spelling(
    tmp_path: Path, kind: str
) -> None:
    """識別パスが同じ改名でも、実ファイル名の大小文字を保存する。"""
    registry = CustomFilterRegistry()
    path = (
        registry.create_group(tmp_path / "Original.json")
        if kind == "preset_group"
        else registry.create_preset(tmp_path / "Original.json")
    )
    registry.save()
    rename = (
        registry.rename_group
        if kind == "preset_group"
        else registry.rename_preset
    )
    assert rename(path, "ORIGINAL")
    entries = registry.groups if kind == "preset_group" else registry.presets
    assert (
        next(item.name for item in entries if item.path == path) == "ORIGINAL"
    )
    registry.save()
    assert Path(path).resolve().name == "ORIGINAL.json"
    assert not registry.is_dirty


def test_external_filter_conflict_prevents_all_structure_writes(
    tmp_path: Path,
) -> None:
    """フィルターの外部変更を検出した場合、構成も更新せず下書きを残す。"""
    registry, filter_path, preset, _group_a, _group_b = _shared_graph(tmp_path)
    draft = CustomFilterDraft(filter_path)
    draft.rename("Pending")
    registry.set_enabled(filter_path, False)
    before = Path(preset).read_bytes()
    Path(filter_path).write_text("{\n}", encoding="utf-8")
    with pytest.raises(CustomFilterError):
        registry.save(draft)
    assert Path(preset).read_bytes() == before
    assert not (tmp_path / "Pending.json").exists()
    assert registry.is_dirty and draft.is_dirty


def test_readonly_reference_prevents_filter_rename(tmp_path: Path) -> None:
    """更新すべき共有プリセットが読取専用なら、フィルターも移動しない。"""
    registry, filter_path, preset, _group_a, _group_b = _shared_graph(tmp_path)
    draft = CustomFilterDraft(filter_path)
    draft.rename("Pending")
    path = Path(preset)
    mode = path.stat().st_mode
    try:
        path.chmod(stat.S_IREAD)
        with pytest.raises(CustomFilterError):
            registry.save(draft)
        assert Path(filter_path).exists()
        assert not (tmp_path / "Pending.json").exists()
        assert draft.is_dirty
    finally:
        path.chmod(mode)


def test_missing_preset_registration_survives_and_blocks_rename(
    tmp_path: Path,
) -> None:
    """参照切れを一覧に残し、参照元を確認できない状態で改名しない。"""
    registry = CustomFilterRegistry()
    missing = normalize_filter_path(tmp_path / "Missing.json")
    registry.add_preset_paths((missing,))
    registry.save()
    assert registry.presets[-1].path == missing
    assert registry.presets[-1].error is not None
    group = registry.active_group
    assert group is not None
    with pytest.raises(CustomFilterError):
        registry.rename_group(group, "Changed")
    registry.remove_presets((missing,))
    registry.save()
    assert all(item.path != missing for item in CustomFilterRegistry().presets)
    assert registry.rename_group(group, "Recovered")


def test_empty_saved_group_list_does_not_restore_defaults(
    tmp_path: Path,
) -> None:
    """全グループ登録の解除を保存した後は、既定グループを再作成しない。"""
    registry = CustomFilterRegistry()
    files = tuple(Path(item.path) for item in registry.groups)
    registry.remove_groups(item.path for item in registry.groups)
    registry.save()
    restored = CustomFilterRegistry()
    assert restored.groups == () and restored.active_group is None
    assert all(path.is_file() for path in files)


def test_group_and_preset_selection_is_remembered_per_group(
    tmp_path: Path,
) -> None:
    """各グループの最後のプリセット選択を、再起動後も維持する。"""
    registry, _filter_path, preset, group_a, group_b = _shared_graph(tmp_path)
    registry.select_group(group_a)
    other = registry.create_preset(tmp_path / "Other.json")
    registry.save()
    registry.select_group(group_b)
    assert registry.active_preset == preset
    registry.select_group(group_a)
    assert registry.active_preset == other and not registry.is_dirty
    restored = CustomFilterRegistry()
    assert restored.active_group == group_a and restored.active_preset == other


def test_filter_rename_rejects_external_extension_of_known_group(
    tmp_path: Path,
) -> None:
    """登録グループへ外部で追加された未知の参照を、改名で取り残さない。"""
    registry, filter_path, preset, _group_a, group_b = _shared_graph(tmp_path)
    group_path = Path(group_b)
    payload: dict[str, object] = json.loads(
        group_path.read_text(encoding="utf-8")
    )
    payload["presets"] = [str(Path(preset).resolve()), "ExternalPreset.json"]
    group_path.write_text(json.dumps(payload), encoding="utf-8")
    external = group_path.read_bytes()
    before = Path(preset).read_bytes()
    draft = CustomFilterDraft(filter_path)
    draft.rename("Pending")
    with pytest.raises(CustomFilterError, match="外部"):
        registry.save(draft)
    assert (
        Path(filter_path).exists() and not (tmp_path / "Pending.json").exists()
    )
    assert Path(preset).read_bytes() == before
    assert group_path.read_bytes() == external
    assert draft.is_dirty


def test_preset_rename_rechecks_known_group_after_staging(
    tmp_path: Path,
) -> None:
    """改名を入力した後の参照元更新も、保存直前に検出する。"""
    registry, _filter_path, preset, _group_a, group_b = _shared_graph(tmp_path)
    registry.rename_preset(preset, "Pending")
    group_path = Path(group_b)
    group_path.write_text(
        '{"schema_version":1,"presets":[]}', encoding="utf-8"
    )
    with pytest.raises(CustomFilterError, match="外部"):
        registry.save()
    assert Path(preset).exists() and not (tmp_path / "Pending.json").exists()
    assert registry.is_dirty


def test_migration_registration_failure_remains_dirty() -> None:
    """移行用JSONを作成しても、個人設定が保存できなければ未保存を維持する。"""

    class FailingRegistry(CustomFilterRegistry):
        """登録一覧の永続化だけを失敗させる。"""

        def _save(self) -> None:
            """共有JSONを変更せず、個人設定の書込エラーを保持する。"""
            self._storage_error = "injected registration failure"

    registry = FailingRegistry()
    assert registry.groups and registry.is_dirty
    assert registry.storage_error == "injected registration failure"
