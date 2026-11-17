# coding: utf-8
"""表示Bindingの共通監視を共有し、選択切替・終了で即解放することを検証する。"""

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.maya.ui import callback as callback_module
from bd_util.ui import qt
from bd_tools.bd_channel_box.controller import ChannelRow
from bd_tools.bd_channel_box.widget import ChannelBoxWidget

_AddEvent = Callable[[str, Callable[..., None], object | None], int]


class _EventCounter:
    """実Mayaへ登録しながら通知名と存続中のIDを記録する。"""

    def __init__(self, native: type[om.MEventMessage]) -> None:
        """差替え前のMaya APIを保持し、登録以外の処理を変更しない。"""
        self._native = native
        self._add = cast(_AddEvent, native.addEventCallback)
        self.counts: dict[str, int] = {}
        self.active: set[int] = set()

    def __getattr__(self, name: str) -> object:
        """登録以外のMaya APIを元のclassへ委譲する。"""
        return getattr(self._native, name)

    def addEventCallback(
        self,
        event: str,
        callback: Callable[..., None],
        client_data: object | None = None,
    ) -> int:
        """登録回数を通知名ごとに数え、実際のcallback IDを返す。"""
        identity = self._add(event, callback, client_data)
        self.counts[event] = self.counts.get(event, 0) + 1
        self.active.add(identity)
        return identity


def _events() -> None:
    """行の再接続と旧QObjectの遅延削除を完了する。"""
    for _ in range(4):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> _EventCounter:
    """実Mayaの登録と解除を記録し、callback自体は加工しない。"""
    recorded = _EventCounter(om.MEventMessage)
    remove = cast(
        Callable[[int], None], callback_module.__dict__["_remove_callback"]
    )

    def remove_callback(identity: int) -> None:
        """実際の解除後に、記録している存続IDから取り除く。"""
        remove(identity)
        recorded.active.discard(identity)

    monkeypatch.setattr(om, "MEventMessage", recorded)
    monkeypatch.setattr(callback_module, "_remove_callback", remove_callback)
    return recorded


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """共通の独立数値属性を持つ二つのnodeを表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    auto_key = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    for name in ("eventsA", "eventsB"):
        cmds.createNode("network", name=name, skipSelect=True)
        for index in range(30):
            cmds.addAttr(
                name,
                longName=f"value{index:02d}",
                attributeType="double",
                keyable=True,
            )
    cmds.select("eventsA", replace=True)
    widget = ChannelBoxWidget()
    widget.controller.set_attribute_filter("all")
    widget.show()
    _events()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        _events()
        cast(Callable[..., str], cmds.file)(new=True, force=True)
        cmds.autoKeyframe(state=auto_key)


def test_common_events_are_registered_once_and_released_immediately(
    editor: ChannelBoxWidget, counter: _EventCounter
) -> None:
    """多数行でも通知は一回登録し、旧選択とWindow終了で即解除する。"""
    before = editor.row_widgets
    old = tuple(
        row.binding
        for row in editor.controller.rows
        if isinstance(row, ChannelRow)
    )
    counter.counts.clear()
    cmds.select("eventsB", replace=True)
    assert all(binding.is_disposed for binding in old)
    _events()
    assert editor.row_widgets == before
    for event in (
        "linearUnitChanged",
        "angularUnitChanged",
        "Undo",
        "Redo",
        "animLayerRefresh",
        "animLayerRebuild",
    ):
        # 名前欄の独立Bindingも選択先へ切り替わり、履歴を一回ずつ監視する
        expected = 2 if event in ("Undo", "Redo") else 1
        assert counter.counts[event] == expected, counter.counts

    row = next(
        row
        for row in editor.controller.rows
        if row.attribute.name == "value00"
    )
    assert isinstance(row, ChannelRow)
    binding = row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    binding.set_value(5.0)
    assert cmds.getAttr("eventsA.value00") == 0.0
    assert cmds.getAttr("eventsB.value00") == 5.0
    cmds.undo()
    _events()
    assert binding.value == 0.0

    # Qtの遅延削除より前に全共有通知を解除する
    assert counter.active
    editor.dispose()
    assert not counter.active


def test_state_mode_keeps_independent_history_monitoring(
    editor: ChannelBoxWidget, counter: _EventCounter
) -> None:
    """状態編集のBindingへ値編集専用の通知共有を適用しない。"""
    counter.counts.clear()
    editor.controller.set_mode("states")
    _events()
    assert counter.counts["Undo"] == len(editor.controller.rows)
    assert counter.counts["Redo"] == len(editor.controller.rows)
    assert counter.counts.get("linearUnitChanged", 0) == 0
    assert counter.counts.get("animLayerRefresh", 0) == 0
