# coding: utf-8
"""値編集モードの属性フィルター選択をMaya version別の個人設定へ保存する。"""

from __future__ import annotations

from collections.abc import Mapping

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt

from .controller import ChannelDisplayFilter
from .custom_filters import (
    CustomFilterError,
    CustomFilterSelection,
    normalize_filter_path,
)

__all__ = ["ValueFilterPreferences"]

_SETTINGS_KEY = "preferences/main/values_attribute_filter"
_STANDARD_FILTERS = ("all", "visible", "keyable", "channel_box", "hidden")
_CUSTOM_PREFIX = "custom:"


class ValueFilterPreferences:
    """標準IDかJSON pathだけを記憶し、利用可能なカスタム定義へ復元する。"""

    def __init__(self) -> None:
        """ほかの操作設定と同じui.iniを開き、最後に同期した選択を保持する。"""
        settings_file = get_ui_settings_file("bd_channel_box/preferences/main")
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        self._settings = qt.QSettings(
            str(settings_file), qt.QSettings.Format.IniFormat
        )
        self._last_saved: str | None = None

    def restore(
        self, available: Mapping[str, CustomFilterSelection]
    ) -> ChannelDisplayFilter:
        """登録・ON・正常読込済みの選択を復元し、利用不能なら標準表示に戻す。"""
        raw: object = self._settings.value(_SETTINGS_KEY, "visible", str)
        if isinstance(raw, str):
            if raw in _STANDARD_FILTERS:
                return raw
            if raw.startswith(_CUSTOM_PREFIX):
                try:
                    path = normalize_filter_path(raw[len(_CUSTOM_PREFIX) :])
                except CustomFilterError:
                    return "visible"
                return available.get(path, "visible")
        return "visible"

    def save(self, value: ChannelDisplayFilter) -> bool:
        """選択変更を同期し、名前変更や表示順変更で保存値を変えない。"""
        identifier = (
            _CUSTOM_PREFIX + value.path
            if isinstance(value, CustomFilterSelection)
            else value
        )
        if identifier != self._last_saved:
            self._settings.setValue(_SETTINGS_KEY, identifier)
            self._settings.sync()
            if self._settings.status() != qt.QSettings.Status.NoError:
                return False
            self._last_saved = identifier
        return True
