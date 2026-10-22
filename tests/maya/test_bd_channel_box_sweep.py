# coding: utf-8
"""なぞり入力とフィルター、複数ノード、Undo、操作中断を統合検証する。"""

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.bd_channel_box.widget import (
    AttributeStateRowWidget,
    ChannelBoxWidget,
)


def _events() -> None:
    """遅延再構築とQt破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """複数transformのKeyable属性を、上位の行が見える大きさで表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    for name in ("sweepA", "sweepB"):
        cmds.createNode("transform", name=name)
    cmds.select("sweepB", "sweepA", replace=True)
    widget = ChannelBoxWidget()
    widget.resize(380, 460)
    widget.mode_combo.setCurrentIndex(1)
    widget.filter_combo.setCurrentIndex(
        widget.filter_combo.findData("keyable")
    )
    widget.show()
    _events()
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def _button(editor: ChannelBoxWidget, name: str) -> qt.QRadioButton:
    """対象行のHideボタンを取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row.display_buttons["hidden"]


def _key_for(editor: ChannelBoxWidget, name: str) -> tuple[str, str]:
    """表示・ロック行の正式pathと型を返す。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row.row.attribute.path, row.row.attribute.kind


def _mouse(
    origin: qt.QtWidgets.QAbstractButton,
    kind: qt.QEvent.Type,
    target: qt.QtWidgets.QAbstractButton,
) -> None:
    """押下元へ別行のグローバル座標を持つマウスイベントを送る。"""
    position = target.mapToGlobal(qt.QPoint(8, target.height() // 2))
    event = qt.QtGui.QMouseEvent(
        kind,
        qt.QPointF(origin.mapFromGlobal(position)),
        qt.QPointF(position),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseMove
            else qt.Qt.MouseButton.LeftButton
        ),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseButtonRelease
            else qt.Qt.MouseButton.LeftButton
        ),
        qt.Qt.KeyboardModifier.NoModifier,
    )
    qt.QApplication.sendEvent(origin, event)


def _start(
    editor: ChannelBoxWidget,
) -> tuple[qt.QRadioButton, qt.QRadioButton]:
    """Translate XからZまで高速になぞり、Yを含む三行を変更する。"""
    first, last = _button(editor, "translateX"), _button(editor, "translateZ")
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    assert editor.state_sweep.is_active
    return first, last


def _assert_keyable(value: bool) -> None:
    """両選択ノードの三軸が同じ状態で、値とlockを維持するか確認する。"""
    for node in ("sweepA", "sweepB"):
        for attribute in ("translateX", "translateY", "translateZ"):
            path = f"{node}.{attribute}"
            assert bool(cmds.getAttr(path, keyable=True)) is value
            assert not cmds.getAttr(path, channelBox=True)
            assert not cmds.getAttr(path, lock=True)
            assert cmds.getAttr(path) == 0.0


def test_sweep_freezes_filtered_rows_and_groups_undo(
    editor: ChannelBoxWidget,
) -> None:
    """変更は即時に反映し、絞り込みはrelease後、Undoは全行一回にする。"""
    editor.table_view.select_keys(
        (_key_for(editor, "translateX"), _key_for(editor, "rotateZ"))
    )
    before = editor.row_widgets
    first, last = _start(editor)
    _events()
    _assert_keyable(False)
    for node in ("sweepA", "sweepB"):
        assert cmds.getAttr(f"{node}.rotateZ", keyable=True)
    assert editor.row_widgets == before
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    assert not editor.state_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    assert not any(
        row.row.attribute.name.startswith("translate")
        for row in editor.row_widgets
    )
    cmds.undo()
    _events()
    _assert_keyable(True)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    _assert_keyable(False)


def _lock(editor: ChannelBoxWidget, name: str) -> qt.QCheckBox:
    """指定行のlock入力を取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row.lock_check_box


def _assert_locked(value: bool) -> None:
    """両選択ノードの三軸が揃い、表示フラグと値を維持するか確認する。"""
    for node in ("sweepA", "sweepB"):
        for attribute in ("translateX", "translateY", "translateZ"):
            path = f"{node}.{attribute}"
            assert bool(cmds.getAttr(path, lock=True)) is value
            assert cmds.getAttr(path, keyable=True)
            assert not cmds.getAttr(path, channelBox=True)
            assert cmds.getAttr(path) == 0.0


def _start_lock(
    editor: ChannelBoxWidget,
) -> tuple[qt.QCheckBox, qt.QCheckBox]:
    """Translate三軸を一度の移動でなぞり、操作中の状態を返す。"""
    first, last = _lock(editor, "translateX"), _lock(editor, "translateZ")
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    assert editor.lock_sweep.is_active
    return first, last


@pytest.mark.parametrize("initial", ["unlocked", "locked", "mixed"])
def test_lock_sweep_normalizes_mixed_rows_and_groups_undo(
    editor: ChannelBoxWidget, initial: str
) -> None:
    """開始元で決めた状態へ混在行を揃え、往復しても一回でUndoする。"""
    if initial in ("locked", "mixed"):
        cmds.setAttr("sweepA.translateX", lock=True)
    if initial == "locked":
        cmds.setAttr("sweepB.translateX", lock=True)
    cmds.setAttr("sweepB.translateY", lock=True)
    _events()
    before = tuple(
        bool(cmds.getAttr(f"{node}.translate{axis}", lock=True))
        for node in ("sweepA", "sweepB")
        for axis in "XYZ"
    )
    cmds.flushUndo()
    editor.table_view.select_keys(
        (_key_for(editor, "translateX"), _key_for(editor, "rotateZ"))
    )
    rows = editor.row_widgets
    first, _last = _start_lock(editor)
    _events()
    target = initial == "unlocked"
    _assert_locked(target)
    for node in ("sweepA", "sweepB"):
        assert not cmds.getAttr(f"{node}.rotateZ", lock=True)
    assert editor.row_widgets == rows
    assert not editor.state_sweep.is_active
    _mouse(first, qt.QEvent.Type.MouseMove, first)
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, first)
    _events()
    _assert_locked(target)
    assert not editor.lock_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    cmds.undo()
    _events()
    assert (
        tuple(
            bool(cmds.getAttr(f"{node}.translate{axis}", lock=True))
            for node in ("sweepA", "sweepB")
            for axis in "XYZ"
        )
        == before
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    _assert_locked(target)


@pytest.mark.parametrize(
    "action",
    [
        "escape",
        "hide",
        "close",
        "mode",
        "filter",
        "refresh",
        "selection",
        "dispose",
    ],
)
def test_lock_sweep_interruption_closes_undo(
    editor: ChannelBoxWidget, action: str
) -> None:
    """中断経路でlock操作を終了し、次の値変更を同じUndoへ含めない。"""
    first, last = _start_lock(editor)
    if action == "escape":
        qt.QApplication.sendEvent(
            first,
            qt.QtGui.QKeyEvent(
                qt.QEvent.Type.KeyPress,
                qt.Qt.Key.Key_Escape,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )
    elif action == "hide":
        editor.hide()
    elif action == "close":
        editor.close()
    elif action == "mode":
        editor.controller.set_mode("values")
    elif action == "filter":
        editor.controller.set_attribute_filter("all")
    elif action == "refresh":
        editor.controller.refresh()
    elif action == "selection":
        cmds.select(clear=True)
    else:
        editor.dispose()
    assert not editor.lock_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    if qt.isValid(first) and qt.isValid(last):
        _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    _assert_locked(True)
    cast(Callable[[str, float], None], cmds.setAttr)("sweepA.rotateX", 20.0)
    cmds.undo()
    assert cmds.getAttr("sweepA.rotateX") == 0.0
    _assert_locked(True)


@pytest.mark.parametrize(
    "action",
    [
        "escape",
        "hide",
        "close",
        "mode",
        "filter",
        "refresh",
        "selection",
        "dispose",
    ],
)
def test_interruption_commits_and_closes_undo(
    editor: ChannelBoxWidget, action: str
) -> None:
    """各中断経路で入力を終了し、後続の値変更を同じUndoへ混ぜない。"""
    first, last = _start(editor)
    if action == "escape":
        qt.QApplication.sendEvent(
            first,
            qt.QtGui.QKeyEvent(
                qt.QEvent.Type.KeyPress,
                qt.Qt.Key.Key_Escape,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )
    elif action == "hide":
        editor.hide()
    elif action == "close":
        editor.close()
    elif action == "mode":
        editor.controller.set_mode("values")
    elif action == "filter":
        editor.controller.set_attribute_filter("all")
    elif action == "refresh":
        editor.controller.refresh()
    elif action == "selection":
        cmds.select(clear=True)
    else:
        editor.dispose()
    assert not editor.state_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    if qt.isValid(first) and qt.isValid(last):
        _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    _assert_keyable(False)
    cast(Callable[[str, float], None], cmds.setAttr)("sweepA.rotateX", 20.0)
    cmds.undo()
    assert cmds.getAttr("sweepA.rotateX") == 0.0
    _assert_keyable(False)


def test_attribute_removal_interrupts_without_deferring_structure(
    editor: ChannelBoxWidget,
) -> None:
    """属性構成の変更はなぞりを中断し、古いBindingへの入力を止める。"""
    cmds.addAttr("sweepA", longName="temporary", attributeType="double")
    _events()
    _start(editor)
    cmds.deleteAttr("sweepA.temporary")
    assert not editor.state_sweep.is_active
    _events()
    assert not editor.controller.state_edit_session.is_editing
    _assert_keyable(False)


def test_lock_failure_restores_current_row_and_stops_sweep(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """途中行の失敗ではその行を復旧し、先行行だけを一回Undoで戻す。"""
    original = cast(Callable[..., None], cmds.setAttr)
    failed = False

    def fail_once(name: str, **flags: object) -> None:
        """二行目の後続ノードへの書込みを一度だけ拒否する。"""
        nonlocal failed
        if (
            name.split(".", 1)[0].rsplit("|", 1)[-1] == "sweepB"
            and name.rsplit(".", 1)[-1] == "translateY"
            and not failed
        ):
            failed = True
            raise RuntimeError("lockなぞりの検証用エラー")
        original(name, **flags)

    monkeypatch.setattr(cmds, "setAttr", fail_once)
    first, last = _lock(editor, "translateX"), _lock(editor, "translateZ")
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    assert failed
    assert not editor.lock_sweep.is_active
    assert not editor.controller.state_edit_session.is_editing
    assert "検証用エラー" in editor.message_label.text()
    for node in ("sweepA", "sweepB"):
        assert cmds.getAttr(node + ".translateX", lock=True)
        assert not cmds.getAttr(node + ".translateY", lock=True)
        assert not cmds.getAttr(node + ".translateZ", lock=True)
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    cmds.undo()
    _events()
    _assert_locked(False)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_lock_sweep_skips_disabled_rows(editor: ChannelBoxWidget) -> None:
    """親lockで操作不可の行を飛ばし、前後の属性だけへ適用する。"""
    cmds.setAttr("sweepA.translate", lock=True)
    _events()
    assert not _lock(editor, "translateX").isEnabled()
    first, last = _lock(editor, "visibility"), _lock(editor, "rotateZ")
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    for node in ("sweepA", "sweepB"):
        assert cmds.getAttr(node + ".visibility", lock=True)
        assert cmds.getAttr(node + ".rotateZ", lock=True)
    assert cmds.getAttr("sweepA.translate", lock=True)
    assert not cmds.getAttr("sweepB.translateX", lock=True)


@pytest.mark.parametrize("operation", ["display", "lock"])
def test_thousand_node_sweep_applies_visually_unchanged_rows_and_one_undo(
    editor: ChannelBoxWidget, operation: str
) -> None:
    """基準が既に要求状態の行も千対象へ適用し、通過行だけを一回で戻す。"""
    nodes = tuple(
        cmds.createNode("transform", name=f"sweepMany{index}")
        for index in range(998)
    ) + ("sweepB", "sweepA")
    if operation == "display":
        for axis in "XYZ":
            cmds.setAttr(
                f"sweepA.translate{axis}", keyable=False, channelBox=True
            )
    else:
        for axis in "YZ":
            cmds.setAttr(f"sweepA.translate{axis}", lock=True)
    editor.controller.set_attribute_filter("visible")
    cmds.select(*nodes, replace=True)
    _events()
    assert len(editor.controller.node_names) == 1000
    assert editor.row_widgets
    editor.table_view.select_keys(
        (_key_for(editor, "translateX"), _key_for(editor, "rotateZ"))
    )

    def flags() -> tuple[tuple[bool, bool, bool], ...]:
        """全対象の通過三行から実際の表示とlock状態を取得する。"""
        return tuple(
            (
                bool(cmds.getAttr(path, keyable=True)),
                bool(cmds.getAttr(path, channelBox=True)),
                bool(cmds.getAttr(path, lock=True)),
            )
            for node in nodes
            for axis in "XYZ"
            for path in (f"{node}.translate{axis}",)
        )

    before = flags()
    if operation == "display":
        rows = tuple(
            next(
                row
                for row in editor.row_widgets
                if row.row.attribute.name == name
            )
            for name in ("translateX", "translateZ")
        )
        assert all(isinstance(row, AttributeStateRowWidget) for row in rows)
        first, last = tuple(
            cast(AttributeStateRowWidget, row).display_buttons["channel_box"]
            for row in rows
        )
        assert first.isChecked() and last.isChecked()
        expected = (False, True, False)
    else:
        first, last = _lock(editor, "translateX"), _lock(editor, "translateZ")
        assert not first.isChecked() and last.isChecked()
        expected = (True, False, True)
    cmds.flushUndo()
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    assert editor.controller.state_edit_session.is_editing
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    assert flags() == (expected,) * (len(nodes) * 3)
    assert not editor.controller.state_edit_session.is_editing
    assert not editor.state_sweep.is_active
    assert not editor.lock_sweep.is_active
    for node in nodes:
        assert cmds.getAttr(f"{node}.rotateZ", keyable=True)
        assert not cmds.getAttr(f"{node}.rotateZ", lock=True)
        assert cmds.getAttr(f"{node}.translateX") == 0.0
    cmds.undo()
    _events()
    assert flags() == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert flags() == (expected,) * (len(nodes) * 3)


def test_display_sweep_keeps_the_start_column_during_horizontal_movement(
    editor: ChannelBoxWidget,
) -> None:
    """開始列のなぞり後に別列へ移動しても、異なる表示状態で上書きしない。"""
    first = _button(editor, "translateX")
    row = next(
        row
        for row in editor.row_widgets
        if row.row.attribute.name == "translateZ"
    )
    assert isinstance(row, AttributeStateRowWidget)
    last = row.display_buttons["hidden"]
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    _assert_keyable(False)
    last = row.display_buttons["keyable"]
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    _assert_keyable(False)
    _mouse(first, qt.QEvent.Type.MouseButtonRelease, last)
    _events()
    _assert_keyable(False)
    cmds.undo()
    _events()
    _assert_keyable(True)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
