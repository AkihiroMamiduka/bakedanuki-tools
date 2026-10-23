# coding: utf-8
"""共有フィルターの名前・保存先選択と新規登録の経路をまとめる。"""

from __future__ import annotations

from pathlib import Path

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt

from .custom_filter_editor import create_custom_filter, duplicate_custom_filter
from .custom_filter_registry import CustomFilterRegistry
from .custom_filters import CustomFilterError, load_custom_filter

__all__ = ["create_registered_filter"]


def create_registered_filter(
    parent: qt.QWidget,
    registry: CustomFilterRegistry,
    *,
    source: str | None = None,
) -> str | None:
    """名前と保存先を選んで新規・複製JSONをONで登録し、pathを返す。

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

    # 名前入力と保存先の選択を終えてからファイルを作成する
    dialog = qt.QDialog(parent)
    dialog.setWindowTitle(
        "カスタムフィルターを複製"
        if source is not None
        else "カスタムフィルターを新規作成"
    )
    name_edit = qt.QLineEdit(dialog)
    name_edit.setObjectName("newCustomFilterName")
    name_edit.setText(initial_name)
    name_edit.selectAll()
    buttons = qt.QDialogButtonBox(
        qt.QDialogButtonBox.StandardButton.Ok
        | qt.QDialogButtonBox.StandardButton.Cancel,
        dialog,
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout = qt.QVBoxLayout(dialog)
    layout.addWidget(qt.QLabel("フィルター名:", dialog))
    layout.addWidget(name_edit)
    layout.addWidget(buttons)
    name_edit.setFocus()
    accepted = dialog.exec() == qt.QDialog.DialogCode.Accepted
    name = name_edit.text().strip() if accepted else ""
    dialog.deleteLater()
    if not accepted:
        return None
    if not name or any(ord(char) < 32 for char in name):
        qt.QMessageBox.warning(
            parent, "作成できません", "名前は空でない1行にしてください。"
        )
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
    suggested = directory / (name + ".json")
    path, _selected_filter = qt.QFileDialog.getSaveFileName(
        parent,
        "カスタムフィルター定義の保存先",
        str(suggested),
        "JSON ファイル (*.json)",
    )
    if not path:
        return None
    if not path.lower().endswith(".json"):
        path += ".json"
    try:
        created = (
            create_custom_filter(path, name)
            if source is None
            else duplicate_custom_filter(source, path, name)
        )
    except CustomFilterError as error:
        qt.QMessageBox.warning(parent, "作成できません", str(error))
        return None

    # 以前の読込エラー登録に保存した場合も、新しい定義を有効にする
    if not registry.add_paths((created,)):
        registry.reload(created)
        registry.set_enabled(created, True)
    return created
