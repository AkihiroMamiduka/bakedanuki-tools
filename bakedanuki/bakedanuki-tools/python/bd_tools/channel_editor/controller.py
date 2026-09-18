# coding: utf-8
"""選択ノードと入力行を結び付けるChannel Editorの制御。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Literal, TypeAlias

from maya.api import OpenMaya as om

from bd_util.maya.node.inspection import (
    ScalarAttributeInfo,
    inspect_scalar_attributes,
    selected_node_names,
)
from bd_util.maya.ui import (
    MayaBoolPlugsBinding,
    MayaCallbackRegistry,
    MayaChannelStateBinding,
    MayaChannelStatePlug,
    MayaEnumPlugsBinding,
    MayaEditSession,
    MayaFloatPlugsBinding,
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
ChannelEditorMode: TypeAlias = Literal["values", "states"]
ChannelAttributeFilter: TypeAlias = Literal[
    "all", "visible", "keyable", "channel_box", "hidden"
]

__all__ = [
    "ChannelBinding",
    "ChannelEditorMode",
    "ChannelAttributeFilter",
    "ChannelRow",
    "ChannelStateRow",
    "ChannelEditorController",
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


@dataclass(frozen=True)
class ChannelStateRow:
    """代表属性、表示・ロックBinding、対応しないノードの理由。"""

    attribute: ScalarAttributeInfo
    state_binding: MayaChannelStateBinding
    excluded: tuple[str, ...]


class ChannelEditorController(qt.QObject):
    """選択・属性構成の変更時だけ入力行を組み直す。"""

    rows_changed = qt.Signal()
    error_occurred = qt.Signal(str)
    mode_changed = qt.Signal()
    filter_changed = qt.Signal()

    def __init__(self, parent: qt.QObject) -> None:
        """表示用状態と、Windowと同じ寿命の監視を初期化する。"""
        super().__init__(parent)
        self.rows: tuple[ChannelRow | ChannelStateRow, ...] = ()
        self.node_names: tuple[str, ...] = ()
        self._mode: ChannelEditorMode = "values"
        self._filters: dict[ChannelEditorMode, ChannelAttributeFilter] = {
            "values": "visible",
            "states": "all",
        }
        self._disposed = False
        self.state_edit_session = MayaEditSession(
            self, chunk_name="SweepChannelStates"
        )
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
    def mode(self) -> ChannelEditorMode:
        """値入力または表示・ロック設定の表示モードを返す。"""
        return self._mode

    def set_mode(self, mode: ChannelEditorMode) -> None:
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
                            attribute, state_binding, tuple(excluded)
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
                rows.append(ChannelRow(attribute, binding, tuple(excluded)))
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
        self.state_edit_session.finish()
        rows, self.rows = self.rows, ()
        for row in rows:
            self._dispose_row(row)

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
