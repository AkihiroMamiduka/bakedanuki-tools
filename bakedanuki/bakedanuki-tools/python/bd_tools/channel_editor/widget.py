# coding: utf-8
"""Channel Editorの値入力画面。"""

from __future__ import annotations

from bd_util.maya.ui import MayaBoolPlugsBinding, get_channel_box_precision
from bd_util.ui import BoolComboBox, FloatSliderSpinBox, FloatSpinBox, qt

from .controller import ChannelEditorController, ChannelRow

__all__ = ["AttributeRowWidget", "ChannelEditorWidget"]


class AttributeRowWidget(qt.QWidget):
    """属性名、既存MVVM View、適用対象と混在状態を1行で表示する。"""

    def __init__(
        self, row: ChannelRow, selection_count: int, parent: qt.QWidget
    ) -> None:
        """初期値を書き込まず、Bindingと表示部品を接続する。"""
        super().__init__(parent)
        self.row = row
        self.selection_count = selection_count
        self.setObjectName(f"channel_{row.attribute.path}")
        self.name_label = qt.QLabel(row.attribute.nice_name, self)
        self.name_label.setMinimumWidth(130)
        self.name_label.setToolTip(row.attribute.path)
        self.status_label = qt.QLabel(self)
        self.status_label.setMinimumWidth(90)
        self.align_button = qt.QPushButton("揃える", self)
        self.align_button.setAutoDefault(False)
        self.align_button.setDefault(False)
        self.align_button.setToolTip("編集可能な対象を基準ノードの値に揃える")
        self.align_button.setMaximumWidth(58)
        self.align_button.clicked.connect(self._align_values)
        self.editor = self._create_editor()

        # 値の混在と編集可能数はBindingの読み取り通知だけで更新する
        row.binding.state_changed.connect(self._update_state)
        layout = qt.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(self.name_label)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.align_button)
        self._update_state()

    def _create_editor(
        self,
    ) -> BoolComboBox | FloatSliderSpinBox | FloatSpinBox:
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
        spin_box = FloatSpinBox(binding, self, decimals=decimals)
        spin_box.setMinimumWidth(110)
        return spin_box

    def _update_state(self) -> None:
        """混在表示と除外理由を更新し、明示的な統一操作の可否を示す。"""
        binding = self.row.binding
        editable = binding.view_model.set_value_command.can_execute
        count = binding.writable_count if editable else 0
        status = f"{count}/{self.selection_count} 件"
        if binding.is_mixed:
            status = f"混在 · {status}"
        self.status_label.setText(status)
        reasons = list(self.row.excluded)
        for target in binding.target_states:
            if target.reason:
                reasons.append(f"{target.name}: {target.reason}")
        tooltip = (
            "\n".join(reasons) if reasons else "すべての対象を編集できます"
        )
        self.status_label.setToolTip(tooltip)
        self.editor.setToolTip(tooltip if reasons else self.row.attribute.path)
        self.align_button.setEnabled(editable and binding.is_mixed)

    def _align_values(self) -> None:
        """ボタンを押した場合だけ、対象を基準ノードの値へ揃える。"""
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
        self.row_widgets: tuple[AttributeRowWidget, ...] = ()
        self.header_label = qt.QLabel("ノードを選択してください", self)
        self.header_label.setTextInteractionFlags(
            qt.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.refresh_button = qt.QPushButton("更新", self)
        self.refresh_button.setAutoDefault(False)
        self.refresh_button.setDefault(False)
        self.refresh_button.setToolTip("属性の構成と入力範囲を読み直す")
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
        layout.setContentsMargins(10, 10, 10, 10)
        header = qt.QHBoxLayout()
        header.addWidget(self.header_label, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.message_label)

        # 選択・表示更新と、ユーザーによる値変更の経路を分離する
        self.controller = ChannelEditorController(self)
        self.controller.rows_changed.connect(self._rebuild_rows)
        self.controller.error_occurred.connect(self._show_error)
        self.refresh_button.clicked.connect(self.refresh)
        self.controller.refresh()

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
            self._rows_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self.row_widgets = ()
        names = self.controller.node_names
        if names:
            self.header_label.setText(
                f"基準: {names[0].rsplit('|', 1)[-1]}   ·   {len(names)} ノード"
            )
            self.header_label.setToolTip("\n".join(names))
        else:
            self.header_label.setText("ノードを選択してください")
            self.header_label.setToolTip("")
        widgets: list[AttributeRowWidget] = []
        try:
            for row in self.controller.rows:
                widget = AttributeRowWidget(row, len(names), self._contents)
                widgets.append(widget)
                self._rows_layout.insertWidget(len(widgets) - 1, widget)
        except Exception:
            self.controller.dispose()
            raise
        self.row_widgets = tuple(widgets)
        self.empty_label.setVisible(not widgets)
        self.empty_label.setText(
            "表示対象の bool・float 系属性がありません。"
            if names
            else "Maya ノードを選択すると、入力可能な種類の属性を表示します。"
        )

    def dispose(self) -> None:
        """画面の入力と監視を即時に終了する。"""
        self.controller.dispose()
