# coding: utf-8
"""共有フィルターの名前・保存先選択と新規登録の経路をまとめる。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from bd_util.maya.ui import (
    get_ui_settings_file,
    get_save_file_name_near as maya_save_file_name_near,
    get_open_file_names_near as maya_open_file_names_near,
)
from bd_util.ui import (
    PathLineEdit,
    exec_dialog_near,
    qt,
)
from bd_util.ui import dialog as ui_dialog

from . import config
from .custom_filter_files import FileOperationPlan
from .custom_filter_editor import (
    create_custom_filter,
    duplicate_custom_filter,
    filter_file_name,
)
from .custom_filter_registry import CustomFilterRegistry
from .custom_filters import CustomFilterError, load_custom_filter

__all__ = [
    "CustomFilterExportCompleteDialog",
    "confirm_export_save",
    "create_registered_filter",
    "create_registered_preset",
    "default_filter_directory",
    "initial_filter_directory",
    "rename_registered_preset",
    "get_save_file_name_near",
    "get_open_file_names_near",
    "confirm_file_operation_save",
    "confirm_file_delete",
]


def get_save_file_name_near(
    parent: qt.QWidget | None,
    caption: str,
    directory: str,
    name_filter: str,
    anchor: qt.QPoint,
    default_suffix: str = "",
) -> tuple[str, str]:
    """ツールで指定した共通寸法をMaya標準の保存先選択へ適用する。"""
    return maya_save_file_name_near(
        parent,
        caption,
        directory,
        name_filter,
        anchor,
        default_suffix,
        initial_size=qt.QSize(
            config.PATH_DIALOG_WIDTH, config.PATH_DIALOG_HEIGHT
        ),
    )


def get_open_file_names_near(
    parent: qt.QWidget | None,
    caption: str,
    directory: str,
    name_filter: str,
    anchor: qt.QPoint,
) -> tuple[list[str], str]:
    """ツールで指定した共通寸法をMaya標準の複数ファイル選択へ適用する。"""
    return maya_open_file_names_near(
        parent,
        caption,
        directory,
        name_filter,
        anchor,
        initial_size=qt.QSize(
            config.PATH_DIALOG_WIDTH, config.PATH_DIALOG_HEIGHT
        ),
    )


def confirm_file_operation_save(
    parent: qt.QWidget, position: qt.QPoint
) -> bool:
    """移動・削除の前に保存するか、未保存編集を維持して中止するか確認する。"""
    dialog = qt.QMessageBox(parent)
    dialog.setWindowTitle("ファイル操作前に保存")
    dialog.setIcon(qt.QMessageBox.Icon.Warning)
    dialog.setText(
        "未保存の変更があります。\n変更をすべて保存してからファイル操作を続けますか？"
    )
    dialog.setStandardButtons(
        qt.QMessageBox.StandardButton.Save
        | qt.QMessageBox.StandardButton.Cancel
    )
    dialog.button(qt.QMessageBox.StandardButton.Save).setText("保存して続ける")
    dialog.button(qt.QMessageBox.StandardButton.Cancel).setText("キャンセル")
    dialog.setDefaultButton(qt.QMessageBox.StandardButton.Cancel)
    try:
        return (
            exec_dialog_near(dialog, position)
            == qt.QMessageBox.StandardButton.Save
        )
    finally:
        dialog.deleteLater()


def confirm_file_delete(
    parent: qt.QWidget, plan: FileOperationPlan, position: qt.QPoint
) -> bool:
    """全削除対象と対象別の参照元を確認し、既定で取り消す実削除確認を行う。"""
    dialog = qt.QDialog(parent)
    dialog.setObjectName("customFilterFileDeleteConfirm")
    dialog.setWindowTitle("ファイルを削除")
    dialog.resize(760, 420)
    description = qt.QLabel(
        f"選択したJSONファイル {len(plan.paths)} 件を削除します。\n"
        "この操作は取り消せません。\n\n"
        "登録済みグループからたどれる参照元から、削除対象への参照を取り除きます。\n"
        "削除対象が参照しているファイルは削除しません。",
        dialog,
    )
    description.setWordWrap(True)
    # 選択は影響範囲の閲覧だけに使い、実削除の予定全件は変更しない
    targets = qt.QComboBox(dialog)
    targets.setObjectName("deleteFileCombo")
    targets.setAccessibleName("削除するファイル")
    targets.setSizeAdjustPolicy(
        qt.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    targets.setMinimumContentsLength(40)
    targets.view().setTextElideMode(qt.Qt.TextElideMode.ElideLeft)
    for deletion in plan.deletions:
        path = str(Path(deletion.source).resolve())
        targets.addItem(path, deletion.source)
        targets.setItemData(
            targets.count() - 1, path, qt.Qt.ItemDataRole.ToolTipRole
        )
    target_label = qt.QLabel(
        f"削除するファイル（{len(plan.paths)}件）", dialog
    )
    target_label.setBuddy(targets)

    # 個別対象を直接参照していて、今回実際に更新する共有JSONだけを表示する
    references = qt.QListWidget(dialog)
    references.setObjectName("deleteReferenceList")
    references.setAccessibleName("更新する参照元ファイル")
    references.setEditTriggers(qt.QAbstractItemView.EditTrigger.NoEditTriggers)
    references.setUniformItemSizes(True)
    references.setTextElideMode(qt.Qt.TextElideMode.ElideNone)
    reference_label = qt.QLabel(dialog)
    reference_label.setObjectName("deleteReferenceLabel")
    reference_label.setBuddy(references)

    def update_references(index: int) -> None:
        """確認中の対象の参照元と件数を切り替え、全文パスを案内する。"""
        path: object = targets.itemData(index)
        sources = (
            plan.reference_sources_for(path) if isinstance(path, str) else ()
        )
        targets.setToolTip(targets.itemText(index))
        references.clear()
        for source in sources:
            full_path = str(Path(source).resolve())
            item = qt.QListWidgetItem(full_path)
            item.setToolTip(full_path)
            references.addItem(item)
        reference_label.setText(f"更新する参照元ファイル（{len(sources)}件）")

    targets.currentIndexChanged.connect(update_references)
    update_references(targets.currentIndex())
    buttons = qt.QDialogButtonBox(
        qt.QDialogButtonBox.StandardButton.Ok
        | qt.QDialogButtonBox.StandardButton.Cancel,
        dialog,
    )
    ok = buttons.button(qt.QDialogButtonBox.StandardButton.Ok)
    cancel = buttons.button(qt.QDialogButtonBox.StandardButton.Cancel)
    ok.setText(f"{len(plan.paths)}件のファイルを削除")
    ok.setDefault(False)
    ok.setAutoDefault(False)
    cancel.setText("キャンセル")
    cancel.setDefault(True)
    cancel.setFocus()
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout = qt.QVBoxLayout(dialog)
    layout.addWidget(description)
    layout.addWidget(target_label)
    layout.addWidget(targets)
    layout.addWidget(reference_label)
    layout.addWidget(references, 1)
    layout.addWidget(buttons)
    try:
        return (
            exec_dialog_near(dialog, position)
            == qt.QDialog.DialogCode.Accepted
        )
    finally:
        dialog.deleteLater()


class CustomFilterExportCompleteDialog(qt.QDialog):
    """出力結果と、コピー・Explorer操作が可能なパス欄を表示する。"""

    def __init__(self, destination: Path, parent: qt.QWidget) -> None:
        """長いパスも横スクロールで確認できる完了画面を構成する。"""
        super().__init__(parent)
        self.setObjectName("customFilterExportCompleteDialog")
        self.setWindowTitle("エクスポート完了")
        self.resize(640, 150)
        self.path_edit = PathLineEdit(destination, self)
        self.path_edit.setObjectName("exportDestinationPath")
        self.path_edit.setAccessibleName("エクスポート先のフルパス")
        buttons = qt.QDialogButtonBox(
            qt.QDialogButtonBox.StandardButton.Ok, self
        )
        buttons.accepted.connect(self.accept)
        layout = qt.QVBoxLayout(self)
        layout.addWidget(
            qt.QLabel("カスタムフィルターの関連ファイルを出力しました。", self)
        )
        layout.addWidget(self.path_edit)
        layout.addWidget(buttons)


def confirm_export_save(parent: qt.QWidget, position: qt.QPoint) -> bool:
    """編集内容を維持して中止するか、保存して出力を続けるか確認する。"""
    dialog = qt.QMessageBox(parent)
    dialog.setWindowTitle("エクスポート前に保存")
    dialog.setIcon(qt.QMessageBox.Icon.Warning)
    dialog.setText(
        "カスタムフィルター設定に未保存の変更があります。\n"
        "変更を保存してからエクスポートしますか？"
    )
    dialog.setStandardButtons(
        qt.QMessageBox.StandardButton.Save
        | qt.QMessageBox.StandardButton.Cancel
    )
    dialog.button(qt.QMessageBox.StandardButton.Save).setText(
        "保存してエクスポート"
    )
    dialog.button(qt.QMessageBox.StandardButton.Cancel).setText("キャンセル")
    dialog.setDefaultButton(qt.QMessageBox.StandardButton.Save)
    try:
        return (
            exec_dialog_near(dialog, position)
            == qt.QMessageBox.StandardButton.Save
        )
    finally:
        dialog.deleteLater()


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
        ui_dialog.warning_near(
            parent,
            "作成できません",
            "正常に読み込めるプリセットを選択してください。",
            anchor,
        )
        return None
    initial_name = ""
    if source is not None:
        try:
            initial_name = load_custom_filter(source).name + "_copy"
        except CustomFilterError as error:
            ui_dialog.warning_near(
                parent, "複製できません", str(error), anchor
            )
            return None

    try:
        directory = initial_filter_directory(
            "filter", source if source is not None else reference_path
        )
    except OSError as error:
        ui_dialog.warning_near(
            parent,
            "作成できません",
            f"保存先フォルダーを用意できません: {error}",
            anchor,
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
            ui_dialog.warning_near(
                parent, "作成できません", str(error), anchor
            )
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
        ui_dialog.warning_near(
            parent,
            "作成できません",
            "正常に読み込めるプリセットグループを選択してください。",
            anchor,
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
        ui_dialog.warning_near(parent, "作成できません", str(error), anchor)
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
            ui_dialog.warning_near(
                parent, "作成できません", str(error), anchor
            )


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
        ui_dialog.warning_near(
            parent, "名前を変更できません", str(error), anchor
        )
        return False
    return True
