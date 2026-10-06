# coding: utf-8
"""共有カスタムフィルターを安全に作成・編集・保存する。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .custom_filters import (
    CustomFilterDefinition,
    CustomFilterError,
    load_custom_filter,
    normalize_filter_path,
)

__all__ = [
    "CustomFilterConflictError",
    "CustomFilterDraft",
    "create_custom_filter",
]


class CustomFilterConflictError(CustomFilterError):
    """編集中に共有ファイルが外部で変わった場合の例外。"""


def _attribute_key(path: str) -> str:
    """先頭ドットの有無を同じ正式属性pathとして比較する。"""
    return path[1:] if path.startswith(".") else path


def _digest(path: Path) -> str:
    """外部更新の検出に使うファイル内容のハッシュを返す。"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise CustomFilterError(
            f"定義ファイルを読み込めません: {path}（{error}）"
        ) from error


def _serialized(name: str, node_types: dict[str, list[str]]) -> bytes:
    """既存schemaで検証できるUTF-8 JSONを生成する。"""
    payload = {
        "schema_version": 1,
        "name": name,
        "node_types": node_types,
    }
    source = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return source.encode("utf-8")


def _write_temporary(path: Path, content: bytes) -> Path:
    """保存先と同じディレクトリに検証用の一時ファイルを書く。"""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        load_custom_filter(temporary)
        return temporary
    except (OSError, CustomFilterError) as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if isinstance(error, CustomFilterError):
            raise
        raise CustomFilterError(
            f"定義ファイルを保存できません: {path}（{error}）"
        ) from error


def create_custom_filter(path: str | Path, name: str) -> str:
    """空の有効なJSONを新規作成し、既存ファイルを上書きしない。"""
    normalized = normalize_filter_path(path)
    destination = Path(normalized)
    if destination.suffix.lower() != ".json":
        raise CustomFilterError("保存先には.jsonファイルを指定してください。")
    if destination.exists():
        raise CustomFilterError("保存先のファイルは既に存在します。")
    if not destination.parent.is_dir():
        raise CustomFilterError("保存先のフォルダーが存在しません。")
    temporary = _write_temporary(destination, _serialized(name, {}))
    try:
        if destination.exists():
            raise CustomFilterError("保存先のファイルは既に存在します。")
        os.rename(temporary, destination)
    except OSError as error:
        raise CustomFilterError(
            f"定義ファイルを作成できません: {destination}（{error}）"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return normalized


class CustomFilterDraft:
    """一つの共有JSONの名前と全ノード型を保存前に編集する。"""

    def __init__(self, path: str | Path) -> None:
        """現在の共有ファイルを読み、外部更新検出用の基準を保持する。"""
        self.path = normalize_filter_path(path)
        source_digest = _digest(Path(self.path))
        definition = load_custom_filter(self.path)
        if _digest(Path(self.path)) != source_digest:
            raise CustomFilterConflictError(
                "共有ファイルが読込中に変更されました。再読込してください。"
            )
        self._source_digest = source_digest
        self.name = definition.name
        self.node_types = {
            node_type: list(paths)
            for node_type, paths in definition.node_types.items()
        }
        self._explicit_types = set(self.node_types)
        self._saved = self._snapshot()

    def _snapshot(self) -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
        """名前・ノード型・属性順を変更判定用に固定する。"""
        return self.name, tuple(
            (node_type, tuple(paths))
            for node_type, paths in self.node_types.items()
        )

    @property
    def is_dirty(self) -> bool:
        """ファイルへ保存していない定義変更があるか返す。"""
        return self._snapshot() != self._saved

    def definition(self) -> CustomFilterDefinition:
        """作業中の定義をプレビュー用に返す。"""
        return CustomFilterDefinition(
            self.name,
            {
                node_type: tuple(paths)
                for node_type, paths in self.node_types.items()
            },
        )

    def set_name(self, name: str) -> None:
        """表示名を作業中の定義へ設定する。"""
        if not name.strip() or any(ord(char) < 32 for char in name):
            raise CustomFilterError(
                "名前は空でない1行の文字列にしてください。"
            )
        self.name = name.strip()

    def has_node_type(self, node_type: str) -> bool:
        """型がJSONに明示されているか返す。"""
        return node_type in self.node_types

    def paths(self, node_type: str) -> tuple[str, ...]:
        """指定型の属性をJSONの順序で返す。"""
        return tuple(self.node_types.get(node_type, ()))

    def is_included(self, node_type: str, path: str) -> bool:
        """先頭ドットの表記差を吸収して所属を返す。"""
        key = _attribute_key(path)
        return any(
            _attribute_key(item) == key
            for item in self.node_types.get(node_type, ())
        )

    def set_included(self, node_type: str, path: str, included: bool) -> None:
        """指定型の属性を末尾へ追加するか、既存定義から除外する。"""
        if included:
            paths = self.node_types.setdefault(node_type, [])
            if not self.is_included(node_type, path):
                paths.append(_attribute_key(path))
            return
        if node_type not in self.node_types:
            return
        key = _attribute_key(path)
        self.node_types[node_type] = [
            item
            for item in self.node_types[node_type]
            if _attribute_key(item) != key
        ]
        if (
            not self.node_types[node_type]
            and node_type not in self._explicit_types
        ):
            del self.node_types[node_type]

    def ensure_node_type(self, node_type: str) -> None:
        """属性0件の明示定義を追加して代替表示を停止する。"""
        self.node_types.setdefault(node_type, [])
        self._explicit_types.add(node_type)

    def remove_node_type(self, node_type: str) -> None:
        """型の定義を削除し、標準条件への切替に戻す。"""
        self.node_types.pop(node_type, None)
        self._explicit_types.discard(node_type)

    def move(self, node_type: str, path: str, offset: int) -> bool:
        """指定型の既存属性をJSON内で一段上下へ移動する。"""
        if offset not in (-1, 1):
            raise ValueError("移動量には-1または1を指定してください")
        paths = self.node_types.get(node_type)
        if paths is None:
            return False
        index = next(
            (
                index
                for index, item in enumerate(paths)
                if _attribute_key(item) == _attribute_key(path)
            ),
            -1,
        )
        target = index + offset
        if index < 0 or not 0 <= target < len(paths):
            return False
        paths[index], paths[target] = paths[target], paths[index]
        return True

    def save(self) -> None:
        """外部変更を検査し、全型と属性順を原子的に書き替える。"""
        destination = Path(self.path)
        if _digest(destination) != self._source_digest:
            raise CustomFilterConflictError(
                "共有ファイルが外部で変更されました。再読込してから保存してください。"
            )
        content = _serialized(self.name, self.node_types)
        temporary = _write_temporary(destination, content)
        try:
            if _digest(destination) != self._source_digest:
                raise CustomFilterConflictError(
                    "共有ファイルが外部で変更されました。再読込してから保存してください。"
                )
            os.replace(temporary, destination)
        except OSError as error:
            raise CustomFilterError(
                f"定義ファイルを保存できません: {destination}（{error}）"
            ) from error
        finally:
            temporary.unlink(missing_ok=True)
        self._source_digest = hashlib.sha256(content).hexdigest()
        self._explicit_types = set(self.node_types)
        self._saved = self._snapshot()
