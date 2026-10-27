# coding: utf-8
"""共有参照を保つ実ファイル移動・削除と、途中失敗からの復元を検証する。"""

from __future__ import annotations

from pathlib import Path
import stat
from collections.abc import Callable
from typing import cast

import pytest

from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.custom_filter_files import FileKind
from bd_tools.bd_channel_box.custom_filter_presets import (
    FilterReference,
    create_preset_document,
    read_preset_document,
)
from bd_tools.bd_channel_box.custom_filter_registry import CustomFilterRegistry
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterError,
    normalize_filter_path,
)


def create_file_library(
    tmp_path: Path,
) -> tuple[CustomFilterRegistry, dict[str, Path]]:
    """2グループで2プリセットと2フィルターを共有する保存済み構成を作る。"""
    paths = {
        key: tmp_path / f"{key}.json"
        for key in ("g1", "g2", "p1", "p2", "f1", "f2")
    }
    for key in ("f1", "f2"):
        create_custom_filter(paths[key], key)
    references = (
        FilterReference(normalize_filter_path(paths["f1"]), False),
        FilterReference(normalize_filter_path(paths["f2"])),
    )
    for key in ("p1", "p2"):
        create_preset_document(paths[key], "preset", references)
    for key in ("g1", "g2"):
        create_preset_document(
            paths[key],
            "preset_group",
            tuple(
                FilterReference(normalize_filter_path(paths[item]))
                for item in ("p1", "p2")
            ),
        )
    registry = CustomFilterRegistry()
    registry.remove_groups(tuple(item.path for item in registry.groups))
    registry.add_group_paths((paths["g1"], paths["g2"]))
    registry.select_group(str(paths["g1"]))
    registry.select_preset(str(paths["p1"]))
    registry.save()
    return registry, paths


@pytest.mark.parametrize(
    ("kind", "prefix"),
    (("preset_group", "g"), ("preset", "p"), ("filter", "f")),
)
def test_bulk_move_rebases_all_shared_references(
    tmp_path: Path, kind: FileKind, prefix: str
) -> None:
    """複数JSONだけを移動し、全親参照・下位参照・OFF・選択を保存する。"""
    registry, paths = create_file_library(tmp_path)
    before = {key: path.read_bytes() for key, path in paths.items()}
    folder = tmp_path / "Moved"
    folder.mkdir()
    selected = tuple(paths[f"{prefix}{index}"] for index in (1, 2))
    moved = registry.move_files(kind, map(str, selected), folder)
    assert moved == tuple(
        normalize_filter_path(folder / path.name) for path in selected
    )
    for key, path in tuple(paths.items()):
        if path in selected:
            assert not path.exists()
            paths[key] = folder / path.name
        else:
            assert path.exists()
    for key in ("g1", "g2"):
        assert tuple(
            ref.path
            for ref in read_preset_document(
                paths[key], "preset_group"
            ).references
        ) == tuple(normalize_filter_path(paths[item]) for item in ("p1", "p2"))
    for key in ("p1", "p2"):
        assert read_preset_document(paths[key], "preset").references == (
            FilterReference(normalize_filter_path(paths["f1"]), False),
            FilterReference(normalize_filter_path(paths["f2"])),
        )
    assert all(paths[key].read_bytes() == before[key] for key in ("f1", "f2"))
    assert registry.active_group == normalize_filter_path(paths["g1"])
    assert registry.active_preset == normalize_filter_path(paths["p1"])
    restored = CustomFilterRegistry()
    assert restored.active_group == registry.active_group
    assert restored.active_preset == registry.active_preset
    assert not registry.is_dirty
    # 同じ保存先を再指定してもファイルと状態は変化しない
    unchanged = {key: path.read_bytes() for key, path in paths.items()}
    assert registry.move_files(kind, moved, folder) == moved
    assert unchanged == {key: path.read_bytes() for key, path in paths.items()}


@pytest.mark.parametrize(
    ("kind", "prefix"),
    (("preset_group", "g"), ("preset", "p"), ("filter", "f")),
)
@pytest.mark.parametrize("count", (1, 2))
def test_delete_updates_all_parents_and_leaves_child_files(
    tmp_path: Path, kind: FileKind, prefix: str, count: int
) -> None:
    """選択したJSONだけを削除し、共有する全親から参照を除く。"""
    registry, paths = create_file_library(tmp_path)
    selected = tuple(
        paths[f"{prefix}{index}"] for index in range(1, count + 1)
    )
    before = {key: path.read_bytes() for key, path in paths.items()}
    plan = registry.prepare_file_delete(kind, map(str, selected))
    assert len(plan.reference_sources) == (0 if kind == "preset_group" else 2)
    registry.delete_files(plan)
    for key, path in paths.items():
        assert path.exists() == (path not in selected)
        if path not in selected and (
            (kind == "preset_group" and key.startswith(("p", "f")))
            or (kind == "preset" and key.startswith("f"))
        ):
            assert path.read_bytes() == before[key]
    if kind == "filter":
        for key in ("p1", "p2"):
            refs = read_preset_document(paths[key], "preset").references
            assert tuple(ref.path for ref in refs) == tuple(
                normalize_filter_path(paths[f"f{index}"])
                for index in range(count + 1, 3)
            )
    if kind == "preset":
        for key in ("g1", "g2"):
            assert tuple(
                ref.path
                for ref in read_preset_document(
                    paths[key], "preset_group"
                ).references
            ) == tuple(
                normalize_filter_path(paths[f"p{index}"])
                for index in range(count + 1, 3)
            )
    assert not registry.is_dirty


@pytest.mark.parametrize("deleting", (False, True))
@pytest.mark.parametrize("failure", ("unlink", "settings"))
def test_file_operation_rolls_back_files_memory_and_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deleting: bool,
    failure: str,
) -> None:
    """2件目の削除失敗と個人設定保存失敗で、全ファイル・登録・選択を復元する。"""
    registry, paths = create_file_library(tmp_path)
    before = {key: path.read_bytes() for key, path in paths.items()}
    events: list[bool] = []
    registry.changed.connect(lambda: events.append(True))
    folder = tmp_path / "Moved"
    folder.mkdir()
    if failure == "unlink":
        unlink = Path.unlink

        def fail_unlink(path: Path, missing_ok: bool = False) -> None:
            """2件目の元JSONだけに削除エラーを発生させる。"""
            if path == paths["f2"]:
                raise OSError("削除失敗を再現")
            unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", fail_unlink)
    else:
        save = cast(Callable[[], None], getattr(registry, "_save"))

        def fail_save() -> None:
            """個人設定を書いた直後の失敗で復元経路を検査する。"""
            save()
            raise CustomFilterError("個人設定保存の失敗を再現")

        monkeypatch.setattr(registry, "_save", fail_save)
    with pytest.raises(CustomFilterError):
        if deleting:
            registry.delete_files(
                registry.prepare_file_delete(
                    "filter", (str(paths["f1"]), str(paths["f2"]))
                )
            )
        else:
            registry.move_files(
                "filter", (str(paths["f1"]), str(paths["f2"])), folder
            )
    assert before == {key: path.read_bytes() for key, path in paths.items()}
    assert not tuple(folder.iterdir())
    assert not registry.is_dirty and not events
    restored = CustomFilterRegistry()
    assert restored.entries == registry.entries
    assert restored.active_preset == registry.active_preset


def test_collisions_dirty_and_external_changes_abort_before_writing(
    tmp_path: Path,
) -> None:
    """上書き・未保存・確認後の外部変更で、対象と参照元を変えない。"""
    registry, paths = create_file_library(tmp_path)
    folder = tmp_path / "Moved"
    folder.mkdir()
    collision = folder / paths["f1"].name
    collision.write_bytes(b"existing")
    with pytest.raises(CustomFilterError, match="同名"):
        registry.move_files("filter", (str(paths["f1"]),), folder)
    assert collision.read_bytes() == b"existing"
    registry.set_enabled(normalize_filter_path(paths["f1"]), True)
    with pytest.raises(CustomFilterError, match="未保存"):
        registry.prepare_file_delete("filter", (str(paths["f1"]),))
    registry.save()
    plan = registry.prepare_file_delete("filter", (str(paths["f1"]),))
    paths["f1"].write_bytes(b"changed externally")
    with pytest.raises(CustomFilterError, match="確認後"):
        registry.delete_files(plan)
    assert paths["f1"].read_bytes() == b"changed externally"
    paths["p2"].write_bytes(b"changed externally")
    with pytest.raises(CustomFilterError, match="外部"):
        registry.prepare_file_delete("filter", (str(paths["f2"]),))
    assert paths["f2"].exists()


def test_move_after_saved_rename(tmp_path: Path) -> None:
    """直前の保存で改名したファイルも正しい保存基準で移動する。"""
    registry, paths = create_file_library(tmp_path)
    registry.rename_preset(normalize_filter_path(paths["p1"]), "Renamed")
    registry.save()
    folder = tmp_path / "Moved"
    folder.mkdir()
    registry.move_files("preset", (str(tmp_path / "Renamed.json"),), folder)
    assert (folder / "Renamed.json").exists()


@pytest.mark.parametrize("readonly", ("f1", "p2"))
def test_readonly_target_or_reference_aborts_before_deletion(
    tmp_path: Path, readonly: str
) -> None:
    """対象または参照元の読取専用設定を検出し、一件も削除・更新しない。"""
    registry, paths = create_file_library(tmp_path)
    before = {key: path.read_bytes() for key, path in paths.items()}
    paths[readonly].chmod(stat.S_IREAD)
    try:
        with pytest.raises(CustomFilterError, match="読取専用"):
            registry.delete_files(
                registry.prepare_file_delete(
                    "filter", (str(paths["f1"]), str(paths["f2"]))
                )
            )
        assert before == {
            key: path.read_bytes() for key, path in paths.items()
        }
        assert not registry.is_dirty
    finally:
        paths[readonly].chmod(stat.S_IREAD | stat.S_IWRITE)


def test_duplicate_basenames_abort_bulk_move(tmp_path: Path) -> None:
    """異なるフォルダーの同名ファイルをまとめて移動する指定を拒否する。"""
    registry, paths = create_file_library(tmp_path)
    other = tmp_path / "Other"
    other.mkdir()
    duplicate = other / paths["f1"].name
    create_custom_filter(duplicate, "f1")
    registry.add_paths((duplicate,))
    registry.save()
    destination = tmp_path / "Moved"
    destination.mkdir()
    with pytest.raises(CustomFilterError, match="同名"):
        registry.move_files(
            "filter", (str(paths["f1"]), str(duplicate)), destination
        )
    assert paths["f1"].exists() and duplicate.exists()
    assert not tuple(destination.iterdir())


def test_invalid_target_can_be_deleted_but_unknown_parents_block(
    tmp_path: Path,
) -> None:
    """削除対象自身の壊れたJSONは削除でき、別の不明な参照元があれば中止する。"""
    registry, paths = create_file_library(tmp_path)
    paths["p1"].write_bytes(b"{")
    registry.reload_all()
    plan = registry.prepare_file_delete("preset", (str(paths["p1"]),))
    registry.delete_files(plan)
    assert paths["f1"].exists() and not paths["p1"].exists()
    paths["g2"].write_bytes(b"{")
    registry.reload_all()
    with pytest.raises(CustomFilterError, match="参照先"):
        registry.prepare_file_delete("filter", (str(paths["f1"]),))
    assert paths["f1"].exists()
