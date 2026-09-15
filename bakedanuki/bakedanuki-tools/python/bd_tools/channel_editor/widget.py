# coding: utf-8
"""Channel Editorの値入力画面。"""

from __future__ import annotations

from functools import partial
from typing import Protocol, cast

from bd_util.maya.ui import MayaBoolPlugsBinding, get_channel_box_precision
from bd_util.ui import (
    BoolComboBox,
    FloatSliderSpinBox,
    FloatStepMode,
    FloatValueStepSpinBox,
    qt,
)

from .controller import ChannelEditorController, ChannelRow

__all__ = ["AttributeRowWidget", "ChannelEditorWidget"]


class _MenuActions(Protocol):
    """Qt同梱stubの版差を、使用するQActionの追加操作だけで閉じる。"""

    def addAction(self, action: qt.QAction, /) -> None:
        """作成済みのQActionをメニューへ追加する。"""
        ...


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
        self.name_label = qt.QLabel(row.attribute.nice_name, self)
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
        if isinstance(self.editor, FloatValueStepSpinBox):
            self.editor.settingsChanged.connect(self._notify_step_changed)

        # 値の混在と編集可能数はBindingの読み取り通知だけで更新する
        row.binding.state_changed.connect(self._update_state)
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.name_label)
        layout.addWidget(self.editor, 1)
        self._update_state()

    def contextMenuEvent(self, event: qt.QtGui.QContextMenuEvent) -> None:
        """属性名や行の余白から操作を開き、値欄の標準メニューを維持する。"""
        self.context_menu.popup(event.globalPos())
        event.accept()

    def _create_editor(
        self,
        single_step: float | None,
    ) -> BoolComboBox | FloatSliderSpinBox | FloatValueStepSpinBox:
        """属性の種類と両側のhard limitから入力Viewを選ぶ。"""
        binding = self.row.binding
        if isinstance(binding, MayaBoolPlugsBinding):
            return BoolComboBox(
                binding, false_text="off", true_text="on", parent=self
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
            )
            editor.slider.setMinimumWidth(110)
            editor.spin_box.setMinimumWidth(110)
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
        )
        value_editor.spin_box.setMinimumWidth(110)
        value_editor.step_spin_box.setFixedWidth(72)
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
        details = [self.row.attribute.path]
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
        details.append("属性名を右クリック: この値に揃える / 表示を更新")
        tooltip = "\n".join(details)
        self.name_label.setToolTip(tooltip)
        self.editor.setToolTip(tooltip)
        self.align_action.setEnabled(editable and binding.is_mixed)

    def _align_values(self) -> None:
        """メニューから明示した場合だけ、対象を基準ノードの値へ揃える。"""
        try:
            self.row.binding.apply_representative_value()
        except (ValueError, RuntimeError):
            # 拒否理由はBindingのedit_failedからWindowへ通知済み
            return


class ChannelEditorWidget(qt.QWidget):
    """基準ノードの情報と、スクロール可能な属性入力欄を表示する。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """画面を作成してから選択監視を開始する。"""
        super().__init__(parent)
        self._steps: dict[tuple[str, str], float] = {}
        self.row_widgets: tuple[AttributeRowWidget, ...] = ()
        self.header_label = qt.QLabel("ノードを選択してください", self)
        self.header_label.setTextInteractionFlags(
            qt.Qt.TextInteractionFlag.TextSelectableByMouse
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
        layout.addWidget(self.header_label)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.message_label)

        # 選択・表示更新と、ユーザーによる値変更の経路を分離する
        self.controller = ChannelEditorController(self)
        self.controller.rows_changed.connect(self._rebuild_rows)
        self.controller.error_occurred.connect(self._show_error)
        self.controller.refresh()

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
        widgets: list[AttributeRowWidget] = []
        try:
            for row in self.controller.rows:
                key = (row.attribute.path, row.attribute.kind)
                widget = AttributeRowWidget(
                    row,
                    len(names),
                    self._contents,
                    single_step=self._steps.get(key),
                )
                widget.step_changed.connect(partial(self._remember_step, key))
                widget.refresh_requested.connect(self.refresh)
                widgets.append(widget)
                self._rows_layout.insertWidget(len(widgets) - 1, widget)
        except Exception:
            self.controller.dispose()
            raise
        self.row_widgets = tuple(widgets)
        # 混在の印を含む共通幅を確保し、全行の入力欄の左端を揃える
        name_width = max(
            [92]
            + [
                widget.name_label.fontMetrics().horizontalAdvance(
                    "• " + widget.row.attribute.nice_name
                )
                + 2
                for widget in widgets
            ]
        )
        for widget in widgets:
            widget.name_label.setFixedWidth(name_width)
        self.empty_label.setVisible(not widgets)
        self.empty_label.setText(
            "表示対象の bool・float 系属性がありません。"
            if names
            else "Maya ノードを選択すると、入力可能な種類の属性を表示します。"
        )

    def _remember_step(self, key: tuple[str, str], value: float) -> None:
        """ノードに依存しない属性path・型ごとのstepをWindow内に保持する。"""
        self._steps[key] = value

    def dispose(self) -> None:
        """画面の入力と監視を即時に終了する。"""
        self.context_menu.close()
        for widget in self.row_widgets:
            widget.context_menu.close()
        self.controller.dispose()
