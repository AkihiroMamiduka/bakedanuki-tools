# coding: utf-8
"""選択ノードと入力行を結び付けるChannel Editorの制御。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from maya.api import OpenMaya as om

from bd_util.maya.node.inspection import (
    ScalarAttributeInfo,
    inspect_scalar_attributes,
    selected_node_names,
)
from bd_util.maya.ui import (
    MayaBoolPlugsBinding,
    MayaCallbackRegistry,
    MayaFloatPlugsBinding,
    resolve_bool_plug,
    resolve_float_plug,
)
from bd_util.ui import qt

ChannelBinding: TypeAlias = MayaBoolPlugsBinding | MayaFloatPlugsBinding

__all__ = ["ChannelBinding", "ChannelRow", "ChannelEditorController"]


@dataclass(frozen=True)
class ChannelRow:
    """代表属性、入力Binding、対応しない選択ノードの理由。"""

    attribute: ScalarAttributeInfo
    binding: ChannelBinding
    excluded: tuple[str, ...]


class ChannelEditorController(qt.QObject):
    """選択・属性構成の変更時だけ入力行を組み直す。"""

    rows_changed = qt.Signal()
    error_occurred = qt.Signal(str)

    def __init__(self, parent: qt.QObject) -> None:
        """表示用状態と、Windowと同じ寿命の監視を初期化する。"""
        super().__init__(parent)
        self.rows: tuple[ChannelRow, ...] = ()
        self.node_names: tuple[str, ...] = ()
        self._disposed = False
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
        self._timer.stop()
        self._refresh_pending()

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
        structural = (
            om.MNodeMessage.kAttributeAdded
            | om.MNodeMessage.kAttributeRemoved
            | om.MNodeMessage.kAttributeRenamed
            | om.MNodeMessage.kAttributeKeyable
            | om.MNodeMessage.kAttributeUnkeyable
        )
        if message & structural:
            self._queue_rebuild()

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
    ) -> tuple[ChannelRow, ...]:
        """先頭ノードの表示対象と、各ノードの同名・同種属性を対応付ける。"""
        if not attributes:
            return ()
        lookup = tuple({a.path: a for a in items} for items in attributes)
        rows: list[ChannelRow] = []
        try:
            for attribute in attributes[0]:
                if not (attribute.keyable or attribute.channel_box):
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
                binding: ChannelBinding
                if attribute.kind == "bool":
                    binding = MayaBoolPlugsBinding(
                        [
                            resolve_bool_plug(n, attribute.path)
                            for n in targets
                        ],
                        parent=self,
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
                row.binding.dispose()
            raise
        return tuple(rows)

    def _dispose_rows(self) -> None:
        """Qtの遅延削除を待たず、すべての入力とMaya監視を終了する。"""
        rows, self.rows = self.rows, ()
        for row in rows:
            row.binding.dispose()

    def dispose(self) -> None:
        """timer、入力Binding、Maya callbackを一度だけ解放する。"""
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        self._dispose_rows()
        self._nodes.dispose()
        self._events.dispose()
