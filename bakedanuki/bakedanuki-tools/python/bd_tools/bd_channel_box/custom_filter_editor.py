# coding: utf-8
"""共有カスタムフィルターを安全に作成・編集・保存する。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .custom_filters import (
    CustomFilterDefinition,
    CustomFilterError,
    filter_display_name,
    load_custom_filter,
    normalize_filter_path,
    serialize_custom_filter,
)

__all__ = [
    "CustomFilterConflictError",
    "CustomFilterDraft",
    "create_custom_filter",
    "duplicate_custom_filter",
    "filter_file_name",
]

_INVALID_FILE_CHARACTERS = frozenset('<>:"/\\|?*')
_RESERVED_FILE_NAMES = frozenset(
    ("con", "prn", "aux", "nul", "conin$", "conout$")
) | frozenset(
    f"{prefix}{suffix}"
    for prefix in ("com", "lpt")
    for suffix in "123456789¹²³"
)


class CustomFilterConflictError(CustomFilterError):
    """編集中に共有ファイルが外部で変わった場合の例外。"""


def filter_file_name(name: str) -> str:
    """前後の空白とJSON拡張子を除き、Windowsのファイル名を検証する。"""
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name):
        raise CustomFilterError("ファイル名に制御文字は使用できません。")
    base_name = name.strip()
    if base_name.lower().endswith(".json"):
        base_name = base_name[:-5]
    if not base_name:
        raise CustomFilterError("ファイル名を入力してください。")
    if base_name.endswith((".", " ")):
        raise CustomFilterError(
            "ファイル名の末尾にピリオドや空白は使えません。"
        )
    if any(
        char in _INVALID_FILE_CHARACTERS
        or ord(char) < 32
        or 127 <= ord(char) <= 159
        for char in base_name
    ):
        raise CustomFilterError(
            "ファイル名に使用できない文字が含まれています。"
        )
    if (
        base_name.split(".", 1)[0].rstrip(" ").casefold()
        in _RESERVED_FILE_NAMES
    ):
        raise CustomFilterError("Windowsの予約名はファイル名に使えません。")
    return base_name


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


def create_custom_filter(path: str | Path, name: str | None = None) -> str:
    """実ファイル名を名前として空のJSONを作り、旧name引数は保存しない。"""
    return _create_definition(path, {})


def duplicate_custom_filter(
    source: str | Path, path: str | Path, name: str | None = None
) -> str:
    """元JSONを読み直し、全ノード型と属性順を別ファイルへ複製する。"""
    draft = CustomFilterDraft(source)
    return _create_definition(path, draft.node_types)


def _create_definition(
    path: str | Path, node_types: dict[str, list[str]]
) -> str:
    """検証済みの定義を新しいJSONとして保存し、既存ファイルを保護する。"""
    normalized = normalize_filter_path(path)
    destination = Path(path).expanduser().resolve()
    if destination.suffix.lower() != ".json":
        raise CustomFilterError("保存先には.jsonファイルを指定してください。")
    if destination.exists():
        raise CustomFilterError("保存先のファイルは既に存在します。")
    if not destination.parent.is_dir():
        raise CustomFilterError("保存先のフォルダーが存在しません。")
    content = serialize_custom_filter(
        CustomFilterDefinition(
            filter_display_name(destination),
            {
                node_type: tuple(paths)
                for node_type, paths in node_types.items()
            },
        )
    )
    temporary = _write_temporary(destination, content)
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
        self._destination_path = str(Path(path).expanduser().resolve())
        source_digest = _digest(Path(self.path))
        definition = load_custom_filter(self.path)
        if _digest(Path(self.path)) != source_digest:
            raise CustomFilterConflictError(
                "共有ファイルが読込中に変更されました。再読込してください。"
            )
        self._source_digest = source_digest
        self.node_types = {
            node_type: list(paths)
            for node_type, paths in definition.node_types.items()
        }
        self._explicit_types = set(self.node_types)
        self._saved = self._snapshot()

    def _snapshot(
        self,
    ) -> tuple[str, str, tuple[tuple[str, tuple[str, ...]], ...]]:
        """名前・保存先・ノード型・属性順を変更判定用に固定する。"""
        return (
            self.name,
            self.destination_path,
            tuple(
                (node_type, tuple(paths))
                for node_type, paths in self.node_types.items()
            ),
        )

    @property
    def destination_path(self) -> str:
        """保存時の移動先を、入力した大文字小文字を保持して返す。"""
        return self._destination_path

    @property
    def name(self) -> str:
        """保存予定の実ファイル名から、大文字小文字を保持して名前を返す。"""
        return Path(self._destination_path).stem

    @property
    def source_digest(self) -> str:
        """全体保存が外部更新を検出するための読込時ハッシュを返す。"""
        return self._source_digest

    @property
    def source_path(self) -> str:
        """保存失敗時も元の大小文字で復元できる、保存済み実ファイル名を返す。"""
        return self._saved[1]

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
        """互換入口として、名前と実ファイル名を同時に改名する。"""
        self.rename(name)

    def rename(self, name: str) -> None:
        """表示名と同じフォルダー内の移動先を下書きだけに設定する。"""
        base_name = filter_file_name(name)
        destination = Path(self.destination_path).with_name(
            f"{base_name}.json"
        )
        self._check_destination(destination)
        self._destination_path = str(destination)

    def _check_destination(self, destination: Path) -> None:
        """現在のファイル自身以外の既存保存先を拒否する。"""
        same_path = os.path.normcase(str(destination)) == self.path
        if not same_path and os.path.lexists(destination):
            raise CustomFilterError("同名ファイルが存在します。")

    def _check_source(self) -> None:
        """読込時と異なる内容の共有ファイルを保護する。"""
        if _digest(Path(self.path)) != self._source_digest:
            raise CustomFilterConflictError(
                "共有ファイルが外部で変更されました。再読込してから保存してください。"
            )

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
        self.remove_many(node_type, (path,))

    def remove_many(self, node_type: str, paths: Iterable[str]) -> None:
        """指定型の属性をまとめて除外し、未確定の型は元へ戻す。"""
        if node_type not in self.node_types:
            return
        keys = {_attribute_key(path) for path in paths}
        if not keys:
            return
        self.node_types[node_type] = [
            item
            for item in self.node_types[node_type]
            if _attribute_key(item) not in keys
        ]
        if (
            not self.node_types[node_type]
            and node_type not in self._explicit_types
        ):
            del self.node_types[node_type]

    def set_many_included(
        self, node_type: str, paths: Iterable[str], included: bool
    ) -> None:
        """候補の属性を一括変更し、既存順と候補外の定義を維持する。"""
        # 入力順を保ちながら先頭ドットの表記差をまとめる
        unique_paths = tuple(
            dict.fromkeys(_attribute_key(path) for path in paths)
        )
        if not unique_paths:
            return

        if included:
            current = self.node_types.setdefault(node_type, [])
            existing = {_attribute_key(path) for path in current}
            for path in unique_paths:
                if path not in existing:
                    current.append(path)
                    existing.add(path)
            return

        # 除外後に0件となる型も明示定義として残し、代替表示を停止する
        excluded = set(unique_paths)
        current = self.node_types.get(node_type, [])
        remaining = [
            path for path in current if _attribute_key(path) not in excluded
        ]
        self.node_types[node_type] = remaining
        if not remaining:
            self._explicit_types.add(node_type)

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
        return self.move_many(node_type, (path,), offset)

    def move_many(
        self, node_type: str, selected_paths: Iterable[str], offset: int
    ) -> bool:
        """選択属性の相対順を保ち、全件を同時に一段移動する。"""
        if offset not in (-1, 1):
            raise ValueError("移動量には-1または1を指定してください")
        paths = self.node_types.get(node_type)
        if paths is None:
            return False
        keys = {_attribute_key(path) for path in selected_paths}
        indices = tuple(
            index
            for index, path in enumerate(paths)
            if _attribute_key(path) in keys
        )
        if not indices or not 0 <= indices[
            0 if offset < 0 else -1
        ] + offset < len(paths):
            return False

        # 上方向は前から、下方向は後ろから入れ替えて選択間の順序を保つ
        for index in indices if offset < 0 else reversed(indices):
            target = index + offset
            paths[index], paths[target] = paths[target], paths[index]
        return True

    def save(self) -> None:
        """外部変更と移動先の衝突を検査し、名前・全型・属性順を保存する。"""
        source = Path(self.source_path)
        destination = Path(self.destination_path)
        self.validate_save()
        content = self.prepared_content()
        temporary = _write_temporary(destination, content)
        try:
            self._check_source()
            self._check_destination(destination)
            if os.path.normcase(str(destination)) == self.path:
                # 同じファイルへの保存は大小文字だけの変更も一度の置換で確定する
                os.replace(temporary, destination)
            else:
                # Windowsの上書きしない移動で新しい保存先を先に確保する
                os.rename(temporary, destination)
                try:
                    self._check_source()
                    if destination.read_bytes() != content:
                        raise CustomFilterConflictError(
                            "移動先の共有ファイルが外部で変更されました。再読込してください。"
                        )
                    source.unlink()
                except (OSError, CustomFilterError):
                    # 外部で変更された新宛先は撤回せず、その内容も保護する
                    if destination.read_bytes() == content:
                        destination.unlink()
                    raise
        except FileExistsError as error:
            raise CustomFilterError("同名ファイルが存在します。") from error
        except OSError as error:
            raise CustomFilterError(
                f"定義ファイルを保存できません: {destination}（{error}）"
            ) from error
        finally:
            temporary.unlink(missing_ok=True)
        self.mark_saved()

    def validate_save(self) -> None:
        """書き込まずに外部更新・改名衝突・定義形式を全体保存前に検査する。"""
        self._check_source()
        self._check_destination(Path(self.destination_path))
        self.prepared_content()

    def prepared_content(self) -> bytes:
        """全体保存に渡す検証済みのUTF-8 JSONを生成する。"""
        return serialize_custom_filter(self.definition())

    def mark_saved(self) -> None:
        """外部トランザクションの保存結果を検証し、下書きの保存基準へ反映する。"""
        destination = Path(self.destination_path)
        content = self.prepared_content()
        digest = hashlib.sha256(content).hexdigest()
        if _digest(destination) != digest:
            raise CustomFilterConflictError(
                "保存先の共有ファイルが外部で変更されました。再読込してください。"
            )
        self.path = normalize_filter_path(destination)
        self._destination_path = str(destination.resolve())
        self._source_digest = digest
        self._explicit_types = set(self.node_types)
        self._saved = self._snapshot()
