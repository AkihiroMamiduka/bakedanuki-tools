# coding: utf-8
"""共有フィルターの登録順と有効状態を個人設定へ保存する。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt

from .custom_filters import (
    CustomFilterDefinition,
    CustomFilterError,
    load_custom_filter,
    normalize_filter_path,
)

__all__ = ["CustomFilterRegistration", "CustomFilterRegistry"]

_SETTINGS_PATH = "bd_channel_box/preferences/custom_filters"
_SETTINGS_KEY = "preferences/custom_filters/registrations"
_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CustomFilterRegistration:
    """個人設定の登録と、共有ファイルの現在の読込結果を保持する。"""

    path: str
    enabled: bool
    definition: CustomFilterDefinition | None
    error: str | None


class CustomFilterRegistry(qt.QObject):
    """登録一覧を Maya の個人設定へ保存し、共有 JSON を読み直す。"""

    changed = qt.Signal()
    path_changed = qt.Signal(str, str)

    def __init__(self, parent: qt.QObject | None = None) -> None:
        """既存登録を読み込み、現在参照できる共有定義を取得する。"""
        super().__init__(parent)
        settings_file = get_ui_settings_file(_SETTINGS_PATH)
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        self._settings = qt.QSettings(
            str(settings_file), qt.QSettings.Format.IniFormat
        )
        self._entries: list[CustomFilterRegistration] = []
        self._storage_error: str | None = None
        self._load()

    @property
    def entries(self) -> tuple[CustomFilterRegistration, ...]:
        """登録順を維持した現在の一覧を返す。"""
        return tuple(self._entries)

    @property
    def storage_error(self) -> str | None:
        """個人設定の読込・保存エラーを返す。"""
        return self._storage_error

    def add_paths(self, paths: Iterable[str | Path]) -> tuple[str, ...]:
        """重複しないパスを末尾に登録し、読込失敗も一覧へ残す。"""
        # 全パスを先に検証し、途中の不正値で登録だけが一部増えるのを防ぐ
        normalized_paths = tuple(normalize_filter_path(path) for path in paths)
        added: list[str] = []
        known = {entry.path for entry in self._entries}
        for normalized in normalized_paths:
            if normalized in known:
                continue
            self._entries.append(self._read_entry(normalized, enabled=True))
            known.add(normalized)
            added.append(normalized)
        if added:
            self._save()
            self.changed.emit()
        return tuple(added)

    def remove(self, path: str) -> bool:
        """登録のみを削除し、参照先の共有ファイルは残す。"""
        return self.remove_many((path,))

    def remove_many(self, paths: Iterable[str]) -> bool:
        """選択登録を一括解除し、共有ファイルを残して一度だけ保存・通知する。"""
        selected = set(paths)
        remaining = [
            entry for entry in self._entries if entry.path not in selected
        ]
        if len(remaining) == len(self._entries):
            return False
        self._entries = remaining
        self._save()
        self.changed.emit()
        return True

    def replace_path(
        self,
        old_path: str,
        new_path: str,
        *,
        saved_definition: CustomFilterDefinition | None = None,
    ) -> bool:
        """保存済み改名先へ登録を移し、確定済みの定義と選択を引き継ぐ。"""
        normalized_old = normalize_filter_path(old_path)
        normalized_new = normalize_filter_path(new_path)
        index = self._index_of(normalized_old)
        if index is None or normalized_old == normalized_new:
            return False
        if self._index_of(normalized_new) is not None:
            raise CustomFilterError("変更先のファイルは既に登録されています")

        # 保存直後は検証済み定義を引き継ぎ、再読込失敗による登録の孤立を防ぐ
        definition = (
            load_custom_filter(normalized_new)
            if saved_definition is None
            else saved_definition
        )
        current = self._entries[index]
        self._entries[index] = CustomFilterRegistration(
            normalized_new, current.enabled, definition, None
        )
        self._save()

        # 一覧更新で旧pathが利用不能と判定される前に保持選択を移す
        self.path_changed.emit(normalized_old, normalized_new)
        self.changed.emit()
        return True

    def set_enabled(self, path: str, enabled: bool) -> bool:
        """登録位置を変えずに ComboBox への表示可否を切り替える。"""
        index = self._index_of(path)
        if index is None or self._entries[index].enabled == enabled:
            return False
        self._entries[index] = replace(self._entries[index], enabled=enabled)
        self._save()
        self.changed.emit()
        return True

    def move(self, path: str, offset: int) -> bool:
        """登録を一段上下へ移動し、順序を個人設定へ保存する。"""
        return self.move_many((path,), offset)

    def move_many(self, paths: Iterable[str], offset: int) -> bool:
        """選択登録の相対順を保ち、全件を一段移動して一度だけ保存・通知する。"""
        if offset not in (-1, 1):
            raise ValueError("移動量には-1または1を指定してください")
        selected = set(paths)
        indices = tuple(
            index
            for index, entry in enumerate(self._entries)
            if entry.path in selected
        )
        if not indices or not 0 <= indices[
            0 if offset < 0 else -1
        ] + offset < len(self._entries):
            return False

        # 上方向は前から、下方向は後ろから入れ替えて選択間の順序を保つ
        for index in indices if offset < 0 else reversed(indices):
            self._entries[index], self._entries[index + offset] = (
                self._entries[index + offset],
                self._entries[index],
            )
        self._save()
        self.changed.emit()
        return True

    def reload(self, path: str) -> bool:
        """選択した共有ファイルを読み直し、登録は変更しない。"""
        index = self._index_of(path)
        if index is None:
            return False
        current = self._entries[index]
        self._entries[index] = self._read_entry(path, current.enabled)
        self.changed.emit()
        return True

    def reload_all(self) -> None:
        """全登録の共有ファイルを読み直して表示へ通知する。"""
        self._entries = [
            self._read_entry(entry.path, entry.enabled)
            for entry in self._entries
        ]
        self.changed.emit()

    def _index_of(self, path: str) -> int | None:
        """正規化済みパスと一致する登録位置を返す。"""
        return next(
            (
                index
                for index, entry in enumerate(self._entries)
                if entry.path == path
            ),
            None,
        )

    @staticmethod
    def _read_entry(path: str, enabled: bool) -> CustomFilterRegistration:
        """不正な共有ファイルも登録として残し、理由を記録する。"""
        try:
            definition = load_custom_filter(path)
        except CustomFilterError as error:
            return CustomFilterRegistration(path, enabled, None, str(error))
        return CustomFilterRegistration(path, enabled, definition, None)

    def _load(self) -> None:
        """個人設定の形式を検証して、登録順と ON/OFF を復元する。"""
        raw: object = self._settings.value(_SETTINGS_KEY, "", str)
        if self._settings.status() != qt.QSettings.Status.NoError:
            self._storage_error = (
                "カスタムフィルター登録設定を読めませんでした"
            )
            return
        if raw == "" or raw is None:
            return
        try:
            if not isinstance(raw, str):
                raise ValueError("登録設定は文字列である必要があります")
            decoded: object = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("登録設定は JSON object である必要があります")
            payload = cast(dict[str, object], decoded)
            if payload.get("version") != _SCHEMA_VERSION:
                raise ValueError("未対応の登録設定 version です")
            files = payload.get("files")
            if not isinstance(files, list):
                raise ValueError("登録設定の files は配列である必要があります")
            known: set[str] = set()
            for item in cast(list[object], files):
                if not isinstance(item, dict):
                    raise ValueError(
                        "登録設定の各項目は object である必要があります"
                    )
                record = cast(dict[str, object], item)
                path = record.get("path")
                enabled = record.get("enabled")
                if not isinstance(path, str) or not isinstance(enabled, bool):
                    raise ValueError(
                        "登録設定の path または enabled が不正です"
                    )
                normalized = normalize_filter_path(path)
                if normalized in known:
                    continue
                self._entries.append(self._read_entry(normalized, enabled))
                known.add(normalized)
        except (TypeError, ValueError) as error:
            self._entries.clear()
            self._storage_error = (
                f"カスタムフィルター登録設定を読めません: {error}"
            )

    def _save(self) -> None:
        """共有 JSON は複製せず、登録パス・有効状態・順序を保存する。"""
        payload = {
            "version": _SCHEMA_VERSION,
            "files": [
                {"path": entry.path, "enabled": entry.enabled}
                for entry in self._entries
            ],
        }
        self._settings.setValue(
            _SETTINGS_KEY, json.dumps(payload, ensure_ascii=False)
        )
        self._settings.sync()
        if self._settings.status() == qt.QSettings.Status.NoError:
            self._storage_error = None
        else:
            self._storage_error = (
                "カスタムフィルター登録設定を保存できませんでした"
            )
