# coding: utf-8
"""Mayaの属性を参照して共有カスタムフィルターを編集する画面。"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

from bd_util.maya.node.inspection import (
    ScalarAttributeDisplayFilter,
    ScalarAttributeInfo,
    inspect_scalar_attributes_by_type,
    matches_scalar_attribute_display_filter,
)
from bd_util.ui import RadioButtonSweep, exec_dialog_near, qt
from bd_util.ui import dialog as ui_dialog

from .custom_filter_dialogs import (
    confirm_export_save,
    create_registered_preset,
    rename_registered_preset,
)
from .custom_filter_editor import CustomFilterDraft, filter_file_name
from . import config
from .custom_filter_registry import CustomFilterRegistry
from .custom_filters import (
    CustomFilterError,
    StandardAttributeOptions,
    normalize_filter_path,
)

__all__ = ["CustomFilterSetupPanel"]


@dataclass(frozen=True)
class _SavedAttribute:
    """型情報を取得できない保存済みpathを、型を捏造せず候補に残す。"""

    path: str

    @property
    def name(self) -> str:
        """検索に用いる末尾の属性名を返す。"""
        return self.path.rsplit(".", 1)[-1]

    @property
    def nice_name(self) -> str:
        """型定義では検証できない候補であることを示す。"""
        return f"{self.path}（保存済み・型情報未確認）"


@dataclass(frozen=True)
class _CandidateRow:
    """候補属性の操作部品と選択色を戻すための元の配色。"""

    attribute: ScalarAttributeInfo | _SavedAttribute
    widget: qt.QWidget
    label: qt.QLabel
    include: qt.QRadioButton
    exclude: qt.QRadioButton
    palette: qt.QPalette
    fill_background: bool


class CustomFilterSetupPanel(qt.QWidget):
    """共有JSONの選択・属性所属・表示順・保存を管理する。"""

    error_occurred = qt.Signal(str)
    saved = qt.Signal(str)
    create_requested = qt.Signal()
    manage_requested = qt.Signal()
    changes_changed = qt.Signal()

    def __init__(
        self,
        registry: CustomFilterRegistry,
        parent: qt.QWidget,
        *,
        dialog_position: Callable[[], qt.QPoint] | None = None,
    ) -> None:
        """登録一覧と現在ノード型に対する作業中の編集画面を作る。"""
        super().__init__(parent)
        self.registry = registry
        self._dialog_position = dialog_position
        self.draft: CustomFilterDraft | None = None
        self._preset_path = registry.active_preset
        self._saving = False
        self._node_name: str | None = None
        self._node_type: str | None = None
        self._selected_node_name: str | None = None
        self._selected_node_type: str | None = None
        self._selected_attributes: tuple[ScalarAttributeInfo, ...] = ()
        self._display_filter: ScalarAttributeDisplayFilter = "all"
        self._type_info_node_type: str | None = None
        self._type_attributes: tuple[ScalarAttributeInfo, ...] = ()
        self._known_paths: dict[str, dict[str, None]] = {}
        self._attributes: tuple[
            ScalarAttributeInfo | _SavedAttribute, ...
        ] = ()
        self._candidate_rows: list[_CandidateRow] = []
        self._candidate_rows_by_path: dict[str, _CandidateRow] = {}
        self._candidate_selection_targets: dict[qt.QObject, str] = {}
        self._selected_candidate_paths: set[str] = set()
        self._selection_anchor: str | None = None
        self._selection_press_path: str | None = None
        self._selection_press_position = qt.QPoint()
        self._selection_dragging = False
        self._selection_drag_base: set[str] = set()
        self._selection_drag_paths: tuple[str, ...] = ()
        self._selection_drag_bottoms: tuple[int, ...] = ()
        self._search_tokens: tuple[str, ...] = ()
        self._radio_sweep_pending = False

        self.target_label = qt.QLabel("編集するフィルター:", self)
        self.target_combo = qt.QComboBox(self)
        self.target_combo.setObjectName("customFilterSetupTarget")
        self.target_combo.setAccessibleName("編集するカスタムフィルター")
        self.new_button = qt.QToolButton(self)
        self.new_button.setObjectName("createCustomFilterInSetupButton")
        self.rename_button = qt.QToolButton(self)
        self.rename_button.setObjectName("customFilterSetupRename")
        self.save_button = qt.QToolButton(self)
        self.save_button.setObjectName("customFilterSetupSave")
        self.discard_button = qt.QToolButton(self)
        self.discard_button.setObjectName("customFilterSetupDiscard")
        self.manage_button = qt.QToolButton(self)
        self.manage_button.setObjectName("customFilterSetupManage")
        self.global_controls = qt.QWidget(self)
        self.global_controls.setObjectName("customFilterGlobalControls")
        self.preset_controls = qt.QWidget(self)
        self.preset_controls.setObjectName("customFilterPresetControls")
        self.preset_label = qt.QLabel("プリセット:", self.preset_controls)
        self.preset_combo = qt.QComboBox(self.preset_controls)
        self.preset_combo.setObjectName("customFilterPresetCombo")
        self.preset_combo.setAccessibleName("使用するプリセット")
        self.preset_combo.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Fixed
        )
        self.preset_new_button = qt.QToolButton(self.preset_controls)
        self.preset_new_button.setObjectName("createPresetInSetupButton")
        self.preset_rename_button = qt.QToolButton(self.preset_controls)
        self.preset_rename_button.setObjectName("renamePresetInSetupButton")
        self.target_combo.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Fixed
        )
        self.search_edit = qt.QLineEdit(self)
        self.search_edit.setObjectName("customFilterSetupSearch")
        self.search_edit.setPlaceholderText("候補属性を検索")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.installEventFilter(self)
        self.node_label = qt.QLabel("ノードを選択してください", self)
        self.node_label.setObjectName("customFilterSetupNode")
        self.node_label.setWordWrap(True)
        self.node_type_label = qt.QLabel("編集するノード型:", self)
        self.node_type_combo = qt.QComboBox(self)
        self.node_type_combo.setObjectName("customFilterSetupNodeType")
        self.node_type_combo.setAccessibleName("編集するノード型")
        self.node_type_combo.addItem("選択ノード", None)
        self.clear_type_button = qt.QToolButton(self)
        self.clear_type_button.setObjectName("customFilterSetupClearType")
        self.standard_enabled_checkbox = qt.QCheckBox(
            "標準条件の属性を追加", self
        )
        self.standard_enabled_checkbox.setObjectName(
            "customFilterStandardEnabled"
        )
        self.standard_enabled_checkbox.setToolTip(
            "手動登録にない属性を、実ノードの現在のKeyable・ChannelBox状態で"
            "判定して追加します。Mayaの属性や表示状態は変更しません。"
        )
        self.standard_filter_combo = qt.QComboBox(self)
        self.standard_filter_combo.setObjectName("customFilterStandardFilter")
        self.standard_filter_combo.setAccessibleName("追加する標準条件")
        for label, value in (
            ("Keyable", "keyable"),
            ("ChannelBox", "channel_box"),
            ("Keyable + ChannelBox", "visible"),
        ):
            self.standard_filter_combo.addItem(label, value)
        self.standard_filter_combo.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Fixed
        )
        self.standard_position_combo = qt.QComboBox(self)
        self.standard_position_combo.setObjectName(
            "customFilterStandardPosition"
        )
        self.standard_position_combo.setAccessibleName("標準属性の追加位置")
        self.standard_position_combo.addItem("先頭", "first")
        self.standard_position_combo.addItem("末尾", "last")
        self.order_list = qt.QListWidget(self)
        self.order_list.setObjectName("customFilterSetupOrder")
        self.order_list.setToolTip(
            "手動登録した属性の順序です。標準条件の属性は重複を除き、"
            "この順序の先頭または末尾へ自動追加します。"
        )
        self.order_list.setSelectionMode(
            qt.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.order_list.setMinimumHeight(28)
        self.order_list.setSizePolicy(
            qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Ignored
        )
        self.order_list.installEventFilter(self)
        self.order_list.viewport().installEventFilter(self)
        self.order_context_menu = qt.QMenu(self.order_list)
        self.order_context_menu.setObjectName("customFilterOrderContextMenu")
        self.remove_order_action = qt.QAction(
            "除外する", self.order_context_menu
        )
        self.remove_order_action.setObjectName("removeCustomFilterOrderAction")
        cast(
            Callable[[qt.QAction], None],
            getattr(self.order_context_menu, "addAction"),
        )(self.remove_order_action)
        self.up_button = qt.QToolButton(self)
        self.down_button = qt.QToolButton(self)
        self.remove_button = qt.QToolButton(self)
        for button, label, icon_name, fallback in (
            (
                self.new_button,
                "カスタムフィルターを新規作成",
                "fileNew.png",
                "fileNew.png",
            ),
            (
                self.rename_button,
                "フィルター名を変更",
                "fileTextureEdit.png",
                "fileTextureEdit.png",
            ),
            (
                self.preset_new_button,
                "プリセットを新規作成",
                "fileNew.png",
                "fileNew.png",
            ),
            (
                self.preset_rename_button,
                "プリセット名を変更",
                "fileTextureEdit.png",
                "fileTextureEdit.png",
            ),
            (
                self.save_button,
                "変更をすべて保存",
                "fileSave.png",
                "fileSave.png",
            ),
            (
                self.discard_button,
                "保存済みの内容に戻す（変更を破棄）",
                "redo_s.png",
                "redo_s.png",
            ),
            (
                self.manage_button,
                "カスタムフィルター管理",
                "QR_settings.png",
                "QR_settings.png",
            ),
            (
                self.clear_type_button,
                "この型のフィルター定義を削除して標準表示に戻す",
                "RS_delete.png",
                "RS_delete.png",
            ),
            (self.up_button, "上へ", "nodeGrapherArrowUp.png", "arrowUp.png"),
            (
                self.down_button,
                "下へ",
                "nodeGrapherArrowDown.png",
                "arrowDown.png",
            ),
            (self.remove_button, "除外", "RS_delete.png", "RS_delete.png"),
        ):
            icon = qt.QIcon(f":/{icon_name}")
            if icon.pixmap(16, 16).isNull():
                icon = qt.QIcon(f":/{fallback}")
            button.setIcon(icon)
            button.setIconSize(qt.QSize(16, 16))
            button.setFixedSize(20, 20)
            button.setToolTip(label)
            button.setAccessibleName(label)
        self.remove_order_action.setIcon(self.remove_button.icon())
        self.candidate_scroll = qt.QScrollArea(self)
        self.candidate_scroll.setObjectName("customFilterSetupAttributes")
        self.candidate_scroll.setMinimumHeight(28)
        self.candidate_scroll.setSizePolicy(
            qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Ignored
        )
        self.candidate_scroll.setWidgetResizable(True)
        self.candidate_scroll.setFrameShape(qt.QFrame.Shape.NoFrame)
        self.candidate_container = qt.QWidget(self.candidate_scroll)
        self.candidate_layout = qt.QVBoxLayout(self.candidate_container)
        self.candidate_layout.setContentsMargins(0, 0, 0, 0)
        self.candidate_layout.setSpacing(2)
        self.candidate_layout.addStretch(1)
        self.candidate_scroll.setWidget(self.candidate_container)
        self.radio_sweep = RadioButtonSweep(self.candidate_scroll)
        self.radio_sweep.finished.connect(self._flush_radio_sweep)
        self.candidate_container.installEventFilter(self)
        self.candidate_scroll.viewport().installEventFilter(self)

        grid = qt.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        # フィルター操作と型操作の横幅を別々に配分する
        filter_controls = qt.QHBoxLayout()
        filter_controls.setContentsMargins(0, 0, 0, 0)
        filter_controls.setSpacing(4)
        filter_controls.addWidget(self.target_combo, 1)
        for button in (
            self.new_button,
            self.rename_button,
        ):
            filter_controls.addWidget(button)
        global_layout = qt.QHBoxLayout(self.global_controls)
        global_layout.setContentsMargins(0, 0, 0, 0)
        global_layout.setSpacing(4)
        global_layout.addStretch(1)
        for button in (
            self.save_button,
            self.discard_button,
            self.manage_button,
        ):
            global_layout.addWidget(button)
        preset_layout = qt.QHBoxLayout(self.preset_controls)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(4)
        preset_layout.addWidget(self.preset_label)
        preset_layout.addWidget(self.preset_combo, 1)
        preset_layout.addWidget(self.preset_new_button)
        preset_layout.addWidget(self.preset_rename_button)
        type_controls = qt.QHBoxLayout()
        type_controls.setContentsMargins(0, 0, 0, 0)
        type_controls.setSpacing(4)
        type_controls.addWidget(self.node_type_combo, 1)
        type_controls.addWidget(self.clear_type_button)
        grid.addWidget(self.target_label, 0, 0)
        grid.addLayout(filter_controls, 0, 1)
        grid.addWidget(self.node_type_label, 1, 0)
        grid.addLayout(type_controls, 1, 1)
        grid.addWidget(self.standard_enabled_checkbox, 2, 0, 1, 2)
        standard_controls = qt.QHBoxLayout()
        standard_controls.setContentsMargins(0, 0, 0, 0)
        standard_controls.setSpacing(4)
        standard_controls.addWidget(qt.QLabel("条件:", self))
        standard_controls.addWidget(self.standard_filter_combo, 1)
        standard_controls.addWidget(qt.QLabel("位置:", self))
        standard_controls.addWidget(self.standard_position_combo)
        grid.addLayout(standard_controls, 3, 0, 1, 2)
        order_buttons = qt.QVBoxLayout()
        order_buttons.setSpacing(2)
        for button in (self.up_button, self.down_button, self.remove_button):
            order_buttons.addWidget(button)
        order_buttons.addStretch(1)
        order_content = qt.QHBoxLayout()
        order_content.setSpacing(4)
        order_content.addLayout(order_buttons)
        order_content.addWidget(self.order_list, 1)
        self.order_page = qt.QWidget(self)
        self.order_page.setSizePolicy(
            qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Ignored
        )
        order_layout = qt.QVBoxLayout(self.order_page)
        order_layout.setContentsMargins(0, 0, 0, 0)
        order_layout.setSpacing(4)
        order_layout.addLayout(order_content, 1)
        self.candidate_page = qt.QWidget(self)
        self.candidate_page.setSizePolicy(
            qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Ignored
        )
        candidate_layout = qt.QVBoxLayout(self.candidate_page)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.setSpacing(4)
        search_layout = qt.QHBoxLayout()
        search_layout.addWidget(qt.QLabel("属性検索:", self))
        search_layout.addWidget(self.search_edit, 1)
        candidate_layout.addLayout(search_layout)
        candidate_layout.addWidget(self.candidate_scroll, 1)
        self.tool_box = qt.QtWidgets.QToolBox(self)
        self.tool_box.setObjectName("customFilterSetupToolBox")
        # ページと候補の背景をMayaのWindow配色へ揃える
        self.tool_box.setBackgroundRole(qt.QPalette.ColorRole.Window)
        self.tool_box.addItem(self.order_page, "手動登録の表示順")
        self.tool_box.addItem(self.candidate_page, "属性を手動登録する")
        self.tool_box.setCurrentWidget(self.candidate_page)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.global_controls)
        layout.addWidget(self.preset_controls)
        layout.addLayout(grid)
        layout.addWidget(self.node_label)
        layout.addWidget(self.tool_box, 1)

        self.target_combo.currentIndexChanged.connect(self._change_target)
        self.new_button.clicked.connect(self._request_create)
        self.manage_button.clicked.connect(self._request_manage)
        self.rename_button.clicked.connect(self._rename_filter)
        self.preset_combo.currentIndexChanged.connect(self._change_preset)
        self.preset_new_button.clicked.connect(self._create_preset)
        self.preset_rename_button.clicked.connect(self._rename_preset)
        self.node_type_combo.currentIndexChanged.connect(
            self._change_node_type
        )
        self.standard_enabled_checkbox.toggled.connect(
            self._change_standard_enabled
        )
        self.standard_filter_combo.currentIndexChanged.connect(
            self._change_standard_choice
        )
        self.standard_position_combo.currentIndexChanged.connect(
            self._change_standard_choice
        )
        self.search_edit.textChanged.connect(self._change_search)
        self.tool_box.currentChanged.connect(self._change_list_page)
        self.order_list.itemSelectionChanged.connect(self._sync_buttons)
        self.up_button.clicked.connect(partial(self._move_selected, -1))
        self.down_button.clicked.connect(partial(self._move_selected, 1))
        self.remove_button.clicked.connect(self._remove_selected)
        self.remove_order_action.triggered.connect(self._remove_selected)
        self.clear_type_button.clicked.connect(self._clear_type)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(self.discard)
        self.registry.changed.connect(self.refresh_entries)
        self.registry.path_changed.connect(self._replace_draft_path)
        self.registry.path_removed.connect(self._remove_draft_path)
        self.refresh_entries()
        self._refresh_view()

    @property
    def is_dirty(self) -> bool:
        """一覧構成か編集中の属性定義に未保存変更があるか返す。"""
        return self.registry.is_dirty or (
            self.draft is not None and self.draft.is_dirty
        )

    def has_unsaved_changes(self) -> bool:
        """管理画面と共有する未保存状態をコールバックとして返す。"""
        return self.is_dirty

    def set_setup_mode(self, enabled: bool) -> None:
        """同じプリセット行を全モードで使い、設定時だけ編集操作を示す。"""
        self.global_controls.setVisible(enabled)
        self.preset_label.setText(
            "編集するプリセット:" if enabled else "プリセット:"
        )
        self.preset_new_button.setVisible(enabled)
        self.preset_rename_button.setVisible(enabled)

    def _refresh_presets(self) -> None:
        """現在グループのプリセット名・未保存状態と選択を同期する。"""
        blocked = self.preset_combo.blockSignals(True)
        try:
            self.preset_combo.clear()
            self.preset_combo.addItem("プリセットを選択してください", None)
            counts = Counter(entry.name for entry in self.registry.presets)
            for entry in self.registry.presets:
                label = entry.name
                if counts[entry.name] > 1:
                    label += f"（{Path(entry.destination_path).parent}）"
                if entry.is_dirty:
                    label += " *"
                if entry.error is not None:
                    label += "（読込エラー）"
                self.preset_combo.addItem(label, entry.path)
                self.preset_combo.setItemData(
                    self.preset_combo.count() - 1,
                    entry.error or entry.destination_path,
                    qt.Qt.ItemDataRole.ToolTipRole,
                )
            self.preset_combo.setCurrentIndex(
                max(0, self.preset_combo.findData(self.registry.active_preset))
            )
        finally:
            self.preset_combo.blockSignals(blocked)
        group = next(
            (
                entry
                for entry in self.registry.groups
                if entry.path == self.registry.active_group
            ),
            None,
        )
        self.preset_combo.setToolTip(
            "プリセットグループ: " + group.name
            if group is not None
            else "管理画面でプリセットグループを選択してください"
        )

    def _change_preset(self, index: int) -> None:
        """未保存編集を確認し、全モード共通の使用プリセットを切り替える。"""
        path: object = self.preset_combo.itemData(index)
        if path is not None and not isinstance(path, str):
            return
        if path == self.registry.active_preset:
            return
        destination = next(
            (
                entry.destination_path
                for entry in self.registry.presets
                if entry.path == path
            ),
            None,
        )
        if not self.confirm_leave():
            self._refresh_presets()
            return
        available = {entry.path for entry in self.registry.presets}
        if path is not None and path not in available:
            # 保存で改名が確定した場合だけ、新しい識別パスを引き継ぐ
            renamed = (
                normalize_filter_path(destination)
                if destination is not None
                else None
            )
            if renamed not in available:
                self._refresh_presets()
                return
            path = renamed
        try:
            self.registry.select_preset(path)
        except CustomFilterError as error:
            self.error_occurred.emit(str(error))
            self._refresh_presets()

    def _create_preset(self) -> None:
        """編集中プリセットのフォルダーから、空のプリセットを作成する。"""
        position = self._popup_position()
        if not self.confirm_leave(position):
            return
        create_registered_preset(
            self,
            self.registry,
            "preset",
            reference_path=self.registry.active_preset,
            position=position,
        )

    def _rename_preset(self) -> None:
        """プリセットファイルの改名を共通下書きへ反映する。"""
        path = self.registry.active_preset
        if path is not None:
            rename_registered_preset(
                self,
                self.registry,
                "preset",
                path,
                position=self._popup_position(),
            )

    def _remove_draft_path(self, path: str) -> None:
        """実削除したフィルターを編集下書きからも外す。"""
        if self.draft is not None and self.draft.path == path:
            self._load_target(None)

    def _replace_draft_path(self, old_path: str, new_path: str) -> None:
        """全体保存中の改名通知では作業中の同じ下書きを維持する。"""
        if self._saving:
            return
        if self.draft is not None and self.draft.path == old_path:
            self._load_target(new_path)

    def refresh_entries(self) -> None:
        """ON/OFFを問わず正常な登録を編集候補へ反映する。"""
        self._finish_radio_sweep()
        self._refresh_presets()
        context_changed = self._preset_path != self.registry.active_preset
        self._preset_path = self.registry.active_preset
        current = self.draft.path if self.draft is not None else None
        if context_changed and not self._saving:
            available = {
                entry.path
                for entry in self.registry.entries
                if entry.definition is not None
            }
            self._load_target(current if current in available else None)
            current = self.draft.path if self.draft is not None else None
        blocked = self.target_combo.blockSignals(True)
        try:
            self.target_combo.clear()
            self.target_combo.addItem("フィルターを選択してください", None)
            for entry in self.registry.entries:
                if entry.definition is None:
                    continue
                label = entry.definition.name
                if not entry.enabled:
                    label += "（一覧ではOFF）"
                self.target_combo.addItem(label, entry.path)
                self.target_combo.setItemData(
                    self.target_combo.count() - 1,
                    entry.path,
                    qt.Qt.ItemDataRole.ToolTipRole,
                )
            if current is not None and self._index_for_path(current) < 0:
                self.target_combo.addItem(
                    f"編集中: {Path(current).name}（登録・読込状態を確認）",
                    current,
                )
            index = self._index_for_path(current) if current else -1
            self.target_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.target_combo.blockSignals(blocked)
        self._refresh_target_label()
        self._sync_buttons()

    def _index_for_path(self, path: str | None) -> int:
        """正規化済みファイルpathに一致する候補位置を返す。"""
        if path is None:
            return -1
        return next(
            (
                index
                for index in range(self.target_combo.count())
                if self.target_combo.itemData(index) == path
            ),
            -1,
        )

    def set_target(self, path: str) -> None:
        """管理画面で作成したファイルを編集対象として選ぶ。"""
        index = self._index_for_path(normalize_filter_path(path))
        if index >= 0:
            self.target_combo.setCurrentIndex(index)

    def _load_target(self, path: str | None) -> None:
        """保存済みJSONから新しい作業中データを取得する。"""
        self._finish_radio_sweep()
        self._clear_candidate_selection()
        self.order_list.clearSelection()
        self.order_list.setCurrentRow(-1)
        self._known_paths.clear()
        self._type_info_node_type = None
        try:
            self.draft = CustomFilterDraft(path) if path is not None else None
        except CustomFilterError as error:
            self.draft = None
            self.error_occurred.emit(str(error))
        self._refresh_view()

    def _change_target(self, index: int) -> None:
        """未保存変更を確認してから別の共有ファイルへ切り替える。"""
        path = self.target_combo.itemData(index)
        if path is not None and not isinstance(path, str):
            return
        if self.draft is not None and path == self.draft.path:
            return
        previous = self.draft.path if self.draft is not None else None
        # 同じプリセット内の一覧下書きは維持し、離れる属性編集だけ確認する
        if (
            self.draft is not None
            and self.draft.is_dirty
            and not self.confirm_leave()
        ):
            blocked = self.target_combo.blockSignals(True)
            try:
                old = self._index_for_path(previous)
                self.target_combo.setCurrentIndex(max(0, old))
            finally:
                self.target_combo.blockSignals(blocked)
            return
        available = {entry.path for entry in self.registry.entries}
        self._load_target(path if path in available else None)
        self.refresh_entries()

    def set_node(
        self,
        node_name: str | None,
        node_type: str | None,
        attributes: tuple[ScalarAttributeInfo, ...],
        *,
        display_filter: ScalarAttributeDisplayFilter = "all",
    ) -> None:
        """選択ノードを保持し、型の固定中は選択変更による編集対象変更を防ぐ。"""
        self._finish_radio_sweep()
        self._selected_node_name = node_name
        self._selected_node_type = node_type
        self._selected_attributes = attributes
        previous_filter = self._display_filter
        self._display_filter = display_filter
        if (
            self.node_type_combo.currentData() is not None
            and display_filter == previous_filter
        ):
            return
        self._refresh_view()

    def _request_create(self) -> None:
        """親画面へ新規作成と未保存変更の確認を依頼する。"""
        self.create_requested.emit()

    def _request_manage(self) -> None:
        """編集中の内容を保ち、親画面へ管理ウィンドウの表示を依頼する。"""
        self.manage_requested.emit()

    def _refresh_node_types(self) -> None:
        """未保存・0件を含む編集中の型を列挙し、削除された型から戻る。"""
        current = self.node_type_combo.currentData()
        node_types = self.draft.node_types if self.draft is not None else {}
        blocked = self.node_type_combo.blockSignals(True)
        try:
            self.node_type_combo.clear()
            self.node_type_combo.addItem("選択ノード", None)
            for node_type, paths in node_types.items():
                self.node_type_combo.addItem(node_type, node_type)
                known = self._known_paths.setdefault(node_type, {})
                known.update((path.lstrip("."), None) for path in paths)
            index = self.node_type_combo.findData(current)
            self.node_type_combo.setCurrentIndex(max(0, index))
        finally:
            self.node_type_combo.blockSignals(blocked)

    def _change_node_type(self, _index: int) -> None:
        """同じ下書き内で型を切り替え、全型の未保存内容を保持する。"""
        self._finish_radio_sweep()
        self._type_info_node_type = None
        self._refresh_view()

    def _refresh_standard_options(self) -> None:
        """編集対象の型の標準追加条件を、下書きを変更せず表示する。"""
        options = (
            self.draft.standard_options(self._node_type)
            if self.draft is not None and self._node_type is not None
            else StandardAttributeOptions()
        )
        controls = (
            self.standard_enabled_checkbox,
            self.standard_filter_combo,
            self.standard_position_combo,
        )
        blocked = tuple(control.blockSignals(True) for control in controls)
        try:
            self.standard_enabled_checkbox.setChecked(options.enabled)
            self.standard_filter_combo.setCurrentIndex(
                self.standard_filter_combo.findData(options.display_filter)
            )
            self.standard_position_combo.setCurrentIndex(
                self.standard_position_combo.findData(options.position)
            )
        finally:
            for control, previous in zip(controls, blocked):
                control.blockSignals(previous)

    def _change_standard_enabled(self, _checked: bool) -> None:
        """標準追加の有効状態を、現在のノード型の下書きへ反映する。"""
        self._apply_standard_options()

    def _change_standard_choice(self, _index: int) -> None:
        """標準追加の条件または位置を、現在のノード型へ反映する。"""
        self._apply_standard_options()

    def _apply_standard_options(self) -> None:
        """手動登録を保ち、標準条件の変更だけを保存前の定義へ記録する。"""
        draft = self.draft
        node_type = self._node_type
        display_filter = self.standard_filter_combo.currentData()
        position = self.standard_position_combo.currentData()
        if draft is None or node_type is None:
            return
        if display_filter not in ("keyable", "channel_box", "visible"):
            return
        if position not in ("first", "last"):
            return
        self._finish_radio_sweep()
        options = StandardAttributeOptions(
            enabled=self.standard_enabled_checkbox.isChecked(),
            display_filter=display_filter,
            position=position,
        )
        if options == draft.standard_options(node_type):
            return
        draft.set_standard_options(node_type, options)
        self._refresh_node_types()
        self._refresh_target_label()
        self._sync_buttons()

    def _refresh_context(self) -> None:
        """選択ノードか固定した型から、編集対象と現在の候補を決める。"""
        fixed_type = self.node_type_combo.currentData()
        node_type = (
            fixed_type
            if isinstance(fixed_type, str)
            else self._selected_node_type
        )
        node_name = (
            None if fixed_type is not None else self._selected_node_name
        )
        if node_type != self._node_type or node_name != self._node_name:
            self._clear_candidate_selection()
            self.order_list.clearSelection()
            self.order_list.setCurrentRow(-1)
        self._node_type = node_type
        self._node_name = node_name
        if not isinstance(fixed_type, str):
            self._attributes = self._selected_attributes
            return

        # 型の標準属性は型切替時に一度だけ読み、選択変更では再取得しない
        if self._type_info_node_type != fixed_type:
            self._type_info_node_type = fixed_type
            try:
                self._type_attributes = inspect_scalar_attributes_by_type(
                    fixed_type
                )
            except (ValueError, RuntimeError) as error:
                self._type_attributes = ()
                self.error_occurred.emit(
                    f"{fixed_type} 型の情報を取得できないため、"
                    f"保存済み属性を編集します。\n{error}"
                )
        priorities = {
            path: index
            for index, path in enumerate(
                dict.fromkeys(config.ATTRIBUTE_PRIORITY_PATHS)
            )
        }
        attributes = sorted(
            self._type_attributes,
            key=lambda attribute: priorities.get(
                attribute.path,
                len(priorities)
                + (not attribute.path.startswith("drawOverride.")),
            ),
        )
        self._attributes = tuple(
            attribute
            for attribute in attributes
            if matches_scalar_attribute_display_filter(
                attribute, self._display_filter
            )
        )
        # 所属を外した保存済みpathも残し、型情報がなくても再追加できるようにする
        if self._display_filter == "all":
            standard_paths = {
                attribute.path.lstrip(".") for attribute in attributes
            }
            self._attributes += tuple(
                _SavedAttribute(path)
                for path in self._known_paths.get(fixed_type, {})
                if path not in standard_paths
            )

    def set_search_tokens(self, tokens: tuple[str, ...]) -> None:
        """現在の属性候補へ検索語を適用し、所属は変更しない。"""
        self._finish_radio_sweep()
        self._search_tokens = tokens
        for candidate in self._candidate_rows:
            candidate.widget.setVisible(
                self._matches_search(candidate.attribute)
            )
        self._set_selected_candidate_paths(self._selected_candidate_paths)
        self._sync_buttons()

    def selected_candidate_paths(self) -> tuple[str, ...]:
        """現在見える候補の選択を属性の表示順で返す。"""
        return tuple(
            path
            for path in self._candidate_paths()
            if path in self._selected_candidate_paths
        )

    def _matches_search(
        self, attribute: ScalarAttributeInfo | _SavedAttribute
    ) -> bool:
        """属性候補が現在の検索語すべてに一致するか返す。"""
        if not self._search_tokens:
            return True
        searchable = " ".join(
            (attribute.nice_name, attribute.name, attribute.path)
        ).casefold()
        return all(token in searchable for token in self._search_tokens)

    def _candidate_paths(self) -> tuple[str, ...]:
        """標準フィルターと検索を通過した候補pathを表示順で返す。"""
        return tuple(
            attribute.path
            for attribute in self._attributes
            if self._matches_search(attribute)
        )

    def _paint_candidate_selection(self, paths: set[str]) -> None:
        """変更した属性名の選択色とラジオの適用範囲だけを更新する。"""
        for path in paths:
            candidate = self._candidate_rows_by_path.get(path)
            if candidate is None or not qt.isValid(candidate.label):
                continue
            selected = path in self._selected_candidate_paths
            palette = qt.QPalette(candidate.palette)
            if selected:
                highlight = self.palette().color(
                    qt.QPalette.ColorRole.Highlight
                )
                text = self.palette().color(
                    qt.QPalette.ColorRole.HighlightedText
                )
                for role in (
                    qt.QPalette.ColorRole.Window,
                    qt.QPalette.ColorRole.Base,
                ):
                    palette.setColor(role, highlight)
                for role in (
                    qt.QPalette.ColorRole.WindowText,
                    qt.QPalette.ColorRole.Text,
                ):
                    palette.setColor(role, text)
            candidate.label.setPalette(palette)
            candidate.label.setAutoFillBackground(
                selected or candidate.fill_background
            )
            candidate.label.update()
            scope = (
                "選択中の属性すべてに適用（スクロール外も対象）"
                if selected
                else "この属性だけに適用"
            )
            tooltip = (
                f"{path}\n{scope}\n"
                "手動登録だけを変更し、標準条件に合う属性は自動追加されます。"
            )
            candidate.include.setToolTip(tooltip)
            candidate.exclude.setToolTip(tooltip)

    def _set_selected_candidate_paths(self, paths: set[str]) -> None:
        """現在見える正式pathだけを選択し、差分の名前欄を描き直す。"""
        visible = set(self._candidate_paths())
        selected = paths & visible
        changed = self._selected_candidate_paths ^ selected
        self._selected_candidate_paths = selected
        if self._selection_anchor not in visible:
            self._selection_anchor = None
        self._paint_candidate_selection(changed)

    def _clear_candidate_selection(self) -> None:
        """候補選択と進行中のドラッグを解除する。"""
        self._finish_candidate_drag()
        self._set_selected_candidate_paths(set())
        self._selection_anchor = None

    def _press_candidate_name(
        self, path: str, event: qt.QtGui.QMouseEvent
    ) -> None:
        """属性名の単独・Ctrl・Shift選択とドラッグ起点を記録する。"""
        visible = self._candidate_paths()
        if path not in visible:
            return
        previous = set(self._selected_candidate_paths)
        modifiers = event.modifiers()
        if modifiers & qt.Qt.KeyboardModifier.ShiftModifier:
            anchor = (
                self._selection_anchor
                if self._selection_anchor in visible
                else path
            )
            start, end = sorted((visible.index(anchor), visible.index(path)))
            selected = set(visible[start : end + 1])
            if modifiers & qt.Qt.KeyboardModifier.ControlModifier:
                selected.update(previous)
            self._selection_anchor = anchor
        elif modifiers & qt.Qt.KeyboardModifier.ControlModifier:
            selected = previous ^ {path}
            self._selection_anchor = path
        else:
            selected = {path}
            self._selection_anchor = path
        self._set_selected_candidate_paths(selected)
        self._selection_press_path = path
        self._selection_press_position = event.globalPosition().toPoint()
        self._selection_drag_base = (
            previous
            if modifiers & qt.Qt.KeyboardModifier.ControlModifier
            else set()
        )
        application = qt.QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def _drag_candidate_selection(self, event: qt.QtGui.QMouseEvent) -> bool:
        """属性名からの縦ドラッグを見えている候補の範囲選択にする。"""
        pressed = self._selection_press_path
        if pressed is None:
            return False
        if not event.buttons() & qt.Qt.MouseButton.LeftButton:
            self._finish_candidate_drag()
            return False
        global_position = event.globalPosition().toPoint()
        if not self._selection_dragging:
            distance = (
                global_position - self._selection_press_position
            ).manhattanLength()
            if distance < qt.QApplication.startDragDistance():
                return False
            self._selection_dragging = True
            candidates = tuple(
                candidate
                for candidate in self._candidate_rows
                if self._matches_search(candidate.attribute)
            )
            self._selection_drag_paths = tuple(
                candidate.attribute.path for candidate in candidates
            )
            self._selection_drag_bottoms = tuple(
                candidate.widget.geometry().bottom()
                for candidate in candidates
            )
        if pressed not in self._selection_drag_paths:
            self._finish_candidate_drag()
            return False

        # 画面外への移動は表示中の端で止め、隠れた候補を巻き込まない
        viewport = self.candidate_scroll.viewport()
        top = self.candidate_container.mapFromGlobal(
            viewport.mapToGlobal(qt.QPoint(0, 0))
        ).y()
        bottom = top + viewport.height() - 1
        local_y = self.candidate_container.mapFromGlobal(global_position).y()
        target_y = max(top, min(bottom, local_y))
        target = min(
            bisect_left(self._selection_drag_bottoms, target_y),
            len(self._selection_drag_paths) - 1,
        )
        origin = self._selection_drag_paths.index(pressed)
        start, end = sorted((origin, target))
        selected = set(self._selection_drag_base)
        selected.update(self._selection_drag_paths[start : end + 1])
        self._set_selected_candidate_paths(selected)
        return True

    def _finish_candidate_drag(self) -> None:
        """クリック・ドラッグ終了時にアプリ全体の一時監視を解除する。"""
        application = qt.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self._selection_press_path = None
        self._selection_dragging = False
        self._selection_drag_base.clear()
        self._selection_drag_paths = ()
        self._selection_drag_bottoms = ()

    def eventFilter(self, watched: qt.QObject, event: qt.QEvent) -> bool:
        """候補の選択と設定専用の右クリックを処理し、通常の入力は維持する。"""
        kind = event.type()
        if isinstance(event, qt.QtGui.QContextMenuEvent):
            if watched is self.search_edit:
                # 標準メニューも親のStepメニューも開かず、キー入力は維持する
                event.accept()
                return True
            if watched in (self.order_list, self.order_list.viewport()):
                viewport = self.order_list.viewport()
                position = (
                    viewport.mapFrom(self.order_list, event.pos())
                    if watched is self.order_list
                    else event.pos()
                )
                if (
                    event.reason()
                    == qt.QtGui.QContextMenuEvent.Reason.Keyboard
                ):
                    current = cast(
                        qt.QListWidgetItem | None,
                        self.order_list.currentItem(),
                    )
                    if current is not None and current.isSelected():
                        position = self.order_list.visualItemRect(
                            current
                        ).center()
                self._show_order_context_menu(position)
                event.accept()
                return True
        if isinstance(event, qt.QtGui.QMouseEvent):
            if (
                watched is self.order_list.viewport()
                and event.button() == qt.Qt.MouseButton.RightButton
                and kind
                in (
                    qt.QEvent.Type.MouseButtonPress,
                    qt.QEvent.Type.MouseButtonRelease,
                )
            ):
                # Qt標準の右押下で既存の複数選択が崩れる前に対象を決める
                if kind == qt.QEvent.Type.MouseButtonPress:
                    self._select_order_context_target(
                        event.position().toPoint()
                    )
                event.accept()
                return True
            if kind == qt.QEvent.Type.MouseMove:
                if self._drag_candidate_selection(event):
                    return True
            elif kind == qt.QEvent.Type.MouseButtonRelease:
                dragging = self._selection_dragging
                self._finish_candidate_drag()
                if dragging:
                    return True
            elif (
                kind == qt.QEvent.Type.MouseButtonPress
                and event.button() == qt.Qt.MouseButton.LeftButton
            ):
                path = self._candidate_selection_targets.get(watched)
                if path is not None:
                    self._press_candidate_name(path, event)
                    return True
                if watched in (
                    self.candidate_container,
                    self.candidate_scroll.viewport(),
                ):
                    self._clear_candidate_selection()
        elif kind in (
            qt.QEvent.Type.ApplicationDeactivate,
            qt.QEvent.Type.WindowDeactivate,
            qt.QEvent.Type.UngrabMouse,
        ):
            self._finish_candidate_drag()
        return super().eventFilter(watched, event)

    def _select_order_context_target(
        self, position: qt.QPoint
    ) -> qt.QListWidgetItem | None:
        """選択内の右押下は集合を保ち、選択外の行だけを新しい単独選択にする。"""
        item = cast(
            qt.QListWidgetItem | None, self.order_list.itemAt(position)
        )
        if item is not None and not item.isSelected():
            self.order_list.clearSelection()
            self.order_list.setCurrentItem(item)
            item.setSelected(True)
        return item

    def _show_order_context_menu(self, position: qt.QPoint) -> None:
        """正式pathを持つ項目上だけで、選択行を除外するメニューを開く。"""
        self._finish_radio_sweep()
        self.order_context_menu.hide()
        item = self._select_order_context_target(position)
        if item is None or not self.remove_button.isEnabled():
            return
        self.order_context_menu.popup(
            self.order_list.viewport().mapToGlobal(position)
        )

    def _change_list_page(self, _index: int) -> None:
        """作業ページを切り替える際にメニューとなぞり・選択ドラッグを閉じる。"""
        self.order_context_menu.hide()
        self._finish_radio_sweep()
        self._finish_candidate_drag()

    def hideEvent(self, event: qt.QtGui.QHideEvent) -> None:
        """設定モードを隠す際にメニューとドラッグの一時状態を終了する。"""
        self.order_context_menu.hide()
        self._finish_radio_sweep()
        self._finish_candidate_drag()
        super().hideEvent(event)

    def _change_search(self, text: str) -> None:
        """検索欄の空白区切り語を候補行だけへ反映する。"""
        self.set_search_tokens(tuple(part.casefold() for part in text.split()))

    def _refresh_view(self) -> None:
        """定義、型、候補属性に合わせて順序と2択を描き直す。"""
        self._refresh_node_types()
        self._refresh_context()
        node_type = self._node_type
        if self.node_type_combo.currentData() is not None:
            self.node_label.setText(
                f"基準: {node_type} 型（標準属性と保存済み属性）"
            )
            self.node_label.setToolTip(
                "表示フラグは型の既定値です。型情報未確認の保存済み属性は"
                "「全て」で表示します。新しい追加属性は「選択ノード」から取得します。"
            )
        else:
            self.node_label.setText(
                f"基準: {self._node_name}（{node_type} 型）"
                if node_type is not None
                else "Maya ノードを選択してください"
            )
            self.node_label.setToolTip("")
        self._refresh_target_label()
        self._refresh_standard_options()
        self._refresh_order()
        self._refresh_candidates()
        self._sync_buttons()

    def _refresh_target_label(self) -> None:
        """同名の定義をpathで区別し、下書き名と未保存印を反映する。"""
        draft = self.draft
        entries = {entry.path: entry for entry in self.registry.entries}
        names = {
            entry.path: entry.definition.name
            for entry in self.registry.entries
            if entry.definition is not None
        }
        if draft is not None:
            names[draft.path] = draft.name
        counts = Counter(names.values())
        file_counts = Counter(
            (name, Path(path).name) for path, name in names.items()
        )
        # 選択項目だけに下書き名を使い、切替前の未保存印を残さない
        blocked = self.target_combo.blockSignals(True)
        try:
            for index in range(1, self.target_combo.count()):
                path = self.target_combo.itemData(index)
                entry = entries.get(path) if isinstance(path, str) else None
                if not isinstance(path, str) or path not in names:
                    continue
                name = names[path]
                label = name
                if counts[name] > 1:
                    location = (
                        path
                        if file_counts[name, Path(path).name] > 1
                        else Path(path).name
                    )
                    label += f"（{location}）"
                if draft is not None and path == draft.path:
                    if entry is None or entry.definition is None:
                        label += "（登録・読込状態を確認）"
                    elif not entry.enabled:
                        label += "（一覧ではOFF）"
                    if draft.is_dirty:
                        label += " *"
                elif entry is not None and entry.definition is not None:
                    if not entry.enabled:
                        label += "（一覧ではOFF）"
                else:
                    continue
                self.target_combo.setItemText(index, label)
                tooltip = path
                if draft is not None and path == draft.path:
                    if draft.is_dirty and draft.destination_path != draft.path:
                        tooltip += "\n保存後: " + draft.destination_path
                self.target_combo.setItemData(
                    index, tooltip, qt.Qt.ItemDataRole.ToolTipRole
                )
        finally:
            self.target_combo.blockSignals(blocked)

    def _refresh_order(self) -> None:
        """全登録pathを並べ、複数選択と現在行を正式pathで復元する。"""
        self.order_context_menu.hide()
        draft = self.draft
        node_type = self._node_type
        previous = set(self._selected_order_paths())
        current = self._selected_order_path()
        fixed_type = self.node_type_combo.currentData() is not None
        available = {
            attribute.path.lstrip(".")
            for attribute in (
                self._type_attributes if fixed_type else self._attributes
            )
        }
        blocked = self.order_list.blockSignals(True)
        try:
            self.order_list.clear()
            if draft is not None and node_type is not None:
                for path in draft.paths(node_type):
                    label = (
                        path
                        if path.lstrip(".") in available
                        else (
                            f"{path}（保存済み・型情報未確認）"
                            if fixed_type
                            else f"{path}（現在の候補にありません）"
                        )
                    )
                    item = qt.QListWidgetItem(label, self.order_list)
                    item.setData(qt.Qt.ItemDataRole.UserRole, path)
                    item.setToolTip(path)
            for index in range(self.order_list.count()):
                item = self.order_list.item(index)
                if item.data(qt.Qt.ItemDataRole.UserRole) == current:
                    self.order_list.setCurrentRow(index)
                    break
            for index in range(self.order_list.count()):
                item = self.order_list.item(index)
                item.setSelected(
                    item.data(qt.Qt.ItemDataRole.UserRole) in previous
                )
        finally:
            self.order_list.blockSignals(blocked)
        self._sync_buttons()

    def _selected_order_path(self) -> str | None:
        """表示順一覧の現在行にある正式pathを返す。"""
        item = cast(qt.QListWidgetItem | None, self.order_list.currentItem())
        if item is None:
            return None
        path: object = item.data(qt.Qt.ItemDataRole.UserRole)
        return path if isinstance(path, str) else None

    def _selected_order_paths(self) -> tuple[str, ...]:
        """表示順一覧で選択した正式pathを現在の並び順で返す。"""
        paths: list[str] = []
        for index in range(self.order_list.count()):
            item = self.order_list.item(index)
            if not item.isSelected():
                continue
            path: object = item.data(qt.Qt.ItemDataRole.UserRole)
            if isinstance(path, str):
                paths.append(path)
        return tuple(paths)

    def _refresh_candidates(self) -> None:
        """属性行を作り直し、Maya値・表示状態への操作を接続しない。"""
        self._finish_radio_sweep()
        self.radio_sweep.clear()
        self._finish_candidate_drag()
        for candidate in self._candidate_rows:
            candidate.widget.removeEventFilter(self)
            candidate.label.removeEventFilter(self)
            self.candidate_layout.removeWidget(candidate.widget)
            candidate.widget.deleteLater()
        self._candidate_rows.clear()
        self._candidate_rows_by_path.clear()
        self._candidate_selection_targets.clear()
        draft = self.draft
        node_type = self._node_type
        if draft is None or node_type is None:
            self._selected_candidate_paths.clear()
            self._selection_anchor = None
            return
        included_paths = {path.lstrip(".") for path in draft.paths(node_type)}
        for attribute in self._attributes:
            row = qt.QWidget(self.candidate_container)
            row.setObjectName("customFilterSetupAttributeRow")
            layout = qt.QHBoxLayout(row)
            layout.setContentsMargins(2, 1, 2, 1)
            layout.setSpacing(6)
            label = qt.QLabel(attribute.nice_name, row)
            label.setToolTip(attribute.path)
            label.setSizePolicy(
                qt.QSizePolicy.Policy.Ignored,
                qt.QSizePolicy.Policy.Preferred,
            )
            include = qt.QRadioButton("含める", row)
            exclude = qt.QRadioButton("含めない", row)
            include.setObjectName("customFilterInclude")
            exclude.setObjectName("customFilterExclude")
            if attribute.path.lstrip(".") in included_paths:
                include.setChecked(True)
            else:
                exclude.setChecked(True)
            include.clicked.connect(
                partial(self._apply_radio_included, attribute.path, True)
            )
            exclude.clicked.connect(
                partial(self._apply_radio_included, attribute.path, False)
            )
            for button, included in ((include, True), (exclude, False)):
                self.radio_sweep.add_button(
                    button,
                    on_change=partial(
                        self._sweep_radio_included, attribute.path, included
                    ),
                    group=included,
                )
            layout.addWidget(label, 1)
            layout.addWidget(include)
            layout.addWidget(exclude)
            self.candidate_layout.insertWidget(
                self.candidate_layout.count() - 1, row
            )
            candidate = _CandidateRow(
                attribute,
                row,
                label,
                include,
                exclude,
                qt.QPalette(label.palette()),
                label.autoFillBackground(),
            )
            self._candidate_rows.append(candidate)
            self._candidate_rows_by_path[attribute.path] = candidate
            for target in (row, label):
                self._candidate_selection_targets[target] = attribute.path
                target.installEventFilter(self)
        self.set_search_tokens(self._search_tokens)
        self._paint_candidate_selection(
            {candidate.attribute.path for candidate in self._candidate_rows}
        )

    def _finish_radio_sweep(self) -> None:
        """旧対象の所属変更を保ち、なぞりと保留した表示更新を終了する。"""
        self.radio_sweep.finish()
        self._flush_radio_sweep()

    def _flush_radio_sweep(self) -> None:
        """なぞりで保留した表示順と未保存印を、一回だけ同期する。"""
        if not self._radio_sweep_pending:
            return
        self._radio_sweep_pending = False
        self._refresh_order()
        self._refresh_target_label()

    def _sweep_radio_included(self, path: str, included: bool) -> None:
        """選択集合を展開せず、通過した候補一行の所属だけを変更する。"""
        draft = self.draft
        node_type = self._node_type
        if draft is None or node_type is None:
            return
        current = {item.lstrip(".") for item in draft.paths(node_type)}
        if (path.lstrip(".") in current) != included:
            self._set_paths_included((path,), included, defer_view=True)

    def _apply_radio_included(
        self, path: str, included: bool, _checked: bool = False
    ) -> None:
        """選択中の行なら選択全体、それ以外なら一行だけ所属を変える。"""
        draft = self.draft
        node_type = self._node_type
        if draft is None or node_type is None:
            return
        paths = (
            self.selected_candidate_paths()
            if path in self._selected_candidate_paths
            else (path,)
        )
        current = {item.lstrip(".") for item in draft.paths(node_type)}
        if not any(
            (item.lstrip(".") in current) != included for item in paths
        ):
            return
        self._set_paths_included(paths, included)

    def _set_paths_included(
        self,
        paths: tuple[str, ...],
        included: bool,
        *,
        defer_view: bool = False,
    ) -> None:
        """指定候補のradioを同期し、なぞり中だけ表示順などの更新を保留する。"""
        draft = self.draft
        node_type = self._node_type
        if draft is None or node_type is None or not paths:
            return
        draft.set_many_included(node_type, paths, included)
        self._refresh_node_types()
        self.candidate_container.setUpdatesEnabled(False)
        try:
            for path in paths:
                candidate = self._candidate_rows_by_path.get(path)
                if candidate is None:
                    continue
                (
                    candidate.include if included else candidate.exclude
                ).setChecked(True)
        finally:
            self.candidate_container.setUpdatesEnabled(True)
        if defer_view:
            self._radio_sweep_pending = True
            return
        self._refresh_order()
        self._refresh_target_label()
        self._sync_buttons()

    def _move_selected(self, offset: int) -> None:
        """選択した全pathをJSONの表示順で同時に一段移動する。"""
        draft = self.draft
        node_type = self._node_type
        paths = self._selected_order_paths()
        if draft is None or node_type is None or not paths:
            return
        if draft.move_many(node_type, paths, offset):
            self._refresh_order()
            self._refresh_target_label()

    def _remove_selected(self) -> None:
        """ノードにないpathも含め、選択した全pathをまとめて除外する。"""
        draft = self.draft
        node_type = self._node_type
        paths = self._selected_order_paths()
        if draft is None or node_type is None or not paths:
            return
        draft.remove_many(node_type, paths)
        self._refresh_view()

    def _clear_type(self) -> None:
        """現在の型定義を削除して標準条件への切替に戻す。"""
        if self.draft is None or self._node_type is None:
            return
        self.draft.remove_node_type(self._node_type)
        self._refresh_view()

    def _rename_filter(self) -> None:
        """ボタンを操作した位置を基準に、フィルター名の入力を開く。"""
        self.rename_filter_at(self._popup_position())

    def rename_filter_at(self, position: qt.QPoint) -> None:
        """同じフォルダーのファイル名と表示名を検証し、改名予定を下書きへ反映する。"""
        self._finish_radio_sweep()
        draft = self.draft
        if draft is None:
            return
        # 現在の下書き名を初期値にして、取消時には変更しない
        dialog = qt.QDialog(self)
        dialog.setWindowTitle("フィルター名を変更")
        name_edit = qt.QLineEdit(dialog)
        name_edit.setObjectName("renameCustomFilterName")
        name_edit.setText(draft.name)
        name_edit.selectAll()
        message = qt.QLabel(dialog)
        message.setObjectName("renameCustomFilterError")
        message.setWordWrap(True)
        buttons = qt.QDialogButtonBox(
            qt.QDialogButtonBox.StandardButton.Ok
            | qt.QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = qt.QVBoxLayout(dialog)
        layout.addWidget(
            qt.QLabel("フィルター名（拡張子 .json は省略可）:", dialog)
        )
        layout.addWidget(name_edit)
        layout.addWidget(message)
        layout.addWidget(buttons)

        def validate(text: str) -> None:
            """入力中の宛先を検査し、衝突・不正名を確定できなくする。"""
            error = self._rename_error(text)
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
            exec_dialog_near(dialog, position)
            == qt.QDialog.DialogCode.Accepted
        )
        name = name_edit.text()
        dialog.deleteLater()
        if not accepted:
            return
        # ダイアログ表示中の外部更新も確定前に再検査する
        try:
            error = self._rename_error(name)
            if error is not None:
                raise CustomFilterError(error)
            draft.rename(name)
        except CustomFilterError as error:
            self.error_occurred.emit(str(error))
            return
        self._refresh_target_label()
        self._sync_buttons()

    def _rename_error(self, name: str) -> str | None:
        """ファイル名の妥当性と、別のファイル・登録への衝突を調べる。"""
        draft = self.draft
        if draft is None:
            return "編集するフィルターを選択してください。"
        try:
            base_name = filter_file_name(name)
            destination = Path(draft.path).with_name(base_name + ".json")
            target = normalize_filter_path(destination)
            if target != draft.path:
                if destination.exists() or destination.is_symlink():
                    return "同名ファイルが存在します。"
                if any(
                    entry.path == target for entry in self.registry.entries
                ):
                    return "同名ファイルが登録されています。"
        except (CustomFilterError, OSError, ValueError) as error:
            return str(error)
        return None

    def _sync_buttons(self) -> None:
        """現在の型・選択・未保存状態に応じて操作を有効化する。"""
        draft = self.draft
        node_type = self._node_type
        selected_rows = tuple(
            index
            for index in range(self.order_list.count())
            if self.order_list.item(index).isSelected()
        )
        has_order = (
            draft is not None and node_type is not None and bool(selected_rows)
        )
        self.rename_button.setEnabled(draft is not None)
        preset_editable = any(
            entry.path == self.registry.active_preset and entry.error is None
            for entry in self.registry.presets
        )
        self.new_button.setEnabled(preset_editable)
        self.preset_new_button.setEnabled(
            any(
                entry.path == self.registry.active_group
                and entry.error is None
                for entry in self.registry.groups
            )
        )
        self.preset_rename_button.setEnabled(preset_editable)
        self.node_type_combo.setEnabled(draft is not None)
        standard_editable = draft is not None and node_type is not None
        self.standard_enabled_checkbox.setEnabled(standard_editable)
        standard_enabled = (
            standard_editable and self.standard_enabled_checkbox.isChecked()
        )
        self.standard_filter_combo.setEnabled(standard_enabled)
        self.standard_position_combo.setEnabled(standard_enabled)
        self.up_button.setEnabled(has_order and selected_rows[0] > 0)
        self.down_button.setEnabled(
            has_order and selected_rows[-1] < self.order_list.count() - 1
        )
        self.remove_button.setEnabled(has_order)
        self.remove_order_action.setEnabled(has_order)
        self.clear_type_button.setEnabled(
            draft is not None
            and node_type is not None
            and draft.has_node_type(node_type)
        )
        self.save_button.setEnabled(self.is_dirty)
        self.discard_button.setEnabled(self.is_dirty)
        self.changes_changed.emit()

    def save(self) -> bool:
        """全構成と編集中のJSONを保存し、改名先と通常表示の参照を引き継ぐ。"""
        self._finish_radio_sweep()
        draft = self.draft
        self._saving = True
        try:
            self.registry.save(draft)
            if draft is not None:
                self.saved.emit(draft.path)
        except CustomFilterError as error:
            self.error_occurred.emit(str(error))
            self._refresh_target_label()
            self._sync_buttons()
            return False
        finally:
            self._saving = False
        self._refresh_view()
        return True

    def discard(self) -> None:
        """構成と属性定義の未保存変更を破棄し、保存済みの状態へ戻す。"""
        path = self.draft.path if self.draft is not None else None
        self.registry.discard()
        available = {entry.path for entry in self.registry.entries}
        self._load_target(path if path in available else None)

    def _popup_position(self) -> qt.QPoint:
        """呼出し元と共有する入力方法から、対話画面の起点を取得する。"""
        return (
            self._dialog_position()
            if self._dialog_position is not None
            else qt.QCursor.pos()
        )

    def confirm_leave(self, position: qt.QPoint | None = None) -> bool:
        """操作位置で未保存の確認を行い、保存・破棄した場合だけ続行する。"""
        anchor = (
            qt.QPoint(position)
            if position is not None
            else self._popup_position()
        )
        self._finish_radio_sweep()
        if not self.is_dirty:
            return True
        choice = ui_dialog.warning_near(
            self,
            "未保存のカスタムフィルター設定",
            "グループ・プリセットの構成、またはフィルターに未保存の変更があります。",
            anchor,
            qt.QMessageBox.StandardButton.Save
            | qt.QMessageBox.StandardButton.Discard
            | qt.QMessageBox.StandardButton.Cancel,
            qt.QMessageBox.StandardButton.Save,
        )
        if choice == qt.QMessageBox.StandardButton.Save:
            return self.save()
        if choice == qt.QMessageBox.StandardButton.Discard:
            self.discard()
            return True
        return False

    def confirm_export(self, position: qt.QPoint) -> bool:
        """未保存変更を保存できた場合だけ、保存済みファイルの出力を許可する。"""
        self._finish_radio_sweep()
        if not self.is_dirty:
            return True
        if not confirm_export_save(self, position):
            return False
        return self.save() and not self.is_dirty
