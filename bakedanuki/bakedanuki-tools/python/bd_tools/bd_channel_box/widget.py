# coding: utf-8
"""bdChannelBoxの値入力と表示・ロック設定画面。"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Protocol, cast

from bd_util.maya.ui import (
    ChannelDisplayState,
    MayaBoolPlugsBinding,
    MayaEnumPlugsBinding,
    MayaEditSession,
    MayaFloatPlugsBinding,
    get_channel_box_precision,
)
from bd_util.ui import (
    BoolCheckBox,
    CheckBoxSweep,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatStepMode,
    FloatValueStepSpinBox,
    RadioButtonSweep,
    qt,
)

from .controller import ChannelBoxController, ChannelRow, ChannelStateRow
from .table import ChannelTableView, TableRow

__all__ = [
    "AttributeRowWidget",
    "AttributeStateRowWidget",
    "ChannelBoxWidget",
]

_VALUE_FIELD_WIDTH = 90
_AUXILIARY_FIELD_WIDTH = 60
_FIELD_SPACING = 6
_EDITOR_WIDTH = _VALUE_FIELD_WIDTH + _FIELD_SPACING + _AUXILIARY_FIELD_WIDTH
_STATE_EDITOR_WIDTH = 200
_NAME_FIELD_PREFERRED_WIDTH = 92
_DISPLAY_OPTIONS: tuple[tuple[ChannelDisplayState, str, str], ...] = (
    ("keyable", "key", "Keyable: キー設定可能"),
    ("channel_box", "ch", "ChannelBox: キー設定不可・Channel Boxに表示"),
    ("hidden", "hide", "Hide: キー設定不可・Channel Boxから非表示"),
)


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
        align_callback: Callable[[], None] | None = None,
        wheel_editing_without_focus: bool = False,
    ) -> None:
        """初期値を書き込まず、Bindingと表示部品を接続する。"""
        if type(wheel_editing_without_focus) is not bool:
            raise TypeError(
                "wheel_editing_without_focusにはboolを指定してください"
            )
        super().__init__(parent)
        self.row = row
        self.selection_count = selection_count
        self._align_callback = align_callback
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
        self.editor = self._create_editor(
            single_step,
            wheel_editing_without_focus,
        )
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
        wheel_editing_without_focus: bool,
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
            return EnumComboBox(
                binding,
                parent=self,
                wheel_requires_focus=not wheel_editing_without_focus,
            )
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
            editor.spin_box.set_wheel_requires_focus(
                not wheel_editing_without_focus
            )
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
            value_wheel_requires_focus=not wheel_editing_without_focus,
            step_wheel_requires_focus=not wheel_editing_without_focus,
            value_width=_VALUE_FIELD_WIDTH,
            step_width=_AUXILIARY_FIELD_WIDTH,
        )
        value_editor.spin_box.setUnitVisible(False)
        return value_editor

    def set_wheel_editing_without_focus(self, enabled: bool) -> None:
        """値欄・Step欄・enumへ、未フォーカス時のホイール方針を反映する。"""
        if type(enabled) is not bool:
            raise TypeError("enabledにはboolを指定してください")
        requires_focus = not enabled
        editor = self.editor
        if isinstance(editor, EnumComboBox):
            editor.set_wheel_requires_focus(requires_focus)
        elif isinstance(editor, FloatSliderSpinBox):
            editor.spin_box.set_wheel_requires_focus(requires_focus)
        elif isinstance(editor, FloatValueStepSpinBox):
            editor.spin_box.set_wheel_requires_focus(requires_focus)
            editor.step_spin_box.set_wheel_requires_focus(requires_focus)

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
        if self._align_callback is not None:
            self._align_callback()
            return
        try:
            self.row.binding.apply_representative_value()
        except (ValueError, RuntimeError):
            # 拒否理由はBindingのedit_failedからWindowへ通知済み
            return


class AttributeStateRowWidget(qt.QWidget):
    """200pxの操作欄へ表示状態のラジオボタンとロックを配置する。"""

    refresh_requested = qt.Signal()

    def __init__(
        self,
        row: ChannelStateRow,
        selection_count: int,
        parent: qt.QWidget,
        *,
        edit_session: MayaEditSession | None = None,
    ) -> None:
        """状態の読取りと、ユーザーが明示した入力だけを接続する。"""
        super().__init__(parent)
        self._edit_session = edit_session
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
        self.editor.setFixedWidth(_STATE_EDITOR_WIDTH)
        self.display_buttons: dict[ChannelDisplayState, qt.QRadioButton] = {}
        self._display_group = qt.QtWidgets.QButtonGroup(self.editor)
        self._display_group.setExclusive(True)
        controls = qt.QHBoxLayout(self.editor)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(_FIELD_SPACING)
        for value, label, description in _DISPLAY_OPTIONS:
            button = qt.QRadioButton(label, self.editor)
            button.setAutoExclusive(False)
            button.setAccessibleName(
                f"{row.attribute.nice_name} {description}"
            )
            self._display_group.addButton(button)
            self.display_buttons[value] = button
            controls.addWidget(button)
            button.clicked.connect(partial(self._set_display_state, value))
        self.lock_check_box: qt.QCheckBox = _LockCheckBox("lock", self.editor)
        self.lock_check_box.setTristate(True)
        self.lock_check_box.setAccessibleName(
            f"{row.attribute.nice_name} ロック"
        )
        controls.addStretch(1)
        controls.addWidget(self.lock_check_box)
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_FIELD_SPACING)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.editor)

        # 初期同期や外部変更は書き込まず、明示選択とクリックだけを入力にする
        self.lock_check_box.clicked.connect(self.set_locked)
        row.state_binding.state_changed.connect(self._update_state)
        self._update_state()

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """属性名から状態を再取得するメニューを開く。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def _update_state(self) -> None:
        """表示とロックの混在を独立して表示し、操作可否を同期する。"""
        state = self.row.state_binding.state
        available = not self.row.state_binding.is_disposed
        old_display = tuple(
            button.blockSignals(True)
            for button in self.display_buttons.values()
        )
        old_lock = self.lock_check_box.blockSignals(True)
        # 混在時には排他制御を一時解除し、3つとも未選択へ同期する
        self._display_group.setExclusive(False)
        try:
            for value, button in self.display_buttons.items():
                button.setChecked(
                    not state.display_mixed and value == state.display_state
                )
                button.setEnabled(available and state.can_set_display)
            self.lock_check_box.setCheckState(
                qt.Qt.CheckState.PartiallyChecked
                if state.lock_mixed
                else (
                    qt.Qt.CheckState.Checked
                    if state.locked
                    else qt.Qt.CheckState.Unchecked
                )
            )
            self.lock_check_box.setEnabled(available and state.can_set_locked)
        finally:
            self._display_group.setExclusive(True)
            for button, blocked in zip(
                self.display_buttons.values(), old_display, strict=True
            ):
                button.blockSignals(blocked)
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
        for value, _label, description in _DISPLAY_OPTIONS:
            self.display_buttons[value].setToolTip(
                f"{description}\n左ドラッグで複数行をなぞって選択\n{tooltip}"
            )
        self.lock_check_box.setToolTip(
            "Lock: 属性自身のロック／解除\n"
            "左ドラッグで開始時の操作を複数行へ適用\n"
            f"{tooltip}"
        )

    def _set_display_state(
        self, value: ChannelDisplayState, _checked: bool = False
    ) -> None:
        """明示選択した表示状態だけを、一括変更する。"""
        try:
            session = self._edit_session
            self.row.state_binding.set_display_state(
                value,
                edit_session=(
                    session
                    if session is not None and session.is_editing
                    else None
                ),
            )
        except (ValueError, RuntimeError, ExceptionGroup):
            # Bindingの通知で理由を表示し、操作後は正本の選択へ戻す
            pass
        finally:
            self._update_state()

    def set_locked(self, locked: bool) -> None:
        """属性自身のロックだけを変更し、親のロックには触れない。"""
        try:
            session = self._edit_session
            self.row.state_binding.set_locked(
                locked,
                edit_session=(
                    session
                    if session is not None and session.is_editing
                    else None
                ),
            )
        except (ValueError, RuntimeError, ExceptionGroup):
            # Bindingの通知で理由を表示し、操作後は正本の状態へ戻す
            pass
        finally:
            self._update_state()


class ChannelBoxWidget(qt.QWidget):
    """基準ノードの情報と、スクロール可能な属性入力欄を表示する。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """画面を作成してから選択監視を開始する。"""
        super().__init__(parent)
        self._steps: dict[tuple[str, str], float] = {}
        self._changing_steps = False
        self.row_widgets: tuple[
            AttributeRowWidget | AttributeStateRowWidget, ...
        ] = ()
        self._scroll_anchor: tuple[str, int] | None = None
        self._table_node_ids: tuple[str, ...] = ()
        self._scroll_timer = qt.QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._restore_scroll_anchor)
        self.menu_bar = qt.QMenuBar(self)
        self.menu_bar.setNativeMenuBar(False)
        self.settings_menu = qt.QMenu("設定", self.menu_bar)
        self.menu_bar.addMenu(self.settings_menu)
        self.wheel_editing_action = qt.QAction(
            "未フォーカス時のホイール編集", self
        )
        self.wheel_editing_action.setObjectName(
            "wheelEditingWithoutFocusAction"
        )
        self.wheel_editing_action.setCheckable(True)
        self.wheel_editing_action.setChecked(False)
        self.wheel_editing_action.setToolTip(
            "フォーカスのない値欄・Step欄・enum欄にマウスを重ねた状態で、"
            "ホイールによる値変更を有効にします。"
        )
        cast(_MenuActions, self.settings_menu).addAction(
            self.wheel_editing_action
        )
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
        self.mode_label = qt.QLabel("Mode:", self)
        self.filter_label = qt.QLabel("Attribute Filter:", self)
        # 説明を右揃えの共通列に置き、残りの幅を選択欄へ配分する
        controls_layout = qt.QGridLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        controls_layout.setColumnStretch(1, 1)
        for index, (label, combo) in enumerate(
            (
                (self.mode_label, self.mode_combo),
                (self.filter_label, self.filter_combo),
            )
        ):
            label.setAlignment(
                qt.Qt.AlignmentFlag.AlignRight
                | qt.Qt.AlignmentFlag.AlignVCenter
            )
            label.setBuddy(combo)
            controls_layout.addWidget(label, index, 0)
            controls_layout.addWidget(combo, index, 1)
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
        self.table_view = ChannelTableView(self)
        self.scroll_area = self.table_view
        self.empty_label = qt.QLabel("", self)
        self.empty_label.setWordWrap(True)
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setMenuBar(self.menu_bar)
        layout.addLayout(controls_layout)
        layout.addWidget(self.header_label)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.message_label)

        # 選択・表示更新と、ユーザーによる値変更の経路を分離する
        self.controller = ChannelBoxController(self)
        self.table_view.numeric_input_requested.connect(
            self._apply_numeric_input
        )
        self.table_view.numeric_input_rejected.connect(self._show_error)
        self.state_sweep = RadioButtonSweep(self.scroll_area)
        self.lock_sweep = CheckBoxSweep(self.scroll_area)
        for sweep in (self.state_sweep, self.lock_sweep):
            sweep.started.connect(self.controller.begin_state_edit)
            sweep.finished.connect(self.controller.state_edit_session.finish)
            self.controller.state_edit_session.finished.connect(sweep.finish)
        self.controller.rows_changed.connect(self._rebuild_rows)
        self.controller.rows_about_to_change.connect(
            self._cancel_transient_input
        )
        self.controller.error_occurred.connect(self._show_error)
        self.controller.operation_reported.connect(self._show_operation_report)
        self.controller.mode_changed.connect(self._sync_mode)
        self.controller.filter_changed.connect(self._sync_filter)
        self.mode_combo.currentIndexChanged.connect(self._change_mode)
        self.filter_combo.currentIndexChanged.connect(self._change_filter)
        self.wheel_editing_action.toggled.connect(
            self._set_wheel_editing_without_focus
        )
        self._sync_filter()
        self.controller.refresh()

    def _set_wheel_editing_without_focus(self, enabled: bool) -> None:
        """表示中の全値入力行へ、メニューで選んだホイール方針を反映する。"""
        for widget in self.row_widgets:
            if isinstance(widget, AttributeRowWidget):
                widget.set_wheel_editing_without_focus(enabled)

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
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.table_view.finish_numeric_edit(commit=True)
        focus_widget = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "focusWidget"),
        )
        focused = focus_widget()
        if focused is not None and self.table_view.isAncestorOf(focused):
            focused.clearFocus()
        self._remember_scroll_anchor()

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
        self._scroll_anchor = next(
            (
                (w.row.attribute.path, w.y())
                for w in self.row_widgets
                if w.y() + w.height() > 0
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
                    self.scroll_area.verticalScrollBar().value()
                    + widget.y()
                    - offset
                )
                return

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """画面の余白から、値を書き込まない表示更新を開く。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def refresh(self) -> None:
        """値を変更せず、現在のノードと属性を再取得する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.message_label.hide()
        self.controller.refresh()

    def _show_error(self, message: str) -> None:
        """入力拒否や再構築失敗を、操作対象の画面へ表示する。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        self.message_label.setText(f"変更できませんでした: {message}")
        self.message_label.show()

    def _show_operation_report(self, message: str) -> None:
        """一括操作で対象外にした属性を通知し、理由がなければ表示を閉じる。"""
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))

    def _cancel_transient_input(self) -> None:
        """Bindingを破棄する前に、古い選択への入力とメニューを終了する。"""
        self.table_view.finish_numeric_edit(commit=False)
        self.context_menu.close()
        for widget in self.row_widgets:
            widget.context_menu.close()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()

    def _apply_numeric_input(self, keys: object, value: float) -> None:
        """Qtの明示入力通知を受け、凍結した選択行へ一度だけ書き込む。"""
        selected = cast(tuple[tuple[str, str], ...], keys)
        try:
            self.controller.apply_numeric_values(selected, value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _request_numeric_value(
        self,
        key: tuple[str, str],
        binding: MayaFloatPlugsBinding,
        value: float,
    ) -> bool:
        """値欄の絶対値入力を、現在選択中の数値属性へ適用する。"""
        display_value = binding.view_model.presentation.to_display(value)
        try:
            self.controller.apply_numeric_values(
                self._action_keys(key), display_value
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_numeric_step(
        self,
        key: tuple[str, str],
        editor: FloatValueStepSpinBox | FloatSliderSpinBox,
        steps: int,
    ) -> bool:
        """操作元のStepによる共通増減量を、選択数値属性の現在値へ加える。"""
        display_offset = editor.spin_box.singleStep() * steps
        try:
            self.controller.offset_numeric_values(
                self._action_keys(key), display_offset
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_slider_value(
        self,
        key: tuple[str, str],
        binding: MayaFloatPlugsBinding,
        editor: FloatSliderSpinBox,
        value: float,
    ) -> bool:
        """Slider入力を選択数値へ適用し、拒否時は連続操作を終了する。"""
        display_value = binding.view_model.presentation.to_display(value)
        try:
            self.controller.apply_numeric_values(
                self._action_keys(key), display_value
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
            editor.slider.setSliderDown(False)
        return True

    def _request_bool_value(self, key: tuple[str, str], value: bool) -> bool:
        """選択中のbool属性を、操作したCheckBoxと同じ状態へ揃える。"""
        try:
            self.controller.apply_bool_values(self._action_keys(key), value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _request_enum_value(self, key: tuple[str, str], value: int) -> bool:
        """選択中で定義が一致するenum属性を、操作した項目へ揃える。"""
        try:
            keys = self._action_keys(key)
            self.controller.apply_enum_values(keys, key, value)
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))
        return True

    def _configure_value_input(
        self, widget: AttributeRowWidget, key: tuple[str, str]
    ) -> None:
        """既存Viewの入力を、属性選択を解釈する一括操作へ接続する。"""
        editor = widget.editor
        binding = widget.row.binding
        if isinstance(
            editor, (FloatValueStepSpinBox, FloatSliderSpinBox)
        ) and isinstance(binding, MayaFloatPlugsBinding):
            editor.spin_box.setValueRequestHandler(
                partial(self._request_numeric_value, key, binding)
            )
            editor.spin_box.setStepRequestHandler(
                partial(self._request_numeric_step, key, editor)
            )
            if isinstance(editor, FloatSliderSpinBox):
                editor.slider.setValueRequestHandler(
                    partial(self._request_slider_value, key, binding, editor)
                )
                editor.slider.editStarted.connect(
                    self.controller.begin_value_edit
                )
                editor.slider.editFinished.connect(
                    self.controller.finish_value_edit
                )
        elif isinstance(editor, BoolCheckBox):
            editor.setValueRequestHandler(
                partial(self._request_bool_value, key)
            )
        elif isinstance(editor, EnumComboBox):
            editor.setValueRequestHandler(
                partial(self._request_enum_value, key)
            )

    def _action_keys(
        self, key: tuple[str, str]
    ) -> tuple[tuple[str, str], ...]:
        """選択内の行は全選択を対象にし、未選択行の操作はその行だけにする。"""
        selected = self.table_view.selected_keys()
        return selected if key in selected else (key,)

    def _run_selected_action(self, action: str, key: tuple[str, str]) -> None:
        """右クリックの明示操作を、入力部品と独立した選択編集入口へ渡す。"""
        self.state_sweep.finish()
        self.lock_sweep.finish()
        selected = self._action_keys(key)
        try:
            if action == "align":
                self.controller.align_selected_values(selected)
            elif action in ("lock", "unlock"):
                self.controller.set_selected_locked(selected, action == "lock")
            elif action in ("keyable", "channel_box", "hidden"):
                self.controller.set_selected_display(selected, action)
            else:
                raise ValueError(f"未対応の選択操作です: {action}")
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self._show_error(str(error))

    def _prepare_row_menu(
        self, widget: AttributeRowWidget | AttributeStateRowWidget
    ) -> None:
        """右クリックした行を選択対象に含め、全選択の状態でメニューを準備する。"""
        key = (widget.row.attribute.path, widget.row.attribute.kind)
        if key not in self.table_view.selected_keys():
            self.table_view.select_key(key)
        if isinstance(widget, AttributeRowWidget):
            selected = set(self.table_view.selected_keys())
            widget.align_action.setEnabled(
                any(
                    isinstance(row, ChannelRow)
                    and (row.attribute.path, row.attribute.kind) in selected
                    and row.binding.is_mixed
                    and row.binding.view_model.set_value_command.can_execute
                    and (
                        not isinstance(row.binding, MayaEnumPlugsBinding)
                        or row.binding.is_value_defined
                    )
                    for row in self.controller.rows
                )
            )

    def _add_selection_menu(
        self, widget: AttributeRowWidget | AttributeStateRowWidget
    ) -> None:
        """値編集と状態編集の両モードに、選択属性の状態操作を追加する。"""
        key = (widget.row.attribute.path, widget.row.attribute.kind)
        menu = widget.context_menu
        menu.addSeparator()
        for action, label in (
            ("lock", "ロック"),
            ("unlock", "ロック解除"),
            ("keyable", "Keyable"),
            ("channel_box", "ChannelBox"),
            ("hidden", "Hide"),
        ):
            item = qt.QAction(label, menu)
            item.setObjectName(f"selected_{action}")
            item.triggered.connect(
                partial(self._run_selected_action, action, key)
            )
            cast(_MenuActions, menu).addAction(item)
        menu.aboutToShow.connect(partial(self._prepare_row_menu, widget))

    def _rebuild_rows(self) -> None:
        """古いViewを破棄して、新しい選択の入力行を配置する。"""
        self.state_sweep.clear()
        self.lock_sweep.clear()
        for widget in self.row_widgets:
            widget.context_menu.close()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()
            widget.hide()
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
                        row,
                        len(names),
                        self.table_view.viewport(),
                        edit_session=self.controller.state_edit_session,
                    )
                    for button in widget.display_buttons.values():
                        self.state_sweep.add_button(button)
                    self.lock_sweep.add_button(
                        widget.lock_check_box, on_change=widget.set_locked
                    )
                else:
                    key = (row.attribute.path, row.attribute.kind)
                    widget = AttributeRowWidget(
                        row,
                        len(names),
                        self.table_view.viewport(),
                        single_step=self._steps.get(key),
                        align_callback=partial(
                            self._run_selected_action, "align", key
                        ),
                        wheel_editing_without_focus=(
                            self.wheel_editing_action.isChecked()
                        ),
                    )
                    widget.step_changed.connect(
                        partial(self._apply_step_value, key)
                    )
                    self._configure_value_input(widget, key)
                widget.refresh_requested.connect(self.refresh)
                self._add_selection_menu(widget)
                widgets.append(widget)
        except Exception:
            self.controller.dispose()
            raise
        self.row_widgets = tuple(widgets)
        self.table_view.set_rows(
            [
                TableRow(
                    key=(widget.row.attribute.path, widget.row.attribute.kind),
                    widget=widget,
                    name_label=widget.name_label,
                    value_field=(
                        widget.editor.spin_box
                        if isinstance(
                            widget.editor,
                            (FloatSliderSpinBox, FloatValueStepSpinBox),
                        )
                        else None
                    ),
                )
                for widget in widgets
            ],
            preserve_selection=self._table_node_ids
            == self.controller.node_ids,
        )
        self._table_node_ids = self.controller.node_ids
        # 行の配置が確定してから、残っている属性のスクロール位置を復元する
        self._scroll_timer.start(0)
        self.empty_label.setVisible(not widgets)
        self.empty_label.setText(
            "フィルターに一致する bool・float 系・enum 属性がありません。"
            if names
            else "Maya ノードを選択すると、入力可能な種類の属性を表示します。"
        )

    def _apply_step_value(
        self, source_key: tuple[str, str], value: float
    ) -> None:
        """同じ表示stepを、選択中でStep欄を持つ属性へ反映して保持する。"""
        if self._changing_steps:
            self._steps[source_key] = value
            return

        target_keys = set(self._action_keys(source_key))
        excluded: list[str] = []
        self._changing_steps = True
        try:
            # 各行固有の増減方式は維持し、表示stepの数値だけを同期する
            for widget in self.row_widgets:
                key = (widget.row.attribute.path, widget.row.attribute.kind)
                if key not in target_keys:
                    continue
                if not isinstance(
                    widget, AttributeRowWidget
                ) or not isinstance(widget.editor, FloatValueStepSpinBox):
                    excluded.append(
                        f"{widget.row.attribute.nice_name}: Step欄なし"
                    )
                    continue
                widget.editor.setSingleStep(value)
                self._steps[key] = value
        finally:
            self._changing_steps = False

        self._show_operation_report(
            "対象外: " + " / ".join(excluded) if excluded else ""
        )

    def dispose(self) -> None:
        """画面の入力と監視を即時に終了する。"""
        self.state_sweep.dispose()
        self.lock_sweep.dispose()
        self._scroll_timer.stop()
        self.context_menu.close()
        for widget in self.row_widgets:
            widget.context_menu.close()
            if isinstance(widget.editor, EnumComboBox):
                widget.editor.hidePopup()
        self.controller.dispose()
        self.table_view.dispose()
