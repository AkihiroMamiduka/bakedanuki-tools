# coding: utf-8
"""実削除の確認に表示する、対象別の直接参照元と保存予定の一致を検証する。"""

from pathlib import Path

import pytest

from bd_tools.bd_channel_box.custom_filter_files import plan_file_operation
from bd_tools.bd_channel_box.custom_filter_presets import (
    DocumentKind,
    FilterReference,
    commit_file_updates,
    create_preset_document,
    read_preset_document,
)
from bd_tools.bd_channel_box.custom_filters import normalize_filter_path


def _filter(path: Path) -> str:
    """参照先として使用する保存済みフィルターを作り、識別パスを返す。"""
    path.write_text(
        '{"schema_version": 2, "node_types": {}}', encoding="utf-8"
    )
    return normalize_filter_path(path)


def test_filter_preview_lists_direct_parents_in_target_order(
    tmp_path: Path,
) -> None:
    """共有・個別・未参照の対象を区別し、同じ親の保存は一回にまとめる。"""
    first = _filter(tmp_path / "First.json")
    second = _filter(tmp_path / "Second.json")
    unused = _filter(tmp_path / "Unused.json")
    kept = _filter(tmp_path / "Kept.json")
    shared = create_preset_document(
        tmp_path / "Shared.json",
        "preset",
        (
            FilterReference(kept, False),
            FilterReference(first, False),
            FilterReference(second),
        ),
    )
    second_only = create_preset_document(
        tmp_path / "SecondOnly.json",
        "preset",
        (FilterReference(second, False), FilterReference(kept)),
    )
    first_only = create_preset_document(
        tmp_path / "FirstOnly.json",
        "preset",
        (FilterReference(first),),
    )
    unchanged = create_preset_document(
        tmp_path / "Unchanged.json",
        "preset",
        (FilterReference(kept),),
    )
    group = create_preset_document(
        tmp_path / "Group.json",
        "preset_group",
        tuple(
            FilterReference(document.path)
            for document in (shared, second_only, first_only, unchanged)
        ),
    )
    originals = {path: path.read_bytes() for path in tmp_path.glob("*.json")}
    plan = plan_file_operation(
        "filter",
        (second, unused, first, second),
        (group, shared, second_only, first_only, unchanged),
        None,
    )

    # 対象の選択順と、実際に書き換える親の探索順をそれぞれ保持する
    assert plan.paths == (second, unused, first)
    assert plan.reference_sources_by_path == (
        (second, (shared.path, second_only.path)),
        (unused, ()),
        (first, (shared.path, first_only.path)),
    )
    assert plan.reference_sources_for(Path(first)) == (
        shared.path,
        first_only.path,
    )
    assert plan.reference_sources_for(
        f"{tmp_path}/./First.json"
    ) == plan.reference_sources_for(first)
    assert plan.reference_sources_for(tmp_path / "Other.json") == ()
    assert plan.reference_sources == (
        shared.path,
        second_only.path,
        first_only.path,
    )
    assert (
        tuple(
            normalize_filter_path(update.source)
            for update in plan.updates
            if update.source is not None
        )
        == plan.reference_sources
    )
    assert len(plan.updates) == 3
    assert all(
        path.read_bytes() == content for path, content in originals.items()
    )

    # 表示した親だけを書き換え、残した参照の順番とOFF状態を保持する
    commit_file_updates(plan.updates, plan.deletions)
    assert read_preset_document(shared.path, "preset").references == (
        FilterReference(kept, False),
    )
    assert read_preset_document(second_only.path, "preset").references == (
        FilterReference(kept),
    )
    assert read_preset_document(first_only.path, "preset").references == ()
    assert Path(group.path).read_bytes() == originals[Path(group.path)]
    assert Path(unchanged.path).read_bytes() == originals[Path(unchanged.path)]
    assert Path(kept).is_file()
    assert all(not Path(path).exists() for path in plan.paths)


def test_preset_preview_lists_groups_and_leaves_children_out(
    tmp_path: Path,
) -> None:
    """プリセットの削除では共有するグループを表示し、配下の参照先は含めない。"""
    child = _filter(tmp_path / "Child.json")
    first = create_preset_document(
        tmp_path / "First.json", "preset", (FilterReference(child),)
    )
    second = create_preset_document(
        tmp_path / "Second.json", "preset", (FilterReference(child, False),)
    )
    shared = create_preset_document(
        tmp_path / "SharedGroup.json",
        "preset_group",
        (FilterReference(first.path), FilterReference(second.path)),
    )
    first_only = create_preset_document(
        tmp_path / "FirstGroup.json",
        "preset_group",
        (FilterReference(first.path),),
    )
    plan = plan_file_operation(
        "preset",
        (second.path, first.path),
        (shared, first, second, first_only),
        None,
    )
    assert plan.reference_sources_by_path == (
        (second.path, (shared.path,)),
        (first.path, (shared.path, first_only.path)),
    )
    assert plan.reference_sources == (shared.path, first_only.path)
    assert len(plan.updates) == 2
    assert all(document.references == () for document in plan.documents)
    commit_file_updates(plan.updates, plan.deletions)
    assert Path(child).is_file()
    assert read_preset_document(shared.path, "preset_group").references == ()
    assert (
        read_preset_document(first_only.path, "preset_group").references == ()
    )


def test_group_preview_includes_empty_entries_and_preserves_children(
    tmp_path: Path,
) -> None:
    """グループ削除の参照元は0件とし、個人設定や配下のJSONを表示に混ぜない。"""
    child = _filter(tmp_path / "Child.json")
    preset = create_preset_document(
        tmp_path / "Preset.json", "preset", (FilterReference(child),)
    )
    first = create_preset_document(
        tmp_path / "FirstGroup.json",
        "preset_group",
        (FilterReference(preset.path),),
    )
    second = create_preset_document(
        tmp_path / "SecondGroup.json", "preset_group"
    )
    child_bytes = Path(child).read_bytes()
    preset_bytes = Path(preset.path).read_bytes()
    plan = plan_file_operation(
        "preset_group",
        (second.path, first.path),
        (first, preset, second),
        None,
    )
    assert plan.reference_sources_by_path == (
        (second.path, ()),
        (first.path, ()),
    )
    assert plan.reference_sources == ()
    assert plan.updates == ()
    commit_file_updates(plan.updates, plan.deletions)
    assert Path(preset.path).read_bytes() == preset_bytes
    assert Path(child).read_bytes() == child_bytes


@pytest.mark.parametrize("kind", ("preset_group", "preset"))
def test_broken_target_preview_keeps_existing_deletion_behavior(
    tmp_path: Path, kind: DocumentKind
) -> None:
    """削除対象が壊れた文書でも、その親の更新予定と対象の削除を維持する。"""
    target = tmp_path / "Broken.json"
    target.write_bytes(b"broken json")
    broken = read_preset_document(target, kind)
    assert broken.error is not None
    parent = create_preset_document(
        tmp_path / "ParentGroup.json",
        "preset_group",
        (FilterReference(broken.path),) if kind == "preset" else (),
    )
    plan = plan_file_operation(kind, (broken.path,), (parent, broken), None)
    expected = (parent.path,) if kind == "preset" else ()
    assert plan.reference_sources_for(target) == expected
    assert plan.reference_sources_by_path == ((broken.path, expected),)
    assert plan.reference_sources == expected
    assert len(plan.updates) == len(expected)
    commit_file_updates(plan.updates, plan.deletions)
    assert not target.exists()
    assert read_preset_document(parent.path, "preset_group").references == ()


def test_move_plan_has_no_deletion_preview(tmp_path: Path) -> None:
    """移動による参照更新は従来どおり集計し、削除専用の対象別表示には含めない。"""
    target = _filter(tmp_path / "Filter.json")
    parent = create_preset_document(
        tmp_path / "Preset.json", "preset", (FilterReference(target),)
    )
    destination = tmp_path / "Moved"
    destination.mkdir()
    plan = plan_file_operation("filter", (target,), (parent,), destination)
    assert plan.reference_sources == (parent.path,)
    assert plan.reference_sources_by_path == ()
    assert plan.reference_sources_for(target) == ()
    assert len(plan.updates) == 2
    assert plan.deletions == ()
