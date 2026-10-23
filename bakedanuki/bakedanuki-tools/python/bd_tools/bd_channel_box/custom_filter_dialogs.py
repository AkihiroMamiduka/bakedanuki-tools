# coding: utf-8
"""共有フィルターの名前・保存先選択と新規登録の経路をまとめる。"""

from __future__ import annotations

from pathlib import Path

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt

from .custom_filter_editor import (
    create_custom_filter,
    duplicate_custom_filter,
    filter_file_name,
)
from .custom_filter_registry import CustomFilterRegistry
from .custom_filters import CustomFilterError, load_custom_filter

__all__ = ["create_registered_filter"]


def create_registered_filter(
    parent: qt.QWidget,
    registry: CustomFilterRegistry,
    *,
    source: str | None = None,
) -> str | None:
    """保存先のファイル名を表示名にして新規・複製JSONをONで登録する。

    未保存編集の確認は呼出し側で先に行う。中止・失敗時はNoneを返し、
    ファイルや登録を作成しない。
    """
    initial_name = ""
    if source is not None:
        try:
            initial_name = load_custom_filter(source).name + "_copy"
        except CustomFilterError as error:
            qt.QMessageBox.warning(parent, "複製できません", str(error))
            return None

    # 新規作成はMaya version別のprefs内、複製は元JSONのフォルダーを開く
    directory = (
        get_ui_settings_file("bd_channel_box/preferences/main").parent
        / "custom_filter"
        if source is None
        else Path(source).parent
    )
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        qt.QMessageBox.warning(
            parent,
            "作成できません",
            f"保存先フォルダーを用意できません: {directory}（{error}）",
        )
        return None
    suggested = directory
    if initial_name:
        try:
            suggested /= filter_file_name(initial_name) + ".json"
        except CustomFilterError:
            # 旧JSONの表示名がファイル名に使えない場合は元の実ファイル名を使う
            assert source is not None
            suggested /= Path(source).stem + "_copy.json"

    # 既存ファイルの指定時は保護したまま保存先を選び直せるようにする
    while True:
        path, _selected_filter = qt.QFileDialog.getSaveFileName(
            parent,
            (
                "カスタムフィルターを複製"
                if source is not None
                else "カスタムフィルターを新規作成"
            ),
            str(suggested),
            "JSON ファイル (*.json)",
        )
        if not path:
            return None
        if not path.lower().endswith(".json"):
            path += ".json"
        suggested = Path(path)
        try:
            name = filter_file_name(suggested.name)
            path = str(suggested.with_name(name + ".json"))
            created = (
                create_custom_filter(path, name)
                if source is None
                else duplicate_custom_filter(source, path, name)
            )
        except CustomFilterError as error:
            qt.QMessageBox.warning(parent, "作成できません", str(error))
            continue
        break

    # 以前の読込エラー登録に保存した場合も、新しい定義を有効にする
    if not registry.add_paths((created,)):
        registry.reload(created)
        registry.set_enabled(created, True)
    return created
