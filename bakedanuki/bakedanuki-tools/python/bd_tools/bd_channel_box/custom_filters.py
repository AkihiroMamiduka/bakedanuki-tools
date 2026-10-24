# coding: utf-8
"""bdChannelBoxで共有する属性フィルター定義を読み込む。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

__all__ = [
    "CustomFilterDefinition",
    "CustomFilterError",
    "CustomFilterSelection",
    "filter_display_name",
    "load_custom_filter",
    "normalize_filter_path",
    "serialize_custom_filter",
]

_SCHEMA_KEYS = {
    1: frozenset(("schema_version", "name", "node_types")),
    2: frozenset(("schema_version", "node_types")),
}
_INVALID_PATH_CHARACTERS = frozenset("[]*?")


class CustomFilterError(ValueError):
    """フィルター定義の読込みまたは形式が無効な場合の例外。"""


@dataclass(frozen=True)
class CustomFilterDefinition:
    """実ファイル名から導いた表示名とノード型別の正式属性path。"""

    name: str
    node_types: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class CustomFilterSelection:
    """正規化済みの定義ファイルpathと、その読み込み結果。"""

    path: str
    definition: CustomFilterDefinition


def normalize_filter_path(path: str | Path) -> str:
    """定義ファイルのpathを絶対pathへ正規化する。"""
    if not str(path).strip():
        raise CustomFilterError("定義ファイルのパスが空です。")
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise CustomFilterError(
            f"定義ファイルのパスを解決できません: {path}"
        ) from exc
    return os.path.normcase(str(resolved))


def filter_display_name(path: str | Path) -> str:
    """実ファイル名の大文字小文字を保ち、拡張子を除いた表示名を返す。"""
    if not str(path).strip():
        raise CustomFilterError("定義ファイルのパスが空です。")
    try:
        return Path(path).expanduser().resolve().stem
    except (OSError, RuntimeError, ValueError) as exc:
        raise CustomFilterError(
            f"定義ファイルの名前を取得できません: {path}"
        ) from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSONオブジェクトの重複キーを拒否して記載順を保つ。"""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CustomFilterError(f"JSONのキーが重複しています: {key}")
        result[key] = value
    return result


def _valid_node_type(value: str) -> bool:
    """ノード型名の空文字と空白・制御文字だけを拒否する。"""
    return bool(value) and all(
        not char.isspace() and ord(char) >= 32 for char in value
    )


def _valid_attribute_path(value: str) -> bool:
    """正式相対pathの区切りと配列・検索記法を検証する。"""
    if not value or any(
        char.isspace() or ord(char) < 32 or char in _INVALID_PATH_CHARACTERS
        for char in value
    ):
        return False
    relative = value[1:] if value.startswith(".") else value
    return all(bool(segment) for segment in relative.split("."))


def _parse_definition(raw: object, name: str) -> CustomFilterDefinition:
    """対応schemaの型と属性pathを検証し、実ファイル由来の名前を付ける。"""
    if not isinstance(raw, dict):
        raise CustomFilterError("JSONの最上位はオブジェクトにしてください。")
    data = cast(dict[str, object], raw)
    if "schema_version" not in data:
        raise CustomFilterError(
            "JSONの項目が正しくありません（不足: schema_version）。"
        )
    version = data["schema_version"]
    if type(version) is not int or version not in _SCHEMA_KEYS:
        raise CustomFilterError(
            "schema_versionは整数の1または2にしてください。"
        )
    keys = _SCHEMA_KEYS[version]
    if data.keys() != keys:
        missing = keys - data.keys()
        extra = data.keys() - keys
        details: list[str] = []
        if missing:
            details.append("不足: " + ", ".join(sorted(missing)))
        if extra:
            details.append("未対応: " + ", ".join(sorted(extra)))
        raise CustomFilterError(
            "JSONの項目が正しくありません（" + "／".join(details) + "）。"
        )

    # 旧形式は検証だけを続け、表示名には保存先の実ファイル名を使う
    if version == 1:
        raw_name = data["name"]
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise CustomFilterError("nameは空でない文字列にしてください。")
        if any(ord(char) < 32 for char in raw_name.strip()):
            raise CustomFilterError("nameに改行や制御文字は使用できません。")

    raw_node_types = data["node_types"]
    if not isinstance(raw_node_types, dict):
        raise CustomFilterError("node_typesはオブジェクトにしてください。")
    node_types = cast(dict[str, object], raw_node_types)
    parsed: dict[str, tuple[str, ...]] = {}

    # JSONのノード型と属性pathの記載順を維持し、同じpathは最初の指定だけ採用する
    for node_type, raw_paths in node_types.items():
        if not _valid_node_type(node_type):
            raise CustomFilterError(
                f"ノード型名が正しくありません: {node_type}"
            )
        if not isinstance(raw_paths, list):
            raise CustomFilterError(
                f"{node_type}の属性pathは配列にしてください。"
            )
        paths = cast(list[object], raw_paths)
        unique: list[str] = []
        seen: set[str] = set()
        for index, attribute_path in enumerate(paths, start=1):
            if not isinstance(
                attribute_path, str
            ) or not _valid_attribute_path(attribute_path):
                raise CustomFilterError(
                    f"{node_type}の{index}番目の属性pathが正しくありません。"
                    "正式な相対pathを指定してください。"
                )
            if attribute_path not in seen:
                unique.append(attribute_path)
                seen.add(attribute_path)
        parsed[node_type] = tuple(unique)

    return CustomFilterDefinition(name=name, node_types=parsed)


def serialize_custom_filter(definition: CustomFilterDefinition) -> bytes:
    """表示名を重複保存せず、検証済みのschema version 2をUTF-8で返す。"""
    payload: dict[str, object] = {
        "schema_version": 2,
        "node_types": {
            node_type: list(paths)
            for node_type, paths in definition.node_types.items()
        },
    }
    _parse_definition(payload, definition.name)
    source = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return source.encode("utf-8")


def load_custom_filter(path: str | Path) -> CustomFilterDefinition:
    """UTF-8のJSON定義ファイルを読み、形式を検証する。"""
    normalized_path = normalize_filter_path(path)
    try:
        source = Path(normalized_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError, ValueError) as exc:
        raise CustomFilterError(
            f"定義ファイルを読み込めません: {normalized_path}（{exc}）"
        ) from exc
    try:
        raw: object = json.loads(source, object_pairs_hook=_unique_object)
        return _parse_definition(raw, filter_display_name(path))
    except json.JSONDecodeError as exc:
        raise CustomFilterError(
            f"JSONの構文が正しくありません: {normalized_path} "
            f"（{exc.lineno}行{exc.colno}列）"
        ) from exc
    except CustomFilterError as exc:
        raise CustomFilterError(
            f"定義ファイルの形式が正しくありません: {normalized_path}（{exc}）"
        ) from exc
