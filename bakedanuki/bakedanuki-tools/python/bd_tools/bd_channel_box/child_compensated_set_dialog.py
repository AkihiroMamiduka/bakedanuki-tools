# coding: utf-8
"""直接の子を補償しながら基準ノードのXYZを設定するダイアログ。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Literal, cast

from maya import cmds
from maya.api import OpenMaya as om

from bd_util import Nodes
from bd_util.ui import MouseFocusSelectAllDoubleSpinBox, qt

from .anchored_dialog import AnchoredDialog
from .controller import RoundTransformKind

__all__ = [
    "ChildCompensatedSetDialog",
    "TRANSLATE_INITIAL_WIDTH",
    "TRANSLATE_INITIAL_HEIGHT",
    "ROTATION_INITIAL_WIDTH",
    "ROTATION_INITIAL_HEIGHT",
]

TransformSpace = Literal["local", "world"]
JointChildCompensationAttr = Literal["rotate", "jointOrient"]
_Values = tuple[float, float, float]

# 移動・回転ダイアログの初期表示サイズ（幅・高さ、Qt論理px）
TRANSLATE_INITIAL_WIDTH = 192
TRANSLATE_INITIAL_HEIGHT = 222
ROTATION_INITIAL_WIDTH = 240
ROTATION_INITIAL_HEIGHT = 312


class ChildCompensatedSetDialog(AnchoredDialog):
    """基準ノードの移動または回転目標値と子の補償方法を編集する。"""

    def __init__(
        self,
        initial_target: RoundTransformKind,
        representative_name: str,
        representative_type: Literal["transform", "joint"],
        values_canonical: Mapping[RoundTransformKind, _Values],
        parent: qt.QWidget | None = None,
    ) -> None:
        """属性の未丸め値を保持し、Maya表示単位でXYZを入力する。"""
        super().__init__(parent)
        self._initial_size_timer = qt.QTimer(self)
        self._initial_size_timer.setSingleShot(True)
        self._initial_size_timer.timeout.connect(self._apply_initial_size)
        if initial_target not in values_canonical:
            raise ValueError("右クリックした属性が見つかりません")
        if representative_type not in ("transform", "joint"):
            raise ValueError("TransformまたはJointを選択してください")
        if initial_target == "jointOrient" and representative_type != "joint":
            raise ValueError("jointOrientはJointのみ設定できます")
        self._is_translate = initial_target == "translate"
        self._ui_unit = (
            om.MDistance.uiUnit() if self._is_translate else om.MAngle.uiUnit()
        )
        self._unit_label = cast(
            str,
            (
                cmds.currentUnit(query=True, linear=True)
                if self._is_translate
                else cmds.currentUnit(query=True, angle=True)
            ),
        )
        self._draft_local = {
            target: list(values) for target, values in values_canonical.items()
        }
        self._draft_world: list[float] | None = None
        self._active_target: RoundTransformKind = initial_target
        self._active_space: TransformSpace = "local"
        self._rendering_values = False
        nodes = Nodes()
        self._operator = (
            nodes.existing.joint(representative_name)
            if representative_type == "joint"
            else nodes.existing.transform(representative_name)
        )
        self.setWindowTitle(
            "移動をセット（子を維持）"
            if self._is_translate
            else "回転をセット（子を維持）"
        )

        self.target_label = qt.QLabel(
            f"設定対象（基準ノードのみ）：{representative_name}", self
        )
        self.target_label.setWordWrap(True)
        self.child_label = qt.QLabel(
            (
                "子のworld座標を保持するため、子のtranslateも変更します"
                if self._is_translate
                else "子のworld姿勢を保持するため、子の回転属性を補償します"
            ),
            self,
        )
        self.child_label.setWordWrap(True)

        # 回転系だけに設定先と子の補償方法の入力欄を作る
        self.target_combo: qt.QComboBox | None = None
        self.preservation_combo: qt.QComboBox | None = None
        self.joint_child_combo: qt.QComboBox | None = None
        if not self._is_translate:
            self.target_combo = qt.QComboBox(self)
            for target in values_canonical:
                if target != "translate":
                    self.target_combo.addItem(target, target)
            self.target_combo.setCurrentIndex(
                self.target_combo.findData(initial_target)
            )
            self.target_combo.currentIndexChanged.connect(self._target_changed)
            self.preservation_combo = qt.QComboBox(self)
            self.preservation_combo.addItem("座標と姿勢", True)
            self.preservation_combo.addItem("姿勢", False)
            self.joint_child_combo = qt.QComboBox(self)
            self.joint_child_combo.addItem("rotate", "rotate")
            self.joint_child_combo.addItem("jointOrient", "jointOrient")
            self.joint_child_combo.setToolTip(
                "子Jointの姿勢補償先。Transform子はrotateで補償します"
            )
        self.space_combo = qt.QComboBox(self)
        self.space_combo.addItem("Local", "local")
        self.space_combo.addItem("World", "world")
        self.space_combo.setToolTip(
            "Local: 属性値\nWorld: "
            + (
                "DAG原点のworld位置"
                if self._is_translate
                else "最終world姿勢（XYZ順）"
            )
        )
        self.space_combo.currentIndexChanged.connect(self._space_changed)

        # 未編集成分の実値はSpinBoxの表示桁数と分けて保持する
        self.value_spins: tuple[qt.QDoubleSpinBox, ...] = tuple(
            self._create_value_spin(axis) for axis in range(3)
        )
        values_group = qt.QWidget(self)
        values_layout = qt.QGridLayout(values_group)
        values_layout.setContentsMargins(0, 0, 0, 0)
        for row, (axis, spin) in enumerate(zip("XYZ", self.value_spins)):
            values_layout.addWidget(qt.QLabel(axis, values_group), row, 0)
            values_layout.addWidget(spin, row, 1)
        values_layout.setColumnStretch(1, 1)
        self.error_label = qt.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.buttons = qt.QDialogButtonBox(
            qt.QDialogButtonBox.StandardButton.Ok
            | qt.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.target_label)
        layout.addWidget(self.child_label)
        separator = qt.QFrame(self)
        separator.setFrameShape(qt.QFrame.Shape.HLine)
        layout.addWidget(separator)
        selection_layout = qt.QGridLayout()
        selector_rows: tuple[tuple[str, qt.QComboBox], ...]
        if self._is_translate:
            selector_rows = (("入力空間", self.space_combo),)
        else:
            assert self.target_combo is not None
            assert self.preservation_combo is not None
            assert self.joint_child_combo is not None
            selector_rows = (
                ("値をセットする属性", self.target_combo),
                ("入力空間", self.space_combo),
                ("子の維持範囲", self.preservation_combo),
                ("子Jointの補償属性", self.joint_child_combo),
            )
        selector_labels: list[qt.QLabel] = []
        for row, (label_text, combo) in enumerate(selector_rows):
            label = qt.QLabel(label_text, self)
            selection_layout.addWidget(label, row, 0)
            selection_layout.addWidget(combo, row, 1)
            selector_labels.append(label)
        # ラベル列を最長の項目に揃えて、入力欄の開始位置を統一する
        label_width = max(
            label.sizeHint().width() for label in selector_labels
        )
        for label in selector_labels:
            label.setMinimumWidth(label_width)
        self.selector_labels = tuple(selector_labels)
        selection_layout.setColumnStretch(1, 1)
        layout.addLayout(selection_layout)
        layout.addWidget(values_group)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)
        self._render_values()

    def set_anchor_position(self, position: qt.QPoint) -> None:
        """表示前に初期サイズを指定し、クリック位置を中心に配置する。"""
        super().set_anchor_position(position)
        self._apply_initial_size()

    def showEvent(self, arg__1: qt.QtGui.QShowEvent) -> None:
        """表示後にウィンドウ枠が確定してから初期サイズを適用する。"""
        super().showEvent(arg__1)
        self._initial_size_timer.start(20)

    def _apply_initial_size(self) -> None:
        """移動・回転それぞれの指定寸法とクリック位置を適用する。"""
        if self._is_translate:
            self.resize(TRANSLATE_INITIAL_WIDTH, TRANSLATE_INITIAL_HEIGHT)
        else:
            self.resize(ROTATION_INITIAL_WIDTH, ROTATION_INITIAL_HEIGHT)
        self._position_near_anchor()

    def _create_value_spin(self, axis: int) -> qt.QDoubleSpinBox:
        """初回クリックで文字を全選択する数値入力欄を作る。"""
        spin = MouseFocusSelectAllDoubleSpinBox(
            self, select_all_on_mouse_focus=True
        )
        spin.setDecimals(15)
        spin.setRange(-1.0e100, 1.0e100)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(partial(self._value_changed, axis))
        return spin

    def _target_changed(self, index: int) -> None:
        """設定先を切り替え、localでは属性ごとの編集中の値を表示する。"""
        del index
        for spin in self.value_spins:
            spin.interpretText()
        self._active_target = self.target()
        self._render_values()

    def _space_changed(self, index: int) -> None:
        """基準ノードの編集中の目標値を新しい空間へ換算する。"""
        del index
        for spin in self.value_spins:
            spin.interpretText()
        next_space = cast(TransformSpace, self.space_combo.currentData())
        if next_space == self._active_space:
            return
        try:
            converted = self._operator.convert_transform_space_values(
                self._active_target,
                self.values_canonical(),
                from_space=self._active_space,
                to_space=next_space,
            )
        except (ValueError, TypeError, RuntimeError) as error:
            self.space_combo.blockSignals(True)
            try:
                self.space_combo.setCurrentIndex(
                    self.space_combo.findData(self._active_space)
                )
            finally:
                self.space_combo.blockSignals(False)
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.error_label.hide()
        if next_space == "world":
            self._draft_world = list(converted)
        else:
            self._draft_local[self._active_target] = list(converted)
        self._active_space = next_space
        self._render_values()

    def _current_draft(self) -> list[float]:
        """現在の属性群・空間に対応する未丸め値を返す。"""
        if self._active_space == "world":
            assert self._draft_world is not None
            return self._draft_world
        return self._draft_local[self._active_target]

    def _render_values(self) -> None:
        """正本を固定した表示単位へ変換し、XYZ欄へ描画する。"""
        description = (
            "属性値"
            if self._active_space == "local"
            else (
                "DAG原点のworld位置"
                if self._is_translate
                else "最終world姿勢・XYZ順"
            )
        )
        for spin in self.value_spins:
            spin.setToolTip(f"{description}（{self._unit_label}）")
        self._rendering_values = True
        try:
            for spin, value in zip(self.value_spins, self._current_draft()):
                if self._is_translate:
                    display = om.MDistance(
                        value, om.MDistance.kCentimeters
                    ).asUnits(self._ui_unit)
                else:
                    display = om.MAngle(value, om.MAngle.kDegrees).asUnits(
                        self._ui_unit
                    )
                spin.setValue(display)
        finally:
            self._rendering_values = False

    def _value_changed(self, axis: int, value: float) -> None:
        """利用者が編集した成分だけをcmまたはdegreeの正本へ反映する。"""
        if self._rendering_values:
            return
        canonical = (
            om.MDistance(value, self._ui_unit).asCentimeters()
            if self._is_translate
            else om.MAngle(value, self._ui_unit).asDegrees()
        )
        self._current_draft()[axis] = canonical

    def target(self) -> RoundTransformKind:
        """現在の設定先属性群を返す。"""
        if self._is_translate:
            return "translate"
        assert self.target_combo is not None
        return cast(RoundTransformKind, self.target_combo.currentData())

    def space(self) -> TransformSpace:
        """現在の入力空間を返す。"""
        return self._active_space

    def values_canonical(self) -> _Values:
        """未編集成分の精度を保ったXYZ目標値を返す。"""
        for spin in self.value_spins:
            spin.interpretText()
        values = self._current_draft()
        return values[0], values[1], values[2]

    def compensate_child_translate(self) -> bool:
        """回転時に子のworld座標も保持するか返す。"""
        if self._is_translate:
            return True
        assert self.preservation_combo is not None
        return cast(bool, self.preservation_combo.currentData())

    def joint_child_compensation_attr(self) -> JointChildCompensationAttr:
        """子Jointの姿勢を補償する属性群を返す。"""
        if self._is_translate:
            return "rotate"
        assert self.joint_child_combo is not None
        return cast(
            JointChildCompensationAttr, self.joint_child_combo.currentData()
        )
