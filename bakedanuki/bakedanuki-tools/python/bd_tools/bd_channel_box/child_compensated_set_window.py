# coding: utf-8
"""現在選択の移動・回転値を子の座標や姿勢を保って編集するWindow。"""

from __future__ import annotations

from typing import Literal, cast

from maya import cmds
from maya.api import OpenMaya as om

from bd_util import Nodes
from bd_util.maya.mpx_cmd import (
    set_joint_orient_compensate_children,
    set_rotate_axis_compensate_children,
    set_rotate_compensate_children,
    set_translate_compensate_children,
)
from bd_util.ui import qt

from .controller import RoundTransformKind
from .live_set_common import LiveSetWindowBase, LiveXyzEditor

__all__ = [
    "ChildCompensatedSetWindow",
    "TRANSLATE_INITIAL_WIDTH",
    "TRANSLATE_INITIAL_HEIGHT",
    "ROTATION_INITIAL_WIDTH",
    "ROTATION_INITIAL_HEIGHT",
]

TransformSpace = Literal["local", "world"]
JointChildCompensationAttr = Literal["rotate", "jointOrient"]
_Values = tuple[float, float, float]

# Step欄を含めたWindowの初期表示サイズ（Qt論理px）
TRANSLATE_INITIAL_WIDTH = 298
TRANSLATE_INITIAL_HEIGHT = 176
ROTATION_INITIAL_WIDTH = 300
ROTATION_INITIAL_HEIGHT = 260


class ChildCompensatedSetWindow(LiveSetWindowBase):
    """操作時の基準ノード1個へXYZ値を即時設定する。"""

    def __init__(
        self,
        parent: qt.QWidget | None = None,
        *,
        initial_target: RoundTransformKind = "translate",
    ) -> None:
        """移動または回転用の選択欄と独立した軸Step欄を作る。"""
        if initial_target not in (
            "translate",
            "rotate",
            "rotateAxis",
            "jointOrient",
        ):
            raise ValueError("移動または回転属性を指定してください")
        super().__init__(parent)
        self._is_translate = initial_target == "translate"
        self._requested_target: RoundTransformKind = initial_target
        self._node_name: str | None = None
        self._node_type: Literal["transform", "joint"] | None = None
        self.setWindowTitle(
            "移動をセット（子を維持）"
            if self._is_translate
            else "回転をセット（子を維持）"
        )
        self.target_label = qt.QLabel("設定対象（基準ノードのみ）：なし", self)
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

        self.target_combo: qt.QComboBox | None = None
        self.preservation_combo: qt.QComboBox | None = None
        self.joint_child_combo: qt.QComboBox | None = None
        if not self._is_translate:
            self.target_combo = qt.QComboBox(self)
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
        self.space_combo.addItem("World", "world")
        self.space_combo.addItem("Local", "local")
        self.space_combo.setCurrentIndex(self.space_combo.findData("local"))
        self.space_combo.setToolTip(
            "Local: 属性値\nWorld: "
            + (
                "DAG原点のworld位置"
                if self._is_translate
                else "最終world姿勢（XYZ順）"
            )
        )
        self.space_combo.currentIndexChanged.connect(self._space_changed)
        self.xyz_editor = LiveXyzEditor(self, angle=not self._is_translate)
        self.xyz_editor.set_value_handler(self._set_axis_value)
        self.xyz_editor.set_step_handler(self._step_axis_value)
        self.error_label = qt.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self.target_label)
        layout.addWidget(self.child_label)
        separator = qt.QFrame(self)
        separator.setFrameShape(qt.QFrame.Shape.HLine)
        layout.addWidget(separator)
        selectors = qt.QGridLayout()
        rows: tuple[tuple[str, qt.QComboBox], ...]
        if self._is_translate:
            rows = (("入力空間", self.space_combo),)
        else:
            assert self.target_combo is not None
            assert self.preservation_combo is not None
            assert self.joint_child_combo is not None
            rows = (
                ("値をセットする属性", self.target_combo),
                ("入力空間", self.space_combo),
                ("子の維持範囲", self.preservation_combo),
                ("子Jointの補償属性", self.joint_child_combo),
            )
        labels: list[qt.QLabel] = []
        for row, (title, combo) in enumerate(rows):
            label = qt.QLabel(title, self)
            selectors.addWidget(label, row, 0)
            selectors.addWidget(combo, row, 1)
            labels.append(label)
        label_width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setMinimumWidth(label_width)
        selectors.setColumnStretch(1, 1)
        layout.addLayout(selectors)
        layout.addWidget(self.xyz_editor)
        layout.addWidget(self.error_label)
        self.resize(
            (
                TRANSLATE_INITIAL_WIDTH
                if self._is_translate
                else ROTATION_INITIAL_WIDTH
            ),
            (
                TRANSLATE_INITIAL_HEIGHT
                if self._is_translate
                else ROTATION_INITIAL_HEIGHT
            ),
        )

        self.selection_invalidated.connect(self._invalidate_selection)
        self.units_invalidated.connect(self.xyz_editor.discard_pending_input)
        self.refresh_requested.connect(self.refresh)
        self.refresh()

    def set_initial_target(self, target: RoundTransformKind) -> None:
        """メニューで右クリックした属性群を今回の設定先にする。"""
        if self._is_translate:
            if target != "translate":
                raise ValueError("移動Windowではtranslateのみ設定できます")
        elif target not in ("rotate", "rotateAxis", "jointOrient"):
            raise ValueError("回転属性を指定してください")
        self._requested_target = target
        self.xyz_editor.discard_pending_input()
        self.refresh()

    def target(self) -> RoundTransformKind:
        """現在値を設定する属性群を返す。"""
        if self._is_translate:
            return "translate"
        return self._requested_target

    def space(self) -> TransformSpace:
        """XYZ欄がLocal属性値かWorld位置・姿勢か返す。"""
        return cast(TransformSpace, self.space_combo.currentData())

    def compensate_child_translate(self) -> bool:
        """回転設定時に子のworld座標も維持するか返す。"""
        combo = self.preservation_combo
        return True if combo is None else cast(bool, combo.currentData())

    def joint_child_compensation_attr(self) -> JointChildCompensationAttr:
        """子Jointの姿勢を補償する属性群を返す。"""
        combo = self.joint_child_combo
        return (
            "rotate"
            if combo is None
            else cast(JointChildCompensationAttr, combo.currentData())
        )

    def _sync_target_combo(
        self, node_type: Literal["transform", "joint"]
    ) -> None:
        """選択ノードで使用可能な回転属性だけを候補へ残す。"""
        combo = self.target_combo
        if combo is None:
            return
        available: tuple[RoundTransformKind, ...] = (
            ("rotate", "rotateAxis", "jointOrient")
            if node_type == "joint"
            else ("rotate", "rotateAxis")
        )
        desired: RoundTransformKind = (
            self._requested_target
            if self._requested_target in available
            else "rotate"
        )
        current = tuple(
            cast(RoundTransformKind, combo.itemData(index))
            for index in range(combo.count())
        )
        blocker = qt.QtCore.QSignalBlocker(combo)
        try:
            if current != available:
                combo.clear()
                for target in available:
                    combo.addItem(target, target)
            combo.setCurrentIndex(combo.findData(desired))
        finally:
            del blocker
        self._requested_target = desired

    def _invalidate_selection(self) -> None:
        """古い対象への入力を直ちに止め、未確定の文字を捨てる。"""
        self._node_name = None
        self._node_type = None
        self.xyz_editor.discard_pending_input()
        self.xyz_editor.set_input_enabled(False)
        self.watch_node(None)

    def _target_changed(self, _index: int) -> None:
        """設定先を切り替え、sceneを書かずに実値を再取得する。"""
        combo = self.target_combo
        if combo is None or combo.currentIndex() < 0:
            return
        self._requested_target = cast(RoundTransformKind, combo.currentData())
        self.xyz_editor.discard_pending_input()
        self.refresh()

    def _space_changed(self, _index: int) -> None:
        """空間を切り替え、sceneを書かずに現在値を換算する。"""
        self.xyz_editor.discard_pending_input()
        self.refresh()

    def _values_canonical(self, node_name: str) -> _Values:
        """未丸めの属性値を読み、World欄では現姿勢へ換算する。"""
        operator = (
            Nodes().existing.joint(node_name)
            if self._node_type == "joint"
            else Nodes().existing.transform(node_name)
        )
        target = self.target()
        local = cast(_Values, tuple(getattr(operator, target).get()))
        if self.space() == "local":
            return local
        return operator.convert_transform_space_values(
            target, local, from_space="local", to_space="world"
        )

    def _to_display(self, value: float) -> float:
        """現在のMaya表示単位でcmまたはdegreeを表示値へ変える。"""
        if self._is_translate:
            return om.MDistance(value, om.MDistance.kCentimeters).asUnits(
                om.MDistance.uiUnit()
            )
        return om.MAngle(value, om.MAngle.kDegrees).asUnits(om.MAngle.uiUnit())

    def _from_display(self, value: float) -> float:
        """現在のMaya表示単位からcmまたはdegreeへ戻す。"""
        if self._is_translate:
            return om.MDistance(value, om.MDistance.uiUnit()).asCentimeters()
        return om.MAngle(value, om.MAngle.uiUnit()).asDegrees()

    def refresh(self) -> None:
        """現在選択の末尾を基準ノードとし、候補と実値を再表示する。"""
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
        self._sync_target_combo(node_type)
        self.target_label.setText(f"設定対象（基準ノードのみ）：{node_name}")
        try:
            values = self._values_canonical(node_name)
            self.watch_node(node_name)
        except (ValueError, TypeError, RuntimeError) as error:
            self.xyz_editor.set_input_enabled(False)
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.xyz_editor.set_values(
            cast(_Values, tuple(self._to_display(value) for value in values))
        )
        self.xyz_editor.set_input_enabled(True)
        self.error_label.hide()

    def _set_axis_value(self, axis: int, display_value: float) -> None:
        """文字入力を現在選択の基準ノードへ1軸ずつ確定する。"""
        self._apply_axis(axis, display_value=display_value)

    def _step_axis_value(
        self, axis: int, steps: int, display_step: float
    ) -> None:
        """現在scene値を起点にStepの指定回数だけ動かす。"""
        self._apply_axis(axis, step_offset=steps * display_step)

    def _apply_axis(
        self,
        axis: int,
        *,
        display_value: float | None = None,
        step_offset: float | None = None,
    ) -> None:
        """未編集軸の実値を読み直して既存のUndo対応コマンドを実行する。"""
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
            values = list(self._values_canonical(node_name))
            if step_offset is not None:
                display_value = self._to_display(values[axis]) + step_offset
            assert display_value is not None
            values[axis] = self._from_display(display_value)
            target_values = cast(_Values, tuple(values))
            space = self.space()
            target = self.target()
            if target == "translate":
                set_translate_compensate_children(
                    (node_name,),
                    target_values,
                    space=space,
                    input_unit="canonical",
                )
            elif target == "rotate":
                set_rotate_compensate_children(
                    (node_name,),
                    target_values,
                    space=space,
                    input_unit="canonical",
                    compensate_child_translate=self.compensate_child_translate(),
                    joint_child_compensation_attr=(
                        self.joint_child_compensation_attr()
                    ),
                )
            elif target == "rotateAxis":
                set_rotate_axis_compensate_children(
                    (node_name,),
                    target_values,
                    space=space,
                    input_unit="canonical",
                    compensate_child_translate=self.compensate_child_translate(),
                    joint_child_compensation_attr=(
                        self.joint_child_compensation_attr()
                    ),
                )
            else:
                set_joint_orient_compensate_children(
                    (node_name,),
                    target_values,
                    space=space,
                    input_unit="canonical",
                    compensate_child_translate=self.compensate_child_translate(),
                    joint_child_compensation_attr=(
                        self.joint_child_compensation_attr()
                    ),
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
