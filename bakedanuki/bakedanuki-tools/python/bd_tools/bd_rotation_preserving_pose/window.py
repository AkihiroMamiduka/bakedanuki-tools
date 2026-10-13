# coding: utf-8
"""選択ノードの姿勢を維持して回転属性を即時編集するWindow。"""

from __future__ import annotations

from typing import Literal, cast

from maya import cmds
from maya.api import OpenMaya as om

from bd_util import Nodes
from bd_util.maya.node import node_display_name
from bd_util.maya.mpx_cmd import set_rotation_preserving_pose
from bd_util.ui import qt

from .._shared.live_set import LiveSetWindowBase, LiveXyzEditor
from .types import RotationTarget

__all__ = ["RotationSetWindow", "INITIAL_WIDTH", "INITIAL_HEIGHT"]

_Values = tuple[float, float, float]

# Step欄と属性選択を含む初期サイズ（Qt論理px）
INITIAL_WIDTH = 306
INITIAL_HEIGHT = 174


class RotationSetWindow(LiveSetWindowBase):
    """回転属性の1軸を設定し、別属性へ姿勢差分を吸収させる。"""

    def __init__(
        self, parent: qt.QWidget | None = None, *, as_page: bool = False
    ) -> None:
        """設定先・補償先とXYZの独立したStep欄を構築する。"""
        super().__init__(parent, as_page=as_page)
        self._node_name: str | None = None
        self._node_type: Literal["transform", "joint"] | None = None
        self._requested_target: RotationTarget = "rotate"
        self._compensation_by_target: dict[
            tuple[Literal["transform", "joint"], RotationTarget],
            RotationTarget,
        ] = {}
        self.setWindowTitle("回転をセット（姿勢を維持）")
        self.target_label = qt.QLabel("設定対象（基準ノードのみ）：なし", self)
        self.target_label.setWordWrap(True)
        self.target_attribute_label = qt.QLabel("値をセットする属性", self)
        self.compensation_attribute_label = qt.QLabel("値を吸収する属性", self)
        self.target_combo = qt.QComboBox(self)
        self.compensation_combo = qt.QComboBox(self)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.compensation_combo.currentIndexChanged.connect(
            self._compensation_changed
        )
        self.xyz_editor = LiveXyzEditor(self, angle=True)
        self.xyz_editor.set_value_handler(self._set_axis_value)
        self.xyz_editor.set_step_handler(self._step_axis_value)
        self.error_label = qt.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        # 設定先と補償先を各行に置き、ラベル幅を揃える
        attributes = qt.QGridLayout()
        label_combos = (
            (self.target_attribute_label, self.target_combo),
            (self.compensation_attribute_label, self.compensation_combo),
        )
        for row, (label, combo) in enumerate(label_combos):
            attributes.addWidget(label, row, 0)
            attributes.addWidget(combo, row, 1)
        label_width = max(
            label.sizeHint().width() for label, _combo in label_combos
        )
        for label, _combo in label_combos:
            label.setMinimumWidth(label_width)
        attributes.setColumnStretch(1, 1)
        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.target_label)
        self.target_separator = qt.QFrame(self)
        self.target_separator.setFrameShape(qt.QFrame.Shape.HLine)
        layout.addWidget(self.target_separator)
        layout.addLayout(attributes)
        layout.addWidget(self.xyz_editor)
        layout.addWidget(self.error_label)
        self.resize(INITIAL_WIDTH, INITIAL_HEIGHT)

        self.selection_invalidated.connect(self._invalidate_selection)
        self.units_invalidated.connect(self.xyz_editor.discard_pending_input)
        self.refresh_requested.connect(self.refresh)
        self.refresh()

    def set_initial_target(self, target: RotationTarget) -> None:
        """指定された回転属性を今回の設定先にする。"""
        if target not in ("rotate", "rotateAxis", "jointOrient"):
            raise ValueError("回転属性を指定してください")
        self._requested_target = target
        self.xyz_editor.discard_pending_input()
        self.refresh()

    def target(self) -> RotationTarget:
        """現在の設定先属性群を返す。"""
        return self._requested_target

    def compensate_with(self) -> RotationTarget:
        """現在の姿勢を吸収する属性群を返す。"""
        return cast(RotationTarget, self.compensation_combo.currentData())

    def _compensation_options(
        self, target: RotationTarget
    ) -> tuple[RotationTarget, ...]:
        """JointではrotateAxis以外を先頭とする候補順を返す。"""
        joint = self._node_type == "joint"
        if target == "rotate":
            return ("jointOrient", "rotateAxis") if joint else ("rotateAxis",)
        if target == "rotateAxis":
            return ("rotate", "jointOrient") if joint else ("rotate",)
        return ("rotate", "rotateAxis")

    def _sync_options(self, node_type: Literal["transform", "joint"]) -> None:
        """選択ノードで有効な設定先と補償先だけを表示する。"""
        available: tuple[RotationTarget, ...] = (
            ("rotate", "rotateAxis", "jointOrient")
            if node_type == "joint"
            else ("rotate", "rotateAxis")
        )
        desired: RotationTarget = (
            self._requested_target
            if self._requested_target in available
            else "rotate"
        )
        target_items = tuple(
            cast(RotationTarget, self.target_combo.itemData(index))
            for index in range(self.target_combo.count())
        )
        blocker = qt.QtCore.QSignalBlocker(self.target_combo)
        try:
            if target_items != available:
                self.target_combo.clear()
                for target in available:
                    self.target_combo.addItem(target, target)
            self.target_combo.setCurrentIndex(
                self.target_combo.findData(desired)
            )
        finally:
            del blocker
        self._requested_target = desired

        options = self._compensation_options(desired)
        key = (node_type, desired)
        selected = self._compensation_by_target.get(key, options[0])
        if selected not in options:
            selected = options[0]
        compensation_items = tuple(
            cast(
                RotationTarget,
                self.compensation_combo.itemData(index),
            )
            for index in range(self.compensation_combo.count())
        )
        blocker = qt.QtCore.QSignalBlocker(self.compensation_combo)
        try:
            if compensation_items != options:
                self.compensation_combo.clear()
                for option in options:
                    self.compensation_combo.addItem(option, option)
            self.compensation_combo.setCurrentIndex(
                self.compensation_combo.findData(selected)
            )
        finally:
            del blocker
        self._compensation_by_target[key] = selected

    def _target_changed(self, _index: int) -> None:
        """設定先の変更時に入力文字を破棄し、新しい実値を読む。"""
        if self.target_combo.currentIndex() < 0:
            return
        self._requested_target = cast(
            RotationTarget, self.target_combo.currentData()
        )
        self.xyz_editor.discard_pending_input()
        self.refresh()

    def _compensation_changed(self, _index: int) -> None:
        """設定先ごとに利用者が選んだ補償先を記憶する。"""
        if self.compensation_combo.currentIndex() >= 0:
            node_type = self._node_type
            if node_type is not None:
                self._compensation_by_target[(node_type, self.target())] = (
                    self.compensate_with()
                )

    def _invalidate_selection(self) -> None:
        """旧ノードへ未確定文字を適用できないよう入力を止める。"""
        self._node_name = None
        self._node_type = None
        self.xyz_editor.discard_pending_input()
        self.xyz_editor.set_input_enabled(False)
        self.watch_node(None)

    def _values_degrees(self, node_name: str) -> _Values:
        """選択ノードの設定先XYZを未丸めのdegreeで読む。"""
        operator = (
            Nodes().existing.joint(node_name)
            if self._node_type == "joint"
            else Nodes().existing.transform(node_name)
        )
        return cast(_Values, tuple(getattr(operator, self.target()).get()))

    def refresh(self) -> None:
        """選択末尾のノードと使用可能な回転属性・実値へ同期する。"""
        if self.is_disposed:
            return
        node_name = self.selected_node_name()
        node_type: Literal["transform", "joint"] | None = None
        if node_name is not None:
            try:
                actual_type = cmds.nodeType(node_name)
            except (ValueError, TypeError, RuntimeError):
                actual_type = None
            if actual_type in ("transform", "joint"):
                node_type = actual_type
        if node_type is None:
            self._invalidate_selection()
            self.target_label.setText("設定対象（基準ノードのみ）：なし")
            self.xyz_editor.set_values((0.0, 0.0, 0.0))
            self.error_label.hide()
            return
        assert node_name is not None
        if node_name != self._node_name:
            self.xyz_editor.discard_pending_input()
        self._node_name = node_name
        self._node_type = node_type
        self._sync_options(node_type)
        self.target_label.setText(
            f"設定対象（基準ノードのみ）：{node_display_name(node_name)}"
        )
        try:
            values = self._values_degrees(node_name)
            self.watch_node(node_name)
        except (ValueError, TypeError, RuntimeError) as error:
            self.xyz_editor.set_input_enabled(False)
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.xyz_editor.set_values(
            cast(
                _Values,
                tuple(
                    om.MAngle(value, om.MAngle.kDegrees).asUnits(
                        om.MAngle.uiUnit()
                    )
                    for value in values
                ),
            )
        )
        self.xyz_editor.set_input_enabled(True)
        self.error_label.hide()

    def _set_axis_value(self, axis: int, display_value: float) -> None:
        """確定した角度を現在選択の1軸へ適用する。"""
        self._apply_axis(axis, display_value=display_value)

    def _step_axis_value(
        self, axis: int, steps: int, display_step: float
    ) -> None:
        """現在の実値からStepの指定回数だけ角度を動かす。"""
        self._apply_axis(axis, step_offset=steps * display_step)

    def _apply_axis(
        self,
        axis: int,
        *,
        display_value: float | None = None,
        step_offset: float | None = None,
    ) -> None:
        """他軸の未丸め実値を保持して姿勢維持コマンドへ渡す。"""
        node_name = self._node_name
        if (
            node_name is None
            or self.is_disposed
            or self.selected_node_name() != node_name
        ):
            self._invalidate_selection()
            self.queue_refresh()
            return
        try:
            values = list(self._values_degrees(node_name))
            unit = om.MAngle.uiUnit()
            if step_offset is not None:
                display_value = (
                    om.MAngle(values[axis], om.MAngle.kDegrees).asUnits(unit)
                    + step_offset
                )
            assert display_value is not None
            values[axis] = om.MAngle(display_value, unit).asDegrees()
            set_rotation_preserving_pose(
                (node_name,),
                cast(_Values, tuple(values)),
                target=self.target(),
                compensate_with=self.compensate_with(),
                angle_unit="degrees",
            )
        except (ValueError, TypeError, RuntimeError, ExceptionGroup) as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.refresh()

    def dispose(self) -> None:
        """XYZ入力元と選択監視をWindow終了時に解除する。"""
        if self.is_disposed:
            return
        self.xyz_editor.dispose()
        super().dispose()
