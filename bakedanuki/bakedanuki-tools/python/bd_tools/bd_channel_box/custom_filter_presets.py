# coding: utf-8
"""共有プリセットの相対参照と、複数JSONの安全な保存を扱う。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from .custom_filters import CustomFilterError, normalize_filter_path

__all__ = [
    "DocumentKind",
    "FilterReference",
    "PresetDocument",
    "FileUpdate",
    "FileDeletion",
    "commit_file_updates",
    "create_preset_document",
    "read_preset_document",
]

DocumentKind = Literal["preset_group", "preset"]


@dataclass(frozen=True, slots=True)
class FilterReference:
    """プリセット内の参照先と、そのプリセットだけの表示状態を保持する。"""

    path: str
    enabled: bool = True


@dataclass(slots=True)
class PresetDocument:
    """共有JSONの読込基準と、保存前の参照・移動先を保持する。"""

    kind: DocumentKind
    path: str
    destination_path: str
    references: tuple[FilterReference, ...]
    saved_references: tuple[FilterReference, ...]
    source_digest: str | None
    error: str | None = None

    @property
    def is_dirty(self) -> bool:
        """参照順・表示状態・ファイル名が保存基準から変わったか返す。"""
        return (
            self.references != self.saved_references
            or self.destination_path != str(Path(self.path).resolve())
        )

    def content(self) -> bytes:
        """移動先を起点とする相対パスで、共有JSONを組み立てる。"""
        parent = Path(self.destination_path).parent
        paths = tuple(
            _relative_path(ref.path, parent) for ref in self.references
        )
        payload: dict[str, object] = {"schema_version": 1}
        if self.kind == "preset_group":
            payload["presets"] = list(paths)
        else:
            payload["filters"] = [
                {"path": path, "enabled": ref.enabled}
                for path, ref in zip(paths, self.references, strict=True)
            ]
        return (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")

    def mark_saved(self, content: bytes | None = None) -> tuple[str, str]:
        """保存先と読込基準を確定し、旧新の識別パスを返す。"""
        expected = _digest(self.content() if content is None else content)
        try:
            if _digest(Path(self.destination_path).read_bytes()) != expected:
                raise CustomFilterError(
                    "保存先の共有ファイルが外部で変更されました。再読込してください。"
                )
        except OSError as error:
            raise CustomFilterError(
                f"保存先を確認できません: {self.destination_path}（{error}）"
            ) from error
        previous = self.path
        self.path = normalize_filter_path(self.destination_path)
        self.destination_path = str(Path(self.destination_path).resolve())
        self.saved_references = self.references
        self.source_digest = expected
        self.error = None
        return previous, self.path


@dataclass(frozen=True, slots=True)
class FileUpdate:
    """外部更新検査と巻戻しに必要な、一つの保存予定を保持する。"""

    source: str | None
    destination: str
    content: bytes
    source_digest: str | None


@dataclass(frozen=True, slots=True)
class FileDeletion:
    """内容を再確認してから削除する、一件の実ファイルを保持する。"""

    source: str
    source_digest: str


def _digest(content: bytes) -> str:
    """外部変更との比較に使用する内容ハッシュを返す。"""
    return hashlib.sha256(content).hexdigest()


def _relative_path(path: str, parent: Path) -> str:
    """同じドライブの参照は相対化し、別ドライブの参照は絶対値で残す。"""
    try:
        return Path(os.path.relpath(Path(path).resolve(), parent)).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """共有JSON内の重複キーを拒否する。"""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSONのキーが重複しています: {key}")
        result[key] = value
    return result


def _parse_references(
    source: object, path: Path, kind: DocumentKind
) -> tuple[FilterReference, ...]:
    """文書種別と各参照の型を厳密に検証し、絶対参照へ変換する。"""
    key = "presets" if kind == "preset_group" else "filters"
    if not isinstance(source, dict):
        raise ValueError("JSONの最上位はobjectにしてください")
    payload = cast(dict[str, object], source)
    if payload.keys() != {"schema_version", key}:
        raise ValueError(f"schema_versionと{key}を指定してください")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
    ):
        raise ValueError("未対応のschema_versionです")
    records = payload[key]
    if not isinstance(records, list):
        raise ValueError(f"{key}は配列にしてください")
    result: list[FilterReference] = []
    known: set[str] = set()
    for value in cast(list[object], records):
        enabled = True
        if kind == "preset":
            if not isinstance(value, dict):
                raise ValueError("filtersの各項目はobjectにしてください")
            record = cast(dict[str, object], value)
            if record.keys() != {"path", "enabled"}:
                raise ValueError("各filterにはpathとenabledを指定してください")
            raw_path = record["path"]
            raw_enabled = record["enabled"]
            if not isinstance(raw_enabled, bool):
                raise ValueError("enabledは真偽値にしてください")
            enabled = raw_enabled
        else:
            raw_path = value
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("参照パスは空でない文字列にしてください")
        resolved = normalize_filter_path(path.parent / raw_path)
        if resolved not in known:
            result.append(FilterReference(resolved, enabled))
            known.add(resolved)
    return tuple(result)


def read_preset_document(
    path: str | Path, kind: DocumentKind
) -> PresetDocument:
    """読込失敗も文書として返し、壊れた参照を一覧へ残す。"""
    normalized = normalize_filter_path(path)
    destination = str(Path(path).expanduser().resolve())
    references: tuple[FilterReference, ...] = ()
    digest: str | None = None
    error: str | None = None
    try:
        content = Path(destination).read_bytes()
        digest = _digest(content)
        source: object = json.loads(
            content.decode("utf-8-sig"), object_pairs_hook=_unique_object
        )
        references = _parse_references(source, Path(destination), kind)
    except (OSError, UnicodeError, ValueError) as failure:
        error = f"共有プリセットを読み込めません: {destination}（{failure}）"
    return PresetDocument(
        kind, normalized, destination, references, references, digest, error
    )


def create_preset_document(
    path: str | Path,
    kind: DocumentKind,
    references: tuple[FilterReference, ...] = (),
) -> PresetDocument:
    """参照先を複製せず、新しい共有JSONだけを上書きせず作成する。"""
    destination = Path(path).expanduser().resolve()
    if destination.suffix.lower() != ".json":
        raise CustomFilterError("保存先には.jsonファイルを指定してください")
    document = PresetDocument(
        kind,
        normalize_filter_path(destination),
        str(destination),
        references,
        references,
        None,
    )
    commit_file_updates(
        (FileUpdate(None, str(destination), document.content(), None),)
    )
    return read_preset_document(destination, kind)


def _check_writable(path: Path) -> None:
    """読取専用ファイルと書込不可フォルダーを保存前に拒否する。"""
    if not path.exists():
        raise CustomFilterError(f"保存先フォルダーがありません: {path}")
    if not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise CustomFilterError(f"読取専用のため保存できません: {path}")
    if not os.access(path, os.W_OK):
        raise CustomFilterError(f"書込権限がありません: {path}")


def _validate_update(update: FileUpdate) -> None:
    """一件の保存元・保存先を再確認し、外部更新と上書きを防ぐ。"""
    destination = Path(update.destination)
    _check_writable(destination.parent)
    if update.source is not None:
        source = Path(update.source)
        try:
            if _digest(source.read_bytes()) != update.source_digest:
                raise CustomFilterError(
                    f"共有ファイルが外部で変更されました: {source}"
                )
        except OSError as error:
            raise CustomFilterError(
                f"保存元を読み込めません: {source}（{error}）"
            ) from error
        _check_writable(source)
        _check_writable(source.parent)
    if destination.exists():
        if update.source is None or normalize_filter_path(
            destination
        ) != normalize_filter_path(update.source):
            raise CustomFilterError(f"同名ファイルが存在します: {destination}")
        _check_writable(destination)


def _temporary(path: Path, content: bytes) -> Path:
    """保存先と同じフォルダーに、置換用の内容を確実に書き出す。"""
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
    except OSError:
        # Windowsでも削除できるよう、ファイルを閉じた後に片付ける
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    assert temporary is not None
    return temporary


def _rollback(
    updates: tuple[FileUpdate, ...], originals: dict[str, bytes]
) -> tuple[str, ...]:
    """今回の書込だけを戻し、処理中に他者が更新したファイルは保護する。"""
    errors: list[str] = []
    written = {
        normalize_filter_path(item.destination): item.content
        for item in updates
    }
    original_ids = {normalize_filter_path(path) for path in originals}
    for source, content in originals.items():
        path = Path(source)
        restore_case = any(
            update.source is not None
            and normalize_filter_path(update.source)
            == normalize_filter_path(path)
            and normalize_filter_path(update.destination)
            == normalize_filter_path(path)
            and Path(update.source).name != Path(update.destination).name
            for update in updates
        )
        try:
            if path.exists():
                current = path.read_bytes()
                if current == content:
                    if not restore_case:
                        continue
                elif current != written.get(normalize_filter_path(path)):
                    raise OSError(
                        "保存中に別の変更が入ったため復元を中止しました"
                    )
            temporary = _temporary(path, content)
            try:
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as error:
            errors.append(f"{source}: {error}")
    for update in updates:
        destination = Path(update.destination)
        if normalize_filter_path(destination) in original_ids:
            continue
        try:
            if destination.exists():
                if destination.read_bytes() != update.content:
                    raise OSError(
                        "保存中に移動先が別の内容へ更新されたため復元を中止しました"
                    )
                destination.unlink()
        except OSError as error:
            errors.append(f"{destination}: {error}")
    return tuple(errors)


def _validate_deletion(deletion: FileDeletion) -> None:
    """削除元の内容と書込可否を再確認し、確認後の外部変更を保護する。"""
    source = Path(deletion.source)
    if (
        not source.is_file()
        or _digest(source.read_bytes()) != deletion.source_digest
    ):
        raise CustomFilterError(f"削除対象が外部で変更されました: {source}")
    _check_writable(source)
    _check_writable(source.parent)


def commit_file_updates(
    updates: tuple[FileUpdate, ...],
    deletions: tuple[FileDeletion, ...] = (),
    *,
    finalize: Callable[[], None] | None = None,
) -> None:
    """全件検証後に保存・移動・削除を確定し、失敗時は今回の内容を戻す。

    `finalize`はファイル操作後に登録情報などを確定する処理です。
    この処理の失敗も巻戻し対象です。OSや他者の変更により復元できない場合は、
    対象を含めた`CustomFilterError`を返します。
    """
    if not updates and not deletions:
        return
    originals: dict[str, bytes] = {}
    temporaries: list[Path] = []
    destinations: set[str] = set()
    applied: list[FileUpdate] = []
    removed: set[str] = set()
    try:
        # 競合を先に検査し、一件の検証失敗でほかのJSONを更新しない
        for update in updates:
            target = normalize_filter_path(update.destination)
            if target in destinations:
                raise CustomFilterError(
                    f"保存先が重複しています: {update.destination}"
                )
            destinations.add(target)
            _validate_update(update)
            if update.source is not None:
                originals[update.source] = Path(update.source).read_bytes()
        deleted_ids: set[str] = set()
        source_ids = {
            normalize_filter_path(update.source)
            for update in updates
            if update.source is not None
        }
        for deletion in deletions:
            source_id = normalize_filter_path(deletion.source)
            if (
                source_id in deleted_ids
                or source_id in destinations
                or source_id in source_ids
            ):
                raise CustomFilterError(
                    f"保存と削除の対象が重複しています: {deletion.source}"
                )
            deleted_ids.add(source_id)
            _validate_deletion(deletion)
            originals[deletion.source] = Path(deletion.source).read_bytes()
        for update in updates:
            temporaries.append(
                _temporary(Path(update.destination), update.content)
            )
        for update in updates:
            _validate_update(update)
        for deletion in deletions:
            _validate_deletion(deletion)

        # 新しい参照元をすべて用意してから、改名前のファイルを削除する
        for update, temporary in zip(updates, temporaries, strict=True):
            # 他の保存対象を処理する間に入った外部変更も保護する
            _validate_update(update)
            same = update.source is not None and normalize_filter_path(
                update.source
            ) == normalize_filter_path(update.destination)
            if same:
                os.replace(temporary, update.destination)
            else:
                os.rename(temporary, update.destination)
            applied.append(update)
        for update in updates:
            if update.source is not None and normalize_filter_path(
                update.source
            ) != normalize_filter_path(update.destination):
                if (
                    _digest(Path(update.source).read_bytes())
                    != update.source_digest
                ):
                    raise CustomFilterError(
                        f"共有ファイルが外部で変更されました: {update.source}"
                    )
                Path(update.source).unlink()
        # 参照元をすべて保存してから、確認時と同じ内容の実ファイルだけを削除する
        for deletion in deletions:
            _validate_deletion(deletion)
            Path(deletion.source).unlink()
            removed.add(normalize_filter_path(deletion.source))
        if finalize is not None:
            finalize()
    except Exception as error:
        applied_sources = {
            normalize_filter_path(update.source)
            for update in applied
            if update.source is not None
        }
        rollback_originals = {
            path: content
            for path, content in originals.items()
            if normalize_filter_path(path) in applied_sources | removed
        }
        rollback_errors = (
            _rollback(tuple(applied), rollback_originals)
            if applied or removed
            else ()
        )
        detail = (
            "\n復元できない項目: " + "／".join(rollback_errors)
            if rollback_errors
            else ""
        )
        raise CustomFilterError(
            f"共有設定を保存できません: {error}{detail}"
        ) from error
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
