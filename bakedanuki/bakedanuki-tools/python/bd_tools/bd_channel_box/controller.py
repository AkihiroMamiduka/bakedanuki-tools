# coding: utf-8
"""選択ノードと入力行を結び付けるbdChannelBoxの制御。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager, nullcontext
from functools import partial, wraps
from typing import Concatenate, Literal, ParamSpec, TypeAlias, TypeVar, cast

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from bd_util import ModifierManager, Nodes, node_types
from bd_util.maya.node.inspection import (
    ScalarAttributeDisplayFilter,
    ScalarAttributeInfo,
    ScalarAttributeKind,
    ScalarAttributeTypeInfo,
    filter_scalar_attribute_paths,
    inspect_scalar_attributes,
    inspect_scalar_attribute_types,
    matches_scalar_attribute_display_filter,
    selected_node_names,
)
from bd_util.maya.mpx_cmd.round_transform import (
    round_joint_orient,
    round_rotate,
    round_rotate_axis,
    round_translate,
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
    MayaFloatRoundEdit,
    MayaFloatValueEdit,
    MayaIntPlugsBinding,
    MayaIntValueEdit,
    MayaIntOffsetEdit,
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
    connected_plug_edit_reason,
    inspect_plug_input_state,
    read_enum_definition,
    resolve_bool_plug,
    resolve_enum_plug,
    resolve_float_plug,
    resolve_int_plug,
    resolve_string_plug,
    shared_plugs_lifetime,
    shared_scalar_plug_nodes,
)
from bd_util.ui import qt

from . import config
from .custom_filters import CustomFilterSelection

ChannelBinding: TypeAlias = (
    MayaBoolPlugsBinding
    | MayaFloatPlugsBinding
    | MayaIntPlugsBinding
    | MayaEnumPlugsBinding
    | MayaStringPlugsBinding
)
ChannelBoxMode: TypeAlias = Literal["values", "states", "custom_filter_setup"]
ChannelAttributeFilter: TypeAlias = ScalarAttributeDisplayFilter
ChannelDisplayFilter: TypeAlias = (
    ChannelAttributeFilter | CustomFilterSelection
)
RotationDestination: TypeAlias = Literal["rotate", "rotateAxis", "jointOrient"]
RoundTransformKind: TypeAlias = Literal[
    "translate", "rotate", "rotateAxis", "jointOrient"
]
ROTATION_ATTRIBUTE_PATHS = frozenset(
    f"{group}.{group}{axis}"
    for group in ("rotate", "rotateAxis", "jointOrient")
    for axis in ("X", "Y", "Z")
)
_DEFAULT_FILTERS: dict[ChannelBoxMode, ChannelAttributeFilter] = {
    "values": "visible",
    "states": "all",
    "custom_filter_setup": "all",
}
_BULK_NUMERIC_IDLE_MS = 500
_FLOAT_KINDS: tuple[ScalarAttributeKind, ...] = (
    "number",
    "distance",
    "angle",
)
_NUMERIC_KINDS: tuple[ScalarAttributeKind, ...] = _FLOAT_KINDS + (
    "byte",
    "short",
    "long",
)
_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


def _bulk_operation(
    method: Callable[Concatenate[ChannelBoxController, _Params], _Result],
) -> Callable[Concatenate[ChannelBoxController, _Params], _Result]:
    """多数ノードの操作中だけ必要なBindingを保持し、例外時も解放する。"""

    @wraps(method)
    def execute(
        self: ChannelBoxController,
        *args: _Params.args,
        **kwargs: _Params.kwargs,
    ) -> _Result:
        """選択実体を検証した操作境界で元の処理を実行する。"""
        with self._bulk_targets():  # pyright: ignore[reportPrivateUsage]
            return method(self, *args, **kwargs)

    return execute


@dataclass
class _BulkValueCache:
    """数値入力で再利用する対象行と、属性構成だけを監視する寿命。"""

    rows: dict[tuple[str, str], ChannelRow]
    registry: MayaCallbackRegistry
    keys: tuple[tuple[str, str], ...] | None = None
    invalidated: bool = False


__all__ = [
    "ChannelBinding",
    "ChannelBoxMode",
    "ChannelAttributeFilter",
    "ChannelDisplayFilter",
    "RotationDestination",
    "RoundTransformKind",
    "ROTATION_ATTRIBUTE_PATHS",
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
class _ChannelOperationTargets:
    """値Bindingを必要としない操作用の属性、対応ノードと除外理由。"""

    attribute: ScalarAttributeInfo
    target_names: tuple[str, ...]
    excluded: tuple[str, ...]


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
    selection_invalidated = qt.Signal()
    error_occurred = qt.Signal(str)
    operation_reported = qt.Signal(str)
    mode_changed = qt.Signal()
    filter_changed = qt.Signal()
    time_changed = qt.Signal(bool)

    def __init__(self, parent: qt.QObject) -> None:
        """表示用状態と、Windowと同じ寿命の監視を初期化する。"""
        super().__init__(parent)
        self.rows: tuple[ChannelRow | ChannelStateRow, ...] = ()
        self.setup_attributes: tuple[ScalarAttributeInfo, ...] = ()
        self.node_names: tuple[str, ...] = ()
        self.node_ids: tuple[str, ...] = ()
        self._node_handles: tuple[om.MObjectHandle, ...] = ()
        self._node_paths: tuple[om.MDagPath | None, ...] = ()
        self._bulk_rows: dict[tuple[str, str], ChannelRow] | None = None
        self._bulk_value_cache: _BulkValueCache | None = None
        self._bulk_numeric_keys: tuple[tuple[str, str], ...] | None = None
        self._bulk_numeric_generation = 0
        self._bulk_value_edit_reuse = True
        self._retain_bulk_value_targets = False
        self._bulk_value_timer = qt.QTimer(self)
        self._bulk_value_timer.setSingleShot(True)
        self._bulk_value_timer.setInterval(_BULK_NUMERIC_IDLE_MS)
        self._bulk_value_timer.timeout.connect(self._discard_bulk_value_cache)
        self.selection_limit_exceeded = False
        self._mode: ChannelBoxMode = "values"
        self._filters: dict[ChannelBoxMode, ChannelDisplayFilter] = {
            "values": "visible",
            "states": "all",
            "custom_filter_setup": "all",
        }
        self._custom_filter_fallback_node_type: str | None = None
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
        self.value_edit_session.finished.connect(self._on_value_edit_finished)
        self._filter_refresh_pending = False
        self._events = MayaCallbackRegistry(self)
        self._nodes = MayaCallbackRegistry(self)
        self._timer = qt.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_pending)

        # 構成変更は次のQtイベントへまとめ、値の同期はBindingへ委譲する
        try:
            self._events.register(
                om.MEventMessage.addEventCallback(
                    "SelectionChanged", self._on_selection_changed
                )
            )
            for name in ("Undo", "Redo"):
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
    def representative_node_name(self) -> str | None:
        """選択リストの末尾にある表示基準ノードを返す。"""
        return self.node_names[-1] if self.node_names else None

    @property
    def mode(self) -> ChannelBoxMode:
        """値入力・状態設定・共有フィルター設定の表示モードを返す。"""
        return self._mode

    @property
    def _enum_validation(self) -> Literal["per_write", "operation"]:
        """値編集では操作単位、ほかのモードでは従来のenum検証を使う。"""
        return "operation" if self._mode == "values" else "per_write"

    def set_mode(self, mode: ChannelBoxMode) -> None:
        """連続編集を終了し、属性を書き換えずに操作する状態を切り替える。"""
        if mode not in (
            "values",
            "states",
            "custom_filter_setup",
        ):
            raise ValueError("未対応の表示モードです")
        if self._disposed or mode == self._mode:
            return
        self._finish_value_edit()
        self._mode = mode
        self.mode_changed.emit()
        self.filter_changed.emit()
        self.refresh()

    @property
    def attribute_filter(self) -> ChannelDisplayFilter:
        """現在のモードに保持している属性フィルターを返す。"""
        return self._filters[self._mode]

    @property
    def values_attribute_filter(self) -> ChannelDisplayFilter:
        """ほかのモードを表示中でも、値編集用に保持している選択を返す。"""
        return self._filters["values"]

    @property
    def custom_filter_fallback_node_type(self) -> str | None:
        """現在のカスタム定義が未指定の基準ノード型を返す。"""
        return self._custom_filter_fallback_node_type

    def set_attribute_filter(self, value: ChannelDisplayFilter) -> None:
        """連続編集を終了し、sceneを変更せず表示対象を絞り込む。"""
        if self._mode == "custom_filter_setup" and isinstance(
            value, CustomFilterSelection
        ):
            raise ValueError("設定モードでは標準フィルターを指定してください")
        if not isinstance(value, CustomFilterSelection) and value not in (
            "all",
            "visible",
            "keyable",
            "channel_box",
            "hidden",
        ):
            raise ValueError("未対応の属性フィルターです")
        if self._disposed or value == self.attribute_filter:
            return
        self._finish_value_edit()
        self._filters[self._mode] = value
        self.filter_changed.emit()
        self.refresh()

    def clear_custom_filter(self, path: str) -> None:
        """利用不能になったカスタム選択を両モードで既定値へ戻す。"""
        if self._disposed:
            return
        active_changed = False
        for mode, default in _DEFAULT_FILTERS.items():
            selected = self._filters[mode]
            if isinstance(selected, CustomFilterSelection) and (
                selected.path == path
            ):
                self._filters[mode] = default
                active_changed |= mode == self._mode
        if active_changed:
            self._finish_value_edit()
            self.filter_changed.emit()
            self.refresh()

    def replace_custom_filter(
        self,
        selection: CustomFilterSelection,
        *,
        previous_path: str | None = None,
    ) -> None:
        """再読込やファイル改名を両モードの保持選択へ反映する。"""
        if self._disposed:
            return
        source_path = (
            selection.path if previous_path is None else previous_path
        )
        active_changed = False
        for mode in ("values", "states"):
            selected = self._filters[mode]
            if isinstance(selected, CustomFilterSelection) and (
                selected.path == source_path
            ):
                self._filters[mode] = selection
                active_changed |= mode == self._mode
        if active_changed:
            self._finish_value_edit()
            self.filter_changed.emit()
            self.refresh()

    def _finish_value_edit(self) -> None:
        """行を切り替える前に、値の連続編集とUndoのまとまりを閉じる。"""
        self.finish_value_edit()
        for row in self.rows:
            if isinstance(row, ChannelRow) and isinstance(
                row.binding, (MayaFloatPlugsBinding, MayaIntPlugsBinding)
            ):
                row.binding.view_model.end_edit()

    def begin_state_edit(self) -> None:
        """行を固定したまま、複数属性の状態編集を一つのUndoへまとめる。"""
        if self._disposed or self._mode != "states":
            return
        self._finish_value_edit()
        self.state_edit_session.begin()

    def begin_value_edit(self, *, reuse_targets: bool = True) -> None:
        """SliderのUndoを開始し、wheelだけは単発入力用の対象保持を使う。"""
        if type(reuse_targets) is not bool:
            raise TypeError("reuse_targetsにはboolを指定してください")
        if self._disposed or self._mode != "values":
            return
        self.state_edit_session.finish()
        if reuse_targets and not self.value_edit_session.is_editing:
            self._discard_bulk_value_cache()
        self._bulk_value_edit_reuse = reuse_targets
        self.value_edit_session.begin()

    def finish_value_edit(self, *, retain_targets: bool = False) -> None:
        """Undoを閉じ、wheelの正常終了時だけ対象を短時間保持する。"""
        if type(retain_targets) is not bool:
            raise TypeError("retain_targetsにはboolを指定してください")
        self._retain_bulk_value_targets = retain_targets
        try:
            self.value_edit_session.finish()
        finally:
            self._retain_bulk_value_targets = False
        if retain_targets and self._bulk_numeric_keys is not None:
            self._bulk_value_timer.start()
        else:
            self._discard_bulk_value_cache()

    def _on_value_edit_finished(self) -> None:
        """外部中断では、待機対象もUndoと同時に解放する。"""
        if not self._retain_bulk_value_targets:
            self._discard_bulk_value_cache()

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
        self._discard_bulk_value_cache()
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

    def _on_selection_changed(self, *_args: object) -> None:
        """選択が切り替わった時点でノード名の未確定入力を止める。"""
        if self._disposed:
            return
        self.selection_invalidated.emit()
        self._queue_rebuild()

    def _before_scene(self, *_args: object) -> None:
        """scene切替前に古い対象と連続編集中のUndoを解放する。"""
        if self._disposed:
            return
        self.selection_invalidated.emit()
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
        """どのモードでも基準の名前・属性構成だけを常時監視する。"""
        self._nodes.dispose()
        self._nodes.deleteLater()
        self._nodes = MayaCallbackRegistry(self)
        for name in self.node_names[-1:]:
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
            if self._mode == "custom_filter_setup":
                # 型別定義の見本だけを保持し、他ノードの属性・識別情報は取得しない
                names = names[-1:]
            self.selection_limit_exceeded = False
            attributes = tuple(
                inspect_scalar_attributes(n) for n in names[-1:]
            )
            self._dispose_rows()
            self.node_names = names
            self.node_ids = tuple(
                om.MFnDependencyNode(self._node_object(name)).uuid().asString()
                for name in names
            )
            self._node_handles = tuple(
                om.MObjectHandle(self._node_object(name)) for name in names
            )
            self._node_paths = tuple(
                self._selected_dag_path(name) for name in names
            )
            self._watch_nodes()
            self.rows = self._create_rows(attributes, representative_only=True)
        except Exception as error:
            self._dispose_rows()
            self.selection_limit_exceeded = False
            self.error_occurred.emit(str(error))
        self.rows_changed.emit()

    def _create_rows(
        self,
        attributes: tuple[tuple[ScalarAttributeInfo, ...], ...],
        *,
        display_filter: ChannelAttributeFilter | None = None,
        representative_only: bool = False,
        target_types: (
            tuple[tuple[ScalarAttributeTypeInfo, ...], ...] | None
        ) = None,
    ) -> tuple[ChannelRow | ChannelStateRow, ...]:
        """基準の表示情報と、対応先の属性情報またはpath・型から行を作る。"""
        if not attributes:
            return ()
        effective_filter = (
            self.attribute_filter if display_filter is None else display_filter
        )
        matching_attributes: tuple[
            tuple[ScalarAttributeInfo | ScalarAttributeTypeInfo, ...], ...
        ] = (
            attributes
            if target_types is None
            else target_types + attributes[-1:]
        )
        lookup = tuple(
            {a.path: a for a in items} for items in matching_attributes
        )
        base_lookup = {a.path: a for a in attributes[-1]}
        # 基準を先頭にしてBindingへ渡し、選択リスト自体の順序は維持する
        names = (
            self.node_names[-1:] if representative_only else self.node_names
        )
        ordered_names = names[-1:] + names[:-1]
        ordered_lookup = lookup[-1:] + lookup[:-1]
        rows: list[ChannelRow | ChannelStateRow] = []
        try:
            # 構築時に現在の設定を読み、重複は最初の指定だけを採用する
            priorities = {
                path: index
                for index, path in enumerate(
                    dict.fromkeys(config.ATTRIBUTE_PRIORITY_PATHS)
                )
            }
            if self._mode == "custom_filter_setup":
                if isinstance(effective_filter, CustomFilterSelection):
                    raise ValueError(
                        "設定モードでは標準フィルターを使用します"
                    )
                # 基準ノードの対応属性だけを提示し、Maya編集用Bindingを作らない
                self.setup_attributes = tuple(
                    attribute
                    for attribute in sorted(
                        attributes[-1],
                        key=partial(
                            _attribute_display_priority, priorities=priorities
                        ),
                    )
                    if matches_scalar_attribute_display_filter(
                        attribute, effective_filter
                    )
                )
                return ()
            custom_paths: tuple[str, ...] | None = None
            if isinstance(effective_filter, CustomFilterSelection):
                node_type = cast(str, cmds.nodeType(self.node_names[-1]))
                custom_paths = effective_filter.definition.node_types.get(
                    node_type
                )
                if custom_paths is None and display_filter is None:
                    self._custom_filter_fallback_node_type = node_type
            if custom_paths is not None:
                # 定義済みの型は表示状態によらずJSONのpath順を使う
                custom_attributes: list[ScalarAttributeInfo] = []
                seen_paths: set[str] = set()
                for path in custom_paths:
                    attribute = base_lookup.get(path)
                    if attribute is None and path.startswith("."):
                        attribute = base_lookup.get(path[1:])
                    if attribute is None or attribute.path in seen_paths:
                        continue
                    custom_attributes.append(attribute)
                    seen_paths.add(attribute.path)
                ordered_attributes = tuple(custom_attributes)
            else:
                # 組込み条件か、型未定義時の既定条件で既存の優先順を使う
                builtin_filter: ChannelAttributeFilter = (
                    "visible"
                    if isinstance(effective_filter, CustomFilterSelection)
                    else effective_filter
                )
                # 同じ優先度では元の属性順を保ち、行の構築時だけ並べ替える
                ordered_attributes = tuple(
                    attribute
                    for attribute in sorted(
                        attributes[-1],
                        key=partial(
                            _attribute_display_priority, priorities=priorities
                        ),
                    )
                    if matches_scalar_attribute_display_filter(
                        attribute, builtin_filter
                    )
                )
            for attribute in ordered_attributes:
                targets: list[str] = []
                excluded: list[str] = []
                for name, info in zip(ordered_names, ordered_lookup):
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
                rows.append(
                    self._create_value_row(
                        attribute,
                        targets,
                        excluded,
                        monitor=self._mode != "values" or representative_only,
                    )
                )
        except Exception:
            for row in rows:
                self._dispose_row(row)
            raise
        if self._bulk_rows is not None and not representative_only:
            self._bulk_rows.update(
                ((row.attribute.path, row.attribute.kind), row)
                for row in rows
                if isinstance(row, ChannelRow)
            )
        return tuple(rows)

    def _create_value_row(
        self,
        attribute: ScalarAttributeInfo,
        targets: list[str],
        excluded: list[str],
        *,
        monitor: bool = True,
    ) -> ChannelRow:
        """型ごとの既存編集規則を保ち、表示用または操作専用Bindingを作る。"""
        binding: ChannelBinding
        path = attribute.path
        if attribute.kind == "bool":
            binding = MayaBoolPlugsBinding(
                [resolve_bool_plug(n, path) for n in targets],
                parent=self,
                edit_connected=True,
                track_input_state=monitor,
                monitor=monitor,
                monitor_lifetime=self._bulk_value_cache is not None,
            )
        elif attribute.kind in ("byte", "short", "long"):
            binding = MayaIntPlugsBinding(
                [resolve_int_plug(n, path) for n in targets],
                parent=self,
                edit_connected=True,
                track_input_state=monitor,
                monitor=monitor,
                monitor_lifetime=(
                    self._bulk_value_cache is not None
                    or self._bulk_numeric_keys is not None
                ),
            )
        elif attribute.kind == "enum":
            binding = self._create_enum_binding(
                path, targets, excluded, monitor=monitor
            )
        elif attribute.kind == "string":
            binding = MayaStringPlugsBinding(
                [resolve_string_plug(n, path) for n in targets],
                parent=self,
                track_input_state=monitor,
                monitor=monitor,
                monitor_lifetime=self._bulk_value_cache is not None,
            )
        else:
            binding = MayaFloatPlugsBinding(
                [resolve_float_plug(n, path) for n in targets],
                parent=self,
                edit_connected=True,
                track_input_state=monitor,
                monitor=monitor,
                monitor_lifetime=(
                    self._bulk_value_cache is not None
                    or self._bulk_numeric_keys is not None
                ),
            )
        binding.edit_failed.connect(self.error_occurred.emit)
        return ChannelRow(attribute, binding, tuple(excluded), tuple(targets))

    @staticmethod
    def _resolve_state_plug(
        name: str, attribute: ScalarAttributeInfo
    ) -> MayaChannelStatePlug:
        """値やenum定義を比較せず、対応scalarの参照だけを取得する。"""
        if attribute.kind == "bool":
            return resolve_bool_plug(name, attribute.path)
        if attribute.kind == "enum":
            return resolve_enum_plug(name, attribute.path)
        if attribute.kind in ("byte", "short", "long"):
            return resolve_int_plug(name, attribute.path)
        if attribute.kind == "string":
            return resolve_string_plug(name, attribute.path)
        return resolve_float_plug(name, attribute.path)

    def _create_enum_binding(
        self,
        path: str,
        targets: list[str],
        excluded: list[str],
        *,
        monitor: bool = True,
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
            edit_connected=True,
            track_input_state=monitor,
            monitor=monitor,
            monitor_lifetime=self._bulk_value_cache is not None,
        )

    def _dispose_rows(self) -> None:
        """Qtの遅延削除を待たず、すべての入力とMaya監視を終了する。"""
        self._filter_refresh_pending = False
        self._custom_filter_fallback_node_type = None
        self.setup_attributes = ()
        self.rows_about_to_change.emit()
        if self._bulk_rows is not None:
            for row in self._bulk_rows.values():
                self._dispose_row(row)
        if self._active_state_binding is not None:
            self._active_state_binding.dispose()
        self.state_edit_session.finish()
        self.finish_value_edit()
        rows, self.rows = self.rows, ()
        for row in rows:
            self._dispose_row(row)

    @staticmethod
    def _node_object(name: str) -> om.MObject:
        """改名に依存しない選択識別子を取得するためnodeを解決する。"""
        selection = om.MSelectionList()
        selection.add(name)
        return selection.getDependNode(0)

    @staticmethod
    def _selected_dag_path(name: str) -> om.MDagPath | None:
        """DAG instanceの選択pathを改名へ追従する実体参照として保持する。"""
        selection = om.MSelectionList()
        selection.add(name)
        if not selection.getDependNode(0).hasFn(om.MFn.kDagNode):
            return None
        return selection.getDagPath(0)

    def _invalidate_bulk_value_cache(self, *_args: object) -> None:
        """構成変更のcallback内では破棄せず、次の入力で旧対象を拒否する。"""
        if self._bulk_value_cache is not None:
            self._bulk_value_cache.invalidated = True

    def _bulk_value_attribute_changed(
        self, message: int, *_args: object
    ) -> None:
        """値・lock通知は無視し、追加・削除・改名時だけ対象を無効化する。"""
        if message & (
            om.MNodeMessage.kAttributeAdded
            | om.MNodeMessage.kAttributeRemoved
            | om.MNodeMessage.kAttributeRenamed
        ):
            self._invalidate_bulk_value_cache()

    def _start_bulk_value_cache(self) -> _BulkValueCache:
        """現在の選択実体に構成監視を結び、値通知の全件同期を避ける。"""
        cache = _BulkValueCache({}, MayaCallbackRegistry(self))
        self._bulk_value_cache = cache
        try:
            for handle in self._node_handles:
                node = handle.object()
                cache.registry.register(
                    om.MNodeMessage.addAttributeChangedCallback(
                        node, self._bulk_value_attribute_changed
                    )
                )
                cache.registry.register(
                    om.MNodeMessage.addNameChangedCallback(
                        node, self._invalidate_bulk_value_cache
                    )
                )
                cache.registry.register(
                    om.MNodeMessage.addNodePreRemovalCallback(
                        node, self._invalidate_bulk_value_cache
                    )
                )
        except Exception:
            self._discard_bulk_value_cache()
            raise
        return cache

    def _discard_bulk_value_cache(self) -> None:
        """書込み中は終了だけ予約し、復旧が終わってから対象と監視を解放する。"""
        self._bulk_value_timer.stop()
        self._bulk_numeric_keys = None
        self._bulk_numeric_generation += 1
        cache = self._bulk_value_cache
        if cache is None:
            return
        if self._bulk_rows is cache.rows:
            cache.invalidated = True
            return
        self._bulk_value_cache = None
        try:
            for row in cache.rows.values():
                self._dispose_row(row)
        finally:
            cache.registry.dispose()
            cache.registry.deleteLater()

    def _refresh_bulk_node_names(self) -> None:
        """保持した実体から名前を読み直し、祖先改名後も別nodeを解決しない。"""
        names: list[str] = []
        handles: list[om.MObjectHandle] = []
        paths: list[om.MDagPath | None] = []
        for handle, path in zip(
            self._node_handles, self._node_paths, strict=True
        ):
            if not handle.isValid() or not handle.isAlive():
                continue
            node = handle.object()
            name = (
                (
                    path.fullPathName()
                    if path is not None
                    and path.isValid()
                    and path.node() == node
                    else om.MFnDagNode(node).getPath().fullPathName()
                )
                if node.hasFn(om.MFn.kDagNode)
                else om.MFnDependencyNode(node).name()
            )
            names.append(name)
            handles.append(handle)
            paths.append(path)
        self.node_names = tuple(names)
        self._node_handles = tuple(handles)
        self._node_paths = tuple(paths)
        self.node_ids = tuple(
            om.MFnDependencyNode(handle.object()).uuid().asString()
            for handle in handles
        )

    @contextmanager
    def _numeric_targets(
        self,
        keys: Sequence[tuple[str, str]],
        *,
        reuse_value_edit: bool = False,
    ) -> Generator[None, None, None]:
        """数値入力の対象保持を選び、開始失敗でもUndoと旧対象を解放する。"""
        try:
            with self._bulk_targets(
                reuse_value_edit=reuse_value_edit, numeric_keys=keys
            ):
                yield
        except Exception:
            self.finish_value_edit()
            raise

    @contextmanager
    def _bulk_targets(
        self,
        *,
        reuse_value_edit: bool = False,
        numeric_keys: Sequence[tuple[str, str]] | None = None,
    ) -> Generator[None, None, None]:
        """実体を確認し、連続する数値入力だけ対象準備を引き継ぐ。"""
        if self._mode not in ("values", "states"):
            yield
            return
        if self._disposed or self._timer.isActive():
            raise RuntimeError(
                "対象が変わりました。表示更新後に操作してください"
            )
        continuous = (
            reuse_value_edit
            and self.value_edit_session.is_editing
            and self._bulk_value_edit_reuse
        )
        cache = self._bulk_value_cache
        if cache is not None and cache.invalidated:
            self.finish_value_edit()
            if continuous or self._bulk_rows is not None:
                raise RuntimeError(
                    "対象の構成が変わりました。操作し直してください"
                )
            cache = None
        if self._bulk_rows is not None:
            yield
            return
        keys = (
            None
            if numeric_keys is None
            else tuple(dict.fromkeys(numeric_keys))
        )
        if keys is None:
            self.finish_value_edit()
        elif not reuse_value_edit and self.value_edit_session.is_editing:
            # ドラッグから値欄へ移った場合は、前のUndoを必ず先に閉じる
            self.finish_value_edit()
        if keys is not None and self._bulk_numeric_keys not in (None, keys):
            self._discard_bulk_value_cache()
        cache = self._bulk_value_cache
        repeat = keys is not None and keys == self._bulk_numeric_keys
        self._bulk_value_timer.stop()
        if not self._node_handles:
            raise RuntimeError("操作するノードが選択されていません")
        if (
            not self._node_handles[-1].isValid()
            or not self._node_handles[-1].isAlive()
        ):
            raise RuntimeError("基準ノードが削除されました")

        # 単発入力は保持せず、二回目またはドラッグで構成監視を開始する
        if cache is None:
            self._refresh_bulk_node_names()
            if continuous or repeat:
                cache = self._start_bulk_value_cache()
        temporary = {} if cache is None else cache.rows
        self._bulk_rows = temporary
        # 保持しない最初の入力にも、書込み中の削除履歴の監視を付ける
        if keys and not continuous:
            self._bulk_numeric_keys = keys
        generation = self._bulk_numeric_generation
        failed = True
        try:
            yield
            failed = False
        finally:
            self._bulk_rows = None
            if cache is None:
                for row in temporary.values():
                    self._dispose_row(row)
            interrupted = (
                failed
                or self._disposed
                or generation != self._bulk_numeric_generation
                or (cache is not None and cache.invalidated)
                or (continuous and not self.value_edit_session.is_editing)
            )
            if interrupted:
                self.finish_value_edit()
            elif keys and not continuous:
                self._bulk_numeric_keys = keys
                if not self.value_edit_session.is_editing:
                    self._bulk_value_timer.start()
            if not self._disposed:
                for row in self.rows:
                    if (
                        isinstance(row, ChannelRow)
                        and (row.attribute.path, row.attribute.kind)
                        in temporary
                    ):
                        row.binding.refresh()

    def _resolve_bulk_rows(
        self, rows: Sequence[ChannelRow | ChannelStateRow]
    ) -> tuple[ChannelRow, ...]:
        """必要なpathだけを照合し、値の表示同期を省くBindingへ結ぶ。"""
        cache = self._bulk_rows
        if cache is None:
            raise RuntimeError("値編集の操作境界が開始されていません")
        gesture = self._bulk_value_cache
        if gesture is not None and gesture.rows is cache:
            keys = tuple((r.attribute.path, r.attribute.kind) for r in rows)
            if gesture.keys is not None and gesture.keys != keys:
                self._refresh_bulk_node_names()
                for previous in cache.values():
                    self._dispose_row(previous)
                cache.clear()
            gesture.keys = keys
        missing = tuple(
            row
            for row in rows
            if (row.attribute.path, row.attribute.kind) not in cache
        )
        if not missing:
            return tuple(
                cache[(r.attribute.path, r.attribute.kind)] for r in rows
            )
        # 構築中のnode解決と削除通知を共有し、各Bindingの検証・復旧寿命は保つ
        with shared_scalar_plug_nodes(), shared_plugs_lifetime():
            for targets in self._resolve_bulk_targets(missing):
                attribute = targets.attribute
                key = (attribute.path, attribute.kind)
                cache[key] = self._create_value_row(
                    attribute,
                    list(targets.target_names),
                    list(targets.excluded),
                    monitor=False,
                )
        return tuple(cache[(r.attribute.path, r.attribute.kind)] for r in rows)

    def _resolve_bulk_targets(
        self, rows: Sequence[ChannelRow | ChannelStateRow]
    ) -> tuple[_ChannelOperationTargets, ...]:
        """正式pathと型・単位を照合し、値の読取りや監視なしで対象名を返す。"""
        if self._bulk_rows is None:
            raise RuntimeError("値編集の操作境界が開始されていません")
        paths = tuple(row.attribute.path for row in rows)
        ordered_names = self.node_names[-1:] + self.node_names[:-1]
        lookup = (
            tuple(
                {
                    a.path: a
                    for a in inspect_scalar_attribute_types(name, paths=paths)
                }
                for name in ordered_names
            )
            if rows
            else ()
        )
        result: list[_ChannelOperationTargets] = []
        for row in rows:
            attribute = row.attribute
            targets: list[str] = []
            excluded: list[str] = []
            for name, attributes in zip(ordered_names, lookup, strict=True):
                match = attributes.get(attribute.path)
                if match is None:
                    excluded.append(f"{name}: 対応する属性なし")
                elif match.kind != attribute.kind:
                    excluded.append(f"{name}: 型・単位が異なる")
                else:
                    targets.append(name)
            if not targets or targets[0] != ordered_names[0]:
                raise RuntimeError("基準属性の構成が変わりました")
            result.append(
                _ChannelOperationTargets(
                    attribute, tuple(targets), tuple(excluded)
                )
            )
        return tuple(result)

    def _selected_operation_targets(
        self,
        keys: Sequence[tuple[str, str]],
        *,
        values_only: bool = False,
    ) -> tuple[_ChannelOperationTargets, ...]:
        """表示中のキーを検証し、操作に必要な対象名だけを準備する。"""
        rows = self._selected_rows(keys, resolve_targets=False)
        if values_only:
            rows = tuple(row for row in rows if isinstance(row, ChannelRow))
        if self._mode in ("values", "states"):
            return self._resolve_bulk_targets(rows)
        return tuple(
            _ChannelOperationTargets(
                row.attribute, row.target_names, row.excluded
            )
            for row in rows
        )

    def _selected_rows(
        self, keys: Sequence[tuple[str, str]], *, resolve_targets: bool = True
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
        rows = tuple(lookup[key] for key in unique)
        if self._mode == "values" and resolve_targets:
            return self._resolve_bulk_rows(rows)
        return rows

    def _selected_value_rows(
        self,
        keys: Sequence[tuple[str, str]],
        kinds: Sequence[ScalarAttributeKind],
    ) -> tuple[ChannelRow | ChannelStateRow, ...]:
        """全キーを検証し、操作対象の型だけを多数ノードの値Bindingへ結ぶ。"""
        rows = self._selected_rows(keys, resolve_targets=False)
        if self._mode != "values":
            return rows
        selected = tuple(row for row in rows if row.attribute.kind in kinds)
        resolved = {
            (row.attribute.path, row.attribute.kind): row
            for row in self._resolve_bulk_rows(selected)
        }
        # 非対応型は代表行のまま返し、既存の行単位の除外理由を報告する
        return tuple(
            resolved.get((row.attribute.path, row.attribute.kind), row)
            for row in rows
        )

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
        if plug.isDestination and connected_plug_edit_reason(plug) is not None:
            return None
        return plug.name()

    @_bulk_operation
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

    @_bulk_operation
    def set_keyframes_selected(
        self, keys: Sequence[tuple[str, str]], *, breakdown: bool = False
    ) -> int:
        """表示中の選択行に対応する全ノードへ指定種別のキーを打つ。"""
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets: list[str] = []
        for row in self._selected_operation_targets(keys, values_only=True):
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

    @_bulk_operation
    def edit_animation_layers_selected(
        self, keys: Sequence[tuple[str, str]], *, add: bool
    ) -> int:
        """選択行と同じ正式path・型の各ノード属性を選択レイヤで変更する。"""
        targets = tuple(
            f"{node}.{row.attribute.path}"
            for row in self._selected_operation_targets(keys)
            if row.attribute.kind != "string"
            for node in row.target_names
        )
        return self._edit_animation_layer_membership(targets, add=add)

    @_bulk_operation
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

    @_bulk_operation
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

    @_bulk_operation
    def set_muted_selected(
        self, keys: Sequence[tuple[str, str]], *, muted: bool
    ) -> int:
        """選択行と対応する全ノードの属性を表示状態に関係なくミュートする。"""
        self.state_edit_session.finish()
        self._finish_value_edit()
        targets: list[str] = []
        for row in self._selected_operation_targets(keys, values_only=True):
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
        copied_node_indices = {curve.node_index for curve in copied}
        source_indices = tuple(
            index
            for index in range(len(self.node_names))
            if index in copied_node_indices
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

    @_bulk_operation
    def copy_animation_curves_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """選択行と対応する各選択ノードの全時間の曲線をコピーする。"""
        # Maya標準clipboardへも、Bindingの代表順ではなく元の選択順で渡す
        sources: list[_AnimationCurveSource] = []
        for row in self._selected_operation_targets(keys, values_only=True):
            target_names = set(row.target_names)
            sources.extend(
                _AnimationCurveSource(
                    index, row.attribute.path, row.attribute.kind
                )
                for index, node in enumerate(self.node_names)
                if node in target_names
            )
        return len(self._copy_animation_curves(sources))

    @_bulk_operation
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

    @_bulk_operation
    def cut_animation_curves_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """選択行と同じ正式pathの全選択ノードの曲線をカットする。"""
        selected_paths = {
            row.attribute.path
            for row in self._selected_rows(keys, resolve_targets=False)
            if isinstance(row, ChannelRow)
        }
        sources = tuple(
            _AnimationCurveSource(index, info.path, info.kind)
            for index, node in enumerate(self.node_names)
            for info in self._inspect_selected_curve_attributes(
                node, selected_paths
            )
        )
        return self._cut_animation_curves(sources)

    @_bulk_operation
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

    @staticmethod
    def _inspect_selected_curve_attributes(
        node: str, selected_paths: set[str]
    ) -> tuple[ScalarAttributeInfo, ...]:
        """一属性なら限定取得し、複数属性は従来のnode内属性順を維持する。"""
        if len(selected_paths) == 1:
            try:
                attributes = inspect_scalar_attributes(
                    node, paths=tuple(selected_paths)
                )
            except ValueError:
                # 曖昧なleaf名は従来の全列挙と正式path比較へ戻す
                attributes = inspect_scalar_attributes(node)
        else:
            attributes = inspect_scalar_attributes(node)
        return tuple(
            info for info in attributes if info.path in selected_paths
        )

    @_bulk_operation
    def delete_animation_curves_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """選択行と同じ正式pathの全選択ノードの曲線を削除する。"""
        selected_paths = {
            row.attribute.path
            for row in self._selected_rows(keys, resolve_targets=False)
            if isinstance(row, ChannelRow)
        }
        names = tuple(
            f"{node}.{info.path}"
            for node in self.node_names
            for info in self._inspect_selected_curve_attributes(
                node, selected_paths
            )
        )
        return self._delete_animation_curves(names)

    @_bulk_operation
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
        selected_rows = (
            self._selected_rows(keys, resolve_targets=False)
            if keys is not None
            else None
        )
        selected_paths = (
            tuple(
                row.attribute.path
                for row in selected_rows
                if isinstance(row, ChannelRow)
            )
            if selected_rows is not None
            else None
        )
        # 元の曲線順を保って分類し、各nodeで全曲線を探索し直さない
        curves_by_node: dict[int, list[_CopiedAnimationCurve]] = {}
        for curve in copied.curves:
            curves_by_node.setdefault(curve.node_index, []).append(curve)
        targets: list[tuple[int, str]] = []
        for destination_index, node in enumerate(self.node_names):
            source_index = 0 if copied.node_count == 1 else destination_index
            source_curves = curves_by_node.get(source_index, ())
            candidate_paths = (
                selected_paths
                if selected_paths is not None
                else tuple(
                    dict.fromkeys(curve.path for curve in source_curves)
                )
            )
            # 行の値編集対象から外れた異種型ノードも、曲線操作では個別に調べる
            try:
                attributes = inspect_scalar_attributes(
                    node, paths=candidate_paths
                )
            except ValueError:
                # 曖昧なleaf名は旧来の正式path比較で対象外として扱う
                attributes = inspect_scalar_attributes(node)
            available_paths = {info.path for info in attributes}
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

    @_bulk_operation
    def paste_animation_curves_same_attributes(self) -> int:
        """コピー元と同じ正式属性パスへ曲線を貼り付ける。"""
        return self._paste_animation_curves(None)

    @_bulk_operation
    def paste_animation_curves_to_selected(
        self, keys: Sequence[tuple[str, str]]
    ) -> int:
        """一曲線は型を問わず選択属性へ、複数曲線は同じパスへ貼る。"""
        return self._paste_animation_curves(keys)

    def apply_numeric_values(
        self, keys: Sequence[tuple[str, str]], display_value: float | int
    ) -> bool:
        """明示入力を選択中のfloat・整数行へ型を保って一括適用する。"""
        with self._numeric_targets(keys, reuse_value_edit=True):
            return self._apply_numeric_values(keys, display_value)

    def _apply_numeric_values(
        self, keys: Sequence[tuple[str, str]], display_value: float | int
    ) -> bool:
        """検証済みの数値行へ、毎回新しい書込み計画で絶対値を適用する。"""
        rows = self._selected_value_rows(keys, _NUMERIC_KINDS)
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        # 行単位の対象選別を保ち、全行の検証と書込みはutilへ委譲する
        for row in rows:
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, (MayaFloatPlugsBinding, MayaIntPlugsBinding)
            ):
                excluded.append(f"{row.attribute.nice_name}: 数値入力の対象外")
                continue
            if not self._prepare_numeric_input(row.binding):
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            if isinstance(row.binding, MayaIntPlugsBinding):
                if (
                    type(display_value) is float
                    and not display_value.is_integer()
                ):
                    raise ValueError("整数属性には整数値を入力してください")
                edits.append(MayaIntValueEdit(row.binding, int(display_value)))
            else:
                edits.append(
                    MayaFloatValueEdit(
                        row.binding,
                        row.binding.store.presentation.from_display(
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
        self, keys: Sequence[tuple[str, str]], display_offset: float | int
    ) -> bool:
        """各float・整数の現在値へ、型に合う同じ増減量を加える。"""
        with self._numeric_targets(keys):
            return self._offset_numeric_values(keys, display_offset)

    def _offset_numeric_values(
        self, keys: Sequence[tuple[str, str]], display_offset: float | int
    ) -> bool:
        """対象だけを再利用し、差分と復旧値は各入力の現在値から作る。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_value_rows(keys, _NUMERIC_KINDS):
            if not isinstance(row, ChannelRow) or not isinstance(
                row.binding, (MayaFloatPlugsBinding, MayaIntPlugsBinding)
            ):
                excluded.append(f"{row.attribute.nice_name}: 数値操作の対象外")
                continue
            if not self._prepare_numeric_input(row.binding):
                excluded.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            if isinstance(row.binding, MayaIntPlugsBinding):
                if (
                    type(display_offset) is float
                    and not display_offset.is_integer()
                ):
                    raise ValueError(
                        "整数属性には整数の増減量を指定してください"
                    )
                edits.append(
                    MayaIntOffsetEdit(row.binding, int(display_offset))
                )
            else:
                edits.append(
                    MayaFloatOffsetEdit(
                        row.binding,
                        row.binding.store.presentation.from_display(
                            display_offset
                        ),
                    )
                )
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def _prepare_numeric_input(
        self, binding: MayaFloatPlugsBinding | MayaIntPlugsBinding
    ) -> bool:
        """一時Bindingは代表だけを確認し、全体同期を適用後へ集約する。"""
        if not binding.view_model.is_disposed and binding.store.is_writable:
            return True
        # 全行が対象外でも最新の除外理由を報告できるよう同期する
        binding.refresh()
        return False

    @_bulk_operation
    def apply_bool_values(
        self, keys: Sequence[tuple[str, str]], value: bool
    ) -> bool:
        """選択中のbool属性だけを同じONまたはOFFへ一括適用する。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_value_rows(keys, ("bool",)):
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

    @_bulk_operation
    def apply_enum_values(
        self,
        keys: Sequence[tuple[str, str]],
        source_key: tuple[str, str],
        value: int,
    ) -> bool:
        """操作元と定義が一致する選択enum属性へ同じ項目を一括適用する。"""
        rows = self._selected_value_rows(keys, ("enum",))
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
        changed = apply_plugs_values(
            edits, enum_validation=self._enum_validation
        )
        self._report_excluded(excluded)
        return changed

    @_bulk_operation
    def apply_string_values(
        self, keys: Sequence[tuple[str, str]], value: str
    ) -> bool:
        """選択中のstring属性へ同じ文字列を一回のUndoで適用する。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_value_rows(keys, ("string",)):
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

    @_bulk_operation
    def align_selected_values(self, keys: Sequence[tuple[str, str]]) -> bool:
        """各選択行を表示ノードの未丸め値へ、一操作で揃える。"""
        rows = tuple(
            row
            for row in self._selected_rows(keys)
            if isinstance(row, ChannelRow)
        )
        return self._align_rows(rows)

    @_bulk_operation
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
        rows, _ = self._create_filtered_rows(display_filter)
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
            elif isinstance(binding, MayaIntPlugsBinding):
                edits.append(MayaIntValueEdit(binding, binding.value))
            elif isinstance(binding, MayaStringPlugsBinding):
                edits.append(MayaStringValueEdit(binding, binding.value))
            else:
                edits.append(MayaFloatValueEdit(binding, binding.value))
        changed = apply_plugs_values(
            edits, enum_validation=self._enum_validation
        )
        self._report_excluded(excluded)
        return changed

    @_bulk_operation
    def round_selected_values(
        self, keys: Sequence[tuple[str, str]], decimals: int
    ) -> bool:
        """表示中の選択float属性を各ノードの現在値から個別に丸める。"""
        rows = tuple(
            row
            for row in self._selected_value_rows(keys, _FLOAT_KINDS)
            if isinstance(row, ChannelRow)
        )
        return self._round_rows(rows, decimals)

    @_bulk_operation
    def round_filtered_values(
        self, display_filter: ChannelAttributeFilter, decimals: int
    ) -> bool:
        """表示ノードの属性状態で選んだ全float属性を個別に丸める。"""
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
        self.state_edit_session.finish()
        self._finish_value_edit()
        rows, excluded = self._create_filtered_rows(
            display_filter, kinds=_FLOAT_KINDS
        )
        try:
            return self._round_rows(
                tuple(row for row in rows if isinstance(row, ChannelRow)),
                decimals,
                excluded=tuple(
                    f"{attribute.nice_name}: 丸め操作の対象外"
                    for attribute in excluded
                ),
            )
        finally:
            for row in rows:
                self._dispose_row(row)

    def _create_filtered_rows(
        self,
        display_filter: ChannelAttributeFilter,
        *,
        kinds: Sequence[ScalarAttributeKind] | None = None,
    ) -> tuple[
        tuple[ChannelRow | ChannelStateRow, ...],
        tuple[ScalarAttributeInfo, ...],
    ]:
        """基準の表示条件で選び、対応先はpathと型だけを取得して行を作る。"""
        base = tuple(
            a
            for a in inspect_scalar_attributes(self.node_names[-1])
            if matches_scalar_attribute_display_filter(a, display_filter)
        )
        excluded = tuple(
            attribute
            for attribute in base
            if kinds is not None and attribute.kind not in kinds
        )
        selected = tuple(
            attribute
            for attribute in base
            if kinds is None or attribute.kind in kinds
        )
        paths = tuple(a.path for a in selected)
        target_types = (
            tuple(
                inspect_scalar_attribute_types(name, paths=paths)
                for name in self.node_names[:-1]
            )
            if selected
            else ()
        )
        # 多数ノードの複数行を構築する間だけ共有し、値の適用前に解放する
        with (
            shared_scalar_plug_nodes()
            if self._mode == "values" and len(selected) > 1
            else nullcontext()
        ):
            rows = self._create_rows(
                (selected,),
                display_filter=display_filter,
                target_types=target_types,
            )
        return rows, excluded

    def _round_rows(
        self,
        rows: Sequence[ChannelRow],
        decimals: int,
        *,
        excluded: Sequence[str] = (),
    ) -> bool:
        """各plugの未丸め実値から一括計画を作り、単一Undoで適用する。"""
        if type(decimals) is not int:
            raise TypeError("decimalsにはintを指定してください")
        if not 0 <= decimals <= 15:
            raise ValueError("decimalsは0から15の範囲で指定してください")
        self.state_edit_session.finish()
        self._finish_value_edit()
        edits: list[MayaPlugsValueEdit] = []
        reasons = list(excluded)
        for row in rows:
            binding = row.binding
            if not isinstance(binding, MayaFloatPlugsBinding):
                reasons.append(f"{row.attribute.nice_name}: 丸め操作の対象外")
                continue
            binding.refresh()
            if not binding.view_model.set_value_command.can_execute:
                reasons.append(
                    f"{row.attribute.nice_name}: 値を編集できません"
                )
                continue
            edits.append(MayaFloatRoundEdit(binding, decimals))
        changed = apply_plugs_values(edits)
        self._report_excluded(reasons)
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

    @_bulk_operation
    def copy_all_values(self) -> int:
        """基準nodeの全対応属性値を、型と正式path付きでOSへコピーする。"""
        representative = self.representative_node_name
        if representative is None:
            raise RuntimeError("コピー元のノードが選択されていません")
        snapshot = capture_all_scalar_node_values(representative)
        self._value_clipboard.write(MayaScalarValueTransfer((snapshot,)))
        count = len(snapshot.values)
        self.operation_reported.emit(
            f"基準ノードから全{count}属性の値をコピーしました"
        )
        return count

    @_bulk_operation
    def copy_selected_values(self, keys: Sequence[tuple[str, str]]) -> int:
        """基準nodeで選択した対応属性値を、正式path付きでOSへコピーする。"""
        representative = self.representative_node_name
        if representative is None:
            raise RuntimeError("コピー元のノードが選択されていません")
        attributes = tuple(
            row.attribute
            for row in self._selected_rows(keys, resolve_targets=False)
            if isinstance(row, ChannelRow)
        )
        if not attributes:
            raise ValueError("コピー元の値属性を選択してください")
        snapshot = capture_scalar_node_values(representative, attributes)
        self._value_clipboard.write(MayaScalarValueTransfer((snapshot,)))
        count = len(snapshot.values)
        self.operation_reported.emit(
            f"基準ノードから選択した{count}属性の値をコピーしました"
        )
        return count

    @_bulk_operation
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
                self.node_names,
                transfer,
                edit_connected=True,
                enum_validation=self._enum_validation,
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
            edit_connected=True,
            enum_validation=self._enum_validation,
        ).changed

    def _paste_paths_for_display_filter(
        self,
        transfer: MayaScalarValueTransfer,
        display_filter: ChannelAttributeFilter,
    ) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
        """基準nodeの表示状態からPaste対象pathと正常な除外件数を求める。"""
        if len(transfer.nodes) != 1:
            raise ValueError("現在は一つのコピー元nodeだけ貼り付けられます")
        base_name = self.representative_node_name
        if base_name is None:
            raise RuntimeError("貼り付け先のノードが選択されていません")
        attributes = inspect_scalar_attributes(base_name)
        by_path = {attribute.path: attribute for attribute in attributes}
        matched_paths = set(
            filter_scalar_attribute_paths(attributes, display_filter)
        )
        paths: list[str] = []
        filtered_count = 0
        excluded: list[str] = []

        # コピー項目順を維持し、基準nodeにないpathは他のnodeへ適用しない
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

    @_bulk_operation
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
            for row in self._selected_rows(keys, resolve_targets=False)
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
                edit_connected=True,
                enum_validation=self._enum_validation,
            )
        else:
            result = apply_scalar_value_transfer_to_paths(
                self.node_names,
                paths,
                transfer,
                edit_connected=True,
                enum_validation=self._enum_validation,
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
        representative = self.representative_node_name
        return (
            not self._disposed
            and representative is not None
            and self._is_transform_node(representative)
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
        return self.has_transform_context() and any(
            self._is_transform_node(name) and cmds.nodeType(name) != "joint"
            for name in self.node_names
        )

    def can_consolidate_rotation(self) -> bool:
        """基準ノードが回転の集約に対応するか返す。"""
        return self.has_transform_context()

    def can_set_rotation_preserving_pose(self) -> bool:
        """基準ノードが姿勢維持付き回転設定の対象か返す。"""
        representative = self.representative_node_name
        return (
            self._mode == "values"
            and self.has_transform_context()
            and representative is not None
            and cmds.nodeType(representative) in ("transform", "joint")
        )

    def can_set_child_compensated_value(self) -> bool:
        """基準ノードが子の補償付き移動・回転設定の対象か返す。"""
        return self.can_set_rotation_preserving_pose()

    @_bulk_operation
    def round_transform_xyz(
        self,
        kind: RoundTransformKind,
        decimals: int,
        *,
        compensate_child_translate: bool = False,
        joint_child_compensation_attr: Literal[
            "rotate", "jointOrient"
        ] = "rotate",
    ) -> int:
        """選択ノードの指定XYZを子補償付きで表示単位の桁数へ丸める。

        対応するノードを一度のMaya Undoで処理し、対象外の選択を報告する。

        Args:
            kind: 丸める属性群。`jointOrient`はJointだけを対象とする。
            decimals: 小数点以下の桁数。0～15を指定する。
            compensate_child_translate: 回転時に子のworld位置も保持するか。
            joint_child_compensation_attr: 子Jointの姿勢補償先。

        Returns:
            値を変更したノード数。対象外や変更なしなら0。
        """
        if kind not in ("translate", "rotate", "rotateAxis", "jointOrient"):
            raise ValueError("未対応の丸め対象です")
        if type(decimals) is not int:
            raise TypeError("decimalsにはintを指定してください")
        if not 0 <= decimals <= 15:
            raise ValueError("decimalsは0から15の範囲で指定してください")
        if kind == "translate" and compensate_child_translate:
            raise ValueError("移動の丸めでは子の移動補償は常に有効です")
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        if self._mode != "values":
            raise RuntimeError("値編集モードで操作してください")
        self.state_edit_session.finish()
        self._finish_value_edit()
        if not self.has_transform_context():
            return 0

        # 混合選択ではプラグインが扱える型だけを渡し、対象外を個別に報告する
        targets: list[str] = []
        excluded: list[str] = []
        for name in dict.fromkeys(self.node_names):
            node_type = cmds.nodeType(name)
            if node_type not in ("transform", "joint"):
                excluded.append(f"{name}: Transform／Jointではありません")
            elif kind == "jointOrient" and node_type != "joint":
                excluded.append(
                    f"{name}: jointOrientを持つJointではありません"
                )
            else:
                targets.append(name)
        if not targets:
            self._report_excluded(excluded)
            return 0

        if kind == "translate":
            changed = round_translate(
                targets,
                decimals,
                rounding_unit="display",
                compensate_children=True,
            )
        else:
            round_command = {
                "rotate": round_rotate,
                "rotateAxis": round_rotate_axis,
                "jointOrient": round_joint_orient,
            }[kind]
            changed = round_command(
                targets,
                decimals,
                rounding_unit="display",
                compensate_children=True,
                compensate_child_translate=compensate_child_translate,
                joint_child_compensation_attr=joint_child_compensation_attr,
            )
        self._report_excluded(excluded)
        return len(changed)

    @_bulk_operation
    def consolidate_rotation(self, destination: RotationDestination) -> int:
        """選択中の各Transform／Jointの現在回転を一属性群へ集約する。"""
        if destination not in ("rotate", "rotateAxis", "jointOrient"):
            raise ValueError("未対応の回転集約先です")
        if self._disposed:
            raise RuntimeError("終了済みの画面には入力できません")
        if self._mode != "values":
            raise RuntimeError("値編集モードで操作してください")
        self.state_edit_session.finish()
        self._finish_value_edit()
        if not self.can_consolidate_rotation():
            return 0

        bd_nodes = Nodes(modifier_manager=ModifierManager())
        plans: list[
            tuple[
                str,
                str,
                tuple[float, float, float],
                tuple[float, float, float],
            ]
        ] = []
        excluded: list[str] = []
        for name in dict.fromkeys(self.node_names):
            operator = bd_nodes.existing(name)
            if not isinstance(operator, node_types.Transform):
                continue
            if destination == "jointOrient" and not isinstance(
                operator, node_types.Joint
            ):
                excluded.append(
                    f"{name}: jointOrientを持つJointではありません"
                )
                continue
            try:
                rotation = operator.consolidated_rotation_values(destination)
            except RuntimeError as error:
                excluded.append(f"{name}: {error}")
                continue
            groups = (
                ("rotate", "rotateAxis", "jointOrient")
                if isinstance(operator, node_types.Joint)
                else ("rotate", "rotateAxis")
            )
            current = {
                group: tuple(getattr(operator, group).get())
                for group in groups
            }
            if all(
                current[group] == (0.0, 0.0, 0.0)
                for group in groups
                if group != destination
            ):
                continue
            for group in groups:
                desired = rotation if group == destination else (0.0, 0.0, 0.0)
                if current[group] != desired:
                    plans.append((name, group, desired, current[group]))
        if not plans:
            self._report_excluded(excluded)
            return 0

        # NodeOperatorと同じ集約値をMaya標準のUndoへ一操作で記録する
        written: list[tuple[str, str, tuple[float, float, float]]] = []
        undo_enabled = bool(cmds.undoInfo(query=True, state=True))
        cmds.undoInfo(openChunk=True, chunkName="ConsolidateRotation")
        try:
            for name, group, values, before in plans:
                display_values = tuple(
                    om.MAngle(value, om.MAngle.kDegrees).asUnits(
                        om.MAngle.uiUnit()
                    )
                    for value in values
                )
                cmds.setAttr(
                    f"{name}.{group}", *display_values, type="double3"
                )
                written.append((name, group, before))
        except Exception as error:
            cmds.undoInfo(closeChunk=True)
            if written:
                try:
                    if undo_enabled:
                        cmds.undo()
                    else:
                        for name, group, before in reversed(written):
                            restore = tuple(
                                om.MAngle(value, om.MAngle.kDegrees).asUnits(
                                    om.MAngle.uiUnit()
                                )
                                for value in before
                            )
                            cmds.setAttr(
                                f"{name}.{group}", *restore, type="double3"
                            )
                except Exception as restore_error:
                    error.add_note(f"回転値の復旧にも失敗: {restore_error}")
            raise
        else:
            cmds.undoInfo(closeChunk=True)
        self._report_excluded(excluded)
        return len({name for name, _, _, _ in plans})

    @_bulk_operation
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
        for row in self._selected_operation_targets(keys):
            excluded.extend(row.excluded)
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

    @_bulk_operation
    def set_selected_locked(
        self,
        keys: Sequence[tuple[str, str]],
        locked: bool,
        *,
        edit_session: MayaEditSession | None = None,
    ) -> bool:
        """選択属性自身のロックを一括変更し、compound祖先は変更しない。"""
        plugs, excluded = self._selected_state_plugs(keys, display=False)
        if not plugs:
            self._report_excluded(excluded, candidates=0)
            return False
        binding = MayaChannelStateBinding(plugs, parent=self)
        self._active_state_binding = binding
        try:
            changed = binding.set_locked(locked, edit_session=edit_session)
        finally:
            self._active_state_binding = None
            binding.dispose()
            binding.deleteLater()
        self._report_excluded(excluded, candidates=len(plugs))
        return changed

    @_bulk_operation
    def set_selected_display(
        self,
        keys: Sequence[tuple[str, str]],
        state: ChannelDisplayState,
        *,
        edit_session: MayaEditSession | None = None,
    ) -> bool:
        """選択属性の表示状態を一括変更し、完了後にフィルターを更新する。"""
        plugs, excluded = self._selected_state_plugs(keys, display=True)
        if not plugs:
            self._report_excluded(excluded, candidates=0)
            return False
        binding = MayaChannelStateBinding(plugs, parent=self)
        self._active_state_binding = binding
        try:
            changed = binding.set_display_state(
                state, edit_session=edit_session
            )
        finally:
            self._active_state_binding = None
            binding.dispose()
            binding.deleteLater()
        self._report_excluded(excluded, candidates=len(plugs))
        return changed

    def _report_bulk_operation(
        self, reasons: Sequence[str], candidates: int
    ) -> None:
        """一括操作自身の候補件数と、重複を除いた除外理由を表示する。"""
        unique = tuple(dict.fromkeys(reasons))
        report = f"適用候補: {candidates}属性 / 対象外: {len(unique)}件"
        if unique:
            report += " / " + " / ".join(unique[:20])
            if len(unique) > 20:
                report += f" / ほか{len(unique) - 20}件"
        self.operation_reported.emit(report)

    def _report_excluded(
        self, reasons: Sequence[str], *, candidates: int | None = None
    ) -> None:
        """一括操作で除外した属性の理由を、成功対象と区別して表示する。"""
        if self._mode in ("values", "states") and candidates is not None:
            self._report_bulk_operation(reasons, candidates)
            return
        if self._bulk_rows is not None:
            details = list(reasons)
            candidates = 0
            for row in self._bulk_rows.values():
                details.extend(row.excluded)
                for target in row.binding.target_states:
                    candidates += int(target.is_writable)
                    if target.reason:
                        details.append(f"{target.name}: {target.reason}")
            self._report_bulk_operation(details, candidates)
            return
        self.operation_reported.emit(
            "対象外: " + " / ".join(reasons) if reasons else ""
        )

    @staticmethod
    def _dispose_row(row: ChannelRow | ChannelStateRow) -> None:
        """表示モードに対応するBindingの監視とQObjectを解放する。"""
        binding = (
            row.binding if isinstance(row, ChannelRow) else row.state_binding
        )
        if qt.isValid(binding):
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
