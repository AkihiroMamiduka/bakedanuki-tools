# coding: utf-8
"""なぞり入力とフィルター、複数ノード、Undo、操作中断を統合検証する。"""

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt
from bd_tools.channel_editor.widget import (
    AttributeStateRowWidget,
    ChannelEditorWidget,
)


def _events() -> None:
    """遅延再構築とQt破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelEditorWidget]:
    """複数transformのKeyable属性を、上位の行が見える大きさで表示する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    for name in ("sweepA", "sweepB"):
        cmds.createNode("transform", name=name)
    cmds.select("sweepA", "sweepB", replace=True)
    widget = ChannelEditorWidget()
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


def _button(editor: ChannelEditorWidget, name: str) -> qt.QRadioButton:
    """対象行のHideボタンを取得する。"""
    row = next(w for w in editor.row_widgets if w.row.attribute.name == name)
    assert isinstance(row, AttributeStateRowWidget)
    return row.display_buttons["hidden"]


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
    editor: ChannelEditorWidget,
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
    editor: ChannelEditorWidget,
) -> None:
    """変更は即時に反映し、絞り込みはrelease後、Undoは全行一回にする。"""
    before = editor.row_widgets
    first, last = _start(editor)
    _events()
    _assert_keyable(False)
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


def _lock(editor: ChannelEditorWidget, name: str) -> qt.QCheckBox:
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
    editor: ChannelEditorWidget,
) -> tuple[qt.QCheckBox, qt.QCheckBox]:
    """Translate三軸を一度の移動でなぞり、操作中の状態を返す。"""
    first, last = _lock(editor, "translateX"), _lock(editor, "translateZ")
    _mouse(first, qt.QEvent.Type.MouseButtonPress, first)
    _mouse(first, qt.QEvent.Type.MouseMove, last)
    assert editor.lock_sweep.is_active
    return first, last


@pytest.mark.parametrize("initial", ["unlocked", "locked", "mixed"])
def test_lock_sweep_normalizes_mixed_rows_and_groups_undo(
    editor: ChannelEditorWidget, initial: str
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
    rows = editor.row_widgets
    first, _last = _start_lock(editor)
    _events()
    target = initial != "locked"
    _assert_locked(target)
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
    ["escape", "hide", "mode", "filter", "refresh", "selection", "dispose"],
)
def test_lock_sweep_interruption_closes_undo(
    editor: ChannelEditorWidget, action: str
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
    ["escape", "hide", "mode", "filter", "refresh", "selection", "dispose"],
)
def test_interruption_commits_and_closes_undo(
    editor: ChannelEditorWidget, action: str
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
    editor: ChannelEditorWidget,
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
    editor: ChannelEditorWidget, monkeypatch: pytest.MonkeyPatch
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


def test_lock_sweep_skips_disabled_rows(editor: ChannelEditorWidget) -> None:
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
