# coding: utf-8
"""共有フィルターの作成、順序編集、競合検出を検証する。"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest


def _load_module(
    name: str, package_name: str, package_path: Path
) -> ModuleType:
    """Mayaを読み込まずに純粋なファイル操作モジュールを読み込む。"""
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.{name}", package_path / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name}のunit testを読み込めません。")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if TYPE_CHECKING:
    from bd_tools.bd_channel_box.custom_filter_editor import (
        CustomFilterConflictError,
        CustomFilterDraft,
        create_custom_filter,
        duplicate_custom_filter,
        filter_file_name,
    )
    from bd_tools.bd_channel_box.custom_filters import (
        CustomFilterError,
        load_custom_filter,
    )
else:
    _PACKAGE_PATH = (
        Path(__file__).resolve().parents[2]
        / "bakedanuki"
        / "bakedanuki-tools"
        / "python"
        / "bd_tools"
        / "bd_channel_box"
    )
    _PACKAGE_NAME = "_bd_channel_box_editor_unit"
    _PACKAGE = ModuleType(_PACKAGE_NAME)
    _PACKAGE.__path__ = [str(_PACKAGE_PATH)]
    sys.modules[_PACKAGE_NAME] = _PACKAGE

    _FILTERS = _load_module("custom_filters", _PACKAGE_NAME, _PACKAGE_PATH)
    _EDITOR = _load_module(
        "custom_filter_editor", _PACKAGE_NAME, _PACKAGE_PATH
    )
    CustomFilterError = _FILTERS.CustomFilterError
    load_custom_filter = _FILTERS.load_custom_filter
    CustomFilterConflictError = _EDITOR.CustomFilterConflictError
    CustomFilterDraft = _EDITOR.CustomFilterDraft
    create_custom_filter = _EDITOR.create_custom_filter
    duplicate_custom_filter = _EDITOR.duplicate_custom_filter
    filter_file_name = _EDITOR.filter_file_name


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("Rig", "Rig"),
        (" Saved ", "Saved"),
        ("日本語.JSON", "日本語"),
        ("rig.json.json", "rig.json"),
    ),
)
def test_filter_file_name_normalizes_optional_extension(
    value: str, expected: str
) -> None:
    """前後空白と拡張子一つだけを除き、日本語名も維持する。"""
    assert filter_file_name(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "",
        " ",
        ".json",
        ".",
        "..",
        "rig.",
        "rig .json",
        "a/b",
        "a\\b",
        "a:b",
        'a"b',
        "a<b",
        "a>b",
        "a|b",
        "a?b",
        "a*b",
        "a\nb",
        "a\x00b",
        "rig\n",
        "\trig",
        "CON",
        "nul.json",
        "COM1",
        "lPt9",
        "com¹",
        "CON.txt",
        "CONIN$",
    ),
)
def test_filter_file_name_rejects_invalid_windows_names(value: str) -> None:
    """空文字・禁止文字・末尾dot・Windows予約名を拒否する。"""
    with pytest.raises(CustomFilterError):
        filter_file_name(value)


def test_rename_is_draft_until_save_and_commits_file_and_display_name(
    tmp_path: Path,
) -> None:
    """リネームは保存まで元ファイルを変えず、保存時に両方の名前を変更する。"""
    source = tmp_path / "rig.json"
    create_custom_filter(source, "Rig")
    original = source.read_bytes()
    draft = CustomFilterDraft(source)
    original_path = draft.path
    destination = tmp_path / "Renamed.json"
    draft.rename("Renamed.json")
    draft.set_included("joint", "visibility", True)
    assert draft.path == original_path
    assert Path(draft.destination_path).name == "Renamed.json"
    assert draft.name == "Renamed"
    assert draft.is_dirty
    assert source.read_bytes() == original
    assert not destination.exists()
    discarded = CustomFilterDraft(source)
    assert discarded.name == "Rig"
    assert not discarded.is_dirty
    draft.save()
    assert not source.exists()
    assert Path(draft.path) == destination
    assert Path(draft.destination_path).name == "Renamed.json"
    assert load_custom_filter(destination).name == "Renamed"
    assert load_custom_filter(destination).node_types["joint"] == (
        "visibility",
    )
    assert not draft.is_dirty
    draft.set_included("joint", "rigMode", True)
    draft.save()
    assert load_custom_filter(destination).node_types["joint"] == (
        "visibility",
        "rigMode",
    )


def test_rename_rejects_existing_destination_and_retains_current_draft(
    tmp_path: Path,
) -> None:
    """同じフォルダーの別ファイルへは名前を変更せず、下書きも保持する。"""
    source = tmp_path / "rig.json"
    other = tmp_path / "Other.json"
    create_custom_filter(source, "Rig")
    create_custom_filter(other, "Other")
    before = other.read_bytes()
    draft = CustomFilterDraft(source)
    with pytest.raises(CustomFilterError, match="同名ファイルが存在"):
        draft.rename("Other")
    assert draft.name == "Rig"
    assert not draft.is_dirty
    assert other.read_bytes() == before


def test_rename_case_only_updates_filename_and_can_revert_draft(
    tmp_path: Path,
) -> None:
    """Windows上で大小文字だけの改名も下書き取消と保存を正しく扱う。"""
    source = tmp_path / "Rig.json"
    create_custom_filter(source, "Rig")
    draft = CustomFilterDraft(source)
    draft.rename("RIG")
    assert draft.is_dirty
    draft.rename("Rig")
    assert not draft.is_dirty
    draft.rename("RIG")
    draft.save()
    assert [path.name for path in tmp_path.iterdir()] == ["RIG.json"]
    assert load_custom_filter(draft.path).name == "RIG"
    assert not draft.is_dirty


def test_create_empty_definition_and_refuse_overwrite(tmp_path: Path) -> None:
    """新規作成時は空定義が有効で、既存ファイルを壊さない。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    assert load_custom_filter(path).node_types == {}
    source = path.read_bytes()

    with pytest.raises(CustomFilterError, match="既に存在"):
        create_custom_filter(path, "Other")
    assert path.read_bytes() == source


def test_duplicate_preserves_all_types_order_empty_definitions_and_source(
    tmp_path: Path,
) -> None:
    """複製が全型・属性順・空定義を引き継ぎ、元JSONを変更しない。"""
    source = tmp_path / "rig.json"
    create_custom_filter(source, "Rig")
    draft = CustomFilterDraft(source)
    draft.set_many_included("joint", (".visibility", "rigMode"), True)
    draft.ensure_node_type("network")
    draft.set_many_included("transform", ("rotateOrder", "visibility"), True)
    draft.save()
    before = source.read_bytes()
    copy = tmp_path / "rig-copy.json"

    duplicate_custom_filter(source, copy, "Rig_copy")

    definition = load_custom_filter(copy)
    assert definition.name == "Rig_copy"
    assert tuple(definition.node_types) == ("joint", "network", "transform")
    assert definition.node_types == load_custom_filter(source).node_types
    assert source.read_bytes() == before
    copied = copy.read_bytes()
    with pytest.raises(CustomFilterError, match="既に存在"):
        duplicate_custom_filter(source, copy, "Other")
    with pytest.raises(CustomFilterError, match="既に存在"):
        duplicate_custom_filter(source, source, "Other")
    assert copy.read_bytes() == copied
    assert source.read_bytes() == before


def test_duplicate_rejects_unreadable_source_without_creating_destination(
    tmp_path: Path,
) -> None:
    """複製元が読込不能なときは不完全な複製ファイルを作成しない。"""
    source = tmp_path / "invalid.json"
    source.write_text("{}", encoding="utf-8")
    destination = tmp_path / "copy.json"
    with pytest.raises(CustomFilterError):
        duplicate_custom_filter(source, destination, "Copy")
    assert not destination.exists()


def test_draft_preserves_other_types_and_json_order(tmp_path: Path) -> None:
    """編集対象外の型を保ち、追加と移動をJSON順に保存する。"""
    path = tmp_path / "rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {
                    "joint": ["jointOrient.jointOrientY", "visibility"],
                    "transform": ["translate.translateX"],
                },
            }
        ),
        encoding="utf-8",
    )
    draft = CustomFilterDraft(path)
    draft.set_included("joint", "rigMode", True)
    assert draft.move("joint", "rigMode", -1)
    draft.set_included("joint", "visibility", False)
    draft.save()

    definition = load_custom_filter(path)
    assert definition.node_types["joint"] == (
        "jointOrient.jointOrientY",
        "rigMode",
    )
    assert definition.node_types["transform"] == ("translate.translateX",)
    assert not draft.is_dirty


def test_move_many_keeps_selected_order_and_stops_at_edges(
    tmp_path: Path,
) -> None:
    """連続・非連続選択を一段動かし、端を含む操作は全件止める。"""
    path = tmp_path / "rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {
                    "joint": ["a", "b", "c", "d", "e"],
                    "transform": ["other"],
                },
            }
        ),
        encoding="utf-8",
    )
    draft = CustomFilterDraft(path)
    assert not draft.move_many("joint", ("a", "c"), -1)
    assert not draft.move_many("joint", ("b", "e"), 1)
    assert not draft.move_many("joint", ("missing",), -1)
    assert draft.paths("joint") == ("a", "b", "c", "d", "e")
    assert not draft.is_dirty

    assert draft.move_many("joint", (".d", "b", "b"), -1)
    assert draft.paths("joint") == ("b", "a", "d", "c", "e")
    assert draft.move_many("joint", ("b", "d"), 1)
    assert draft.paths("joint") == ("a", "b", "c", "d", "e")
    assert draft.move_many("joint", ("b", "c"), -1)
    assert draft.paths("joint") == ("b", "c", "a", "d", "e")
    assert draft.move_many("joint", ("b", "c"), 1)
    assert draft.paths("joint") == ("a", "b", "c", "d", "e")
    assert not draft.is_dirty

    assert draft.move_many("joint", ("a", "c"), 1)
    draft.save()
    assert load_custom_filter(path).node_types["joint"] == (
        "b",
        "a",
        "d",
        "c",
        "e",
    )
    assert load_custom_filter(path).node_types["transform"] == ("other",)


def test_remove_many_keeps_explicit_empty_and_restores_new_type(
    tmp_path: Path,
) -> None:
    """一括除外は明示型の空配列と未確定型の取消を区別する。"""
    path = tmp_path / "rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {
                    "joint": [".visibility", "rigMode"],
                    "transform": ["other"],
                },
            }
        ),
        encoding="utf-8",
    )
    draft = CustomFilterDraft(path)
    draft.remove_many("joint", ("visibility", "rigMode", "missing"))
    assert draft.has_node_type("joint")
    assert draft.paths("joint") == ()
    assert draft.paths("transform") == ("other",)
    draft.save()
    assert load_custom_filter(path).node_types["joint"] == ()

    fresh = tmp_path / "fresh.json"
    create_custom_filter(fresh, "Fresh")
    uncommitted = CustomFilterDraft(fresh)
    uncommitted.set_included("joint", "rigMode", True)
    uncommitted.remove_many("joint", ("rigMode",))
    assert not uncommitted.has_node_type("joint")
    assert not uncommitted.is_dirty


def test_empty_type_differs_from_missing_type(tmp_path: Path) -> None:
    """明示した空配列と型未定義を往復保存できる。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    draft = CustomFilterDraft(path)
    draft.ensure_node_type("joint")
    draft.save()
    assert load_custom_filter(path).node_types["joint"] == ()
    draft.remove_node_type("joint")
    draft.save()
    assert "joint" not in load_custom_filter(path).node_types


def test_reverting_first_inclusion_restores_undefined_type(
    tmp_path: Path,
) -> None:
    """未定義型での一時的な追加を戻すとfallback状態も元に戻る。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    draft = CustomFilterDraft(path)
    draft.set_included("joint", "visibility", True)
    draft.set_included("joint", "visibility", False)
    assert not draft.has_node_type("joint")
    assert not draft.is_dirty


def test_batch_include_preserves_order_other_types_and_missing_paths(
    tmp_path: Path,
) -> None:
    """一括追加は既存順を保持し、重複候補を入力順で一度だけ追加する。"""
    path = tmp_path / "rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {
                    "joint": [".visibility", "oldRigSetting"],
                    "transform": ["translate.translateX"],
                },
            }
        ),
        encoding="utf-8",
    )
    draft = CustomFilterDraft(path)
    draft.set_many_included(
        "joint",
        (
            "rigMode",
            ".visibility",
            ".rigMode",
            "translate.translateY",
            "translate.translateY",
        ),
        True,
    )
    draft.save()

    definition = load_custom_filter(path)
    assert definition.node_types["joint"] == (
        ".visibility",
        "oldRigSetting",
        "rigMode",
        "translate.translateY",
    )
    assert definition.node_types["transform"] == ("translate.translateX",)
    assert not draft.is_dirty


def test_batch_exclude_keeps_missing_paths_and_explicit_empty_type(
    tmp_path: Path,
) -> None:
    """一括除外は候補外を保ち、全件除外なら空配列を明示する。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    draft = CustomFilterDraft(path)
    draft.set_many_included(
        "joint", (".visibility", "rigMode", "oldRigSetting"), True
    )
    draft.set_many_included(
        "joint", ("visibility", ".rigMode", ".rigMode"), False
    )
    assert draft.paths("joint") == ("oldRigSetting",)
    draft.set_many_included("joint", ("oldRigSetting",), False)
    assert draft.has_node_type("joint")
    assert draft.paths("joint") == ()
    draft.set_included("joint", "visibility", False)
    assert draft.has_node_type("joint")
    draft.save()
    assert load_custom_filter(path).node_types["joint"] == ()

    draft.remove_node_type("joint")
    draft.save()
    assert "joint" not in load_custom_filter(path).node_types


def test_batch_exclude_undefined_type_creates_empty_definition(
    tmp_path: Path,
) -> None:
    """未定義型を一括除外すると標準条件へ戻さず空配列を作る。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    draft = CustomFilterDraft(path)
    draft.set_many_included("joint", ("visibility",), False)
    assert draft.has_node_type("joint")
    assert draft.paths("joint") == ()
    draft.save()
    assert load_custom_filter(path).node_types["joint"] == ()


def test_batch_empty_input_does_not_define_type(tmp_path: Path) -> None:
    """候補が空なら一括操作でノード型定義を増やさない。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    draft = CustomFilterDraft(path)
    draft.set_many_included("joint", iter(()), True)
    draft.set_many_included("joint", iter(()), False)
    assert not draft.has_node_type("joint")
    assert not draft.is_dirty


def test_external_change_blocks_save(tmp_path: Path) -> None:
    """読込後に別の利用者が書き換えた内容を上書きしない。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    draft = CustomFilterDraft(path)
    draft.set_included("joint", "visibility", True)
    path.write_text(
        json.dumps({"schema_version": 1, "name": "Other", "node_types": {}}),
        encoding="utf-8",
    )

    with pytest.raises(CustomFilterConflictError, match="外部で変更"):
        draft.save()
    assert load_custom_filter(path).name == "Other"


def test_rename_save_rechecks_destination_created_after_dialog(
    tmp_path: Path,
) -> None:
    """改名入力後に作られた同名ファイルも保存時に上書きしない。"""
    source = tmp_path / "rig.json"
    destination = tmp_path / "Other.json"
    create_custom_filter(source, "Rig")
    original = source.read_bytes()
    draft = CustomFilterDraft(source)
    draft.rename("Other")
    create_custom_filter(destination, "Other")
    occupied = destination.read_bytes()
    with pytest.raises(CustomFilterError, match="同名ファイルが存在"):
        draft.save()
    assert source.read_bytes() == original
    assert destination.read_bytes() == occupied
    assert draft.is_dirty


def test_rename_save_does_not_overwrite_racing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """最終検査直後の競合でもWindowsの無上書き移動で両ファイルを守る。"""
    source = tmp_path / "rig.json"
    destination = tmp_path / "Other.json"
    create_custom_filter(source, "Rig")
    original = source.read_bytes()
    draft = CustomFilterDraft(source)
    draft.rename("Other")
    original_rename = os.rename

    def occupy_destination(temporary: Path, target: Path) -> None:
        """移動直前に別の利用者が宛先を確保した状態を再現する。"""
        target.write_bytes(b"occupied")
        original_rename(temporary, target)

    monkeypatch.setattr(os, "rename", occupy_destination)
    with pytest.raises(CustomFilterError, match="同名ファイルが存在"):
        draft.save()
    assert source.read_bytes() == original
    assert destination.read_bytes() == b"occupied"
    assert len(tuple(tmp_path.iterdir())) == 2
    assert draft.is_dirty


def test_rename_retracts_destination_if_source_cannot_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """元ファイルの削除に失敗したら新宛先を撤回して元データを残す。"""
    source = tmp_path / "rig.json"
    destination = tmp_path / "Other.json"
    create_custom_filter(source, "Rig")
    original = source.read_bytes()
    draft = CustomFilterDraft(source)
    original_path = draft.path
    draft.rename("Other")
    original_unlink = Path.unlink

    def block_source_unlink(path: Path, missing_ok: bool = False) -> None:
        """元JSONだけ削除できない状態を再現する。"""
        if path == source:
            raise PermissionError("source is locked")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", block_source_unlink)
    with pytest.raises(CustomFilterError, match="保存できません"):
        draft.save()
    assert source.read_bytes() == original
    assert not destination.exists()
    assert draft.path == original_path
    assert draft.is_dirty
    assert len(tuple(tmp_path.iterdir())) == 1


def test_rename_external_source_change_retracts_new_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新宛先確保中に元JSONが更新された場合も、元の変更を消さない。"""
    source = tmp_path / "rig.json"
    destination = tmp_path / "Other.json"
    create_custom_filter(source, "Rig")
    draft = CustomFilterDraft(source)
    draft.rename("Other")
    original_rename = os.rename

    def edit_source_after_move(temporary: Path, target: Path) -> None:
        """新宛先作成と元ファイル削除の間に外部更新を差し込む。"""
        original_rename(temporary, target)
        source.write_bytes(b"external update")

    monkeypatch.setattr(os, "rename", edit_source_after_move)
    with pytest.raises(CustomFilterConflictError, match="外部で変更"):
        draft.save()
    assert source.read_bytes() == b"external update"
    assert not destination.exists()
    assert draft.is_dirty
    assert len(tuple(tmp_path.iterdir())) == 1


def test_rename_external_destination_change_preserves_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新宛先確保中の外部更新を検出し、元JSONと変更後の新宛先を残す。"""
    source = tmp_path / "rig.json"
    destination = tmp_path / "Other.json"
    create_custom_filter(source, "Rig")
    before = source.read_bytes()
    draft = CustomFilterDraft(source)
    draft.rename("Other")
    original_rename = os.rename

    def edit_destination_after_move(temporary: Path, target: Path) -> None:
        """新宛先確保と元ファイル削除の間に宛先の外部更新を再現する。"""
        original_rename(temporary, target)
        target.write_bytes(b"external destination update")

    monkeypatch.setattr(os, "rename", edit_destination_after_move)
    with pytest.raises(CustomFilterConflictError, match="移動先.*外部で変更"):
        draft.save()
    assert source.read_bytes() == before
    assert destination.read_bytes() == b"external destination update"
    assert draft.is_dirty
