# coding: utf-8
"""Mayaの属性を参照して共有カスタムフィルターを編集する画面。"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

from bd_util.maya.node.inspection import ScalarAttributeInfo
from bd_util.ui import qt

from .custom_filter_editor import CustomFilterDraft
from .custom_filter_registry import CustomFilterRegistry
from .custom_filters import CustomFilterError, normalize_filter_path

__all__ = ["CustomFilterSetupPanel"]


@dataclass(frozen=True)
class _CandidateRow:
    """候補属性の操作部品と選択色を戻すための元の配色。"""

    attribute: ScalarAttributeInfo
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

    def __init__(
        self, registry: CustomFilterRegistry, parent: qt.QWidget
    ) -> None:
        """登録一覧と現在ノード型に対する作業中の編集画面を作る。"""
        super().__init__(parent)
        self.registry = registry
        self.draft: CustomFilterDraft | None = None
        self._node_name: str | None = None
        self._node_type: str | None = None
        self._attributes: tuple[ScalarAttributeInfo, ...] = ()
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

        self.target_label = qt.QLabel("編集するフィルター:", self)
        self.target_combo = qt.QComboBox(self)
        self.target_combo.setObjectName("customFilterSetupTarget")
        self.target_combo.setAccessibleName("編集するカスタムフィルター")
        self.name_label = qt.QLabel("表示名:", self)
        self.name_edit = qt.QLineEdit(self)
        self.name_edit.setObjectName("customFilterSetupName")
        self.search_edit = qt.QLineEdit(self)
        self.search_edit.setObjectName("customFilterSetupSearch")
        self.search_edit.setPlaceholderText("候補属性を検索")
        self.search_edit.setClearButtonEnabled(True)
        self.node_label = qt.QLabel("ノードを選択してください", self)
        self.node_label.setObjectName("customFilterSetupNode")
        self.node_label.setWordWrap(True)
        self.status_label = qt.QLabel(self)
        self.status_label.setObjectName("customFilterSetupStatus")
        self.status_label.setWordWrap(True)
        self.order_label = qt.QLabel("フィルターの表示順:", self)
        self.order_list = qt.QListWidget(self)
        self.order_list.setObjectName("customFilterSetupOrder")
        self.order_list.setMinimumHeight(28)
        self.order_list.setSizePolicy(
            qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Ignored
        )
        self.up_button = qt.QPushButton("上へ", self)
        self.down_button = qt.QPushButton("下へ", self)
        self.remove_button = qt.QPushButton("除外", self)
        self.define_type_button = qt.QPushButton("この型を0件で定義", self)
        self.clear_type_button = qt.QPushButton("この型の定義を削除", self)
        self.save_button = qt.QPushButton("JSONに保存", self)
        self.save_button.setObjectName("customFilterSetupSave")
        self.discard_button = qt.QPushButton("変更を破棄", self)
        self.candidates_label = qt.QLabel("属性をフィルターに含める:", self)
        self.include_all_button = qt.QPushButton("候補をすべて含める", self)
        self.include_all_button.setObjectName(
            "customFilterIncludeAllCandidates"
        )
        self.exclude_all_button = qt.QPushButton("候補をすべて含めない", self)
        self.exclude_all_button.setObjectName(
            "customFilterExcludeAllCandidates"
        )
        bulk_tooltip = (
            "現在のAttribute Filterと属性検索に一致する候補全件に適用します。"
            "スクロール外の候補も対象です。"
        )
        self.include_all_button.setToolTip(bulk_tooltip)
        self.exclude_all_button.setToolTip(bulk_tooltip)
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
        self.candidate_container.installEventFilter(self)
        self.candidate_scroll.viewport().installEventFilter(self)

        grid = qt.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self.target_label, 0, 0)
        grid.addWidget(self.target_combo, 0, 1)
        grid.addWidget(self.name_label, 1, 0)
        grid.addWidget(self.name_edit, 1, 1)
        grid.addWidget(qt.QLabel("属性検索:", self), 2, 0)
        grid.addWidget(self.search_edit, 2, 1)
        order_buttons = qt.QHBoxLayout()
        for button in (self.up_button, self.down_button, self.remove_button):
            order_buttons.addWidget(button)
        order_pane = qt.QWidget(self)
        order_layout = qt.QVBoxLayout(order_pane)
        order_layout.setContentsMargins(0, 0, 0, 0)
        order_layout.setSpacing(4)
        order_layout.addWidget(self.order_label)
        order_layout.addWidget(self.order_list, 1)
        order_layout.addLayout(order_buttons)
        bulk_buttons = qt.QHBoxLayout()
        bulk_buttons.addWidget(self.include_all_button)
        bulk_buttons.addWidget(self.exclude_all_button)
        candidate_pane = qt.QWidget(self)
        candidate_layout = qt.QVBoxLayout(candidate_pane)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.setSpacing(4)
        candidate_layout.addWidget(self.candidates_label)
        candidate_layout.addLayout(bulk_buttons)
        candidate_layout.addWidget(self.candidate_scroll, 1)
        self.list_splitter = qt.QSplitter(qt.Qt.Orientation.Vertical, self)
        self.list_splitter.setObjectName("customFilterSetupSplitter")
        self.list_splitter.setChildrenCollapsible(False)
        # 大量の候補行は境界を離したときだけ再配置する
        self.list_splitter.setOpaqueResize(False)
        self.list_splitter.addWidget(order_pane)
        self.list_splitter.addWidget(candidate_pane)
        self.list_splitter.setStretchFactor(0, 1)
        self.list_splitter.setStretchFactor(1, 2)
        self.list_splitter.setSizes([140, 280])
        type_buttons = qt.QHBoxLayout()
        type_buttons.addWidget(self.define_type_button)
        type_buttons.addWidget(self.clear_type_button)
        save_buttons = qt.QHBoxLayout()
        save_buttons.addWidget(self.save_button)
        save_buttons.addWidget(self.discard_button)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(grid)
        layout.addWidget(self.node_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.list_splitter, 1)
        layout.addLayout(type_buttons)
        layout.addLayout(save_buttons)

        self.target_combo.currentIndexChanged.connect(self._change_target)
        self.name_edit.textChanged.connect(self._change_name)
        self.search_edit.textChanged.connect(self._change_search)
        self.order_list.currentRowChanged.connect(self._sync_buttons)
        self.up_button.clicked.connect(partial(self._move_selected, -1))
        self.down_button.clicked.connect(partial(self._move_selected, 1))
        self.remove_button.clicked.connect(self._remove_selected)
        self.include_all_button.clicked.connect(
            partial(self._apply_bulk_included, True)
        )
        self.exclude_all_button.clicked.connect(
            partial(self._apply_bulk_included, False)
        )
        self.define_type_button.clicked.connect(self._define_type)
        self.clear_type_button.clicked.connect(self._clear_type)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(self.discard)
        self.registry.changed.connect(self.refresh_entries)
        self.refresh_entries()
        self._refresh_view()

    def refresh_entries(self) -> None:
        """ON/OFFを問わず正常な登録を編集候補へ反映する。"""
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
        self._clear_candidate_selection()
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
        if not self.confirm_leave():
            blocked = self.target_combo.blockSignals(True)
            try:
                old = self._index_for_path(
                    self.draft.path if self.draft is not None else None
                )
                self.target_combo.setCurrentIndex(max(0, old))
            finally:
                self.target_combo.blockSignals(blocked)
            return
        self._load_target(path)

    def set_node(
        self,
        node_name: str | None,
        node_type: str | None,
        attributes: tuple[ScalarAttributeInfo, ...],
    ) -> None:
        """選択末尾のノード型と現在の標準表示条件の候補を示す。"""
        if node_name != self._node_name or node_type != self._node_type:
            self._clear_candidate_selection()
        self._node_name = node_name
        self._node_type = node_type
        self._attributes = attributes
        self._refresh_view()

    def set_search_tokens(self, tokens: tuple[str, ...]) -> None:
        """現在の属性候補へ検索語を適用し、所属は変更しない。"""
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

    def _matches_search(self, attribute: ScalarAttributeInfo) -> bool:
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
            tooltip = f"{path}\n{scope}"
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
        """属性名と余白の選択操作だけを受け、ラジオ操作を妨げない。"""
        kind = event.type()
        if isinstance(event, qt.QtGui.QMouseEvent):
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

    def hideEvent(self, event: qt.QtGui.QHideEvent) -> None:
        """設定モードを隠す際にドラッグの一時監視を解除する。"""
        self._finish_candidate_drag()
        super().hideEvent(event)

    def _change_search(self, text: str) -> None:
        """検索欄の空白区切り語を候補行だけへ反映する。"""
        self.set_search_tokens(tuple(part.casefold() for part in text.split()))

    def _refresh_view(self) -> None:
        """定義、型、候補属性に合わせて順序と2択を描き直す。"""
        draft = self.draft
        node_type = self._node_type
        blocked = self.name_edit.blockSignals(True)
        try:
            self.name_edit.setText(draft.name if draft is not None else "")
        finally:
            self.name_edit.blockSignals(blocked)
        self.node_label.setText(
            f"基準: {self._node_name}（{node_type} 型）"
            if node_type is not None
            else "Maya ノードを選択してください"
        )
        self._refresh_status()
        self._refresh_order()
        self._refresh_candidates()
        self._sync_buttons()

    def _refresh_status(self) -> None:
        """未定義型の代替表示と未保存状態を明示する。"""
        draft = self.draft
        node_type = self._node_type
        if draft is None:
            message = "編集するフィルターを選択してください"
        elif node_type is None:
            message = "基準ノードを選ぶと型ごとの属性を編集できます"
        elif not draft.has_node_type(node_type):
            message = (
                f"{node_type} 型は未定義: 保存後も"
                "keyable + channelbox を表示します"
            )
        else:
            message = (
                f"{node_type} 型は{len(draft.paths(node_type))}件を定義中"
            )
        if draft is not None and draft.is_dirty:
            message += "（未保存）"
        self.status_label.setText(message)

    def _refresh_order(self) -> None:
        """現在の型の全登録pathを、ノードにないものも含めて並べる。"""
        draft = self.draft
        node_type = self._node_type
        previous = self._selected_order_path()
        available = {attribute.path for attribute in self._attributes}
        blocked = self.order_list.blockSignals(True)
        try:
            self.order_list.clear()
            if draft is not None and node_type is not None:
                for path in draft.paths(node_type):
                    label = (
                        path
                        if path.lstrip(".") in available
                        else f"{path}（現在のノードにありません）"
                    )
                    item = qt.QListWidgetItem(label, self.order_list)
                    item.setData(qt.Qt.ItemDataRole.UserRole, path)
                    item.setToolTip(path)
            if previous is not None:
                for index in range(self.order_list.count()):
                    item = self.order_list.item(index)
                    if item.data(qt.Qt.ItemDataRole.UserRole) == previous:
                        self.order_list.setCurrentRow(index)
                        break
        finally:
            self.order_list.blockSignals(blocked)
        self._sync_buttons()

    def _selected_order_path(self) -> str | None:
        """表示順一覧で選択した正式pathを返す。"""
        item = cast(qt.QListWidgetItem | None, self.order_list.currentItem())
        if item is None:
            return None
        path: object = item.data(qt.Qt.ItemDataRole.UserRole)
        return path if isinstance(path, str) else None

    def _refresh_candidates(self) -> None:
        """属性行を作り直し、Maya値・表示状態への操作を接続しない。"""
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
            if attribute.path in included_paths:
                include.setChecked(True)
            else:
                exclude.setChecked(True)
            include.clicked.connect(
                partial(self._apply_radio_included, attribute.path, True)
            )
            exclude.clicked.connect(
                partial(self._apply_radio_included, attribute.path, False)
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
        if not any((item in current) != included for item in paths):
            return
        self._set_paths_included(paths, included)

    def _set_paths_included(
        self, paths: tuple[str, ...], included: bool
    ) -> None:
        """指定候補だけを一度で変更し、radioと表示順を一度ずつ同期する。"""
        draft = self.draft
        node_type = self._node_type
        if draft is None or node_type is None or not paths:
            return
        draft.set_many_included(node_type, paths, included)
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
        self._refresh_order()
        self._refresh_status()
        self._sync_buttons()

    def _apply_bulk_included(self, included: bool) -> None:
        """現在候補の所属を一括変更し、行と表示順を一度ずつ更新する。"""
        paths = self._candidate_paths()
        # 候補外pathを保持したまま、検索結果だけを作業中の定義へ反映する
        self._set_paths_included(paths, included)

    def _move_selected(self, offset: int) -> None:
        """選択したpathをJSONの表示順で一段移動する。"""
        draft = self.draft
        node_type = self._node_type
        path = self._selected_order_path()
        if draft is None or node_type is None or path is None:
            return
        if draft.move(node_type, path, offset):
            self._refresh_order()
            self._refresh_status()

    def _remove_selected(self) -> None:
        """現在ノードにないpathも順序一覧から除外できるようにする。"""
        draft = self.draft
        node_type = self._node_type
        path = self._selected_order_path()
        if draft is None or node_type is None or path is None:
            return
        draft.set_included(node_type, path, False)
        self._refresh_view()

    def _define_type(self) -> None:
        """属性0件の明示的なノード型定義を作る。"""
        if self.draft is None or self._node_type is None:
            return
        self.draft.ensure_node_type(self._node_type)
        self._refresh_view()

    def _clear_type(self) -> None:
        """現在の型定義を削除して標準条件への切替に戻す。"""
        if self.draft is None or self._node_type is None:
            return
        self.draft.remove_node_type(self._node_type)
        self._refresh_view()

    def _change_name(self, text: str) -> None:
        """表示名の入力を保存前の作業中データへ保持する。"""
        if self.draft is None:
            return
        self.draft.name = text
        self._refresh_status()

    def _sync_buttons(self, _row: int = -1) -> None:
        """現在の型・選択・未保存状態に応じて操作を有効化する。"""
        draft = self.draft
        node_type = self._node_type
        row = self.order_list.currentRow()
        has_order = draft is not None and node_type is not None and row >= 0
        self.name_edit.setEnabled(draft is not None)
        self.up_button.setEnabled(has_order and row > 0)
        self.down_button.setEnabled(
            has_order and row < self.order_list.count() - 1
        )
        self.remove_button.setEnabled(has_order)
        self.define_type_button.setEnabled(
            draft is not None
            and node_type is not None
            and not draft.has_node_type(node_type)
        )
        self.clear_type_button.setEnabled(
            draft is not None
            and node_type is not None
            and draft.has_node_type(node_type)
        )
        self.save_button.setEnabled(draft is not None and draft.is_dirty)
        self.discard_button.setEnabled(draft is not None and draft.is_dirty)
        has_candidates = (
            draft is not None
            and node_type is not None
            and any(
                self._matches_search(attribute)
                for attribute in self._attributes
            )
        )
        self.include_all_button.setEnabled(has_candidates)
        self.exclude_all_button.setEnabled(has_candidates)

    def save(self) -> bool:
        """共有JSONへ保存し、通常モードの登録定義を再読込する。"""
        draft = self.draft
        if draft is None:
            return False
        try:
            draft.set_name(self.name_edit.text())
            if draft.is_dirty:
                draft.save()
                self.registry.reload(draft.path)
                self.saved.emit(draft.path)
        except CustomFilterError as error:
            self.error_occurred.emit(str(error))
            self._refresh_status()
            self._sync_buttons()
            return False
        self._refresh_view()
        return True

    def discard(self) -> None:
        """未保存の変更を破棄し、現在の共有JSONを読み直す。"""
        if self.draft is not None:
            self._load_target(self.draft.path)

    def confirm_leave(self) -> bool:
        """未保存のまま編集対象やモードを離れる操作を確認する。"""
        if self.draft is None or not self.draft.is_dirty:
            return True
        choice = qt.QMessageBox.warning(
            self,
            "未保存のカスタムフィルター",
            "JSONに保存していない変更があります。",
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
