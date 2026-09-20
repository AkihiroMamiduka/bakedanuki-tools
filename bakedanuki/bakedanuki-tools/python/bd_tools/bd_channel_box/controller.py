# coding: utf-8
"""選択ノードと入力行を結び付けるbdChannelBoxの制御。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from functools import partial
from typing import Literal, TypeAlias

from maya.api import OpenMaya as om

from bd_util.maya.node.inspection import (
    ScalarAttributeInfo,
    inspect_scalar_attributes,
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
    apply_scalar_value_transfer,
    apply_plugs_values,
    capture_scalar_node_values,
    read_enum_definition,
    resolve_bool_plug,
    resolve_enum_plug,
    resolve_float_plug,
)
from bd_util.ui import qt

from . import config

ChannelBinding: TypeAlias = (
    MayaBoolPlugsBinding | MayaFloatPlugsBinding | MayaEnumPlugsBinding
)
ChannelBoxMode: TypeAlias = Literal["values", "states"]
ChannelAttributeFilter: TypeAlias = Literal[
    "all", "visible", "keyable", "channel_box", "hidden"
]

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


class ChannelBoxController(qt.QObject):
    """選択・属性構成の変更時だけ入力行を組み直す。"""

    rows_changed = qt.Signal()
    rows_about_to_change = qt.Signal()
    error_occurred = qt.Signal(str)
    operation_reported = qt.Signal(str)
    mode_changed = qt.Signal()
    filter_changed = qt.Signal()

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
        self._active_state_binding: MayaChannelStateBinding | None = None
        self.state_edit_session = MayaEditSession(
            self, chunk_name="SweepChannelStates"
        )
        self.value_edit_session = MayaEditSession(
            self, chunk_name="EditSelectedAttributes"
        )
        self._value_clipboard = MayaScalarValueClipboard()
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
        self, attributes: tuple[tuple[ScalarAttributeInfo, ...], ...]
    ) -> tuple[ChannelRow | ChannelStateRow, ...]:
        """基準属性を表示順に絞り込み、同名・同種属性を対応付ける。"""
        if not attributes:
            return ()
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
                if not self._matches_filter(attribute):
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
                    )
                elif attribute.kind == "enum":
                    binding = self._create_enum_binding(
                        attribute.path, targets, excluded
                    )
                else:
                    binding = MayaFloatPlugsBinding(
                        [
                            resolve_float_plug(n, attribute.path)
                            for n in targets
                        ],
                        parent=self,
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

    def _matches_filter(self, attribute: ScalarAttributeInfo) -> bool:
        """Keyableを優先する三状態分類で、基準属性の表示可否を返す。"""
        selected = self.attribute_filter
        if selected == "all":
            return True
        if selected == "visible":
            return attribute.keyable or attribute.channel_box
        if selected == "keyable":
            return attribute.keyable
        if selected == "channel_box":
            return not attribute.keyable and attribute.channel_box
        return not attribute.keyable and not attribute.channel_box

    @staticmethod
    def _resolve_state_plug(
        name: str, attribute: ScalarAttributeInfo
    ) -> MayaChannelStatePlug:
        """値やenum定義を比較せず、対応scalarの参照だけを取得する。"""
        if attribute.kind == "bool":
            return resolve_bool_plug(name, attribute.path)
        if attribute.kind == "enum":
            return resolve_enum_plug(name, attribute.path)
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
        return MayaEnumPlugsBinding(plugs, parent=self)

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

    def align_selected_values(self, keys: Sequence[tuple[str, str]]) -> bool:
        """各選択行をそれぞれの基準ノードの未丸め値へ、一操作で揃える。"""
        edits: list[MayaPlugsValueEdit] = []
        excluded: list[str] = []
        for row in self._selected_rows(keys):
            if not isinstance(row, ChannelRow):
                continue
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
            else:
                edits.append(MayaFloatValueEdit(binding, binding.value))
        changed = apply_plugs_values(edits)
        self._report_excluded(excluded)
        return changed

    def can_paste_values(self) -> bool:
        """対応する属性値dataが現在のOS clipboardにあるか返す。"""
        return not self._disposed and self._value_clipboard.contains()

    def copy_selected_values(self, keys: Sequence[tuple[str, str]]) -> int:
        """基準nodeの選択属性値を、型と正式path付きでOSへコピーする。"""
        rows = self._selected_rows(keys)
        if not self.node_names:
            raise RuntimeError("コピー元のノードが選択されていません")
        attributes = tuple(
            row.attribute for row in rows if isinstance(row, ChannelRow)
        )
        if not attributes:
            raise ValueError("コピーする値属性を選択してください")
        snapshot = capture_scalar_node_values(self.node_names[0], attributes)
        self._value_clipboard.write(MayaScalarValueTransfer((snapshot,)))
        count = len(snapshot.values)
        self.operation_reported.emit(
            f"基準ノードから{count}属性の値をコピーしました"
        )
        return count

    def paste_copied_values(self) -> bool:
        """OS clipboardの属性値を、全選択nodeの同じ正式pathへ貼り付ける。"""
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
        result = apply_scalar_value_transfer(self.node_names, transfer)
        message = f"貼り付け対象: {result.eligible_count}属性"
        if result.excluded:
            message += " / 対象外: " + " / ".join(result.excluded)
        self.operation_reported.emit(message)
        return result.changed

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
