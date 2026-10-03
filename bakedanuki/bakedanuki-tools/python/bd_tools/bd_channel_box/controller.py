# coding: utf-8
"""選択ノードと入力行を結び付けるbdChannelBoxの制御。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from functools import partial
from typing import Literal, TypeAlias, cast

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from bd_util.maya.node.inspection import (
    ScalarAttributeDisplayFilter,
    ScalarAttributeInfo,
    ScalarAttributeKind,
    filter_scalar_attribute_paths,
    inspect_scalar_attributes,
    matches_scalar_attribute_display_filter,
    selected_node_names,
)
from bd_util.maya.ui import (
    ChannelDisplayState,
    MayaBoolValueEdit,
    MayaBoolPlugsBinding,
    MayaCallbackRegistry,
    MayaChannelStateBinding,
    MayaChannelStatePlug,
    MayaEnumPlugsBinding,
    MayaEnumValueEdit,
    MayaEditSession,
    MayaFloatPlugsBinding,
    MayaFloatOffsetEdit,
    MayaFloatValueEdit,
    MayaPlugsValueEdit,
    MayaScalarValueClipboard,
    MayaScalarValueTransfer,
    MayaStringPlugsBinding,
    MayaStringValueEdit,
    apply_scalar_value_transfer,
    apply_scalar_value_transfer_to_paths,
    apply_scalar_value_to_paths,
    apply_plugs_values,
    capture_all_scalar_node_values,
    capture_scalar_node_values,
    inspect_plug_input_state,
    read_enum_definition,
    resolve_bool_plug,
    resolve_enum_plug,
    resolve_float_plug,
    resolve_string_plug,
)
from bd_util.ui import qt

from . import config

ChannelBinding: TypeAlias = (
    MayaBoolPlugsBinding
    | MayaFloatPlugsBinding
    | MayaEnumPlugsBinding
    | MayaStringPlugsBinding
)
ChannelBoxMode: TypeAlias = Literal["values", "states"]
ChannelAttributeFilter: TypeAlias = ScalarAttributeDisplayFilter

__all__ = [
    "ChannelBinding",
    "ChannelBoxMode",
    "ChannelAttributeFilter",
    "ChannelRow",
    "ChannelStateRow",
    "ChannelBoxController",
]


def _attribute_display_priority(
    attribute: ScalarAttributeInfo, *, priorities: dict[str, int]
) -> int:
    """指定属性、drawOverride配下、その他の順に表示優先度を返す。"""
    priority = priorities.get(attribute.path)
    if priority is not None:
        return priority
    if attribute.path.startswith("drawOverride."):
        return len(priorities)
    return len(priorities) + 1


@dataclass(frozen=True)
class ChannelRow:
    """代表属性、入力Binding、対応しない選択ノードの理由。"""

    attribute: ScalarAttributeInfo
    binding: ChannelBinding
    excluded: tuple[str, ...]
    target_names: tuple[str, ...]


@dataclass(frozen=True)
class ChannelStateRow:
    """代表属性、表示・ロックBinding、対応しないノードの理由。"""

    attribute: ScalarAttributeInfo
    state_binding: MayaChannelStateBinding
    excluded: tuple[str, ...]
    target_names: tuple[str, ...]


@dataclass(frozen=True)
class _AnimationCurveSource:
    """コピー元ノードの選択順と正式属性パスを保持する。"""

    node_index: int
    path: str
    kind: ScalarAttributeKind


@dataclass(frozen=True)
class _CopiedAnimationCurve:
    """Mayaのキー用クリップボード内の曲線を属性へ対応付ける。"""

    node_index: int
    path: str
    item_index: int


@dataclass(frozen=True)
class _AnimationCurveCopy:
    """コピー時の曲線とノード順をシーン変更後も保持する。"""

    clipboard: oma.MAnimCurveClipboard
    node_count: int
    curves: tuple[_CopiedAnimationCurve, ...]


class ChannelBoxController(qt.QObject):
    """選択・属性構成の変更時だけ入力行を組み直す。"""

    rows_changed = qt.Signal()
    rows_about_to_change = qt.Signal()
    error_occurred = qt.Signal(str)
    operation_reported = qt.Signal(str)
    mode_changed = qt.Signal()
    filter_changed = qt.Signal()
    time_changed = qt.Signal(bool)

    def __init__(self, parent: qt.QObject) -> None:
        """表示用状態と、Windowと同じ寿命の監視を初期化する。"""
        super().__init__(parent)
        self.rows: tuple[ChannelRow | ChannelStateRow, ...] = ()
        self.node_names: tuple[str, ...] = ()
        self.node_ids: tuple[str, ...] = ()
        self._mode: ChannelBoxMode = "values"
        self._filters: dict[ChannelBoxMode, ChannelAttributeFilter] = {
            "values": "visible",
            "states": "all",
        }
        self._disposed = False
        self._current_time_seconds = oma.MAnimControl.currentTime().asUnits(
            om.MTime.kSeconds
        )
        self._active_state_binding: MayaChannelStateBinding | None = None
        self.state_edit_session = MayaEditSession(
            self, chunk_name="SweepChannelStates"
        )
        self.value_edit_session = MayaEditSession(
            self, chunk_name="EditSelectedAttributes"
        )
        self._value_clipboard = MayaScalarValueClipboard()
        self._animation_curve_copy: _AnimationCurveCopy | None = None
        self.state_edit_session.finished.connect(self._finish_state_edit)
        self._filter_refresh_pending = False
        self._events = MayaCallbackRegistry(self)
        self._nodes = MayaCallbackRegistry(self)
        self._timer = qt.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_pending)

        # 構成変更は次のQtイベントへまとめ、値の同期はBindingへ委譲する
        try:
            for name in ("SelectionChanged", "Undo", "Redo"):
                self._events.register(
                    om.MEventMessage.addEventCallback(
                        name, self._queue_rebuild
                    )
                )
            self._events.register(
                om.MEventMessage.addEventCallback(
                    "timeChanged", self._on_time_changed
                )
            )
            for message in (
                om.MSceneMessage.kBeforeNew,
                om.MSceneMessage.kBeforeOpen,
            ):
                self._events.register(
                    om.MSceneMessage.addCallback(message, self._before_scene)
                )
            for message in (
                om.MSceneMessage.kAfterNew,
                om.MSceneMessage.kAfterOpen,
            ):
                self._events.register(
                    om.MSceneMessage.addCallback(message, self._queue_rebuild)
                )
        except Exception:
            self.dispose()
            raise

    def refresh(self) -> None:
        """現在の選択を読み直し、値を書き込まずに入力行を再構築する。"""
        if self._disposed:
            return
        self.state_edit_session.finish()
        self._timer.stop()
        self._refresh_pending()

    @property
    def mode(self) -> ChannelBoxMode:
        """値入力または表示・ロック設定の表示モードを返す。"""
        return self._mode

    def set_mode(self, mode: ChannelBoxMode) -> None:
        """連続編集を終了し、属性を書き換えずに操作する状態を切り替える。"""
        if mode not in ("values", "states"):
            raise ValueError("modeにはvaluesまたはstatesを指定してください")
        if self._disposed or mode == self._mode:
            return
        self._finish_value_edit()
        self._mode = mode
        self.mode_changed.emit()
        self.filter_changed.emit()
        self.refresh()

    @property
    def attribute_filter(self) -> ChannelAttributeFilter:
        """現在のモードに保持している属性フィルターを返す。"""
        return self._filters[self._mode]

    def set_attribute_filter(self, value: ChannelAttributeFilter) -> None:
        """連続編集を終了し、sceneを変更せず表示対象を絞り込む。"""
        if value not in ("all", "visible", "keyable", "channel_box", "hidden"):
            raise ValueError("未対応の属性フィルターです")
        if self._disposed or value == self.attribute_filter:
            return
        self._finish_value_edit()
        self._filters[self._mode] = value
        self.filter_changed.emit()
        self.refresh()

    def _finish_value_edit(self) -> None:
        """行を切り替える前に、値の連続編集とUndoのまとまりを閉じる。"""
        self.value_edit_session.finish()
        for row in self.rows:
            if isinstance(row, ChannelRow) and isinstance(
                row.binding, MayaFloatPlugsBinding
            ):
                row.binding.view_model.end_edit()

    def begin_state_edit(self) -> None:
        """行を固定したまま、複数属性の状態編集を一つのUndoへまとめる。"""
        if self._disposed or self._mode != "states":
            return
        self._finish_value_edit()
        self.state_edit_session.begin()

    def begin_value_edit(self) -> None:
        """Sliderによる複数属性の連続入力を一つのUndoとして開始する。"""
        if self._disposed or self._mode != "values":
            return
        self.state_edit_session.finish()
        self.value_edit_session.begin()

    def finish_value_edit(self) -> None:
        """複数属性の連続入力を確定してUndoのまとまりを閉じる。"""
        self.value_edit_session.finish()

    def _on_time_changed(self, *_args: object) -> None:
        """時刻が変わると旧時刻の入力を終了し、同時刻の再評価は維持する。"""
        if self._disposed:
            return
        current = oma.MAnimControl.currentTime().asUnits(om.MTime.kSeconds)
        if current == self._current_time_seconds:
            return
        self._current_time_seconds = current
        was_editing = self.value_edit_session.is_editing
        if was_editing:
            self.value_edit_session.finish()
        self.time_changed.emit(was_editing)

    def _finish_state_edit(self) -> None:
        """なぞり操作で保留したフィルターを、操作終了後にまとめて反映する。"""
        if self._filter_refresh_pending and not self._disposed:
            self._timer.start(0)

    @property
    def is_disposed(self) -> bool:
        """入力と選択監視が終了済みか返す。"""
        return self._disposed

    def _queue_rebuild(self, *_args: object) -> None:
        """古い対象への入力を終了して、構成の再取得を予約する。"""
        if self._disposed:
            return
        self._dispose_rows()
        self._timer.start(0)

    def _before_scene(self, *_args: object) -> None:
        """scene切替前に古い対象と連続編集中のUndoを解放する。"""
        if self._disposed:
            return
        self._timer.stop()
        self._dispose_rows()
        self._nodes.dispose()

    def _attribute_changed(
        self,
        message: int,
        _plug: om.MPlug,
        _other: om.MPlug,
        *_args: object,
    ) -> None:
        """属性構成と表示フラグの変化をまとめて確認する。"""
        if self._disposed:
            return
        structural = (
            om.MNodeMessage.kAttributeAdded
            | om.MNodeMessage.kAttributeRemoved
            | om.MNodeMessage.kAttributeRenamed
        )
        if message & structural:
            self._queue_rebuild()
        elif self.attribute_filter != "all" and message & (
            om.MNodeMessage.kAttributeKeyable
            | om.MNodeMessage.kAttributeUnkeyable
        ):
            # なぞり中は行を固定し、単発入力も書込み完了後に絞り込む
            self._filter_refresh_pending = True
            if not self.state_edit_session.is_editing:
                self._timer.start(0)

    def _watch_nodes(self) -> None:
        """現在の選択ノードだけに名前・属性構成の監視を登録する。"""
        self._nodes.dispose()
        self._nodes.deleteLater()
        self._nodes = MayaCallbackRegistry(self)
        for name in self.node_names:
            selection = om.MSelectionList()
            selection.add(name)
            node = selection.getDependNode(0)
            self._nodes.register(
                om.MNodeMessage.addAttributeChangedCallback(
                    node, self._attribute_changed
                )
            )
            self._nodes.register(
                om.MNodeMessage.addNameChangedCallback(
                    node, self._queue_rebuild
                )
            )
            self._nodes.register(
                om.MNodeMessage.addNodePreRemovalCallback(
                    node, self._queue_rebuild
                )
            )

    def _refresh_pending(self) -> None:
        """最新の構成を取得し、再構築の失敗は画面へ通知する。"""
        if self._disposed:
            return
        if self.state_edit_session.is_editing:
            self._filter_refresh_pending = True
            return
        self._filter_refresh_pending = False
        try:
            names = selected_node_names()
            attributes = tuple(inspect_scalar_attributes(n) for n in names)
            self._dispose_rows()
            self.node_names = names
            self.node_ids = tuple(
                om.MFnDependencyNode(self._node_object(name)).uuid().asString()
                for name in names
            )
            self._watch_nodes()
            self.rows = self._create_rows(attributes)
        except Exception as error:
            self._dispose_rows()
            self.error_occurred.emit(str(error))
        self.rows_changed.emit()

    def _create_rows(
        self,
        attributes: tuple[tuple[ScalarAttributeInfo, ...], ...],
        *,
        display_filter: ChannelAttributeFilter | None = None,
    ) -> tuple[ChannelRow | ChannelStateRow, ...]:
        """指定した表示条件で基準属性を絞り、同名・同種属性を対応付ける。"""
        if not attributes:
            return ()
        effective_filter = (
            self.attribute_filter if display_filter is None else display_filter
        )
        lookup = tuple({a.path: a for a in items} for items in attributes)
        rows: list[ChannelRow | ChannelStateRow] = []
        try:
            # 構築時に現在の設定を読み、重複は最初の指定だけを採用する
            priorities = {
                path: index
                for index, path in enumerate(
                    dict.fromkeys(config.ATTRIBUTE_PRIORITY_PATHS)
                )
            }
            # 同じ優先度では元の属性順を保ち、行の構築時だけ並べ替える
            for attribute in sorted(
                attributes[0],
                key=partial(
                    _attribute_display_priority, priorities=priorities
                ),
            ):
                if not matches_scalar_attribute_display_filter(
                    attribute, effective_filter
                ):
                    continue
                targets: list[str] = []
                excluded: list[str] = []
                for name, info in zip(self.node_names, lookup):
                    match = info.get(attribute.path)
                    if match is None:
                        excluded.append(f"{name}: 対応する属性なし")
                    elif match.kind != attribute.kind:
                        excluded.append(f"{name}: 型・単位が異なる")
                    else:
                        targets.append(name)
                if self._mode == "states":
                    state_binding = MayaChannelStateBinding(
                        [
                            self._resolve_state_plug(n, attribute)
                            for n in targets
                        ],
                        parent=self,
                    )
                    state_binding.edit_failed.connect(self.error_occurred.emit)
                    rows.append(
                        ChannelStateRow(
                            attribute,
                            state_binding,
                            tuple(excluded),
                            tuple(targets),
                        )
                    )
                    continue
                binding: ChannelBinding
                if attribute.kind == "bool":
                    binding = MayaBoolPlugsBinding(
                        [
                            resolve_bool_plug(n, attribute.path)
                            for n in targets
                        ],
                        parent=self,
                        key_animated=True,
                        track_input_state=True,
                    )
                elif attribute.kind == "enum":
                    binding = self._create_enum_binding(
                        attribute.path, targets, excluded
                    )
                elif attribute.kind == "string":
                    binding = MayaStringPlugsBinding(
                        [
                            resolve_string_plug(n, attribute.path)
                            for n in targets
                        ],
                        parent=self,
                        track_input_state=True,
                    )
                else:
                    binding = MayaFloatPlugsBinding(
                        [
                            resolve_float_plug(n, attribute.path)
                            for n in targets
                        ],
                        parent=self,
                        key_animated=True,
                        track_input_state=True,
                    )
                binding.edit_failed.connect(self.error_occurred.emit)
                rows.append(
                    ChannelRow(
                        attribute, binding, tuple(excluded), tuple(targets)
                    )
                )
        except Exception:
            for row in rows:
                self._dispose_row(row)
            raise
        return tuple(rows)

    @staticmethod
    def _resolve_state_plug(
        name: str, attribute: ScalarAttributeInfo
    ) -> MayaChannelStatePlug:
        """値やenum定義を比較せず、対応scalarの参照だけを取得する。"""
        if attribute.kind == "bool":
            return resolve_bool_plug(name, attribute.path)
        if attribute.kind == "enum":
            return resolve_enum_plug(name, attribute.path)
        if attribute.kind == "string":
            return resolve_string_plug(name, attribute.path)
        return resolve_float_plug(name, attribute.path)

    def _create_enum_binding(
        self, path: str, targets: list[str], excluded: list[str]
    ) -> MayaEnumPlugsBinding:
        """代表と定義が一致するenumだけを、一括編集用Bindingへ渡す。"""
        representative = resolve_enum_plug(targets[0], path)
        definition = read_enum_definition(representative)
        plugs = [representative]
        for name in targets[1:]:
            plug = resolve_enum_plug(name, path)
            if definition.matches(read_enum_definition(plug)):
                plugs.append(plug)
            else:
                excluded.append(f"{name}: enum定義（整数値と項目名）が異なる")
        return MayaEnumPlugsBinding(
            plugs,
            parent=self,
            key_animated=True,
            track_input_state=True,
        )

    def _dispose_rows(self) -> None:
        """Qtの遅延削除を待たず、すべての入力とMaya監視を終了する。"""
        self._filter_refresh_pending = False
        self.rows_about_to_change.emit()
        if self._active_state_binding is not None:
            self._active_state_binding.dispose()
        self.state_edit_session.finish()
        self.value_edit_session.finish()
        rows, self.rows = self.rows, ()
        for row in rows:
            self._dispose_row(row)

    @staticmethod
    def _node_object(name: str) -> om.MObject:
        """改名に依存しない選択識別子を取得するためnodeを解決する。"""
        selection = om.MSelectionList()
        selection.add(name)
        return selection.getDependNode(0)

    def _selected_rows(
        self, keys: Sequence[tuple[str, str]]
    ) -> tuple[ChannelRow | ChannelStateRow, ...]:
        """表示中の正式pathと型だけを受け付け、古い選択への入力を拒否する。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        if self._active_state_binding is not None:
            raise RuntimeError(
                "選択属性の状態変更中には別の操作を開始できません"
            )
        lookup = {(r.attribute.path, r.attribute.kind): r for r in self.rows}
        unique = tuple(dict.fromkeys(keys))
        if any(key not in lookup for key in unique):
            raise RuntimeError(
                "属性の構成が変わりました。選択し直してください"
            )
        return tuple(lookup[key] for key in unique)

    @staticmethod
    def _keyframe_plug(name: str) -> str | None:
        """キー設定可能な単一属性だけを、接続を変更しない対象として返す。"""
        selection = om.MSelectionList()
        try:
            selection.add(name)
            plug = selection.getPlug(0)
        except (RuntimeError, TypeError):
            return None
        attribute = plug.attribute()
        if (
            plug.isArray
            or plug.isCompound
            or not (
                attribute.hasFn(om.MFn.kNumericAttribute)
                or attribute.hasFn(om.MFn.kEnumAttribute)
                or attribute.hasFn(om.MFn.kUnitAttribute)
            )
        ):
            return None
        if not om.MFnAttribute(attribute).writable:
            return None
        if om.MFnDependencyNode(plug.node()).isLocked:
            return None
        ancestor = plug
        while True:
            if ancestor.isLocked or (
                ancestor != plug and ancestor.isDestination
            ):
                return None
            if not ancestor.isChild:
                break
            ancestor = ancestor.parent()
        if inspect_plug_input_state(plug) not in (
            "unconnected",
            "nonkeyable",
            "keyed",
            "animated",
            "key_altered",
            "animation_layer",
        ):
            return None
        return plug.name()

    def set_keyframes_all_keyable(self, *, breakdown: bool = False) -> int:
        """選択ノード自身の全Keyable属性へ、指定種別のキーを打つ。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets: list[str] = []
        for node in self.node_names:
            for attribute in cmds.listAttr(node, keyable=True) or ():
                plug = self._keyframe_plug(f"{node}.{attribute}")
                if plug is not None:
                    targets.append(plug)
        if not targets:
            return 0
        return cmds.setKeyframe(
            *dict.fromkeys(targets), insertBlend=False, breakdown=breakdown
        )

    def set_keyframes_selected(
        self, keys: Sequence[tuple[str, str]], *, breakdown: bool = False
    ) -> int:
        """表示中の選択行に対応する全ノードへ指定種別のキーを打つ。"""
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets: list[str] = []
        for row in self._selected_rows(keys):
            if not isinstance(row, ChannelRow):
                continue
            for node in row.target_names:
                plug = self._keyframe_plug(f"{node}.{row.attribute.path}")
                if plug is not None:
                    targets.append(plug)
        if not targets:
            return 0
        return cmds.setKeyframe(
            *dict.fromkeys(targets), insertBlend=False, breakdown=breakdown
        )

    def selected_animation_layers(self) -> tuple[str, ...]:
        """選択中の実アニメーションレイヤを取得し、BaseAnimationを除く。"""
        if self._disposed:
            return ()
        root = cast(str | None, cmds.animLayer(query=True, root=True))
        layers = cast(list[str] | None, cmds.ls(type="animLayer")) or ()
        return tuple(
            layer
            for layer in layers
            if layer != root
            and cmds.animLayer(layer, query=True, selected=True)
        )

    @staticmethod
    def _animation_layer_members(layer: str) -> set[str]:
        """レイヤ所属属性をDAGの完全パスで正規化して返す。"""
        attributes = (
            cast(
                list[str] | None,
                cmds.animLayer(layer, query=True, attribute=True),
            )
            or ()
        )
        if not attributes:
            return set()
        return set(
            cast(list[str] | None, cmds.ls(*attributes, long=True)) or ()
        )

    def _edit_animation_layer_membership(
        self, targets: Sequence[str], *, add: bool
    ) -> int:
        """選択レイヤと対象属性の所属を変更し、全変更を一度のUndoへまとめる。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        layers = self.selected_animation_layers()
        # 正式属性pathをMayaのレイヤ所属照会と同じプラグ名へ揃える
        unique_targets = (
            tuple(
                dict.fromkeys(
                    cast(list[str] | None, cmds.ls(*targets, long=True)) or ()
                )
            )
            if targets
            else ()
        )
        if not layers or not unique_targets:
            return 0

        changed = 0
        cmds.undoInfo(
            openChunk=True,
            chunkName=(
                "AddSelectedAttributesToAnimationLayers"
                if add
                else "RemoveSelectedAttributesFromAnimationLayers"
            ),
        )
        try:
            for layer in layers:
                before = self._animation_layer_members(layer)
                # 対応できない属性はMayaのレイヤ操作に任せて静かに除外する
                for target in unique_targets:
                    if (target in before) == add:
                        continue
                    try:
                        if add:
                            cmds.animLayer(layer, edit=True, attribute=target)
                        else:
                            cmds.animLayer(
                                layer, edit=True, removeAttribute=target
                            )
                    except (RuntimeError, TypeError):
                        continue
                after = self._animation_layer_members(layer)
                changed += len(
                    (
                        (after - before) if add else (before - after)
                    ).intersection(unique_targets)
                )
        finally:
            cmds.undoInfo(closeChunk=True)
        return changed

    def edit_animation_layers_selected(
        self, keys: Sequence[tuple[str, str]], *, add: bool
    ) -> int:
        """選択行と同じ正式path・型の各ノード属性を選択レイヤで変更する。"""
        targets = tuple(
            f"{node}.{row.attribute.path}"
            for row in self._selected_rows(keys)
            if row.attribute.kind != "string"
            for node in row.target_names
        )
        return self._edit_animation_layer_membership(targets, add=add)

    def edit_animation_layers_all_keyable(self, *, add: bool) -> int:
        """各選択ノードの全Keyable属性を選択レイヤで変更する。"""
        targets = tuple(
            f"{node}.{attribute}"
            for node in self.node_names
            for attribute in cmds.listAttr(node, keyable=True) or ()
        )
        return self._edit_animation_layer_membership(targets, add=add)

    @staticmethod
    def _mute_target(name: str, *, muted: bool) -> str | None:
        """入力接続があり、指定したミュート状態へ変更できる単一属性を返す。"""
        selection = om.MSelectionList()
        try:
            selection.add(name)
            plug = selection.getPlug(0)
        except (RuntimeError, TypeError):
            return None
        attribute = plug.attribute()
        if (
            plug.isArray
            or plug.isCompound
            or not (
                attribute.hasFn(om.MFn.kNumericAttribute)
                or attribute.hasFn(om.MFn.kEnumAttribute)
                or attribute.hasFn(om.MFn.kUnitAttribute)
            )
            or not plug.isDestination
            or not om.MFnAttribute(attribute).writable
            or om.MFnDependencyNode(plug.node()).isLocked
        ):
            return None
        ancestor = plug
        while True:
            if ancestor.isLocked:
                return None
            if not ancestor.isChild:
                break
            ancestor = ancestor.parent()
        try:
            if bool(cmds.mute(plug.name(), query=True)) == muted:
                return None
        except (RuntimeError, TypeError):
            return None
        return plug.name()

    def set_muted_all_visible(self, *, muted: bool) -> int:
        """各選択ノードのKeyable／ChannelBox表示属性を一括ミュートする。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets: list[str] = []
        # 画面の検索・表示フィルターではなく各ノード自身の表示フラグで列挙する
        for node in self.node_names:
            attributes = inspect_scalar_attributes(node)
            for path in filter_scalar_attribute_paths(attributes, "visible"):
                target = self._mute_target(f"{node}.{path}", muted=muted)
                if target is not None:
                    targets.append(target)
        if not targets:
            return 0
        cmds.mute(*dict.fromkeys(targets), disable=not muted)
        return len(targets)

    def set_muted_selected(
        self, keys: Sequence[tuple[str, str]], *, muted: bool
    ) -> int:
        """選択行と対応する全ノードの属性を表示状態に関係なくミュートする。"""
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets: list[str] = []
        for row in self._selected_rows(keys):
            if not isinstance(row, ChannelRow):
                continue
            for node in row.target_names:
                target = self._mute_target(
                    f"{node}.{row.attribute.path}", muted=muted
                )
                if target is not None:
                    targets.append(target)
        if not targets:
            return 0
        cmds.mute(*dict.fromkeys(targets), disable=not muted)
        return len(targets)

    def can_paste_animation_curves(self) -> bool:
        """この画面でコピーしたアニメーションカーブがあるか返す。"""
        return self._animation_curve_copy is not None

    def _copy_animation_curves(
        self, sources: Sequence[_AnimationCurveSource]
    ) -> tuple[_CopiedAnimationCurve, ...]:
        """対象曲線をキー用clipboardへコピーし、元属性との対応を返す。"""
        self.state_edit_session.finish()
        self._finish_value_edit()
        selected: list[_AnimationCurveSource] = []
        for source in dict.fromkeys(sources):
            name = f"{self.node_names[source.node_index]}.{source.path}"
            if source.kind == "string":
                continue
            try:
                if cmds.keyframe(name, query=True, keyframeCount=True):
                    selected.append(source)
            except (RuntimeError, TypeError):
                continue
        if not selected:
            return ()

        names = tuple(
            f"{self.node_names[source.node_index]}.{source.path}"
            for source in selected
        )
        api_clipboard = oma.MAnimCurveClipboard.theAPIClipboard
        previous = oma.MAnimCurveClipboard()
        previous.set(api_clipboard)
        undo_enabled = bool(cmds.undoInfo(query=True, state=True))
        # 読み取り操作でsceneのUndo履歴を増やさず、Maya標準のキー用clipboardも更新する
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            count = cmds.copyKey(
                *names,
                animation="objects",
                clipboard="api",
                hierarchy="none",
                shape=False,
            )
            if not count:
                return ()
            snapshot = oma.MAnimCurveClipboard()
            snapshot.set(api_clipboard)
            known = {
                (
                    self.node_names[source.node_index].lstrip("|"),
                    source.path,
                ): source
                for source in selected
            }
            copied: list[_CopiedAnimationCurve] = []
            for index, item in enumerate(snapshot.clipboardItems()):
                source = known.get(
                    (item.nodeName.lstrip("|"), item.fullAttributeName)
                )
                if source is not None:
                    copied.append(
                        _CopiedAnimationCurve(
                            source.node_index,
                            source.path,
                            index,
                        )
                    )
            if not copied:
                return ()
            copied_names = tuple(
                dict.fromkeys(
                    f"{self.node_names[curve.node_index]}.{curve.path}"
                    for curve in copied
                )
            )
            native_count = cmds.copyKey(
                *copied_names,
                animation="objects",
                clipboard="anim",
                hierarchy="none",
                shape=False,
            )
            if native_count != len(copied):
                raise RuntimeError(
                    "Mayaのキー用clipboardへコピーできませんでした"
                )
        finally:
            cmds.undoInfo(stateWithoutFlush=undo_enabled)
            api_clipboard.set(previous)

        # キーを持つコピー元だけでノード順を詰め、次の貼り付けへ保持する
        source_indices = tuple(
            index
            for index in range(len(self.node_names))
            if any(curve.node_index == index for curve in copied)
        )
        compact_indices = {
            source_index: index
            for index, source_index in enumerate(source_indices)
        }
        self._animation_curve_copy = _AnimationCurveCopy(
            snapshot,
            len(source_indices),
            tuple(
                _CopiedAnimationCurve(
                    compact_indices[curve.node_index],
                    curve.path,
                    curve.item_index,
                )
                for curve in copied
            ),
        )
        return tuple(copied)

    def copy_animation_curves_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """選択行と対応する各選択ノードの全時間の曲線をコピーする。"""
        sources = tuple(
            _AnimationCurveSource(
                self.node_names.index(node),
                row.attribute.path,
                row.attribute.kind,
            )
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
            for node in row.target_names
        )
        return len(self._copy_animation_curves(sources))

    def copy_animation_curves_all_visible(self) -> int:
        """各選択ノードのKeyable／ChannelBox表示属性の曲線をコピーする。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        sources = tuple(
            _AnimationCurveSource(index, info.path, info.kind)
            for index, node in enumerate(self.node_names)
            for info in inspect_scalar_attributes(node)
            if info.keyable or info.channel_box
        )
        return len(self._copy_animation_curves(sources))

    def _cut_animation_curves(
        self, sources: Sequence[_AnimationCurveSource]
    ) -> int:
        """コピーと削除が一致する属性だけ、全時間のキーをカットする。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        eligible = tuple(
            source
            for source in dict.fromkeys(sources)
            if source.kind != "string"
            and self._deletable_animation_curve_target(
                f"{self.node_names[source.node_index]}.{source.path}"
            )
            is not None
        )
        if not eligible:
            return 0

        # 実際にコピーできた属性だけを削除し、貼り付け情報との食い違いを防ぐ
        copied = self._copy_animation_curves(eligible)
        if not copied:
            return 0
        targets = tuple(
            dict.fromkeys(
                f"{self.node_names[curve.node_index]}.{curve.path}"
                for curve in copied
            )
        )
        cmds.cutKey(
            *targets,
            animation="objects",
            clear=True,
            hierarchy="none",
            shape=False,
        )
        return len(targets)

    def cut_animation_curves_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """選択行と同じ正式pathの全選択ノードの曲線をカットする。"""
        selected_paths = {
            row.attribute.path
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
        }
        sources = tuple(
            _AnimationCurveSource(index, info.path, info.kind)
            for index, node in enumerate(self.node_names)
            for info in inspect_scalar_attributes(node)
            if info.path in selected_paths
        )
        return self._cut_animation_curves(sources)

    def cut_animation_curves_all_visible(self) -> int:
        """各選択ノードのKeyable／ChannelBox表示属性をカットする。"""
        sources = tuple(
            _AnimationCurveSource(index, info.path, info.kind)
            for index, node in enumerate(self.node_names)
            for info in inspect_scalar_attributes(node)
            if info.keyable or info.channel_box
        )
        return self._cut_animation_curves(sources)

    @staticmethod
    def _deletable_animation_curve_target(name: str) -> str | None:
        """キーがあり、他属性と曲線を共有しない属性だけを返す。"""
        try:
            if not cmds.keyframe(name, query=True, keyframeCount=True):
                return None
            curves = (
                cast(
                    list[str] | None,
                    cmds.keyframe(name, query=True, name=True),
                )
                or ()
            )
            if not curves:
                return None
            # 共有曲線の全キー削除が選択外の属性へ波及することを防ぐ
            for curve in curves:
                destinations = (
                    cast(
                        list[str] | None,
                        cmds.listConnections(
                            f"{curve}.output",
                            source=False,
                            destination=True,
                            plugs=True,
                            skipConversionNodes=True,
                        ),
                    )
                    or ()
                )
                if len(set(destinations)) != 1:
                    return None
        except (RuntimeError, TypeError):
            return None
        return name

    def _delete_animation_curves(self, names: Sequence[str]) -> int:
        """対象属性の全時間のキーをMaya標準の方法で一括削除する。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets = tuple(
            dict.fromkeys(
                target
                for name in names
                if (target := self._deletable_animation_curve_target(name))
                is not None
            )
        )
        if not targets:
            return 0
        cmds.cutKey(
            *targets,
            animation="objects",
            clear=True,
            hierarchy="none",
            shape=False,
        )
        return len(targets)

    def delete_animation_curves_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """選択行と同じ正式pathの全選択ノードの曲線を削除する。"""
        selected_paths = {
            row.attribute.path
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
        }
        names = tuple(
            f"{node}.{info.path}"
            for node in self.node_names
            for info in inspect_scalar_attributes(node)
            if info.path in selected_paths
        )
        return self._delete_animation_curves(names)

    def delete_animation_curves_all_visible(self) -> int:
        """各選択ノードのKeyable／ChannelBox表示属性の曲線を削除する。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        names = tuple(
            f"{node}.{info.path}"
            for node in self.node_names
            for info in inspect_scalar_attributes(node)
            if info.keyable or info.channel_box
        )
        return self._delete_animation_curves(names)

    def _animation_paste_targets(
        self, keys: Sequence[tuple[str, str]] | None
    ) -> tuple[tuple[int, str], ...]:
        """ノード順と正式pathを保ち、型によらず貼り付け先を決める。"""
        copied = self._animation_curve_copy
        if copied is None or not self.node_names:
            return ()
        if copied.node_count != 1 and copied.node_count != len(
            self.node_names
        ):
            raise ValueError(
                "複数ノードのカーブは、同じ数の選択ノードへ貼り付けてください"
            )
        selected_rows = self._selected_rows(keys) if keys is not None else None
        selected_paths = (
            tuple(
                row.attribute.path
                for row in selected_rows
                if isinstance(row, ChannelRow)
            )
            if selected_rows is not None
            else None
        )
        targets: list[tuple[int, str]] = []
        for destination_index, node in enumerate(self.node_names):
            source_index = 0 if copied.node_count == 1 else destination_index
            source_curves = tuple(
                curve
                for curve in copied.curves
                if curve.node_index == source_index
            )
            # 行の値編集対象から外れた異種型ノードも、曲線操作では個別に調べる
            available_paths = {
                info.path for info in inspect_scalar_attributes(node)
            }
            if selected_paths is not None:
                available_paths.intersection_update(selected_paths)
            for curve in source_curves:
                paths = (
                    selected_paths
                    if selected_paths is not None and len(source_curves) == 1
                    else (curve.path,)
                )
                for path in paths:
                    if path not in available_paths:
                        continue
                    target = self._keyframe_plug(f"{node}.{path}")
                    if target is not None:
                        targets.append((curve.item_index, target))
        return tuple(dict.fromkeys(targets))

    def _paste_animation_curves(
        self, keys: Sequence[tuple[str, str]] | None
    ) -> int:
        """各曲線だけをMayaのキー用clipboardへ移し、現在時刻へ一括貼付する。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets = self._animation_paste_targets(keys)
        copied = self._animation_curve_copy
        if not targets or copied is None:
            return 0
        api_clipboard = oma.MAnimCurveClipboard.theAPIClipboard
        previous = oma.MAnimCurveClipboard()
        previous.set(api_clipboard)
        items = copied.clipboard.clipboardItems()
        current_time = cmds.currentTime(query=True)
        pasted = 0
        # 複数曲線の順序任せの割当を避け、各曲線を対応済みの一属性へ貼る
        cmds.undoInfo(openChunk=True, chunkName="PasteAnimationCurves")
        try:
            for item_index, target in targets:
                source = items[item_index]
                item = oma.MAnimCurveClipboardItem()
                item.setAnimCurve(source.animCurve)
                item.setNameInfo(
                    source.nodeName,
                    source.fullAttributeName,
                    source.leafAttributeName,
                )
                item.setAddressingInfo(0, 0, 0)
                api_clipboard.set([item])
                pasted += cmds.pasteKey(
                    target,
                    animation="objects",
                    clipboard="api",
                    time=(current_time, current_time),
                    connect=True,
                    option="insert",
                )
        finally:
            cmds.undoInfo(closeChunk=True)
            api_clipboard.set(previous)
        return pasted

    def paste_animation_curves_same_attributes(self) -> int:
        """コピー元と同じ正式属性パスへ曲線を貼り付ける。"""
        return self._paste_animation_curves(None)

    def paste_animation_curves_to_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """一曲線は型を問わず選択属性へ、複数曲線は同じパスへ貼る。"""
        return self._paste_animation_curves(keys)

    def apply_numeric_values(
        self, keys: Sequence[tuple[str, str]], display_value: float
    ) -> bool:
        """明示入力した表示数値を、選択行ごとの単位へ変換して一括適用する。"""
        rows = self._selected_rows(keys)
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        # 行単位の対象選別を保ち、全行の検証と書込みはutilへ委譲する
        for row in rows:
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, MayaFloatPlugsBinding
            ):
                excluded.append(f"{row.attribute.nice_name}: 数値入力の対象外")
                continue
            row.binding.refresh()
            if not row.binding.view_model.set_value_command.can_execute:
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            edits.append(
                MayaFloatValueEdit(
                    row.binding,
                    row.binding.view_model.presentation.from_display(
                        display_value
                    ),
                )
            )
        changed = apply_plugs_values(
            edits,
            edit_session=(
                self.value_edit_session
                if self.value_edit_session.is_editing
                else None
            ),
        )
        self._report_excluded(excluded)
        return changed

    def offset_numeric_values(
        self, keys: Sequence[tuple[str, str]], display_offset: float
    ) -> bool:
        """各数値の現在値へ、表示単位で同じ増減量を一括適用する。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_rows(keys):
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, MayaFloatPlugsBinding
            ):
                excluded.append(f"{row.attribute.nice_name}: 数値操作の対象外")
                continue
            row.binding.refresh()
            if not row.binding.view_model.set_value_command.can_execute:
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            edits.append(
                MayaFloatOffsetEdit(
                    row.binding,
                    row.binding.view_model.presentation.from_display(
                        display_offset
                    ),
                )
            )
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def apply_bool_values(
        self, keys: Sequence[tuple[str, str]], value: bool
    ) -> bool:
        """選択中のbool属性だけを同じONまたはOFFへ一括適用する。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_rows(keys):
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, MayaBoolPlugsBinding
            ):
                excluded.append(f"{row.attribute.nice_name}: bool操作の対象外")
                continue
            row.binding.refresh()
            if not row.binding.view_model.set_value_command.can_execute:
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            edits.append(MayaBoolValueEdit(row.binding, value))
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def apply_enum_values(
        self,
        keys: Sequence[tuple[str, str]],
        source_key: tuple[str, str],
        value: int,
    ) -> bool:
        """操作元と定義が一致する選択enum属性へ同じ項目を一括適用する。"""
        rows = self._selected_rows(keys)
        source = next(
            (
                row
                for row in rows
                if (row.attribute.path, row.attribute.kind) == source_key
            ),
            None,
        )
        if not isinstance(source, ChannelRow) or not isinstance(
            source.binding, MayaEnumPlugsBinding
        ):
            raise ValueError("操作元のenum属性が選択対象にありません")
        source.binding.refresh()
        definition = source.binding.view_model.definition
        definition.require_value(value)
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in rows:
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, MayaEnumPlugsBinding
            ):
                excluded.append(f"{row.attribute.nice_name}: enum操作の対象外")
                continue
            row.binding.refresh()
            if not definition.matches(row.binding.view_model.definition):
                excluded.append(
                    f"{row.attribute.nice_name}: enum定義が操作元と異なる"
                )
                continue
            if not row.binding.view_model.set_value_command.can_execute:
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            edits.append(MayaEnumValueEdit(row.binding, value))
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def apply_string_values(
        self, keys: Sequence[tuple[str, str]], value: str
    ) -> bool:
        """選択中のstring属性へ同じ文字列を一回のUndoで適用する。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_rows(keys):
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, MayaStringPlugsBinding
            ):
                excluded.append(
                    f"{row.attribute.nice_name}: string操作の対象外"
                )
                continue
            row.binding.refresh()
            if not row.binding.view_model.set_value_command.can_execute:
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            edits.append(MayaStringValueEdit(row.binding, value))
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def align_selected_values(self, keys: Sequence[tuple[str, str]]) -> bool:
        """各選択行を表示ノードの未丸め値へ、一操作で揃える。"""
        rows = tuple(
            row
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
        )
        return self._align_rows(rows)

    def align_filtered_values(
        self, display_filter: ChannelAttributeFilter
    ) -> bool:
        """表示ノードの指定状態に合う全属性を、行表示と独立して揃える。"""
        if display_filter not in (
            "all",
            "visible",
            "keyable",
            "channel_box",
            "hidden",
        ):
            raise ValueError("未対応の属性表示フィルターです")
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        if self._active_state_binding is not None:
            raise RuntimeError(
                "選択属性の状態変更中には別の操作を開始できません"
            )
        if self._mode != "values":
            raise RuntimeError("値編集モードで操作してください")
        if not self.node_names:
            raise RuntimeError("表示ノードが選択されていません")
        if len(self.node_names) < 2:
            return False
        self.state_edit_session.finish()
        self._finish_value_edit()
        attributes = tuple(
            inspect_scalar_attributes(name) for name in self.node_names
        )
        rows = self._create_rows(attributes, display_filter=display_filter)
        try:
            return self._align_rows(
                tuple(
                    row
                    for row in rows
                    if isinstance(row, ChannelRow) and row.binding.is_mixed
                )
            )
        finally:
            for row in rows:
                self._dispose_row(row)

    def _align_rows(self, rows: Sequence[ChannelRow]) -> bool:
        """各属性の表示ノードの未丸め値を検証し、差分を一操作で適用する。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in rows:
            binding = row.binding
            binding.refresh()
            if not binding.view_model.set_value_command.can_execute:
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            if isinstance(binding, MayaEnumPlugsBinding):
                if not binding.is_value_defined:
                    excluded.append(
                        f"{row.attribute.nice_name}: enumの値が未定義です"
                    )
                    continue
                edits.append(MayaEnumValueEdit(binding, binding.value))
            elif isinstance(binding, MayaBoolPlugsBinding):
                edits.append(MayaBoolValueEdit(binding, binding.value))
            elif isinstance(binding, MayaStringPlugsBinding):
                edits.append(MayaStringValueEdit(binding, binding.value))
            else:
                edits.append(MayaFloatValueEdit(binding, binding.value))
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def can_paste_values(self) -> bool:
        """対応する属性値dataが現在のOS clipboardにあるか返す。"""
        return not self._disposed and self._value_clipboard.contains()

    def can_paste_single_value(self) -> bool:
        """clipboardに検証済みの一属性値だけがあるか返す。"""
        if self._disposed or not self._value_clipboard.contains():
            return False
        try:
            transfer = self._value_clipboard.read()
        except (TypeError, ValueError, RuntimeError):
            return False
        return len(transfer.nodes) == 1 and len(transfer.nodes[0].values) == 1

    def copy_all_values(self) -> int:
        """基準nodeの全対応属性値を、型と正式path付きでOSへコピーする。"""
        if not self.node_names:
            raise RuntimeError("コピー元のノードが選択されていません")
        snapshot = capture_all_scalar_node_values(self.node_names[0])
        self._value_clipboard.write(MayaScalarValueTransfer((snapshot,)))
        count = len(snapshot.values)
        self.operation_reported.emit(
            f"基準ノードから全{count}属性の値をコピーしました"
        )
        return count

    def copy_selected_values(self, keys: Sequence[tuple[str, str]]) -> int:
        """基準nodeで選択した対応属性値を、正式path付きでOSへコピーする。"""
        if not self.node_names:
            raise RuntimeError("コピー元のノードが選択されていません")
        attributes = tuple(
            row.attribute
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
        )
        if not attributes:
            raise ValueError("コピー元の値属性を選択してください")
        snapshot = capture_scalar_node_values(self.node_names[0], attributes)
        self._value_clipboard.write(MayaScalarValueTransfer((snapshot,)))
        count = len(snapshot.values)
        self.operation_reported.emit(
            f"基準ノードから選択した{count}属性の値をコピーしました"
        )
        return count

    def paste_copied_values(
        self, display_filter: ChannelAttributeFilter = "all"
    ) -> bool:
        """OS clipboardの属性値を、表示条件で絞った同じ正式pathへ貼る。"""
        if display_filter not in (
            "all",
            "visible",
            "keyable",
            "channel_box",
            "hidden",
        ):
            raise ValueError("未対応の属性表示フィルターです")
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        if not self.node_names:
            raise RuntimeError("貼り付け先のノードが選択されていません")
        if self._active_state_binding is not None:
            raise RuntimeError(
                "選択属性の状態変更中には別の操作を開始できません"
            )
        self.state_edit_session.finish()
        self._finish_value_edit()
        transfer = self._value_clipboard.read()
        if display_filter == "all":
            return apply_scalar_value_transfer(
                self.node_names, transfer, key_animated=True
            ).changed
        paths, _filtered_count, _base_excluded = (
            self._paste_paths_for_display_filter(transfer, display_filter)
        )
        if not paths:
            return False
        return apply_scalar_value_transfer_to_paths(
            self.node_names,
            paths,
            transfer,
            key_animated=True,
        ).changed

    def _paste_paths_for_display_filter(
        self,
        transfer: MayaScalarValueTransfer,
        display_filter: ChannelAttributeFilter,
    ) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
        """基準nodeの表示状態からPaste対象pathと正常な除外件数を求める。"""
        if len(transfer.nodes) != 1:
            raise ValueError("現在は一つのコピー元nodeだけ貼り付けられます")
        base_name = self.node_names[0]
        attributes = inspect_scalar_attributes(base_name)
        by_path = {attribute.path: attribute for attribute in attributes}
        matched_paths = set(
            filter_scalar_attribute_paths(attributes, display_filter)
        )
        paths: list[str] = []
        filtered_count = 0
        excluded: list[str] = []

        # コピー項目順を維持し、基準nodeにないpathは後続nodeへ適用しない
        for snapshot in transfer.nodes[0].values:
            if snapshot.path not in by_path:
                excluded.append(
                    f"{base_name}.{snapshot.path}: 対応する属性なし"
                )
            elif snapshot.path in matched_paths:
                paths.append(snapshot.path)
            else:
                filtered_count += 1
        return tuple(paths), filtered_count, tuple(excluded)

    def paste_copied_values_to_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> bool:
        """OS clipboardの項目数に応じた規則で選択属性へ貼り付ける。"""
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        if not self.node_names:
            raise RuntimeError("貼り付け先のノードが選択されていません")
        if self._active_state_binding is not None:
            raise RuntimeError(
                "選択属性の状態変更中には別の操作を開始できません"
            )
        paths = tuple(
            row.attribute.path
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
        )
        if not paths:
            raise ValueError("貼り付け先の値属性を選択してください")
        self.state_edit_session.finish()
        self._finish_value_edit()
        transfer = self._value_clipboard.read()
        if len(transfer.nodes) != 1:
            raise ValueError("現在は一つのコピー元nodeだけ貼り付けられます")
        if len(transfer.nodes[0].values) == 1:
            result = apply_scalar_value_to_paths(
                self.node_names,
                paths,
                transfer,
                key_animated=True,
            )
        else:
            result = apply_scalar_value_transfer_to_paths(
                self.node_names,
                paths,
                transfer,
                key_animated=True,
            )
        return result.changed

    @staticmethod
    def _is_transform_node(name: str) -> bool:
        """通常transformとjointなどの派生ノードを判定する。"""
        try:
            return cast(bool, cmds.objectType(name, isAType="transform"))
        except (RuntimeError, TypeError):
            return False

    def has_transform_context(self) -> bool:
        """画面の基準ノードでフリーズメニューを表示できるか返す。"""
        return (
            not self._disposed
            and bool(self.node_names)
            and self._is_transform_node(self.node_names[0])
        )

    def _freeze_targets(self, *, translate_only: bool) -> tuple[str, ...]:
        """選択順を保ち、移動指定ではjointを除いた対象を返す。"""
        return tuple(
            name
            for name in self.node_names
            if self._is_transform_node(name)
            and (not translate_only or cmds.nodeType(name) != "joint")
        )

    def can_freeze_translation(self) -> bool:
        """基準ノードがtransform系で、移動をフリーズできる対象があるか返す。"""
        return self.has_transform_context() and bool(
            self._freeze_targets(translate_only=True)
        )

    def freeze_transforms(
        self, component: Literal["translate", "rotate", "scale", "all"]
    ) -> int:
        """選択中のtransform系ノードへMaya標準のフリーズを適用する。"""
        if component not in ("translate", "rotate", "scale", "all"):
            raise ValueError("未対応のフリーズ対象です")
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        self.state_edit_session.finish()
        self._finish_value_edit()
        if not self.has_transform_context():
            return 0
        targets = self._freeze_targets(translate_only=component == "translate")
        if not targets:
            return 0

        # Maya標準と同じ設定で形状・子階層を補正し、一操作のUndoへまとめる
        cmds.makeIdentity(
            *targets,
            apply=True,
            translate=component in ("translate", "all"),
            rotate=component in ("rotate", "all"),
            scale=component in ("scale", "all"),
            normal=0,
        )
        return len(targets)

    def _selected_state_plugs(
        self, keys: Sequence[tuple[str, str]], *, display: bool
    ) -> tuple[list[MayaChannelStatePlug], list[str]]:
        """各行の基準属性の制約を維持して、操作可能な状態編集先を集約する。"""
        plugs: list[MayaChannelStatePlug] = []
        excluded: list[str] = []
        for row in self._selected_rows(keys):
            targets = [
                self._resolve_state_plug(n, row.attribute)
                for n in row.target_names
            ]
            probe = MayaChannelStateBinding(targets, parent=self)
            try:
                state = probe.state
                if not (
                    state.can_set_display if display else state.can_set_locked
                ):
                    excluded.append(
                        f"{row.attribute.nice_name}: 状態を変更できません"
                    )
                    continue
                for plug, target in zip(targets, state.targets, strict=True):
                    if (
                        target.can_set_display
                        if display
                        else target.can_set_locked
                    ):
                        plugs.append(plug)
                    else:
                        reason = (
                            target.display_reason
                            if display
                            else target.lock_reason
                        )
                        excluded.append(f"{target.plug_name}: {reason}")
            finally:
                probe.dispose()
                probe.deleteLater()
        return plugs, excluded

    def set_selected_locked(
        self, keys: Sequence[tuple[str, str]], locked: bool
    ) -> bool:
        """選択属性自身のロックを一括変更し、compound祖先は変更しない。"""
        plugs, excluded = self._selected_state_plugs(keys, display=False)
        if not plugs:
            self._report_excluded(excluded)
            return False
        binding = MayaChannelStateBinding(plugs, parent=self)
        self._active_state_binding = binding
        try:
            changed = binding.set_locked(locked)
        finally:
            self._active_state_binding = None
            binding.dispose()
            binding.deleteLater()
        self._report_excluded(excluded)
        return changed

    def set_selected_display(
        self, keys: Sequence[tuple[str, str]], state: ChannelDisplayState
    ) -> bool:
        """選択属性の表示状態を一括変更し、完了後にフィルターを更新する。"""
        plugs, excluded = self._selected_state_plugs(keys, display=True)
        if not plugs:
            self._report_excluded(excluded)
            return False
        binding = MayaChannelStateBinding(plugs, parent=self)
        self._active_state_binding = binding
        try:
            changed = binding.set_display_state(state)
        finally:
            self._active_state_binding = None
            binding.dispose()
            binding.deleteLater()
        self._report_excluded(excluded)
        return changed

    def _report_excluded(self, reasons: Sequence[str]) -> None:
        """一括操作で除外した属性の理由を、成功対象と区別して表示する。"""
        self.operation_reported.emit(
            "対象外: " + " / ".join(reasons) if reasons else ""
        )

    @staticmethod
    def _dispose_row(row: ChannelRow | ChannelStateRow) -> None:
        """表示モードに対応するBindingの監視とQObjectを解放する。"""
        binding = (
            row.binding if isinstance(row, ChannelRow) else row.state_binding
        )
        binding.dispose()
        binding.deleteLater()

    def dispose(self) -> None:
        """timer、入力Binding、Maya callbackを一度だけ解放する。"""
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        self._dispose_rows()
        self._nodes.dispose()
        self._events.dispose()
        self.state_edit_session.dispose()
        self.value_edit_session.dispose()
