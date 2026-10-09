# coding: utf-8
"""姿勢を維持して回転属性のXYZを設定する入力ダイアログ。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from typing import cast

from maya import cmds
from maya.api import OpenMaya as om

from bd_util.ui import MouseFocusSelectAllDoubleSpinBox, qt

from .controller import RotationDestination

__all__ = ["RotationSetDialog"]


def _centered_position_within_screen(
    anchor: qt.QPoint, frame_size: qt.QSize, available: qt.QRect
) -> qt.QPoint:
    """クリック位置を中心にし、画面の作業領域へ収まる左上座標を返す。"""
    maximum_x = max(
        available.left(), available.right() - frame_size.width() + 1
    )
    maximum_y = max(
        available.top(), available.bottom() - frame_size.height() + 1
    )
    return qt.QPoint(
        min(
            max(anchor.x() - frame_size.width() // 2, available.left()),
            maximum_x,
        ),
        min(
            max(anchor.y() - frame_size.height() // 2, available.top()),
            maximum_y,
        ),
    )


class RotationSetDialog(qt.QDialog):
    """設定先・補償先・共通のXYZ目標値を編集する。"""

    def __init__(
        self,
        initial_target: RotationDestination,
        representative_name: str,
        representative_type: str,
        values_degrees: Mapping[
            RotationDestination, tuple[float, float, float]
        ],
        selected_node_types: Sequence[str],
        parent: qt.QWidget | None = None,
    ) -> None:
        """代表ノードの未丸め値を保持し、Maya表示角度単位で入力する。"""
        super().__init__(parent)
        if representative_type not in ("transform", "joint"):
            raise ValueError("TransformまたはJointを選択してください")
        if initial_target not in values_degrees:
            raise ValueError("右クリックした回転属性が見つかりません")
        self.setWindowTitle("回転をセット（姿勢を維持）")
        self._representative_name = representative_name
        self._is_joint = representative_type == "joint"
        self._selected_node_types = tuple(selected_node_types)
        self._ui_angle_unit = om.MAngle.uiUnit()
        self._draft_degrees = {
            target: list(values) for target, values in values_degrees.items()
        }
        self._compensation_by_target: dict[
            RotationDestination, RotationDestination
        ] = {}
        self._active_target = initial_target
        self._rendering_values = False
        self._anchor_position: qt.QPoint | None = None

        # 設定先と補償先の候補をノード種別に合わせる
        self.target_combo = qt.QComboBox(self)
        for target in values_degrees:
            self.target_combo.addItem(target, target)
        self.compensation_combo = qt.QComboBox(self)
        self.target_combo.setCurrentIndex(
            self.target_combo.findData(initial_target)
        )
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.compensation_combo.currentIndexChanged.connect(
            self._compensation_changed
        )

        # 入力表示の丸めが未編集成分の正本へ伝わらないよう、実値は別に保持する
        self.value_spins: tuple[qt.QDoubleSpinBox, ...] = tuple(
            self._create_value_spin(axis) for axis in range(3)
        )
        unit_label = cast(str, cmds.currentUnit(query=True, angle=True))
        values_row = qt.QWidget(self)
        values_layout = qt.QHBoxLayout(values_row)
        values_layout.setContentsMargins(0, 0, 0, 0)
        for axis, spin in zip("XYZ", self.value_spins):
            values_layout.addWidget(qt.QLabel(axis, values_row))
            values_layout.addWidget(spin)

        self.target_count_label = qt.QLabel(self)
        self.target_count_label.setWordWrap(True)
        # 設定先と補償先を同じ高さの二列に配置する
        attribute_layout = qt.QGridLayout()
        attribute_layout.addWidget(qt.QLabel("値をセットする属性", self), 0, 0)
        attribute_layout.addWidget(qt.QLabel("値を吸収する属性", self), 0, 1)
        attribute_layout.addWidget(self.target_combo, 1, 0)
        attribute_layout.addWidget(self.compensation_combo, 1, 1)
        attribute_layout.setColumnStretch(0, 1)
        attribute_layout.setColumnStretch(1, 1)
        form = qt.QFormLayout()
        form.addRow(f"XYZ（{unit_label}）", values_row)
        self.buttons = qt.QDialogButtonBox(
            qt.QDialogButtonBox.StandardButton.Ok
            | qt.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = qt.QVBoxLayout(self)
        layout.addLayout(attribute_layout)
        layout.addLayout(form)
        layout.addWidget(self.target_count_label)
        layout.addWidget(self.buttons)
        self._populate_compensation()
        self._render_values()

    def _create_value_spin(self, axis: int) -> qt.QDoubleSpinBox:
        """単位を固定した入力欄を作り、編集した成分だけを記録する。"""
        spin = MouseFocusSelectAllDoubleSpinBox(
            self, select_all_on_mouse_focus=True
        )
        spin.setDecimals(15)
        spin.setRange(-1.0e100, 1.0e100)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(partial(self._value_changed, axis))
        return spin

    def set_anchor_position(self, position: qt.QPoint) -> None:
        """ダイアログの中心にしたいメニュークリック位置を保存する。"""
        self._anchor_position = qt.QPoint(position.x(), position.y())
        self.adjustSize()
        self._position_near_anchor()

    def showEvent(self, arg__1: qt.QtGui.QShowEvent) -> None:
        """表示時に確定したウィンドウ枠寸法で配置を補正する。"""
        super().showEvent(arg__1)
        self._position_near_anchor()

    def _position_near_anchor(self) -> None:
        """クリック位置のモニターを選び、枠ごと画面内へ移動する。"""
        anchor = self._anchor_position
        if anchor is None:
            return
        application = qt.QtGui.QGuiApplication.instance()
        if not isinstance(application, qt.QtGui.QGuiApplication):
            return
        screen = cast(
            qt.QtGui.QScreen | None,
            qt.QtGui.QGuiApplication.screenAt(anchor),
        )
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, self.screen())
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, application.primaryScreen())
        if screen is None:
            return
        available = screen.availableGeometry()
        if available.isEmpty():
            return
        frame_size = self.frameGeometry().size()
        self.move(
            _centered_position_within_screen(anchor, frame_size, available)
        )

    def _compensation_options(
        self, target: RotationDestination
    ) -> tuple[RotationDestination, ...]:
        """現在の設定先で使用できる補償先を既定値優先で返す。"""
        if target == "rotate":
            return (
                ("jointOrient", "rotateAxis")
                if self._is_joint
                else ("rotateAxis",)
            )
        if target == "rotateAxis":
            return ("rotate", "jointOrient") if self._is_joint else ("rotate",)
        return ("rotate", "rotateAxis")

    def _populate_compensation(self) -> None:
        """設定先の変更後に補償先と適用ノード数を更新する。"""
        target = self.target()
        options = self._compensation_options(target)
        selected = self._compensation_by_target.get(target, options[0])
        self.compensation_combo.blockSignals(True)
        try:
            self.compensation_combo.clear()
            for option in options:
                self.compensation_combo.addItem(option, option)
            self.compensation_combo.setCurrentIndex(
                self.compensation_combo.findData(selected)
            )
        finally:
            self.compensation_combo.blockSignals(False)
        self._compensation_by_target[target] = self.compensate_with()
        self._update_target_count()

    def _target_changed(self, index: int) -> None:
        """設定先の切替時に編集中の値を保持して表示を更新する。"""
        del index
        for spin in self.value_spins:
            spin.interpretText()
        self._active_target = self.target()
        self._populate_compensation()
        self._render_values()

    def _compensation_changed(self, index: int) -> None:
        """選択した補償先を設定先ごとに記憶する。"""
        del index
        self._compensation_by_target[self.target()] = self.compensate_with()
        self._update_target_count()

    def _render_values(self) -> None:
        """現在の設定先のXYZ値を固定した表示単位へ変換して描画する。"""
        self._rendering_values = True
        try:
            for spin, degrees in zip(
                self.value_spins, self._draft_degrees[self._active_target]
            ):
                spin.setValue(
                    om.MAngle(degrees, om.MAngle.kDegrees).asUnits(
                        self._ui_angle_unit
                    )
                )
        finally:
            self._rendering_values = False

    def _value_changed(self, axis: int, value: float) -> None:
        """利用者が変更した成分だけをdegree実値へ変換して保存する。"""
        if self._rendering_values:
            return
        self._draft_degrees[self._active_target][axis] = om.MAngle(
            value, self._ui_angle_unit
        ).asDegrees()

    def _update_target_count(self) -> None:
        """補償先を扱える選択ノード数をダイアログに示す。"""
        requires_joint = (
            self.target() == "jointOrient"
            or self.compensate_with() == "jointOrient"
        )
        applicable = sum(
            node_type == "joint"
            or (node_type == "transform" and not requires_joint)
            for node_type in self._selected_node_types
        )
        excluded = len(self._selected_node_types) - applicable
        self.target_count_label.setText(
            f"基準: {self._representative_name}／同じXYZを設定："
            f"対象 {applicable} ノード"
            + (f"、対象外 {excluded} ノード" if excluded else "")
        )
        ok_button = self.buttons.button(qt.QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(applicable > 0)

    def target(self) -> RotationDestination:
        """現在選択した設定先を返す。"""
        return cast(RotationDestination, self.target_combo.currentData())

    def compensate_with(self) -> RotationDestination:
        """現在選択した補償先を返す。"""
        return cast(RotationDestination, self.compensation_combo.currentData())

    def values_degrees(self) -> tuple[float, float, float]:
        """未編集成分の精度を保ったXYZ目標値をdegreeで返す。"""
        for spin in self.value_spins:
            spin.interpretText()
        values = self._draft_degrees[self._active_target]
        return values[0], values[1], values[2]
