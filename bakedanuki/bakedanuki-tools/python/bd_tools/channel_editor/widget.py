# coding: utf-8
"""Channel Editorの値入力と表示・ロック設定画面。"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Protocol, cast

from bd_util.maya.ui import (
    MayaBoolPlugsBinding,
    MayaEnumPlugsBinding,
    get_channel_box_precision,
)
from bd_util.ui import (
    BoolCheckBox,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatStepMode,
    FloatValueStepSpinBox,
    qt,
)

from .controller import ChannelEditorController, ChannelRow, ChannelStateRow

__all__ = [
    "AttributeRowWidget",
    "AttributeStateRowWidget",
    "ChannelEditorWidget",
]

_VALUE_FIELD_WIDTH = 90
_AUXILIARY_FIELD_WIDTH = 60
_FIELD_SPACING = 6
_EDITOR_WIDTH = _VALUE_FIELD_WIDTH + _FIELD_SPACING + _AUXILIARY_FIELD_WIDTH
_NAME_FIELD_PREFERRED_WIDTH = 92


class _MenuActions(Protocol):
    """Qt同梱stubの版差を、使用するQActionの追加操作だけで閉じる。"""

    def addAction(self, action: qt.QAction, /) -> None:
        """作成済みのQActionをメニューへ追加する。"""
        ...


class _AttributeNameLabel(qt.QLabel):
    """設定モードの長い属性名でも入力列を押し広げない名前欄。"""

    def sizeHint(self) -> qt.QSize:
        """属性名の文字数に依存しない推奨幅を返す。"""
        return qt.QSize(
            _NAME_FIELD_PREFERRED_WIDTH, super().sizeHint().height()
        )

    def minimumSizeHint(self) -> qt.QSize:
        """狭いドックでは名前欄を縮めて入力欄を維持する。"""
        return qt.QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, arg__1: qt.QtGui.QPaintEvent) -> None:
        """完全な名前を保持し、表示領域へ収まる文字列だけを描画する。"""
        del arg__1
        painter = qt.QPainter(self)
        painter.setPen(self.palette().color(qt.QPalette.ColorRole.WindowText))
        painter.drawText(
            self.contentsRect(),
            self.alignment(),
            self.fontMetrics().elidedText(
                self.text(), qt.Qt.TextElideMode.ElideRight, self.width()
            ),
        )
        painter.end()


class _LockCheckBox(qt.QCheckBox):
    """混在を表示しつつ、明示入力ではロックか解除だけを選ぶ。"""

    def nextCheckState(self) -> None:
        """混在からはロックへ進み、その後は二状態で切り替える。"""
        self.setCheckState(
            qt.Qt.CheckState.Unchecked
            if self.checkState() == qt.Qt.CheckState.Checked
            else qt.Qt.CheckState.Checked
        )


class AttributeRowWidget(qt.QWidget):
    """右揃えの属性名と入力Viewを並べ、詳細と操作を必要時に表示する。"""

    step_changed = qt.Signal(float)
    refresh_requested = qt.Signal()

    def __init__(
        self,
        row: ChannelRow,
        selection_count: int,
        parent: qt.QWidget,
        *,
        single_step: float | None = None,
    ) -> None:
        """初期値を書き込まず、Bindingと表示部品を接続する。"""
        super().__init__(parent)
        self.row = row
        self.selection_count = selection_count
        self.setObjectName(f"channel_{row.attribute.path}")
        self.name_label = _AttributeNameLabel(row.attribute.nice_name, self)
        self.name_label.setAlignment(
            qt.Qt.AlignmentFlag.AlignRight | qt.Qt.AlignmentFlag.AlignVCenter
        )
        self.context_menu = qt.QMenu(self)
        self.align_action = qt.QAction("この値に揃える", self)
        self.align_action.setToolTip("編集可能な対象を基準ノードの値に揃える")
        self.align_action.triggered.connect(self._align_values)
        self.refresh_action = qt.QAction("表示を更新", self)
        self.refresh_action.triggered.connect(self.refresh_requested.emit)
        menu_actions = cast(_MenuActions, self.context_menu)
        menu_actions.addAction(self.align_action)
        self.context_menu.addSeparator()
        menu_actions.addAction(self.refresh_action)
        self.editor = self._create_editor(single_step)
        # 入力グループを固定幅にし、余剰幅は属性名側へ配分する
        self.editor.setFixedWidth(_EDITOR_WIDTH)
        if isinstance(
            self.editor, (FloatSliderSpinBox, FloatValueStepSpinBox)
        ):
            editor_layout = self.editor.layout()
            if isinstance(editor_layout, qt.QHBoxLayout):
                editor_layout.setSpacing(_FIELD_SPACING)
        if isinstance(self.editor, FloatValueStepSpinBox):
            self.editor.settingsChanged.connect(self._notify_step_changed)

        # 値の混在と編集可能数はBindingの読み取り通知だけで更新する
        row.binding.state_changed.connect(self._update_state)
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.editor)
        self._update_state()

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """属性名や行の余白から操作を開き、値欄の標準メニューを維持する。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def _create_editor(
        self,
        single_step: float | None,
    ) -> (
        BoolCheckBox
        | EnumComboBox
        | FloatSliderSpinBox
        | FloatValueStepSpinBox
    ):
        """属性の種類と両側のhard limitから入力Viewを選ぶ。"""
        binding = self.row.binding
        if isinstance(binding, MayaBoolPlugsBinding):
            # ラベルを重複させず、入力列の左端にチェックを表示する
            return BoolCheckBox(binding, parent=self)
        if isinstance(binding, MayaEnumPlugsBinding):
            return EnumComboBox(binding, parent=self)
        presentation = binding.view_model.presentation
        minimum, maximum = presentation.minimum, presentation.maximum
        decimals = get_channel_box_precision()
        if minimum is not None and maximum is not None and minimum < maximum:
            editor = FloatSliderSpinBox(
                binding,
                self,
                minimum=minimum,
                maximum=maximum,
                decimals=decimals,
                layout_order="value_slider",
            )
            editor.spin_box.setUnitVisible(False)
            editor.spin_box.setFixedWidth(_VALUE_FIELD_WIDTH)
            editor.slider.setFixedWidth(_AUXILIARY_FIELD_WIDTH)
            return editor
        # 属性名の特例を型の既定値より優先し、保存済みstepだけを上書きする
        default, mode, increment = self._step_defaults()
        value_editor = FloatValueStepSpinBox(
            binding,
            self,
            decimals=decimals,
            single_step=default if single_step is None else single_step,
            step_mode=mode,
            step_increment=increment,
            step_show_unit=False,
            value_width=_VALUE_FIELD_WIDTH,
            step_width=_AUXILIARY_FIELD_WIDTH,
        )
        value_editor.spin_box.setUnitVisible(False)
        return value_editor

    def _step_defaults(self) -> tuple[float, FloatStepMode, float]:
        """Slider以外の属性に、名前・型に応じた刻み幅を割り当てる。"""
        if self.row.attribute.name == "radius":
            return 0.1, "multiplicative", 1.0
        if self.row.attribute.kind == "angle":
            return 15.0, "additive", 15.0
        return 1.0, "multiplicative", 1.0

    def _notify_step_changed(self) -> None:
        """現在のstepを通知し、Window側で属性ごとの設定を保持する。"""
        if isinstance(self.editor, FloatValueStepSpinBox):
            self.step_changed.emit(self.editor.singleStep())

    def _update_state(self) -> None:
        """混在だけを小さな印で示し、対象数と除外理由をtooltipへまとめる。"""
        binding = self.row.binding
        editable = binding.view_model.set_value_command.can_execute
        count = binding.writable_count if editable else 0
        details = [self.row.attribute.nice_name, self.row.attribute.path]
        details.append(f"編集対象: {count}/{self.selection_count} 件")
        if binding.is_mixed:
            details.append(
                "• 選択ノード間で値が異なります（基準ノードの値を表示）"
            )
        self.name_label.setText(
            ("• " if binding.is_mixed else "") + self.row.attribute.nice_name
        )
        reasons = list(self.row.excluded)
        for target in binding.target_states:
            if target.reason:
                reasons.append(f"{target.name}: {target.reason}")
        details.extend(reasons)
        defined = True
        if isinstance(binding, MayaEnumPlugsBinding):
            defined = binding.is_value_defined
            item = binding.definition.item_for_value(binding.value)
            details.append(
                f"基準値: {item.name} ({item.value})"
                if item is not None
                else f"基準値: 未定義 ({binding.value}) — 揃える操作はできません"
            )
            if not binding.definition.items:
                details.append("enumの選択肢がないため入力できません")
            details.append("定義変更後の対象の再判定: 表示を更新")
        details.append("属性名を右クリック: この値に揃える / 表示を更新")
        tooltip = "\n".join(details)
        self.name_label.setToolTip(tooltip)
        self.editor.setToolTip(tooltip)
        self.align_action.setEnabled(editable and binding.is_mixed and defined)

    def _align_values(self) -> None:
        """メニューから明示した場合だけ、対象を基準ノードの値へ揃える。"""
        try:
            self.row.binding.apply_representative_value()
        except (ValueError, RuntimeError):
            # 拒否理由はBindingのedit_failedからWindowへ通知済み
            return


class AttributeStateRowWidget(qt.QWidget):
    """値入力と同じ幅へ表示状態とロックの操作を配置する。"""

    refresh_requested = qt.Signal()

    def __init__(
        self,
        row: ChannelStateRow,
        selection_count: int,
        parent: qt.QWidget,
    ) -> None:
        """状態の読取りと、ユーザーが明示した入力だけを接続する。"""
        super().__init__(parent)
        self.row = row
        self.selection_count = selection_count
        self.setObjectName(f"channel_state_{row.attribute.path}")
        self.name_label = _AttributeNameLabel(row.attribute.nice_name, self)
        self.name_label.setAlignment(
            qt.Qt.AlignmentFlag.AlignRight | qt.Qt.AlignmentFlag.AlignVCenter
        )
        self.context_menu = qt.QMenu(self)
        self.refresh_action = qt.QAction("表示を更新", self)
        self.refresh_action.triggered.connect(self.refresh_requested.emit)
        cast(_MenuActions, self.context_menu).addAction(self.refresh_action)
        self.editor = qt.QWidget(self)
        self.editor.setFixedWidth(_EDITOR_WIDTH)
        self.display_combo = qt.QComboBox(self.editor)
        self.display_combo.setFixedWidth(_VALUE_FIELD_WIDTH)
        self.display_combo.setAccessibleName(
            f"{row.attribute.nice_name} 表示状態"
        )
        self.lock_check_box: qt.QCheckBox = _LockCheckBox(
            "ロック", self.editor
        )
        self.lock_check_box.setTristate(True)
        self.lock_check_box.setFixedWidth(_AUXILIARY_FIELD_WIDTH)
        self.lock_check_box.setAccessibleName(
            f"{row.attribute.nice_name} ロック"
        )
        controls = qt.QHBoxLayout(self.editor)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(_FIELD_SPACING)
        controls.addWidget(self.display_combo)
        controls.addWidget(self.lock_check_box)
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_FIELD_SPACING)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.editor)

        # 初期同期や外部変更は書き込まず、明示選択とクリックだけを入力にする
        self.display_combo.activated.connect(self._set_display_state)
        self.lock_check_box.clicked.connect(self._set_locked)
        row.state_binding.state_changed.connect(self._update_state)
        self._update_state()

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """属性名から状態を再取得するメニューを開く。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def _update_state(self) -> None:
        """表示とロックの混在を独立して表示し、操作可否を同期する。"""
        state = self.row.state_binding.state
        old_display = self.display_combo.blockSignals(True)
        old_lock = self.lock_check_box.blockSignals(True)
        try:
            self.display_combo.clear()
            if state.display_mixed:
                self.display_combo.addItem("混在", None)
            for label, value in (
                ("Keyable", "keyable"),
                ("ChannelBox", "channel_box"),
                ("Hide", "hidden"),
            ):
                self.display_combo.addItem(label, value)
            self.display_combo.setCurrentIndex(
                0
                if state.display_mixed
                else self.display_combo.findData(state.display_state)
            )
            self.display_combo.setEnabled(state.can_set_display)
            self.lock_check_box.setCheckState(
                qt.Qt.CheckState.PartiallyChecked
                if state.lock_mixed
                else (
                    qt.Qt.CheckState.Checked
                    if state.locked
                    else qt.Qt.CheckState.Unchecked
                )
            )
            self.lock_check_box.setEnabled(state.can_set_locked)
        finally:
            self.display_combo.blockSignals(old_display)
            self.lock_check_box.blockSignals(old_lock)

        mixed = state.display_mixed or state.lock_mixed
        self.name_label.setText(
            ("• " if mixed else "") + self.row.attribute.nice_name
        )
        details = [self.row.attribute.nice_name, self.row.attribute.path]
        display_count = (
            state.display_writable_count if state.can_set_display else 0
        )
        lock_count = state.lock_writable_count if state.can_set_locked else 0
        details.append(f"表示変更: {display_count}/{self.selection_count} 件")
        details.append(f"ロック変更: {lock_count}/{self.selection_count} 件")
        if state.display_mixed:
            details.append("表示状態が混在しています。項目の選択で揃えます")
        if state.lock_mixed:
            details.append(
                "ロック状態が混在しています。クリックでロックへ揃えます"
            )
        details.extend(self.row.excluded)
        for target in state.targets:
            reasons = tuple(
                dict.fromkeys(
                    reason
                    for reason in (target.display_reason, target.lock_reason)
                    if reason
                )
            )
            if reasons:
                details.append(f"{target.plug_name}: {' / '.join(reasons)}")
        tooltip = "\n".join(details)
        self.name_label.setToolTip(tooltip)
        self.display_combo.setToolTip(tooltip)
        self.lock_check_box.setToolTip(tooltip)

    def _set_display_state(self, index: int) -> None:
        """明示選択した表示状態だけを、一括変更する。"""
        value = self.display_combo.itemData(index)
        if value not in ("keyable", "channel_box", "hidden"):
            return
        try:
            self.row.state_binding.set_display_state(value)
        except (ValueError, RuntimeError, ExceptionGroup):
            # Bindingの通知で理由を表示し、失敗前の正本へUIを戻す
            self._update_state()

    def _set_locked(self, locked: bool) -> None:
        """属性自身のロックだけを変更し、親のロックには触れない。"""
        try:
            self.row.state_binding.set_locked(locked)
        except (ValueError, RuntimeError, ExceptionGroup):
            self._update_state()


class ChannelEditorWidget(qt.QWidget):
    """基準ノードの情報と、スクロール可能な属性入力欄を表示する。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """画面を作成してから選択監視を開始する。"""
        super().__init__(parent)
        self._steps: dict[tuple[str, str], float] = {}
        self.row_widgets: tuple[
            AttributeRowWidget | AttributeStateRowWidget, ...
        ] = ()
        self._scroll_anchor: tuple[str, int] | None = None
        self._scroll_timer = qt.QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._restore_scroll_anchor)
        self.mode_combo = qt.QComboBox(self)
        self.mode_combo.addItem("値編集", "values")
        self.mode_combo.addItem("表示・ロック", "states")
        self.mode_combo.setAccessibleName("表示モード")
        self.filter_combo = qt.QComboBox(self)
        for label, value in (
            ("全て", "all"),
            ("keyable + channelbox", "visible"),
            ("keyable", "keyable"),
            ("channelbox", "channel_box"),
            ("hide", "hidden"),
        ):
            self.filter_combo.addItem(label, value)
        self.filter_combo.setAccessibleName("属性の表示フィルター")
        self.filter_combo.setToolTip(
            "先頭の選択ノードの表示状態で絞り込みます。\n"
            "channelboxは非keyableでChannel Boxに表示する属性です。"
        )
        self.header_label = qt.QLabel("ノードを選択してください", self)
        self.header_label.setTextInteractionFlags(
            qt.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.header_label.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Preferred
        )
        self.context_menu = qt.QMenu(self)
        self.refresh_action = qt.QAction("表示を更新", self)
        self.refresh_action.setToolTip("属性の構成と入力範囲を読み直す")
        self.refresh_action.triggered.connect(self.refresh)
        cast(_MenuActions, self.context_menu).addAction(self.refresh_action)
        self.message_label = qt.QLabel(self)
        self.message_label.setWordWrap(True)
        self.message_label.hide()
        self.scroll_area = qt.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(qt.QFrame.Shape.NoFrame)
        # 内容が収まるときは縦スクロールバーの領域を名前列へ戻す
        self.scroll_area.setVerticalScrollBarPolicy(
            qt.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._contents = qt.QWidget(self.scroll_area)
        self._rows_layout = qt.QVBoxLayout(self._contents)
        self._rows_layout.setContentsMargins(0, 0, 4, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch()
        self.scroll_area.setWidget(self._contents)
        self.empty_label = qt.QLabel("", self)
        self.empty_label.setWordWrap(True)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.filter_combo)
        layout.addWidget(self.header_label)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.message_label)

        # 選択・表示更新と、ユーザーによる値変更の経路を分離する
        self.controller = ChannelEditorController(self)
        self.controller.rows_changed.connect(self._rebuild_rows)
        self.controller.error_occurred.connect(self._show_error)
        self.controller.mode_changed.connect(self._sync_mode)
        self.controller.filter_changed.connect(self._sync_filter)
        self.mode_combo.currentIndexChanged.connect(self._change_mode)
        self.filter_combo.currentIndexChanged.connect(self._change_filter)
        self._sync_filter()
        self.controller.refresh()

    def _change_mode(self, index: int) -> None:
        """編集中の値を通常のフォーカス移動で確定してから表示を切り替える。"""
        self._prepare_view_change()
        self.controller.set_mode("states" if index == 1 else "values")

    def _change_filter(self, index: int) -> None:
        """編集中の値を確定し、現在のモードのフィルターを切り替える。"""
        value = self.filter_combo.itemData(index)
        if value in ("all", "visible", "keyable", "channel_box", "hidden"):
            self._prepare_view_change()
            self.controller.set_attribute_filter(value)

    def _prepare_view_change(self) -> None:
        """行の入力を確定し、再構築前のスクロール位置を保持する。"""
        focus_widget = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "focusWidget"),
        )
        focused = focus_widget()
        if focused is not None and self._contents.isAncestorOf(focused):
            focused.clearFocus()
        self._remember_scroll_anchor()
        self.message_label.hide()

    def _sync_mode(self) -> None:
        """controllerからのモード変更を属性へ入力せず表示へ反映する。"""
        blocked = self.mode_combo.blockSignals(True)
        try:
            self.mode_combo.setCurrentIndex(
                1 if self.controller.mode == "states" else 0
            )
        finally:
            self.mode_combo.blockSignals(blocked)

    def _sync_filter(self) -> None:
        """モードごとのフィルター選択を再入力せずComboBoxへ反映する。"""
        blocked = self.filter_combo.blockSignals(True)
        try:
            self.filter_combo.setCurrentIndex(
                self.filter_combo.findData(self.controller.attribute_filter)
            )
        finally:
            self.filter_combo.blockSignals(blocked)

    def _remember_scroll_anchor(self) -> None:
        """表示先頭の属性pathを記録して、設定行の増減後も位置を保つ。"""
        position = self.scroll_area.verticalScrollBar().value()
        self._scroll_anchor = next(
            (
                (w.row.attribute.path, w.y() - position)
                for w in self.row_widgets
                if w.y() + w.height() > position
            ),
            None,
        )

    def _restore_scroll_anchor(self) -> None:
        """同じ属性が残っている場合だけスクロール位置を復元する。"""
        anchor, self._scroll_anchor = self._scroll_anchor, None
        if anchor is None or self.controller.is_disposed:
            return
        path, offset = anchor
        for widget in self.row_widgets:
            if widget.row.attribute.path == path:
                self.scroll_area.verticalScrollBar().setValue(
                    widget.y() - offset
                )
                return

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """画面の余白から、値を書き込まない表示更新を開く。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def refresh(self) -> None:
        """値を変更せず、現在のノードと属性を再取得する。"""
        self.message_label.hide()
        self.controller.refresh()

    def _show_error(self, message: str) -> None:
        """入力拒否や再構築失敗を、操作対象の画面へ表示する。"""
        self.message_label.setText(f"変更できませんでした: {message}")
        self.message_label.show()

    def _rebuild_rows(self) -> None:
        """古いViewを破棄して、新しい選択の入力行を配置する。"""
        for widget in self.row_widgets:
            widget.context_menu.close()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()
            if isinstance(widget, AttributeStateRowWidget):
                widget.display_combo.hidePopup()
            self._rows_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self.row_widgets = ()
        names = self.controller.node_names
        if names:
            self.header_label.setText(names[0].rsplit("|", 1)[-1])
            self.header_label.setToolTip(
                f"選択: {len(names)} ノード（先頭が基準）\n" + "\n".join(names)
            )
        else:
            self.header_label.setText("ノードを選択してください")
            self.header_label.setToolTip("")
        widgets: list[AttributeRowWidget | AttributeStateRowWidget] = []
        try:
            for row in self.controller.rows:
                widget: AttributeRowWidget | AttributeStateRowWidget
                if isinstance(row, ChannelStateRow):
                    widget = AttributeStateRowWidget(
                        row, len(names), self._contents
                    )
                else:
                    key = (row.attribute.path, row.attribute.kind)
                    widget = AttributeRowWidget(
                        row,
                        len(names),
                        self._contents,
                        single_step=self._steps.get(key),
                    )
                    widget.step_changed.connect(
                        partial(self._remember_step, key)
                    )
                widget.refresh_requested.connect(self.refresh)
                widgets.append(widget)
                self._rows_layout.insertWidget(len(widgets) - 1, widget)
        except Exception:
            self.controller.dispose()
            raise
        self.row_widgets = tuple(widgets)
        # 行の配置が確定してから、残っている属性のスクロール位置を復元する
        self._scroll_timer.start(0)
        self.empty_label.setVisible(not widgets)
        self.empty_label.setText(
            "フィルターに一致する bool・float 系・enum 属性がありません。"
            if names
            else "Maya ノードを選択すると、入力可能な種類の属性を表示します。"
        )

    def _remember_step(self, key: tuple[str, str], value: float) -> None:
        """ノードに依存しない属性path・型ごとのstepをWindow内に保持する。"""
        self._steps[key] = value

    def dispose(self) -> None:
        """画面の入力と監視を即時に終了する。"""
        self._scroll_timer.stop()
        self.context_menu.close()
        for widget in self.row_widgets:
            widget.context_menu.close()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()
            if isinstance(widget, AttributeStateRowWidget):
                widget.display_combo.hidePopup()
        self.controller.dispose()
