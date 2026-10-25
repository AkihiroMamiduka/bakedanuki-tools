# coding: utf-8
"""共有グループ・プリセット・フィルターを3段の一覧で管理する。"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Literal, cast

from bd_util.ui import (
    exec_dialog_near,
    get_existing_directory_near,
    get_open_file_names_near,
    qt,
)
from bd_util.ui import dialog as ui_dialog

from .._shared.window_position import centered_position_within_screen
from .custom_filter_dialogs import (
    confirm_export_save,
    create_registered_filter,
    create_registered_preset,
    initial_filter_directory,
    rename_registered_preset,
)
from .custom_filter_export import ExportKind, export_custom_filter_files
from .custom_filter_manager_view import (
    CustomFilterRegistrationTree,
    create_manager_tool_button,
)
from .custom_filter_registry import (
    CustomFilterRegistration,
    CustomFilterRegistry,
    PresetRegistration,
)
from .custom_filters import normalize_filter_path
from .custom_filters import CustomFilterError, filter_display_name

__all__ = ["CustomFilterManagerDialog"]

_PresetKind = Literal["preset_group", "preset"]


def _configure_tree(tree: qt.QTreeWidget, name: str) -> None:
    """名前と状態を内容幅、ファイルパスを伸縮列にして複数行を扱う。"""
    set_labels = cast(
        Callable[[list[str]], None], getattr(tree, "setHeaderLabels")
    )
    set_labels([name, "ファイルパス", "読込状態"])
    tree.setRootIsDecorated(False)
    tree.setUniformRowHeights(True)
    tree.setSortingEnabled(False)
    tree.setSelectionBehavior(
        qt.QAbstractItemView.SelectionBehavior.SelectRows
    )
    tree.setSelectionMode(qt.QAbstractItemView.SelectionMode.ExtendedSelection)
    header = tree.header()
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    header.setSectionResizeMode(0, qt.QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, qt.QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(2, qt.QHeaderView.ResizeMode.ResizeToContents)


def _configure_button(
    button: qt.QToolButton, label: str, icon_name: str
) -> None:
    """Mayaの標準アイコンと操作説明を20四方のボタンへ設定する。"""
    icon = qt.QIcon(f":/{icon_name}")
    if icon.pixmap(16, 16).isNull():
        fallback = {
            "nodeGrapherArrowUp.png": "arrowUp.png",
            "nodeGrapherArrowDown.png": "arrowDown.png",
        }.get(icon_name, icon_name)
        icon = qt.QIcon(f":/{fallback}")
    button.setIcon(icon)
    button.setIconSize(qt.QSize(16, 16))
    button.setFixedSize(20, 20)
    button.setToolTip(label)
    button.setAccessibleName(label)


class _PresetSection(qt.QWidget):
    """上位ドキュメントの見出し、操作列、一覧をまとめる。"""

    def __init__(self, name: str, parent: qt.QWidget) -> None:
        """目の切替を持たない一覧と編集操作、右端の出力操作を構成する。"""
        super().__init__(parent)
        self.label = qt.QLabel(name, self)
        self.tree = CustomFilterRegistrationTree(self, show_visibility=False)
        self.tree.setAccessibleName(f"{name}登録一覧")
        _configure_tree(self.tree, f"{name}名")
        self.new_button = create_manager_tool_button(self)
        self.add_button = create_manager_tool_button(self)
        self.duplicate_button = create_manager_tool_button(self)
        self.rename_button = create_manager_tool_button(self)
        self.remove_button = create_manager_tool_button(self)
        self.move_up_button = create_manager_tool_button(self)
        self.move_down_button = create_manager_tool_button(self)
        self.export_button = create_manager_tool_button(self)
        toolbar = qt.QHBoxLayout()
        toolbar.setSpacing(4)
        for button, label, icon in (
            (self.new_button, f"{name}を新規作成", "fileNew.png"),
            (self.add_button, f"既存の{name}を追加", "item_add.png"),
            (self.duplicate_button, f"選択した{name}を複製", "polyCopyUV.png"),
            (
                self.rename_button,
                f"選択した{name}をリネーム",
                "fileTextureEdit.png",
            ),
            (
                self.remove_button,
                "登録から削除（JSONファイルは削除しません）",
                "RS_delete.png",
            ),
            (self.move_up_button, "上へ", "nodeGrapherArrowUp.png"),
            (self.move_down_button, "下へ", "nodeGrapherArrowDown.png"),
        ):
            _configure_button(button, label, icon)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        _configure_button(
            self.export_button,
            f"選択した{name}と関連ファイルをエクスポート",
            "UVTkNudgeUp.png",
        )
        toolbar.addWidget(self.export_button)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label)
        layout.addLayout(toolbar)
        layout.addWidget(self.tree, 1)


class CustomFilterManagerDialog(qt.QDialog):
    """共有JSONの3階層を編集し、現在行に応じて下段を切り替える。"""

    created = qt.Signal(str)
    rename_requested = qt.Signal(str, qt.QPoint)

    def __init__(
        self,
        registry: CustomFilterRegistry,
        parent: qt.QWidget,
        *,
        confirm_create: Callable[[qt.QPoint], bool] | None = None,
        confirm_export: Callable[[qt.QPoint], bool] | None = None,
        save_changes: Callable[[], bool] | None = None,
        discard_changes: Callable[[], None] | None = None,
        changes_pending: Callable[[], bool] | None = None,
        dialog_position: Callable[[], qt.QPoint] | None = None,
    ) -> None:
        """共通保存と各階層の一覧を作り、登録と選択の変更へ追従する。"""
        super().__init__(parent)
        self.registry = registry
        self._confirm_create = confirm_create
        self._confirm_export = confirm_export
        self._dialog_position = dialog_position
        self._save_changes = save_changes
        self._discard_changes = discard_changes
        self._changes_pending = changes_pending
        self._refreshing = False
        self.setObjectName("bdChannelBoxCustomFilterManager")
        self.setWindowTitle("カスタムフィルター管理")
        self.resize(760, 720)
        self._placement_anchor: qt.QPoint | None = None
        self._placement_timer = qt.QTimer(self)
        self._placement_timer.setSingleShot(True)
        self._placement_timer.timeout.connect(self._position_near_anchor)

        # 上位の現在行が下段の表示先、複数選択は一括操作の対象になる
        self.splitter = qt.QSplitter(qt.Qt.Orientation.Vertical, self)
        self._group_section = _PresetSection("プリセットグループ", self)
        self._preset_section = _PresetSection("プリセット", self)
        self.group_tree_widget: qt.QTreeWidget = self._group_section.tree
        self.preset_tree_widget: qt.QTreeWidget = self._preset_section.tree
        self.group_tree_widget.setObjectName("customFilterPresetGroupTree")
        self.preset_tree_widget.setObjectName("customFilterPresetTree")
        self.group_new_button = self._group_section.new_button
        self.group_add_button = self._group_section.add_button
        self.group_duplicate_button = self._group_section.duplicate_button
        self.group_rename_button = self._group_section.rename_button
        self.group_remove_button = self._group_section.remove_button
        self.group_move_up_button = self._group_section.move_up_button
        self.group_move_down_button = self._group_section.move_down_button
        self.group_export_button = self._group_section.export_button
        self.group_export_button.setObjectName("exportCustomFilterGroupButton")
        self.preset_new_button = self._preset_section.new_button
        self.preset_add_button = self._preset_section.add_button
        self.preset_duplicate_button = self._preset_section.duplicate_button
        self.preset_rename_button = self._preset_section.rename_button
        self.preset_remove_button = self._preset_section.remove_button
        self.preset_move_up_button = self._preset_section.move_up_button
        self.preset_move_down_button = self._preset_section.move_down_button
        self.preset_export_button = self._preset_section.export_button
        self.preset_export_button.setObjectName(
            "exportCustomFilterPresetButton"
        )
        self.splitter.addWidget(self._group_section)
        self.splitter.addWidget(self._preset_section)

        filter_section = qt.QWidget(self)
        filter_layout = qt.QVBoxLayout(filter_section)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)
        self.filter_label = qt.QLabel("カスタムフィルター", filter_section)
        filter_layout.addWidget(self.filter_label)
        filter_layout.addWidget(
            qt.QLabel(
                "目のアイコンで Attribute Filter への表示を切り替えます",
                filter_section,
            )
        )
        tree = CustomFilterRegistrationTree(filter_section)
        tree.visibility_clicked.connect(self._toggle_filter_visibility)
        self.tree_widget: qt.QTreeWidget = tree
        self.tree_widget.setObjectName("customFilterRegistrationTree")
        self.tree_widget.setAccessibleName("カスタムフィルター登録一覧")
        _configure_tree(self.tree_widget, "フィルター名")
        self.new_button = create_manager_tool_button(self)
        self.new_button.setObjectName("createCustomFilterButton")
        self.add_button = create_manager_tool_button(self)
        self.duplicate_button = create_manager_tool_button(self)
        self.duplicate_button.setObjectName("duplicateCustomFilterButton")
        self.rename_button = create_manager_tool_button(self)
        self.remove_button = create_manager_tool_button(self)
        self.move_up_button = create_manager_tool_button(self)
        self.move_down_button = create_manager_tool_button(self)
        self.export_button = create_manager_tool_button(self)
        self.export_button.setObjectName("exportCustomFilterButton")
        buttons = qt.QHBoxLayout()
        buttons.setSpacing(4)
        for button, label, icon in (
            (self.new_button, "カスタムフィルターを新規作成", "fileNew.png"),
            (
                self.add_button,
                "既存のカスタムフィルターを追加",
                "item_add.png",
            ),
            (
                self.duplicate_button,
                "選択したカスタムフィルターを複製",
                "polyCopyUV.png",
            ),
            (
                self.rename_button,
                "選択したカスタムフィルターをリネーム",
                "fileTextureEdit.png",
            ),
            (
                self.remove_button,
                "登録から削除（JSONファイルは削除しません）",
                "RS_delete.png",
            ),
            (self.move_up_button, "上へ", "nodeGrapherArrowUp.png"),
            (self.move_down_button, "下へ", "nodeGrapherArrowDown.png"),
        ):
            _configure_button(button, label, icon)
            buttons.addWidget(button)
        buttons.addStretch(1)
        _configure_button(
            self.export_button,
            "選択したカスタムフィルターをエクスポート",
            "UVTkNudgeUp.png",
        )
        buttons.addWidget(self.export_button)
        filter_layout.addLayout(buttons)
        filter_layout.addWidget(self.tree_widget, 1)
        self.splitter.addWidget(filter_section)
        cast(Callable[[list[int]], None], getattr(self.splitter, "setSizes"))(
            [150, 150, 300]
        )
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 2)

        self.save_button = create_manager_tool_button(self)
        self.discard_button = create_manager_tool_button(self)
        self.reload_all_button = create_manager_tool_button(self)
        global_buttons = qt.QHBoxLayout()
        global_buttons.setSpacing(4)
        for button, label, icon in (
            (self.save_button, "変更をすべて保存", "fileSave.png"),
            (self.discard_button, "変更をすべて破棄", "redo_s.png"),
            (self.reload_all_button, "全て再読込", "UVTkRotateCW.png"),
        ):
            _configure_button(button, label, icon)
            global_buttons.addWidget(button)
        global_buttons.addStretch(1)
        self.storage_error_label = qt.QLabel(self)
        self.storage_error_label.setObjectName("customFilterStorageError")
        self.storage_error_label.setWordWrap(True)
        self.storage_error_label.setTextInteractionFlags(
            qt.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout = qt.QVBoxLayout(self)
        self._content_layout = layout
        layout.addLayout(global_buttons)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.storage_error_label)

        for kind, section in (
            ("preset_group", self._group_section),
            ("preset", self._preset_section),
        ):
            typed_kind = cast(_PresetKind, kind)
            section.tree.currentItemChanged.connect(
                partial(self._change_document_selection, typed_kind)
            )
            section.tree.itemSelectionChanged.connect(
                partial(self._change_document_selection, typed_kind)
            )
            section.new_button.clicked.connect(
                partial(self._create_document, typed_kind)
            )
            section.add_button.clicked.connect(
                partial(self._add_documents, typed_kind)
            )
            section.duplicate_button.clicked.connect(
                partial(self._duplicate_document, typed_kind)
            )
            section.rename_button.clicked.connect(
                partial(self._rename_document, typed_kind)
            )
            section.remove_button.clicked.connect(
                partial(self._remove_documents, typed_kind)
            )
            section.move_up_button.clicked.connect(
                partial(self._move_documents, typed_kind, -1)
            )
            section.move_down_button.clicked.connect(
                partial(self._move_documents, typed_kind, 1)
            )
            section.export_button.clicked.connect(
                partial(self._export, typed_kind)
            )
        self.tree_widget.itemChanged.connect(self._change_enabled)
        self.tree_widget.itemSelectionChanged.connect(self._sync_selection)
        self.new_button.clicked.connect(self._create_file)
        self.add_button.clicked.connect(self._add_files)
        self.duplicate_button.clicked.connect(self._duplicate_selected)
        self.rename_button.clicked.connect(self._rename_filter)
        self.remove_button.clicked.connect(self._remove_selected)
        self.move_up_button.clicked.connect(self._move_up)
        self.move_down_button.clicked.connect(self._move_down)
        self.export_button.clicked.connect(partial(self._export, "filter"))
        self.save_button.clicked.connect(self._save)
        self.discard_button.clicked.connect(self._discard)
        self.reload_all_button.clicked.connect(self._reload_all)
        self.registry.path_changed.connect(self._replace_path)
        self.registry.document_path_changed.connect(
            self._replace_document_path
        )
        self.registry.changed.connect(self._refresh)
        self.registry.selection_changed.connect(self._refresh)
        self._refresh()

    def show_near(self, position: qt.QPoint) -> None:
        """同じ管理画面を指定位置付近へ表示し、画面内へ収めて前面に出す。"""
        self._placement_anchor = qt.QPoint(position)
        self.show()
        self._position_near_anchor()
        # nativeの外枠寸法が確定した後も、同じ起点で補正する
        self._placement_timer.start(0)
        self.raise_()
        self.activateWindow()

    def _position_near_anchor(self) -> None:
        """クリックした画面に外枠まで収め、大きすぎる場合だけ縮小する。"""
        anchor = self._placement_anchor
        if anchor is None or not self.isVisible():
            return
        screen = cast(
            qt.QtGui.QScreen | None, qt.QtGui.QGuiApplication.screenAt(anchor)
        )
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, self.screen())
        if screen is None:
            screen = cast(
                qt.QtGui.QScreen | None,
                qt.QtGui.QGuiApplication.primaryScreen(),
            )
        if screen is None:
            return
        available = screen.availableGeometry()
        if available.isEmpty():
            return
        frame = self.frameGeometry().size()
        maximum_client = qt.QSize(
            max(1, available.width() - max(0, frame.width() - self.width())),
            max(
                1, available.height() - max(0, frame.height() - self.height())
            ),
        )
        self.setMinimumSize(
            self._content_layout.totalMinimumSize()
            .boundedTo(maximum_client)
            .boundedTo(self.size())
        )
        self.resize(self.size().boundedTo(maximum_client))
        self.move(
            centered_position_within_screen(
                anchor, self.frameGeometry().size(), available
            )
        )

    @staticmethod
    def _item_path(item: qt.QTreeWidgetItem | None) -> str | None:
        """行に保存した正規化済みパスを返す。"""
        if item is None:
            return None
        value: object = item.data(0, qt.Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    @classmethod
    def _tree_selected_paths(cls, tree: qt.QTreeWidget) -> tuple[str, ...]:
        """選択中のパスを一覧の順序で返す。"""
        selected = {cls._item_path(item) for item in tree.selectedItems()}
        return tuple(
            path
            for index in range(tree.topLevelItemCount())
            if (path := cls._item_path(tree.topLevelItem(index))) is not None
            and path in selected
        )

    def _selected_paths(self) -> tuple[str, ...]:
        """選択中のフィルター登録パスを一覧の順序で返す。"""
        return self._tree_selected_paths(self.tree_widget)

    def _single_selected_path(self) -> str | None:
        """複製元を一意に決められるときだけ選択パスを返す。"""
        paths = self._selected_paths()
        return paths[0] if len(paths) == 1 else None

    @classmethod
    def _select_tree_path(cls, tree: qt.QTreeWidget, path: str) -> None:
        """指定した登録を単独選択し、表示範囲へ移す。"""
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if cls._item_path(item) == path:
                tree.setCurrentItem(
                    item,
                    0,
                    qt.QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | qt.QItemSelectionModel.SelectionFlag.Rows,
                )
                tree.scrollToItem(item)
                return

    def _select_path(self, path: str) -> None:
        """作成・追加したフィルターを単独選択する。"""
        self._select_tree_path(self.tree_widget, path)

    @classmethod
    def _replace_tree_path(
        cls, tree: qt.QTreeWidget, old_path: str, new_path: str
    ) -> None:
        """保存後の再描画に備え、選択行の識別子だけを更新する。"""
        blocked = tree.blockSignals(True)
        try:
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                if cls._item_path(item) == old_path:
                    item.setData(0, qt.Qt.ItemDataRole.UserRole, new_path)
                    break
        finally:
            tree.blockSignals(blocked)

    def _replace_path(self, old_path: str, new_path: str) -> None:
        """フィルター改名後も選択対象を同じ登録へ引き継ぐ。"""
        self._replace_tree_path(self.tree_widget, old_path, new_path)

    def _replace_document_path(
        self, kind: str, old_path: str, new_path: str
    ) -> None:
        """上位ファイルの改名後も同じ現在行と選択を保つ。"""
        if kind in ("preset_group", "preset"):
            section = self._section(kind)
            self._replace_tree_path(section.tree, old_path, new_path)

    def _update_item(
        self, item: qt.QTreeWidgetItem, entry: CustomFilterRegistration
    ) -> None:
        """既存の行を破棄せず、名前・目・パス・読込結果を更新する。"""
        name = (
            entry.definition.name
            if entry.definition is not None
            else filter_display_name(entry.path)
        )
        item.setText(0, name)
        item.setText(1, entry.path)
        item.setText(2, "読込済み" if entry.error is None else "読込エラー")
        item.setData(0, qt.Qt.ItemDataRole.UserRole, entry.path)
        item.setFlags(item.flags() | qt.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            0,
            (
                qt.Qt.CheckState.Checked
                if entry.enabled
                else qt.Qt.CheckState.Unchecked
            ),
        )
        item.setToolTip(0, name)
        item.setToolTip(1, entry.path)
        item.setToolTip(
            2, entry.error or "JSONファイルの読込・形式検証に成功しました"
        )

    def _update_document_item(
        self, item: qt.QTreeWidgetItem, entry: PresetRegistration
    ) -> None:
        """上位JSONの予定名と未保存印、実パス、読込結果を描画する。"""
        item.setText(0, entry.name + (" *" if entry.is_dirty else ""))
        item.setText(1, entry.destination_path)
        item.setText(2, "読込済み" if entry.error is None else "読込エラー")
        item.setData(0, qt.Qt.ItemDataRole.UserRole, entry.path)
        item.setToolTip(0, entry.name)
        item.setToolTip(1, entry.destination_path)
        item.setToolTip(
            2, entry.error or "JSONファイルの読込・形式検証に成功しました"
        )

    def _refresh_tree(
        self,
        tree: qt.QTreeWidget,
        paths: tuple[str, ...],
        update: Callable[[qt.QTreeWidgetItem, int], None],
    ) -> None:
        """既存行を優先して使い、選択・現在行・スクロールを保持する。"""
        existing = tuple(
            self._item_path(tree.topLevelItem(index))
            for index in range(tree.topLevelItemCount())
        )
        selected = set(self._tree_selected_paths(tree))
        current = cast(qt.QTreeWidgetItem | None, tree.currentItem())
        current_path = self._item_path(current)
        old_row = (
            tree.indexOfTopLevelItem(current) if current is not None else -1
        )
        scroll = tree.verticalScrollBar().value()
        blocked = tree.blockSignals(True)
        try:
            if existing == paths:
                for index in range(len(paths)):
                    update(tree.topLevelItem(index), index)
                return
            tree.clear()
            items: dict[str, qt.QTreeWidgetItem] = {}
            for index, path in enumerate(paths):
                item = qt.QTreeWidgetItem(tree)
                items[path] = item
                update(item, index)
            restored = items.get(current_path or "")
            if restored is None and paths:
                restored = tree.topLevelItem(
                    min(max(old_row, 0), len(paths) - 1)
                )
            if restored is not None:
                tree.setCurrentItem(
                    restored, 0, qt.QItemSelectionModel.SelectionFlag.NoUpdate
                )
            surviving = selected.intersection(items)
            for path in surviving:
                items[path].setSelected(True)
            if (
                not surviving
                and (selected or not existing)
                and restored is not None
            ):
                restored.setSelected(True)
            tree.verticalScrollBar().setValue(scroll)
        finally:
            tree.blockSignals(blocked)

    def _refresh(self) -> None:
        """3段の登録一覧を現在のグループ・プリセットへ同期する。"""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            for kind in ("preset_group", "preset"):
                typed_kind = kind
                section = self._section(typed_kind)
                entries = self._documents(typed_kind)

                def update_document(
                    item: qt.QTreeWidgetItem,
                    index: int,
                    values: tuple[PresetRegistration, ...] = entries,
                ) -> None:
                    """一覧の同じ行へ最新のドキュメント状態を反映する。"""
                    self._update_document_item(item, values[index])

                self._refresh_tree(
                    section.tree,
                    tuple(entry.path for entry in entries),
                    update_document,
                )
                self._restore_document_selection(typed_kind)
                self._sync_document_buttons(typed_kind)
            entries = self.registry.entries

            def update_filter(item: qt.QTreeWidgetItem, index: int) -> None:
                """フィルター一覧の同じ行へ最新の読込状態を反映する。"""
                self._update_item(item, entries[index])

            self._refresh_tree(
                self.tree_widget,
                tuple(entry.path for entry in entries),
                update_filter,
            )
            group = self._active_name("preset_group")
            preset = self._active_name("preset")
            self._preset_section.label.setText(
                f"プリセット — {group}" if group else "プリセット"
            )
            self.filter_label.setText(
                f"カスタムフィルター — {preset}"
                if preset
                else "カスタムフィルター"
            )
            self._sync_selection()
        finally:
            self._refreshing = False

    def _section(self, kind: _PresetKind) -> _PresetSection:
        """指定階層の一覧と操作列を返す。"""
        return (
            self._group_section
            if kind == "preset_group"
            else self._preset_section
        )

    def _documents(self, kind: _PresetKind) -> tuple[PresetRegistration, ...]:
        """指定階層に現在表示する登録を返す。"""
        return (
            self.registry.groups
            if kind == "preset_group"
            else self.registry.presets
        )

    def _active_path(self, kind: _PresetKind) -> str | None:
        """下段の表示先を決める現在の登録パスを返す。"""
        return (
            self.registry.active_group
            if kind == "preset_group"
            else self.registry.active_preset
        )

    def _active_name(self, kind: _PresetKind) -> str | None:
        """現在表示する登録の予定ファイル名を返す。"""
        path = self._active_path(kind)
        return next(
            (
                entry.name
                for entry in self._documents(kind)
                if entry.path == path
            ),
            None,
        )

    def _restore_document_selection(self, kind: _PresetKind) -> None:
        """registryの現在行へ戻し、変更のない複数選択は保つ。"""
        tree = self._section(kind).tree
        active = self._active_path(kind)
        current = cast(qt.QTreeWidgetItem | None, tree.currentItem())
        if active == self._item_path(current) and (
            active is None or tree.selectedItems()
        ):
            return
        blocked = tree.blockSignals(True)
        try:
            if active is None:
                tree.clearSelection()
                tree.setCurrentIndex(qt.QModelIndex())
            else:
                self._select_tree_path(tree, active)
        finally:
            tree.blockSignals(blocked)

    def _popup_position(self) -> qt.QPoint:
        """設定画面と共有する入力方法から、対話画面の起点を取得する。"""
        return (
            self._dialog_position()
            if self._dialog_position is not None
            else qt.QCursor.pos()
        )

    def _confirm(self, position: qt.QPoint | None = None) -> bool:
        """指定した起点で共通の保存・破棄・中止を確認する。"""
        anchor = (
            qt.QPoint(position)
            if position is not None
            else self._popup_position()
        )
        return self._confirm_create is None or self._confirm_create(anchor)

    def _change_document_selection(
        self, kind: _PresetKind, *_args: object
    ) -> None:
        """複数選択は操作対象とし、現在行だけを下段の表示先にする。"""
        if self._refreshing:
            return
        tree = self._section(kind).tree
        current = cast(qt.QTreeWidgetItem | None, tree.currentItem())
        # 一部の列だけが選択された行も、通常の操作対象として扱う
        selected_items = tree.selectedItems()
        selected_paths = {
            path
            for item in selected_items
            if (path := self._item_path(item)) is not None
        }
        if self._item_path(current) not in selected_paths:
            current = min(
                selected_items, key=tree.indexOfTopLevelItem, default=None
            )
            blocked = tree.blockSignals(True)
            try:
                if current is None:
                    tree.setCurrentIndex(qt.QModelIndex())
                else:
                    tree.setCurrentItem(
                        current,
                        0,
                        qt.QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
            finally:
                tree.blockSignals(blocked)
        path = self._item_path(current)
        if path == self._active_path(kind):
            self._sync_document_buttons(kind)
            return
        destination = next(
            (
                entry.destination_path
                for entry in self._documents(kind)
                if entry.path == path
            ),
            None,
        )
        if not self._confirm():
            self._restore_document_selection(kind)
            self._sync_document_buttons(kind)
            return
        available = {entry.path for entry in self._documents(kind)}
        if path is not None and path not in available:
            renamed = (
                normalize_filter_path(destination)
                if destination is not None
                else None
            )
            if renamed not in available:
                self._refresh()
                return
            path = renamed
        if kind == "preset_group":
            self.registry.select_group(path)
        else:
            self.registry.select_preset(path)
        self._refresh()

    def _sync_document_buttons(self, kind: _PresetKind) -> None:
        """上位一覧の選択と読込状態に応じて操作を有効にする。"""
        section = self._section(kind)
        entries = self._documents(kind)
        selected = set(self._tree_selected_paths(section.tree))
        indices = tuple(
            index
            for index, entry in enumerate(entries)
            if entry.path in selected
        )
        single = next(
            (entry for entry in entries if entry.path in selected), None
        )
        editable = kind == "preset_group" or any(
            entry.path == self.registry.active_group and entry.error is None
            for entry in self.registry.groups
        )
        section.new_button.setEnabled(editable)
        section.add_button.setEnabled(editable)
        section.duplicate_button.setEnabled(
            len(indices) == 1 and single is not None and single.error is None
        )
        section.rename_button.setEnabled(
            len(indices) == 1 and single is not None and single.error is None
        )
        section.remove_button.setEnabled(bool(indices))
        section.move_up_button.setEnabled(bool(indices) and indices[0] > 0)
        section.move_down_button.setEnabled(
            bool(indices) and indices[-1] < len(entries) - 1
        )
        section.export_button.setEnabled(bool(self._export_paths(kind)))

    def _sync_selection(self) -> None:
        """フィルター選択に応じて操作と保存エラーを表示する。"""
        selected = set(self._selected_paths())
        entries = self.registry.entries
        indices = tuple(
            index
            for index, item in enumerate(entries)
            if item.path in selected
        )
        entry = next((item for item in entries if item.path in selected), None)
        editable = any(
            entry.path == self.registry.active_preset and entry.error is None
            for entry in self.registry.presets
        )
        self.new_button.setEnabled(editable)
        self.add_button.setEnabled(editable)
        self.remove_button.setEnabled(bool(indices))
        single = (
            len(indices) == 1
            and entry is not None
            and entry.definition is not None
        )
        self.duplicate_button.setEnabled(single)
        self.rename_button.setEnabled(single)
        self.move_up_button.setEnabled(bool(indices) and indices[0] > 0)
        self.move_down_button.setEnabled(
            bool(indices) and indices[-1] < len(entries) - 1
        )
        self.export_button.setEnabled(bool(self._export_paths("filter")))
        self.reload_all_button.setEnabled(bool(self.registry.groups))
        error = self.registry.storage_error
        self.storage_error_label.setText(error or "")
        self.storage_error_label.setToolTip(error or "")
        self.storage_error_label.setVisible(error is not None)
        self.refresh_save_state()

    def refresh_save_state(self) -> None:
        """フィルター本体だけの変更も含め、共通保存と破棄を同期する。"""
        dirty = (
            self._changes_pending()
            if self._changes_pending is not None
            else self.registry.is_dirty
        )
        self.save_button.setEnabled(dirty)
        self.discard_button.setEnabled(dirty)

    def _single_document_path(self, kind: _PresetKind) -> str | None:
        """上位ファイルを一件だけ選択している場合にそのパスを返す。"""
        paths = self._tree_selected_paths(self._section(kind).tree)
        return paths[0] if len(paths) == 1 else None

    def _choose_document(self, kind: _PresetKind, path: str) -> None:
        """新規登録した上位ファイルを追加の確認なしで現在行にする。"""
        if kind == "preset_group":
            self.registry.select_group(path)
        else:
            self.registry.select_preset(path)
        self._refresh()

    def _initial_reference(
        self, kind: Literal["preset_group", "preset", "filter"]
    ) -> str | None:
        """ファイル選択の基準として、選択に含まれる現在行のパスを返す。"""
        tree = (
            self.tree_widget if kind == "filter" else self._section(kind).tree
        )
        current = cast(qt.QTreeWidgetItem | None, tree.currentItem())
        if current is None or current not in tree.selectedItems():
            return None
        return self._item_path(current)

    def _dialog_directory(
        self,
        kind: Literal["preset_group", "preset", "filter"],
        position: qt.QPoint,
    ) -> str | None:
        """追加ダイアログの初期フォルダーを用意し、失敗を画面へ伝える。"""
        try:
            return str(
                initial_filter_directory(kind, self._initial_reference(kind))
            )
        except OSError as error:
            ui_dialog.warning_near(
                self, "フォルダーを開けません", str(error), position
            )
            return None

    def _create_document(self, kind: _PresetKind) -> None:
        """選択中の現在行のフォルダーから、空の上位JSONを新規登録する。"""
        position = self._popup_position()
        if not self._confirm(position):
            return
        path = create_registered_preset(
            self,
            self.registry,
            kind,
            reference_path=self._initial_reference(kind),
            position=position,
        )
        if path is not None:
            self._choose_document(kind, path)

    def _add_documents(self, kind: _PresetKind) -> None:
        """既存のグループまたはプリセットをまとめて登録する。"""
        position = self._popup_position()
        if not self._confirm(position):
            return
        directory = self._dialog_directory(kind, position)
        if directory is None:
            return
        label = (
            "プリセットグループ" if kind == "preset_group" else "プリセット"
        )
        paths, _selected_filter = get_open_file_names_near(
            self,
            f"{label}を追加",
            directory,
            "JSON ファイル (*.json);;すべてのファイル (*)",
            position,
        )
        if not paths:
            return
        added = (
            self.registry.add_group_paths(paths)
            if kind == "preset_group"
            else self.registry.add_preset_paths(paths)
        )
        if added:
            self._choose_document(kind, added[-1])

    def _duplicate_document(self, kind: _PresetKind) -> None:
        """一件の上位JSONを同じフォルダーの_copy候補から複製する。"""
        position = self._popup_position()
        path = self._single_document_path(kind)
        if path is None or not self._confirm(position):
            return
        path = self._single_document_path(kind)
        if path is None:
            return
        created = create_registered_preset(
            self, self.registry, kind, source=path, position=position
        )
        if created is not None:
            self._choose_document(kind, created)

    def _rename_document(self, kind: _PresetKind) -> None:
        """保存時の実ファイル改名を下書きとして登録する。"""
        path = self._single_document_path(kind)
        if path is not None:
            rename_registered_preset(
                self,
                self.registry,
                kind,
                path,
                position=self._popup_position(),
            )

    def _remove_documents(self, kind: _PresetKind) -> None:
        """選択した上位登録を解除し、参照先の実ファイルは残す。"""
        if not self._confirm():
            return
        paths = self._tree_selected_paths(self._section(kind).tree)
        if kind == "preset_group":
            self.registry.remove_groups(paths)
        else:
            self.registry.remove_presets(paths)

    def _move_documents(self, kind: _PresetKind, offset: int) -> None:
        """選択した上位登録の相対順を保ち、一段ずつ移動する。"""
        paths = self._tree_selected_paths(self._section(kind).tree)
        if kind == "preset_group":
            self.registry.move_groups(paths, offset)
        else:
            self.registry.move_presets(paths, offset)

    def _toggle_filter_visibility(self, clicked: object) -> None:
        """選択内は全件、選択外は一件をクリックした目の反対状態へ揃える。"""
        if not isinstance(clicked, qt.QTreeWidgetItem):
            return
        path = self._item_path(clicked)
        if path is None:
            return
        selected = self._selected_paths()
        paths = selected if path in selected else (path,)
        self.registry.set_enabled_many(
            paths, clicked.checkState(0) != qt.Qt.CheckState.Checked
        )

    def _change_enabled(self, item: qt.QTreeWidgetItem, column: int) -> None:
        """名前列の目の状態だけを選択中のプリセットへ反映する。"""
        path = self._item_path(item)
        if column == 0 and path is not None:
            self.registry.set_enabled(
                path, item.checkState(0) == qt.Qt.CheckState.Checked
            )

    def _add_files(self) -> None:
        """既存フィルターJSONを選択中のプリセット末尾へ登録する。"""
        position = self._popup_position()
        if not self._confirm(position):
            return
        directory = self._dialog_directory("filter", position)
        if directory is None:
            return
        paths, _selected_filter = get_open_file_names_near(
            self,
            "カスタムフィルター定義を追加",
            directory,
            "JSON ファイル (*.json);;すべてのファイル (*)",
            position,
        )
        if paths:
            added = self.registry.add_paths(paths)
            if added:
                self._select_path(added[-1])
                self._sync_selection()

    def _create_file(self) -> None:
        """保存先のファイル名で空の定義を作成し、末尾へ登録する。"""
        position = self._popup_position()
        if self._confirm(position):
            self._register_created(
                create_registered_filter(
                    self,
                    self.registry,
                    reference_path=self._initial_reference("filter"),
                    position=position,
                )
            )

    def _duplicate_selected(self) -> None:
        """未保存変更を確認し、選択フィルターの全型を別名で複製する。"""
        position = self._popup_position()
        path = self._single_selected_path()
        if path is None or not self._confirm(position):
            return
        path = self._single_selected_path()
        if path is not None:
            self._register_created(
                create_registered_filter(
                    self, self.registry, source=path, position=position
                )
            )

    def _rename_filter(self) -> None:
        """選択フィルターを編集対象にして共用の改名入力を要求する。"""
        position = self._popup_position()
        path = self._single_selected_path()
        if path is None or not self._confirm(position):
            return
        path = self._single_selected_path()
        if path is not None:
            self.rename_requested.emit(path, position)

    def _register_created(self, path: str | None) -> None:
        """作成したフィルターを単独選択し、設定モードでの編集を要求する。"""
        if path is not None:
            self._select_path(path)
            self.created.emit(path)

    def _remove_selected(self) -> None:
        """選択フィルターの登録を解除し、JSONファイルは残す。"""
        if self._confirm():
            self.registry.remove_many(self._selected_paths())

    def _move_up(self) -> None:
        """選択フィルターの相対順を保ち、一段上へ移動する。"""
        self.registry.move_many(self._selected_paths(), -1)

    def _move_down(self) -> None:
        """選択フィルターの相対順を保ち、一段下へ移動する。"""
        self.registry.move_many(self._selected_paths(), 1)

    def _export_paths(self, kind: ExportKind) -> tuple[str, ...]:
        """選択行を全件検証し、上位一件または正常な複数フィルターを返す。"""
        tree = (
            self.tree_widget if kind == "filter" else self._section(kind).tree
        )
        paths = self._tree_selected_paths(tree)
        if not paths or len(paths) != len(tree.selectedItems()):
            return ()
        if kind == "filter":
            valid = {
                entry.path
                for entry in self.registry.entries
                if entry.definition is not None and entry.error is None
            }
        else:
            if len(paths) != 1:
                return ()
            valid = {
                entry.path
                for entry in self._documents(kind)
                if entry.error is None
            }
        return paths if all(path in valid for path in paths) else ()

    def _export_changes_pending(self) -> bool:
        """構成と外部の属性下書きのどちらかに未保存変更があるか返す。"""
        return self.registry.is_dirty or (
            self._changes_pending is not None and self._changes_pending()
        )

    def _prepare_export(self, position: qt.QPoint) -> bool:
        """変更を保存するか確認し、保存失敗や変更の残存では出力を止める。"""
        if self._confirm_export is not None:
            return self._confirm_export(position) and not (
                self._export_changes_pending()
            )
        if not self._export_changes_pending():
            return True
        if not confirm_export_save(self, position):
            return False
        if self._save_changes is not None:
            if not self._save_changes():
                return False
        else:
            self.registry.save()
        return not self._export_changes_pending()

    def _export(self, kind: ExportKind) -> None:
        """選択した同一対象を保存後も追跡し、依存ファイル一式を出力する。"""
        paths = list(self._export_paths(kind))
        if not paths:
            return
        position = self._popup_position()

        def replace_filter(old: str, new: str) -> None:
            """保存時に改名した選択フィルターを、改名後のパスへ引き継ぐ。"""
            if kind == "filter":
                paths[:] = [new if path == old else path for path in paths]

        def replace_document(changed_kind: str, old: str, new: str) -> None:
            """保存時に改名した選択文書だけを、改名後のパスへ引き継ぐ。"""
            if kind == changed_kind:
                paths[:] = [new if path == old else path for path in paths]

        # 保存による選択更新より前に、出力する同一対象の改名を追跡する
        self.registry.path_changed.connect(replace_filter)
        self.registry.document_path_changed.connect(replace_document)
        try:
            if not self._prepare_export(position):
                return
            directory = get_existing_directory_near(
                self,
                "エクスポート先のフォルダーを選択",
                str(Path(paths[0]).parent),
                position,
            )
            if not directory:
                return
            destination = export_custom_filter_files(kind, paths, directory)
            dialog = qt.QMessageBox(self)
            dialog.setWindowTitle("エクスポート完了")
            dialog.setIcon(qt.QMessageBox.Icon.Information)
            dialog.setText("カスタムフィルターの関連ファイルを出力しました。")
            dialog.setInformativeText(str(destination))
            dialog.setStandardButtons(qt.QMessageBox.StandardButton.Ok)
            try:
                exec_dialog_near(dialog, position)
            finally:
                dialog.deleteLater()
        except CustomFilterError as error:
            ui_dialog.warning_near(
                self, "エクスポートできません", str(error), position
            )
        finally:
            self.registry.path_changed.disconnect(replace_filter)
            self.registry.document_path_changed.disconnect(replace_document)
            self.refresh_save_state()

    def _save(self) -> None:
        """管理画面と設定画面の未保存変更をまとめて保存する。"""
        position = self._popup_position()
        try:
            if self._save_changes is not None:
                self._save_changes()
            else:
                self.registry.save()
        except CustomFilterError as error:
            ui_dialog.warning_near(
                self, "保存できません", str(error), position
            )
        self._refresh()

    def _discard(self) -> None:
        """管理画面と設定画面の未保存変更をまとめて破棄する。"""
        position = self._popup_position()
        try:
            if self._discard_changes is not None:
                self._discard_changes()
            else:
                self.registry.discard()
        except CustomFilterError as error:
            ui_dialog.warning_near(
                self, "読み直せません", str(error), position
            )
        self._refresh()

    def _reload_all(self) -> None:
        """未保存変更を確認してから、関連するJSONを再読込する。"""
        if self._confirm():
            self.registry.reload_all()
