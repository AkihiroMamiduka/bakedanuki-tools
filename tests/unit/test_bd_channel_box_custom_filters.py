# coding: utf-8
"""共有可能なbdChannelBox属性フィルター定義の純粋な読込みを検証する。"""

from __future__ import annotations

import json
import importlib.util
import os
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from bd_tools.bd_channel_box.custom_filters import (
        CustomFilterError,
        CustomFilterSelection,
        load_custom_filter,
        normalize_filter_path,
    )
else:
    _ROOT = Path(__file__).resolve().parents[2]
    _SOURCE = (
        _ROOT
        / "bakedanuki"
        / "bakedanuki-tools"
        / "python"
        / "bd_tools"
        / "bd_channel_box"
        / "custom_filters.py"
    )
    _SPEC = importlib.util.spec_from_file_location(
        "_bd_channel_box_custom_filters_unit", _SOURCE
    )
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError("属性フィルター定義のunit testを読み込めません。")
    _MODULE: ModuleType = importlib.util.module_from_spec(_SPEC)
    sys.modules[_SPEC.name] = _MODULE
    _SPEC.loader.exec_module(_MODULE)
    CustomFilterError = _MODULE.CustomFilterError
    CustomFilterSelection = _MODULE.CustomFilterSelection
    load_custom_filter = _MODULE.load_custom_filter
    normalize_filter_path = _MODULE.normalize_filter_path


def _write_json(path: Path, value: object) -> Path:
    """UTF-8の定義ファイルをテスト用pathへ保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_valid_definition_keeps_order_and_first_duplicate(
    tmp_path: Path,
) -> None:
    """ノード型と属性pathの記載順を維持し、重複pathは最初だけ採用する。"""
    path = _write_json(
        tmp_path / "リグ.json",
        {
            "schema_version": 1,
            "name": "  リグ  ",
            "node_types": {
                "joint": [
                    "jointOrient.jointOrientY",
                    ".specialValue",
                    "jointOrient.jointOrientY",
                    "visibility",
                ],
                "transform": ["translate.translateX", "visibility"],
            },
        },
    )

    definition = load_custom_filter(path)

    assert definition.name == "リグ"
    assert tuple(definition.node_types) == ("joint", "transform")
    assert definition.node_types["joint"] == (
        "jointOrient.jointOrientY",
        ".specialValue",
        "visibility",
    )
    assert definition.node_types["transform"] == (
        "translate.translateX",
        "visibility",
    )
    selection = CustomFilterSelection(
        path=normalize_filter_path(path), definition=definition
    )
    assert selection.path == os.path.normcase(str(path.resolve()))
    with pytest.raises(FrozenInstanceError):
        setattr(selection, "path", "other.json")


@pytest.mark.parametrize(
    ("value", "message"),
    (
        ([], "最上位"),
        ({"name": "Rig", "node_types": {"joint": ["visibility"]}}, "不足"),
        (
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {"joint": ["visibility"]},
                "unknown": True,
            },
            "未対応",
        ),
        (
            {"schema_version": True, "name": "Rig", "node_types": {}},
            "schema_version",
        ),
        (
            {"schema_version": 1, "name": "  ", "node_types": {}},
            "name",
        ),
        (
            {"schema_version": 1, "name": "Rig", "node_types": []},
            "node_types",
        ),
        (
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {"joint type": ["visibility"]},
            },
            "ノード型名",
        ),
        (
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {"joint": "visibility"},
            },
            "配列",
        ),
        (
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {"joint": [".translate."]},
            },
            "相対path",
        ),
        (
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {"joint": ["weights[0]"]},
            },
            "相対path",
        ),
    ),
)
def test_invalid_schema_is_rejected(
    tmp_path: Path, value: object, message: str
) -> None:
    """不正な型・必須項目・属性pathを日本語の理由付きで拒否する。"""
    path = _write_json(tmp_path / "invalid.json", value)

    with pytest.raises(CustomFilterError, match=message):
        load_custom_filter(path)


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    """JSONオブジェクト内の重複キーを黙って上書きしない。"""
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":1,"name":"Rig","name":"Other",'
        '"node_types":{"joint":["visibility"]}}',
        encoding="utf-8",
    )

    with pytest.raises(CustomFilterError, match="キーが重複"):
        load_custom_filter(path)


def test_invalid_json_encoding_and_missing_file(tmp_path: Path) -> None:
    """読めないファイルと壊れたJSONを区別できる例外で通知する。"""
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(CustomFilterError, match="構文"):
        load_custom_filter(broken)

    invalid_encoding = tmp_path / "encoding.json"
    invalid_encoding.write_bytes(b"\xff")
    with pytest.raises(CustomFilterError, match="読み込めません"):
        load_custom_filter(invalid_encoding)

    with pytest.raises(CustomFilterError, match="読み込めません"):
        load_custom_filter(tmp_path / "missing.json")


def test_normalize_filter_path_resolves_relative_segments(
    tmp_path: Path,
) -> None:
    """相対区間を含むpathを正規化済み絶対pathへ変換する。"""
    source = tmp_path / "nested" / ".." / "rig.json"
    assert normalize_filter_path(source) == os.path.normcase(
        str((tmp_path / "rig.json").resolve())
    )
    with pytest.raises(CustomFilterError, match="パスが空"):
        normalize_filter_path("  ")
