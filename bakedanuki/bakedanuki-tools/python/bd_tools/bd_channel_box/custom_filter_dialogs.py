# coding: utf-8
"""共有フィルターの名前・保存先選択と新規登録の経路をまとめる。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import exec_dialog_near, get_save_file_name_near, qt

from .custom_filter_editor import (
    create_custom_filter,
    duplicate_custom_filter,
    filter_file_name,
)
from .custom_filter_registry import CustomFilterRegistry
from .custom_filters import CustomFilterError, load_custom_filter

__all__ = [
    "create_registered_filter",
    "create_registered_preset",
    "default_filter_directory",
    "initial_filter_directory",
    "rename_registered_preset",
]


def default_filter_directory(
    kind: Literal["preset_group", "preset", "filter"],
) -> Path:
    """使用中のMayaのprefsにある種類別の作成先を返す。"""
    return (
        get_ui_settings_file("bd_channel_box/preferences/main").parent
        / "custom_filter"
        / kind
    )


def initial_filter_directory(
    kind: Literal["preset_group", "preset", "filter"],
    reference_path: str | Path | None = None,
) -> Path:
    """基準JSONの既存フォルダーを優先し、利用できなければ種類別prefsを用意する。"""
    if reference_path is not None:
        try:
            directory = Path(reference_path).expanduser().resolve().parent
            if directory.is_dir():
                return directory
        except OSError:
            # 利用不能な共有先は再作成せず、個人用の初期フォルダーへ戻す
            pass
    directory = default_filter_directory(kind)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def create_registered_filter(
    parent: qt.QWidget,
    registry: CustomFilterRegistry,
    *,
    source: str | None = None,
    reference_path: str | Path | None = None,
    position: qt.QPoint | None = None,
) -> str | None:
    """保存先のファイル名を表示名にして新規・複製JSONをONで登録する。

    未保存編集の確認は呼出し側で先に行う。中止・失敗時はNoneを返し、
    ファイルや登録を作成しない。
    """
    anchor = qt.QPoint(position) if position is not None else qt.QCursor.pos()
    if not any(
        entry.path == registry.active_preset and entry.error is None
        for entry in registry.presets
    ):
        qt.QMessageBox.warning(
            parent,
            "作成できません",
            "正常に読み込めるプリセットを選択してください。",
        )
        return None
    initial_name = ""
    if source is not None:
        try:
            initial_name = load_custom_filter(source).name + "_copy"
        except CustomFilterError as error:
            qt.QMessageBox.warning(parent, "複製できません", str(error))
            return None

    try:
        directory = initial_filter_directory(
            "filter", source if source is not None else reference_path
        )
    except OSError as error:
        qt.QMessageBox.warning(
            parent,
            "作成できません",
            f"保存先フォルダーを用意できません: {error}",
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
        path, _selected_filter = get_save_file_name_near(
            parent,
            (
                "カスタムフィルターを複製"
                if source is not None
                else "カスタムフィルターを新規作成"
            ),
            str(suggested),
            "JSON ファイル (*.json)",
            anchor,
            "json",
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


def create_registered_preset(
    parent: qt.QWidget,
    registry: CustomFilterRegistry,
    kind: Literal["preset_group", "preset"],
    *,
    source: str | None = None,
    reference_path: str | Path | None = None,
    position: qt.QPoint | None = None,
) -> str | None:
    """保存先を選び、空または複製した文書を作成して登録する。"""
    anchor = qt.QPoint(position) if position is not None else qt.QCursor.pos()
    if kind == "preset" and not any(
        item.path == registry.active_group and item.error is None
        for item in registry.groups
    ):
        qt.QMessageBox.warning(
            parent,
            "作成できません",
            "正常に読み込めるプリセットグループを選択してください。",
        )
        return None
    label = "プリセットグループ" if kind == "preset_group" else "プリセット"
    entries = registry.groups if kind == "preset_group" else registry.presets
    entry = next((item for item in entries if item.path == source), None)
    if source is not None and entry is None:
        return None
    try:
        directory = initial_filter_directory(
            kind, source if source is not None else reference_path
        )
    except OSError as error:
        qt.QMessageBox.warning(parent, "作成できません", str(error))
        return None
    suggested = (
        directory if entry is None else directory / (entry.name + "_copy.json")
    )
    title = label + ("を新規作成" if source is None else "を複製")
    while True:
        path, _selected_filter = get_save_file_name_near(
            parent,
            title,
            str(suggested),
            "JSON ファイル (*.json)",
            anchor,
            "json",
        )
        if not path:
            return None
        suggested = Path(path)
        try:
            name = filter_file_name(suggested.name)
            suggested = suggested.with_name(name + ".json")
            create = (
                registry.create_group
                if kind == "preset_group"
                else registry.create_preset
            )
            return create(str(suggested), source=source)
        except (CustomFilterError, OSError) as error:
            qt.QMessageBox.warning(parent, "作成できません", str(error))


def rename_registered_preset(
    parent: qt.QWidget,
    registry: CustomFilterRegistry,
    kind: Literal["preset_group", "preset"],
    path: str,
    *,
    position: qt.QPoint | None = None,
) -> bool:
    """既存ファイルとの衝突を入力中に示し、改名予定を下書きへ反映する。"""
    anchor = qt.QPoint(position) if position is not None else qt.QCursor.pos()
    entries = registry.groups if kind == "preset_group" else registry.presets
    entry = next((item for item in entries if item.path == path), None)
    if entry is None or entry.error is not None:
        return False
    label = "プリセットグループ" if kind == "preset_group" else "プリセット"
    dialog = qt.QDialog(parent)
    dialog.setWindowTitle(label + "名を変更")
    name_edit = qt.QLineEdit(dialog)
    name_edit.setObjectName("renamePresetName")
    name_edit.setText(entry.name)
    name_edit.selectAll()
    message = qt.QLabel(dialog)
    message.setObjectName("renamePresetError")
    message.setWordWrap(True)
    buttons = qt.QDialogButtonBox(
        qt.QDialogButtonBox.StandardButton.Ok
        | qt.QDialogButtonBox.StandardButton.Cancel,
        dialog,
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout = qt.QVBoxLayout(dialog)
    layout.addWidget(qt.QLabel(label + "名（拡張子 .json は省略可）:", dialog))
    layout.addWidget(name_edit)
    layout.addWidget(message)
    layout.addWidget(buttons)

    def validate(text: str) -> None:
        """入力先の競合を示し、確定できる場合だけOKを有効にする。"""
        error = registry.rename_error(kind, path, text)
        message.setText(error or "")
        ok = cast(
            qt.QPushButton | None,
            buttons.button(qt.QDialogButtonBox.StandardButton.Ok),
        )
        if ok is not None:
            ok.setEnabled(error is None)

    name_edit.textChanged.connect(validate)
    validate(name_edit.text())
    name_edit.setFocus()
    accepted = (
        exec_dialog_near(dialog, anchor) == qt.QDialog.DialogCode.Accepted
    )
    name = name_edit.text()
    dialog.deleteLater()
    if not accepted:
        return False
    try:
        rename: Callable[[str, str], bool] = (
            registry.rename_group
            if kind == "preset_group"
            else registry.rename_preset
        )
        rename(path, name)
    except CustomFilterError as error:
        qt.QMessageBox.warning(parent, "名前を変更できません", str(error))
        return False
    return True
