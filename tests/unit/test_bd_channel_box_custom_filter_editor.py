# coding: utf-8
"""共有フィルターの作成、順序編集、競合検出を検証する。"""

from __future__ import annotations

import importlib.util
import json
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


def test_create_empty_definition_and_refuse_overwrite(tmp_path: Path) -> None:
    """新規作成時は空定義が有効で、既存ファイルを壊さない。"""
    path = tmp_path / "rig.json"
    create_custom_filter(path, "Rig")
    assert load_custom_filter(path).node_types == {}
    source = path.read_bytes()

    with pytest.raises(CustomFilterError, match="既に存在"):
        create_custom_filter(path, "Other")
    assert path.read_bytes() == source


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
