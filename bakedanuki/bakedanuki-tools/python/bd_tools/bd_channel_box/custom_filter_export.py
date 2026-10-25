# coding: utf-8
"""保存済みフィルターの参照を、共有用ディレクトリの中へまとめる。"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .custom_filter_presets import (
    FilterReference,
    PresetDocument,
    read_preset_document,
)
from .custom_filters import (
    CustomFilterError,
    load_custom_filter,
    normalize_filter_path,
)

__all__ = ["ExportKind", "export_custom_filter_files"]

ExportKind = Literal["preset_group", "preset", "filter"]
_SourceKey = tuple[ExportKind, str]


@dataclass(frozen=True)
class _Source:
    """同じ内容を検証して確保した、出力元の一件を保持する。"""

    kind: ExportKind
    path: Path
    content: bytes
    document: PresetDocument | None


def _read_source(kind: ExportKind, path: str | Path) -> _Source:
    """検証前後の内容を比較し、読込中の更新や不正な参照元を拒否する。"""
    source = Path(path).expanduser().resolve()
    content = source.read_bytes()
    document: PresetDocument | None = None
    if kind == "filter":
        load_custom_filter(source)
    else:
        document = read_preset_document(source, kind)
        if document.error is not None:
            raise CustomFilterError(document.error)
        if document.source_digest != hashlib.sha256(content).hexdigest():
            raise CustomFilterError(
                f"読込中にファイルが変更されました: {source}"
            )
    if source.read_bytes() != content:
        raise CustomFilterError(f"読込中にファイルが変更されました: {source}")
    return _Source(kind, source, content, document)


def _child_kind(kind: ExportKind) -> ExportKind:
    """参照元から一段下の文書種別を返す。"""
    if kind == "preset_group":
        return "preset"
    if kind == "preset":
        return "filter"
    raise CustomFilterError("フィルターには下位の参照がありません")


def _collect_sources(
    kind: ExportKind, paths: Sequence[str | Path]
) -> dict[_SourceKey, _Source]:
    """登録順に全依存を検証し、同じ実パスへの参照を集約する。"""
    sources: dict[_SourceKey, _Source] = {}

    def visit(source_kind: ExportKind, path: str | Path) -> None:
        """一件を確保してから、OFFを含む全参照を順番に辿る。"""
        key = (source_kind, normalize_filter_path(path))
        if key in sources:
            return
        source = _read_source(source_kind, path)
        sources[key] = source
        if source.document is not None:
            for ref in source.document.references:
                visit(_child_kind(source_kind), ref.path)

    for path in paths:
        visit(kind, path)
    return sources


def _assign_names(
    sources: dict[_SourceKey, _Source],
) -> dict[_SourceKey, Path]:
    """元の実ファイル名を優先し、大文字小文字を含む同名衝突を解消する。"""
    reserved: dict[ExportKind, set[str]] = {
        kind: set() for kind in ("preset_group", "preset", "filter")
    }
    used: dict[ExportKind, set[str]] = {
        kind: set() for kind in ("preset_group", "preset", "filter")
    }
    for source in sources.values():
        reserved[source.kind].add(source.path.name.casefold())
    names: dict[_SourceKey, Path] = {}
    for key, source in sources.items():
        name = source.path.name
        number = 1
        if name.casefold() in used[source.kind]:
            while True:
                name = f"{source.path.stem}_{number:03d}{source.path.suffix}"
                if (
                    name.casefold() not in used[source.kind]
                    and name.casefold() not in reserved[source.kind]
                ):
                    break
                number += 1
        used[source.kind].add(name.casefold())
        names[key] = Path(source.kind) / name
    return names


def _output_content(
    source: _Source, root: Path, names: dict[_SourceKey, Path]
) -> bytes:
    """フィルター内容を維持し、上位文書だけ出力内への相対参照に直す。"""
    if source.kind == "filter":
        return source.content
    document = source.document
    if document is None:
        raise CustomFilterError("参照元の文書が読み込まれていません")
    path = root / names[(source.kind, normalize_filter_path(source.path))]
    child_kind = _child_kind(source.kind)
    references = tuple(
        FilterReference(
            str(root / names[(child_kind, normalize_filter_path(ref.path))]),
            ref.enabled,
        )
        for ref in document.references
    )
    return PresetDocument(
        kind=source.kind,
        path=str(path),
        destination_path=str(path),
        references=references,
        saved_references=(),
        source_digest=None,
    ).content()


def _publish_directory(staging: Path, parent: Path) -> Path:
    """Windowsの上書きしないrenameで、空いている連番へ一式を公開する。"""
    number = 0
    while True:
        name = (
            "export_custom_filter"
            if number == 0
            else f"export_custom_filter_{number:03d}"
        )
        destination = parent / name
        number += 1
        if os.path.lexists(destination):
            continue
        try:
            return staging.rename(destination)
        except OSError:
            # 公開直前に作られた既存の出力も保護して次の連番へ進む
            if os.path.lexists(destination):
                continue
            raise


def _remove_staging(staging: Path, parent: Path) -> None:
    """所有する一時ディレクトリの絶対位置を確認してから破棄する。"""
    resolved = staging.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(
        ".export_custom_filter-"
    ):
        raise CustomFilterError(f"一時出力の場所を確認できません: {staging}")
    try:
        shutil.rmtree(resolved)
    except OSError as error:
        raise CustomFilterError(
            f"一時出力を削除できません: {resolved}（{error}）"
        ) from error


def export_custom_filter_files(
    kind: ExportKind,
    paths: Sequence[str | Path],
    destination_directory: str | Path,
) -> Path:
    """保存済みのJSONと全依存を、参照が内部で完結する一式へコピーする。

    グループ・プリセットは1件、フィルターは1件以上を指定します。出力先の
    既存ディレクトリ内へ`export_custom_filter`を作り、既存名は連番で避けます。
    元のファイルや登録は変更しません。

    Args:
        kind: 出力基準の種類。
        paths: 保存済みファイルのパス。フィルターのみ複数指定できます。
        destination_directory: 保存先の既存ディレクトリ。

    Returns:
        作成したエクスポートディレクトリの絶対パス。

    Raises:
        CustomFilterError: 選択、不正なJSON、参照の消失、保存先や書込みの失敗。
    """
    staging: Path | None = None
    parent = Path(destination_directory)
    try:
        parent = parent.expanduser().resolve()
        if kind not in ("preset_group", "preset", "filter"):
            raise CustomFilterError("出力するファイルの種類が不正です")
        if not paths or kind != "filter" and len(paths) != 1:
            raise CustomFilterError(
                "グループ・プリセットは1件、フィルターは1件以上選択してください"
            )
        if not parent.is_dir():
            raise CustomFilterError(
                f"保存先のフォルダーがありません: {parent}"
            )

        # 全依存を確保してから、同じ親の所有一時フォルダーだけへ書き込む
        sources = _collect_sources(kind, paths)
        names = _assign_names(sources)
        staging = Path(
            tempfile.mkdtemp(prefix=".export_custom_filter-", dir=parent)
        )
        for key, source in sources.items():
            destination = staging / names[key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(_output_content(source, staging, names))
            if source.kind == "filter":
                # 元ファイルの更新タイミングに依存せず、コピーした内容自体を検証する
                load_custom_filter(destination)

        # 完成したディレクトリだけを公開し、失敗時は所有一時出力だけを戻す
        destination = _publish_directory(staging, parent)
        staging = None
        return destination
    except CustomFilterError:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise CustomFilterError(f"エクスポートできません: {error}") from error
    finally:
        if staging is not None:
            _remove_staging(staging, parent)
