# coding: utf-8
"""共有プリセットの構成下書きと、個人設定の現在選択を管理する。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt

from .custom_filter_editor import CustomFilterDraft, filter_file_name
from .custom_filter_presets import (
    DocumentKind,
    FileUpdate,
    FilterReference,
    PresetDocument,
    commit_file_updates,
    create_preset_document,
    read_preset_document,
)
from .custom_filters import (
    CustomFilterDefinition,
    CustomFilterError,
    filter_display_name,
    load_custom_filter,
    normalize_filter_path,
)

__all__ = [
    "CustomFilterRegistration",
    "PresetRegistration",
    "CustomFilterRegistry",
]

_SETTINGS_PATH = "bd_channel_box/preferences/custom_filters"
_SETTINGS_KEY = "preferences/custom_filters/registrations"
_SELECTION_KEY = "preferences/custom_filters/selection"


@dataclass(frozen=True, slots=True)
class CustomFilterRegistration:
    """現在プリセットの表示状態と、共有フィルターの読込結果を保持する。"""

    path: str
    enabled: bool
    definition: CustomFilterDefinition | None
    error: str | None


@dataclass(frozen=True, slots=True)
class PresetRegistration:
    """一覧の識別パス・保存予定名・読込状態を保持する。"""

    path: str
    name: str
    destination_path: str
    error: str | None
    is_dirty: bool


def _move_references(
    values: tuple[FilterReference, ...], paths: Iterable[str], offset: int
) -> tuple[FilterReference, ...]:
    """選択行の相対順を保ち、一段移動した参照順を返す。"""
    if offset not in (-1, 1):
        raise ValueError("移動量には-1または1を指定してください")
    selected = set(paths)
    indices = tuple(
        index for index, ref in enumerate(values) if ref.path in selected
    )
    if not indices or not 0 <= indices[0 if offset < 0 else -1] + offset < len(
        values
    ):
        return values
    result = list(values)
    for index in indices if offset < 0 else reversed(indices):
        result[index], result[index + offset] = (
            result[index + offset],
            result[index],
        )
    return tuple(result)


class CustomFilterRegistry(qt.QObject):
    """既知の共有JSONを一つの下書きにまとめ、選択だけを自動保存する。"""

    changed = qt.Signal()
    selection_changed = qt.Signal()
    path_changed = qt.Signal(str, str)
    document_path_changed = qt.Signal(str, str, str)

    def __init__(self, parent: qt.QObject | None = None) -> None:
        """個人設定と参照先を読み、旧一覧は既定グループへ移行する。"""
        super().__init__(parent)
        settings_file = get_ui_settings_file(_SETTINGS_PATH)
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        self._settings = qt.QSettings(
            str(settings_file), qt.QSettings.Format.IniFormat
        )
        self._roots: list[str] = []
        self._saved_roots: tuple[str, ...] = ()
        self._documents: dict[tuple[DocumentKind, str], PresetDocument] = {}
        self._filters: dict[str, CustomFilterRegistration] = {}
        self._active_group: str | None = None
        self._active_preset: str | None = None
        self._preset_selections: dict[str, str] = {}
        self._storage_error: str | None = None
        self._load()

    @property
    def entries(self) -> tuple[CustomFilterRegistration, ...]:
        """現在プリセットのフィルターを順序と表示状態付きで返す。"""
        document = self._current("preset")
        if document is None or document.error is not None:
            return ()
        return tuple(
            replace(self._filter(ref.path), enabled=ref.enabled)
            for ref in document.references
        )

    @property
    def groups(self) -> tuple[PresetRegistration, ...]:
        """登録済みグループを個人設定の並び順で返す。"""
        return tuple(
            self._registration("preset_group", path) for path in self._roots
        )

    @property
    def presets(self) -> tuple[PresetRegistration, ...]:
        """現在グループのプリセットを参照順で返す。"""
        document = self._current("preset_group")
        if document is None or document.error is not None:
            return ()
        return tuple(
            self._registration("preset", ref.path)
            for ref in document.references
        )

    @property
    def active_group(self) -> str | None:
        """現在グループの識別パスを返す。"""
        return self._active_group

    @property
    def active_preset(self) -> str | None:
        """現在プリセットの識別パスを返す。"""
        return self._active_preset

    @property
    def is_dirty(self) -> bool:
        """グループ登録または共有文書に未保存変更があるか返す。"""
        return tuple(self._roots) != self._saved_roots or any(
            document.is_dirty for document in self._documents.values()
        )

    @property
    def storage_error(self) -> str | None:
        """個人設定の読込・保存エラーを返す。"""
        return self._storage_error

    def select_group(self, path: str | None) -> bool:
        """グループと最後のプリセット選択を復元し、選択だけを保存する。"""
        normalized = normalize_filter_path(path) if path is not None else None
        if (
            normalized == self._active_group
            or normalized is not None
            and normalized not in self._roots
        ):
            return False
        self._active_group = normalized
        self._ensure_preset()
        self._selection_changed()
        return True

    def select_preset(self, path: str | None) -> bool:
        """現在グループ内のプリセット選択を切り替え、個人設定へ保存する。"""
        normalized = normalize_filter_path(path) if path is not None else None
        if (
            normalized == self._active_preset
            or normalized is not None
            and normalized not in {item.path for item in self.presets}
        ):
            return False
        self._active_preset = normalized
        if self._active_group is not None:
            if normalized is None:
                self._preset_selections.pop(self._active_group, None)
            else:
                self._preset_selections[self._active_group] = normalized
        self._selection_changed()
        return True

    def add_group_paths(self, paths: Iterable[str | Path]) -> tuple[str, ...]:
        """共有グループを登録し、参照先を下書きへ読み込む。"""
        normalized = tuple(normalize_filter_path(path) for path in paths)
        added = tuple(
            dict.fromkeys(
                path for path in normalized if path not in self._roots
            )
        )
        if added:
            self._roots.extend(added)
            self._load_graph()
            self.changed.emit()
        return added

    def add_preset_paths(self, paths: Iterable[str | Path]) -> tuple[str, ...]:
        """現在グループへ共有プリセットを重複せず登録する。"""
        return self._add("preset_group", paths)

    def add_paths(self, paths: Iterable[str | Path]) -> tuple[str, ...]:
        """現在プリセットへフィルターを重複せずONで登録する。"""
        return self._add("preset", paths)

    def create_group(self, path: str | Path, source: str | None = None) -> str:
        """新規・複製グループを作成し、登録して選択する。"""
        return self._create("preset_group", path, source)

    def create_preset(
        self, path: str | Path, source: str | None = None
    ) -> str:
        """新規・複製プリセットを作成し、現在グループへ登録して選択する。"""
        self._require("preset_group")
        return self._create("preset", path, source)

    def rename_group(self, path: str, name: str) -> bool:
        """グループの実ファイル名変更を下書きへ積む。"""
        return self._rename("preset_group", path, name)

    def rename_preset(self, path: str, name: str) -> bool:
        """プリセットの実ファイル名変更を下書きへ積む。"""
        return self._rename("preset", path, name)

    def rename_error(
        self, kind: DocumentKind, path: str, name: str
    ) -> str | None:
        """名前入力中の競合・ファイル名エラーを返す。"""
        try:
            self._rename_destination(kind, path, name)
        except (OSError, CustomFilterError) as error:
            return str(error)
        return None

    def remove_groups(self, paths: Iterable[str]) -> bool:
        """グループ登録だけを解除し、参照先のJSON本体を残す。"""
        selected = set(paths)
        roots = [path for path in self._roots if path not in selected]
        if roots == self._roots:
            return False
        self._roots = roots
        self._prune_documents()
        self._ensure_group()
        self.changed.emit()
        return True

    def remove_presets(self, paths: Iterable[str]) -> bool:
        """現在グループから選択プリセットの参照だけを解除する。"""
        return self._remove("preset_group", paths)

    def remove(self, path: str) -> bool:
        """フィルター登録だけを解除し、共有JSONを残す。"""
        return self.remove_many((path,))

    def remove_many(self, paths: Iterable[str]) -> bool:
        """現在プリセットから選択フィルターの参照だけを解除する。"""
        return self._remove("preset", paths)

    def move_groups(self, paths: Iterable[str], offset: int) -> bool:
        """選択グループの相対順を保ち、登録順を一段移動する。"""
        before = tuple(FilterReference(path) for path in self._roots)
        after = _move_references(before, paths, offset)
        if before == after:
            return False
        self._roots = [ref.path for ref in after]
        self.changed.emit()
        return True

    def move_presets(self, paths: Iterable[str], offset: int) -> bool:
        """現在グループ内の選択プリセットを一段移動する。"""
        return self._move("preset_group", paths, offset)

    def move(self, path: str, offset: int) -> bool:
        """選択フィルターを一段移動する。"""
        return self.move_many((path,), offset)

    def move_many(self, paths: Iterable[str], offset: int) -> bool:
        """現在プリセット内の選択フィルターを一段移動する。"""
        return self._move("preset", paths, offset)

    def set_enabled(self, path: str, enabled: bool) -> bool:
        """現在プリセットだけの表示状態を変更する。"""
        return self.set_enabled_many((path,), enabled)

    def set_enabled_many(self, paths: Iterable[str], enabled: bool) -> bool:
        """選択フィルターの表示状態を、一度に下書きへ反映する。"""
        document = self._require("preset")
        selected = set(paths)
        references = tuple(
            replace(ref, enabled=enabled) if ref.path in selected else ref
            for ref in document.references
        )
        if references == document.references:
            return False
        document.references = references
        self.changed.emit()
        return True

    def validate_filter_rename(self, old_path: str, new_path: str) -> None:
        """全既知参照を更新できることと、同一プリセット内の重複を検査する。"""
        old, new = normalize_filter_path(old_path), normalize_filter_path(
            new_path
        )
        if old == new:
            return
        self._validate_graph()
        for document in self._documents.values():
            paths: set[str] = (
                {ref.path for ref in document.references}
                if document.kind == "preset"
                else set()
            )
            if old in paths and new in paths:
                raise CustomFilterError(
                    "変更先のファイルは既に登録されています"
                )

    def replace_path(
        self,
        old_path: str,
        new_path: str,
        *,
        saved_definition: CustomFilterDefinition | None = None,
    ) -> bool:
        """保存済みフィルターの改名先へ、すべての既知プリセット参照を移す。"""
        old, new = normalize_filter_path(old_path), normalize_filter_path(
            new_path
        )
        if old == new:
            return False
        self.validate_filter_rename(old, new)
        definition = (
            load_custom_filter(new)
            if saved_definition is None
            else saved_definition
        )
        changed = False
        for document in self._documents.values():
            if document.kind != "preset":
                continue
            references = tuple(
                replace(ref, path=new) if ref.path == old else ref
                for ref in document.references
            )
            if references != document.references:
                document.references = references
                changed = True
        if changed:
            self._filters[new] = CustomFilterRegistration(
                new, True, definition, None
            )
            self._filters.pop(old, None)
            self.path_changed.emit(old, new)
            self.changed.emit()
        return changed

    def save(self, draft: CustomFilterDraft | None = None) -> None:
        """構成全体と編集中のフィルターを、一括検証と巻戻し付きで保存する。"""
        filter_map: dict[str, str] = {}
        changed_filter = draft is not None and draft.is_dirty
        if draft is not None and changed_filter:
            draft.validate_save()
            destination = normalize_filter_path(draft.destination_path)
            self.validate_filter_rename(draft.path, destination)
            if destination != draft.path:
                filter_map[draft.path] = destination
        preset_map = {
            document.path: normalize_filter_path(document.destination_path)
            for document in self._documents.values()
            if document.kind == "preset"
            and normalize_filter_path(document.destination_path)
            != document.path
        }
        if preset_map:
            self._validate_graph()

        # 保存失敗では下書きを変えないよう、参照の書換えも一時内容へ積む
        planned: list[
            tuple[PresetDocument, tuple[FilterReference, ...], bytes]
        ] = []
        updates: list[FileUpdate] = []
        for document in self._documents.values():
            mapping = (
                preset_map if document.kind == "preset_group" else filter_map
            )
            references = tuple(
                replace(ref, path=mapping.get(ref.path, ref.path))
                for ref in document.references
            )
            if not document.is_dirty and references == document.references:
                continue
            if document.error is not None:
                raise CustomFilterError(document.error)
            content = replace(document, references=references).content()
            planned.append((document, references, content))
            updates.append(
                FileUpdate(
                    str(Path(document.path).resolve()),
                    document.destination_path,
                    content,
                    document.source_digest,
                )
            )
        if draft is not None and changed_filter:
            updates.append(
                FileUpdate(
                    draft.source_path,
                    draft.destination_path,
                    draft.prepared_content(),
                    draft.source_digest,
                )
            )
        commit_file_updates(tuple(updates))

        # 全ファイルの保存成功後だけ、識別子と選択を改名先へ切り替える
        moved: list[tuple[DocumentKind, str, str]] = []
        document_map: dict[str, str] = {}
        for document, references, content in planned:
            document.references = references
            old, new = document.mark_saved(content)
            if old != new:
                moved.append((document.kind, old, new))
                document_map[old] = new
        self._documents = {
            (document.kind, document.path): document
            for document in self._documents.values()
        }
        self._roots = [document_map.get(path, path) for path in self._roots]
        self._active_group = (
            document_map.get(self._active_group, self._active_group)
            if self._active_group is not None
            else None
        )
        self._active_preset = (
            document_map.get(self._active_preset, self._active_preset)
            if self._active_preset is not None
            else None
        )
        self._preset_selections = {
            document_map.get(group, group): document_map.get(preset, preset)
            for group, preset in self._preset_selections.items()
        }
        if draft is not None and changed_filter:
            old_filter = draft.path
            draft.mark_saved()
            self._filters.pop(old_filter, None)
            self._filters[draft.path] = CustomFilterRegistration(
                draft.path, True, draft.definition(), None
            )
        self._save()
        self._persist_selection()
        for kind, old, new in moved:
            self.document_path_changed.emit(kind, old, new)
        for old, new in filter_map.items():
            self.path_changed.emit(old, new)
        self.changed.emit()
        if self._storage_error is not None:
            raise CustomFilterError(self._storage_error)

    def discard(self) -> None:
        """構成下書きを破棄し、保存済みの登録とJSONを読み直す。"""
        self._roots = list(self._saved_roots)
        self._documents.clear()
        self._filters.clear()
        self._load_graph()
        self._ensure_group()
        self.changed.emit()

    def reload(self, path: str) -> bool:
        """構成下書きを維持したまま、指定フィルターを再読込する。"""
        normalized = normalize_filter_path(path)
        if not any(
            ref.path == normalized
            for document in self._documents.values()
            if document.kind == "preset"
            for ref in document.references
        ):
            return False
        self._filters[normalized] = self._read_entry(normalized, True)
        self.changed.emit()
        return True

    def reload_all(self) -> None:
        """未編集文書と全フィルターを再読込し、編集済み下書きを維持する。"""
        for key, document in tuple(self._documents.items()):
            if not document.is_dirty:
                self._documents[key] = read_preset_document(
                    document.path, document.kind
                )
        self._filters.clear()
        self._load_graph()
        self._ensure_group()
        self.changed.emit()

    def _registration(
        self, kind: DocumentKind, path: str
    ) -> PresetRegistration:
        """文書の保存予定名と読込状態を、UI用の値へ変換する。"""
        document = self._document(kind, path)
        name = (
            Path(document.destination_path).stem
            if document.is_dirty
            else filter_display_name(document.destination_path)
        )
        return PresetRegistration(
            path,
            name,
            document.destination_path,
            document.error,
            document.is_dirty,
        )

    def _document(self, kind: DocumentKind, path: str) -> PresetDocument:
        """既知文書を返し、未読込の参照だけを読み込む。"""
        key = kind, path
        if key not in self._documents:
            self._documents[key] = read_preset_document(path, kind)
        return self._documents[key]

    def _current(self, kind: DocumentKind) -> PresetDocument | None:
        """現在選択に対応する共有文書を返す。"""
        path = (
            self._active_group
            if kind == "preset_group"
            else self._active_preset
        )
        return self._document(kind, path) if path is not None else None

    def _require(self, kind: DocumentKind) -> PresetDocument:
        """編集可能な現在文書を取得し、未選択・読込失敗を拒否する。"""
        document = self._current(kind)
        if document is None:
            raise CustomFilterError(
                "編集するグループまたはプリセットを選択してください"
            )
        if document.error is not None:
            raise CustomFilterError(document.error)
        return document

    def _filter(self, path: str) -> CustomFilterRegistration:
        """共有フィルターの読込結果を再利用する。"""
        if path not in self._filters:
            self._filters[path] = self._read_entry(path, True)
        return self._filters[path]

    @staticmethod
    def _read_entry(path: str, enabled: bool) -> CustomFilterRegistration:
        """読込エラーも登録として残し、理由を保持する。"""
        try:
            definition = load_custom_filter(path)
        except CustomFilterError as error:
            return CustomFilterRegistration(path, enabled, None, str(error))
        return CustomFilterRegistration(path, enabled, definition, None)

    def _add(
        self, kind: DocumentKind, paths: Iterable[str | Path]
    ) -> tuple[str, ...]:
        """現在文書の末尾へ、重複しない参照を追加する。"""
        normalized = tuple(normalize_filter_path(path) for path in paths)
        document = self._require(kind)
        known = {ref.path for ref in document.references}
        added = tuple(
            dict.fromkeys(path for path in normalized if path not in known)
        )
        if added:
            document.references += tuple(
                FilterReference(path) for path in added
            )
            self._load_graph()
            self.changed.emit()
        return added

    def _remove(self, kind: DocumentKind, paths: Iterable[str]) -> bool:
        """参照だけをまとめて解除し、利用可能な選択へ戻す。"""
        document = self._current(kind)
        if document is None or document.error is not None:
            return False
        selected = set(paths)
        references = tuple(
            ref for ref in document.references if ref.path not in selected
        )
        if references == document.references:
            return False
        document.references = references
        self._prune_documents()
        if kind == "preset_group":
            self._ensure_preset()
        self.changed.emit()
        return True

    def _move(
        self, kind: DocumentKind, paths: Iterable[str], offset: int
    ) -> bool:
        """現在文書内の選択参照を一段移動する。"""
        document = self._current(kind)
        if document is None:
            if offset not in (-1, 1):
                raise ValueError("移動量には-1または1を指定してください")
            return False
        references = _move_references(document.references, paths, offset)
        if references == document.references:
            return False
        document.references = references
        self.changed.emit()
        return True

    def _create(
        self, kind: DocumentKind, path: str | Path, source: str | None
    ) -> str:
        """保存済み参照を複製し、新しいファイルだけを登録する。"""
        references: tuple[FilterReference, ...] = ()
        if source is not None:
            original = read_preset_document(source, kind)
            if original.error is not None:
                raise CustomFilterError(original.error)
            references = original.references
        document = create_preset_document(path, kind, references)
        self._documents[kind, document.path] = document
        if kind == "preset_group":
            self.add_group_paths((document.path,))
            self.select_group(document.path)
        else:
            self.add_preset_paths((document.path,))
            self.select_preset(document.path)
        return document.path

    def _rename_destination(
        self, kind: DocumentKind, path: str, name: str
    ) -> str:
        """改名先の妥当性と、既存ファイル・他下書きとの衝突を検査する。"""
        document = self._document(kind, normalize_filter_path(path))
        if document.error is not None:
            raise CustomFilterError(document.error)
        self._validate_graph()
        destination = (
            Path(document.path)
            .resolve()
            .with_name(filter_file_name(name) + ".json")
        )
        target = normalize_filter_path(destination)
        if destination.exists() and target != document.path:
            raise CustomFilterError("同名ファイルが存在します")
        if any(
            other is not document
            and normalize_filter_path(other.destination_path) == target
            for other in self._documents.values()
        ):
            raise CustomFilterError("同名ファイルが保存予定にあります")
        return str(destination)

    def _rename(self, kind: DocumentKind, path: str, name: str) -> bool:
        """検証済みの改名先だけを下書きへ反映する。"""
        destination = self._rename_destination(kind, path, name)
        document = self._document(kind, normalize_filter_path(path))
        if document.destination_path == destination:
            return False
        document.destination_path = destination
        self.changed.emit()
        return True

    def _validate_graph(self) -> None:
        """既知参照元の外部変更を検査し、不完全な改名更新を拒否する。"""
        for document in self._documents.values():
            if document.error is not None:
                raise CustomFilterError(
                    "参照先を確認できない共有文書があります。\n"
                    + document.error
                )
            try:
                digest = hashlib.sha256(
                    Path(document.path).read_bytes()
                ).hexdigest()
            except OSError as error:
                raise CustomFilterError(
                    f"参照元を確認できません: {document.path}（{error}）"
                ) from error
            if digest != document.source_digest:
                raise CustomFilterError(
                    "参照元の共有ファイルが外部で変更されました。"
                    f"再読込してから改名してください。\n{document.path}"
                )

    def _load_graph(self) -> None:
        """登録グループから到達するプリセットとフィルターを読み込む。"""
        for path in self._roots:
            group = self._document("preset_group", path)
            for ref in group.references:
                preset = self._document("preset", ref.path)
                for filter_ref in preset.references:
                    self._filter(filter_ref.path)

    def _prune_documents(self) -> None:
        """登録から外れた未編集文書を除き、見えないエラーの残留を防ぐ。"""
        retained: set[tuple[DocumentKind, str]] = {
            ("preset_group", path) for path in self._roots
        }
        retained.update(
            key
            for key, document in self._documents.items()
            if document.is_dirty
        )
        for kind, path in tuple(retained):
            if kind == "preset_group":
                document = self._document(kind, path)
                retained.update(
                    ("preset", ref.path) for ref in document.references
                )
        self._documents = {
            key: document
            for key, document in self._documents.items()
            if key in retained
        }

    def _ensure_preset(self) -> None:
        """現在グループの最後のプリセットか、先頭行を選択する。"""
        available = tuple(item.path for item in self.presets)
        selected = (
            self._preset_selections.get(self._active_group)
            if self._active_group is not None
            else None
        )
        self._active_preset = (
            selected
            if selected in available
            else available[0] if available else None
        )
        if self._active_group is not None and self._active_preset is not None:
            self._preset_selections[self._active_group] = self._active_preset

    def _ensure_group(self) -> None:
        """利用不能な選択を、残っている先頭グループへ戻す。"""
        if self._active_group not in self._roots:
            self._active_group = self._roots[0] if self._roots else None
        self._ensure_preset()
        self._persist_selection()

    def _selection_changed(self) -> None:
        """構成保存とは独立して、現在選択を保存・通知する。"""
        self._persist_selection()
        self.selection_changed.emit()
        self.changed.emit()

    def _persist_selection(self) -> None:
        """グループとプリセットの選択だけを即時保存する。"""
        payload = {
            "group": self._active_group,
            "presets": self._preset_selections,
        }
        self._settings.setValue(
            _SELECTION_KEY, json.dumps(payload, ensure_ascii=False)
        )
        self._settings.sync()
        if self._settings.status() != qt.QSettings.Status.NoError:
            self._storage_error = (
                "カスタムフィルター選択を保存できませんでした"
            )

    def _load_selection(self) -> None:
        """保存選択を読み、現在利用できる構成へ補正する。"""
        raw: object = self._settings.value(_SELECTION_KEY, "", str)
        try:
            decoded: object = (
                json.loads(raw) if isinstance(raw, str) and raw else {}
            )
            if isinstance(decoded, dict):
                payload = cast(dict[str, object], decoded)
                group = payload.get("group")
                self._active_group = group if isinstance(group, str) else None
                presets = payload.get("presets")
                if isinstance(presets, dict):
                    self._preset_selections = {
                        key: value
                        for key, value in cast(
                            dict[str, object], presets
                        ).items()
                        if isinstance(value, str)
                    }
        except ValueError:
            self._active_group = None
        self._ensure_group()

    def _load(self) -> None:
        """旧一覧またはグループ登録を読み、共有構成を初期化する。"""
        raw: object = self._settings.value(_SETTINGS_KEY, "", str)
        try:
            if raw in ("", None):
                self._migrate(())
            else:
                if not isinstance(raw, str):
                    raise ValueError("登録設定は文字列である必要があります")
                decoded: object = json.loads(raw)
                if not isinstance(decoded, dict):
                    raise ValueError("登録設定はobjectである必要があります")
                payload = cast(dict[str, object], decoded)
                if payload.get("version") == 1:
                    self._migrate(
                        self._legacy_references(payload.get("files"))
                    )
                elif payload.get("version") == 2:
                    groups = payload.get("groups")
                    if not isinstance(groups, list) or not all(
                        isinstance(path, str)
                        for path in cast(list[object], groups)
                    ):
                        raise ValueError(
                            "groupsはパスの配列である必要があります"
                        )
                    self._roots = list(
                        dict.fromkeys(
                            normalize_filter_path(path)
                            for path in cast(list[str], groups)
                        )
                    )
                    self._saved_roots = tuple(self._roots)
                else:
                    raise ValueError("未対応の登録設定versionです")
            self._load_graph()
            self._load_selection()
        except (OSError, ValueError) as error:
            self._storage_error = (
                f"カスタムフィルター登録設定を読めません: {error}"
            )

    @staticmethod
    def _legacy_references(files: object) -> tuple[FilterReference, ...]:
        """旧一覧の登録順と表示状態を、移行用の参照へ変換する。"""
        if not isinstance(files, list):
            raise ValueError("登録設定のfilesは配列である必要があります")
        result: list[FilterReference] = []
        known: set[str] = set()
        for item in cast(list[object], files):
            if not isinstance(item, dict):
                raise ValueError(
                    "登録設定の各項目はobjectである必要があります"
                )
            record = cast(dict[str, object], item)
            path, enabled = record.get("path"), record.get("enabled")
            if not isinstance(path, str) or not isinstance(enabled, bool):
                raise ValueError("登録設定のpathまたはenabledが不正です")
            normalized = normalize_filter_path(path)
            if normalized not in known:
                result.append(FilterReference(normalized, enabled))
                known.add(normalized)
        return tuple(result)

    def _migrate(self, references: tuple[FilterReference, ...]) -> None:
        """既存JSONを動かさず、旧登録一覧を既定グループへ保存する。"""
        directory = (
            get_ui_settings_file("bd_channel_box/preferences/main").parent
            / "custom_filter"
        )
        preset_directory, group_directory = (
            directory / "preset",
            directory / "preset_group",
        )
        preset_directory.mkdir(parents=True, exist_ok=True)
        group_directory.mkdir(parents=True, exist_ok=True)
        preset = create_preset_document(
            self._available_default(preset_directory), "preset", references
        )
        group = create_preset_document(
            self._available_default(group_directory),
            "preset_group",
            (FilterReference(preset.path),),
        )
        self._documents["preset", preset.path] = preset
        self._documents["preset_group", group.path] = group
        self._roots = [group.path]
        self._save()

    @staticmethod
    def _available_default(directory: Path) -> Path:
        """既存の共有JSONを上書きしない既定名を返す。"""
        path = directory / "Default.json"
        suffix = 2
        while path.exists():
            path = directory / f"Default_{suffix}.json"
            suffix += 1
        return path

    def _save(self) -> None:
        """グループ登録だけを個人設定へ確定し、失敗時は未保存状態を保つ。"""
        self._settings.setValue(
            _SETTINGS_KEY,
            json.dumps(
                {"version": 2, "groups": self._roots}, ensure_ascii=False
            ),
        )
        self._settings.sync()
        if self._settings.status() == qt.QSettings.Status.NoError:
            self._saved_roots = tuple(self._roots)
            self._storage_error = None
        else:
            self._storage_error = (
                "カスタムフィルター登録設定を保存できませんでした"
            )
