# coding: utf-8
"""選択した共有JSONの移動・削除と、参照元更新の保存予定を作る。"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .custom_filter_presets import FileDeletion, FileUpdate, PresetDocument
from .custom_filters import CustomFilterError, normalize_filter_path

__all__ = ["FileKind", "FileOperationPlan", "plan_file_operation"]

FileKind = Literal["preset_group", "preset", "filter"]


@dataclass(frozen=True, slots=True)
class FileOperationPlan:
    """確認後の外部変更も検出できる、実ファイル操作の保存予定。"""

    kind: FileKind
    paths: tuple[str, ...]
    mapping: tuple[tuple[str, str], ...]
    documents: tuple[PresetDocument, ...]
    updates: tuple[FileUpdate, ...]
    deletions: tuple[FileDeletion, ...]
    reference_sources: tuple[str, ...]
    reference_sources_by_path: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def reference_sources_for(self, path: str | Path) -> tuple[str, ...]:
        """確認対象を直接参照し、今回書き換える共有JSONだけを返す。"""
        normalized = normalize_filter_path(path)
        return next(
            (
                sources
                for target, sources in self.reference_sources_by_path
                if target == normalized
            ),
            (),
        )


def plan_file_operation(
    kind: FileKind,
    paths: Iterable[str],
    documents: Iterable[PresetDocument],
    directory: str | Path | None,
) -> FileOperationPlan:
    """移動先基準の相対参照を計算し、`directory=None`なら実削除を計画する。

    下位JSONは移動・削除しません。参照順と表示ON/OFFを保持し、移動先の上書きや
    選択ファイル間の同名衝突を拒否します。呼出し元が登録範囲と読込基準を検証します。
    """
    selected = tuple(
        dict.fromkeys(normalize_filter_path(path) for path in paths)
    )
    if not selected:
        raise CustomFilterError("操作するファイルを選択してください")
    folder = (
        Path(directory).expanduser().resolve()
        if directory is not None
        else None
    )
    if folder is not None and not folder.is_dir():
        raise CustomFilterError("移動先のフォルダーが存在しません")
    # 全対象の実体と衝突を確認してから、書込み予定を組み立てる
    sources: dict[str, Path] = {}
    contents: dict[str, bytes] = {}
    destinations: dict[str, str] = {}
    destination_ids: set[str] = set()
    for path in selected:
        source = Path(path).resolve()
        if not source.is_file():
            raise CustomFilterError(f"対象ファイルが存在しません: {path}")
        sources[path] = source
        contents[path] = source.read_bytes()
        if folder is not None:
            target = folder / source.name
            target_id = normalize_filter_path(target)
            if (
                target_id in destination_ids
                or target.exists()
                and target_id != path
            ):
                raise CustomFilterError(
                    f"移動先に同名ファイルがあります: {target}"
                )
            destination_ids.add(target_id)
            destinations[path] = str(target)
    # 親参照の付替えと、移動する文書内部の相対参照を同じ予定へまとめる
    mapping = {
        old: normalize_filter_path(new) for old, new in destinations.items()
    }
    removed: set[str] = set(selected) if folder is None else set()
    changed_documents: list[PresetDocument] = []
    updates: list[FileUpdate] = []
    reference_sources: list[str] = []
    sources_by_path: dict[str, list[str]] = (
        {path: [] for path in selected} if folder is None else {}
    )
    for document in documents:
        if document.kind == kind and document.path in removed:
            continue
        affects_references = (
            kind == "preset" and document.kind == "preset_group"
        ) or (kind == "filter" and document.kind == "preset")
        references = document.references
        if affects_references:
            references = tuple(
                replace(ref, path=mapping.get(ref.path, ref.path))
                for ref in references
                if ref.path not in removed
            )
        destination = (
            destinations.get(document.path, document.destination_path)
            if document.kind == kind
            else document.destination_path
        )
        if references != document.references:
            if document.path not in reference_sources:
                reference_sources.append(document.path)
            if folder is None:
                for reference in document.references:
                    if (
                        reference.path in sources_by_path
                        and document.path
                        not in sources_by_path[reference.path]
                    ):
                        sources_by_path[reference.path].append(document.path)
        if (
            references == document.references
            and normalize_filter_path(destination) == document.path
        ):
            continue
        planned = replace(
            document, references=references, destination_path=destination
        )
        changed_documents.append(planned)
        updates.append(
            FileUpdate(
                str(Path(document.path).resolve()),
                destination,
                planned.content(),
                document.source_digest,
            )
        )
    # フィルター本体は旧形式や整形を変えず、保存済みのbytesをそのまま移す
    if kind == "filter" and folder is not None:
        for path in selected:
            if mapping[path] != path:
                updates.append(
                    FileUpdate(
                        str(sources[path]),
                        destinations[path],
                        contents[path],
                        hashlib.sha256(contents[path]).hexdigest(),
                    )
                )
    deletions = tuple(
        FileDeletion(
            str(sources[path]), hashlib.sha256(contents[path]).hexdigest()
        )
        for path in selected
        if folder is None
    )
    return FileOperationPlan(
        kind,
        selected,
        tuple(mapping.items()),
        tuple(changed_documents),
        tuple(updates),
        deletions,
        tuple(reference_sources),
        tuple(
            (path, tuple(sources)) for path, sources in sources_by_path.items()
        ),
    )
