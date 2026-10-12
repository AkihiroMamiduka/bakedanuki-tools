# coding: utf-8
"""子維持のdockable画面と姿勢維持Windowの即時入力を検証する。"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaDockableWindow
from bd_util.maya.ui.dock import workspace_control
from bd_util.ui import qt
from bd_tools.bd_channel_box import (
    child_rotation_ui,
    child_set_ui,
    child_translate_ui,
    rotation_set_ui,
)
from bd_tools.bd_channel_box.child_compensated_set_window import (
    ChildCompensatedSetWindow,
)
from bd_tools.bd_channel_box.child_set_dock_window import (
    ROTATION_INITIAL_HEIGHT,
    ROTATION_INITIAL_WIDTH,
    TRANSLATE_INITIAL_HEIGHT,
    TRANSLATE_INITIAL_WIDTH,
    ChildSetDockWindow,
)
from bd_tools.bd_channel_box.rotation_set_window import RotationSetWindow


@pytest.fixture
def clean_scene(qt_application: qt.QApplication) -> Iterator[None]:
    """表示単位を固定した空sceneを用意してテスト後に復旧する。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    linear = cast(str, cmds.currentUnit(query=True, linear=True))
    angle = cast(str, cmds.currentUnit(query=True, angle=True))
    cmds.currentUnit(linear="cm", angle="deg")
    try:
        yield
    finally:
        cmds.flushUndo()
        cmds.currentUnit(linear=linear, angle=angle)
        cast(Callable[..., str], cmds.file)(new=True, force=True)


def _xyz(node: str, attribute: str) -> tuple[float, float, float]:
    """Maya表示単位でXYZ属性の実値を返す。"""
    return cast(
        tuple[float, float, float], cmds.getAttr(f"{node}.{attribute}")[0]
    )


def _set_xyz(
    node: str, attribute: str, values: tuple[float, float, float]
) -> None:
    """型付きMaya facade越しにXYZ複合属性を設定する。"""
    cast(Callable[..., None], cmds.setAttr)(
        f"{node}.{attribute}", *values, type="double3"
    )


def _matrix(node: str, *, world: bool = False) -> tuple[float, ...]:
    """補償前後を比較するためノードの行列を返す。"""
    return cast(
        tuple[float, ...],
        cmds.xform(
            node,
            query=True,
            matrix=True,
            worldSpace=world,
            objectSpace=not world,
        ),
    )


def _assert_close(actual: Sequence[float], expected: Sequence[float]) -> None:
    """変換値をMayaの計算誤差内で比較する。"""
    assert len(actual) == len(expected)
    assert all(
        math.isclose(left, right, rel_tol=1.0e-8, abs_tol=1.0e-8)
        for left, right in zip(actual, expected)
    )


def _process_events(application: qt.QApplication) -> None:
    """選択callbackから予約された画面更新まで処理する。"""
    application.processEvents()
    application.processEvents()


def _assert_step_fields_visible(
    window: ChildCompensatedSetWindow | RotationSetWindow,
) -> None:
    """各軸のStep欄がWindowの表示領域内に収まることを確かめる。"""
    for editor in window.xyz_editor.value_editors:
        step = editor.step_spin_box
        assert step.isVisible()
        assert step.width() > 0
        assert editor.rect().contains(
            step.mapTo(editor, step.rect().bottomRight())
        )
        assert window.rect().contains(
            step.mapTo(window, step.rect().bottomRight())
        )


def _xyz_vertical_gaps(
    window: ChildCompensatedSetWindow | RotationSetWindow,
) -> tuple[int, int]:
    """XYZ入力行の間にある空白の高さを返す。"""
    editors = window.xyz_editor.value_editors
    return (
        editors[1].geometry().top() - editors[0].geometry().bottom() - 1,
        editors[2].geometry().top() - editors[1].geometry().bottom() - 1,
    )


class _ChildSetDockHost:
    """batch Mayaにない浮動workspaceControlをQtで代替する。"""

    def __init__(self) -> None:
        """共通Windowと内側controlより4px大きい浮動枠を保持する。"""
        self.window: MayaDockableWindow | None = None
        self.size = qt.QSize(TRANSLATE_INITIAL_WIDTH, TRANSLATE_INITIAL_HEIGHT)
        self.floating_host = qt.QWidget()
        self.floating_host.resize(self.size)
        self.floating_host.show()
        self.floating = True

    def attach(self, window: MayaDockableWindow, _pointer: int = 0) -> None:
        """生成またはrestoreしたWindowを表示する。"""
        self.window = window
        qt.QWidget.setVisible(window, True)

    def delete(self, _name: str) -> None:
        """MayaがworkspaceControlを削除する動作を再現する。"""
        window, self.window = self.window, None
        if window is not None:
            window.hide()
            window.deleteLater()

    def resize(self, size: qt.QSize) -> None:
        """浮動枠と内側controlの4px差を維持して寸法を変える。"""
        self.size = qt.QSize(size)
        self.floating_host.resize(size)
        window = self.window
        if window is not None:
            qt.QWidget.resize(
                window, qt.QSize(size.width() - 4, size.height() - 4)
            )


@pytest.fixture
def child_set_dock_host(
    qt_application: qt.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[_ChildSetDockHost]:
    """実Window・controllerを使いMayaのworkspaceControl境界を置き換える。"""
    from bd_util.maya.ui import settings as maya_settings

    host = _ChildSetDockHost()

    def show_dockable(window: MayaDockableWindow, **options: object) -> None:
        """初回のDockOptionsサイズで共通Windowを表示する。"""
        width = options.get("width")
        height = options.get("height")
        if isinstance(width, int) and isinstance(height, int):
            host.size = qt.QSize(width, height)
        host.attach(window)

    def resize_control(window: ChildSetDockWindow, size: qt.QSize) -> None:
        """浮動枠のサイズ変更をQtの実Widgetへ反映する。"""
        del window
        host.resize(size)

    def exists(_name: str) -> bool:
        """代替workspaceControlの有無を返す。"""
        return host.window is not None

    def no_state(_name: str) -> bool:
        """Mayaの保存済み配置がない初回状態を再現する。"""
        return False

    def restore(_name: str) -> None:
        """代替workspaceControlの再表示を受け付ける。"""
        return None

    def current_parent() -> int:
        """restore時に使う代替親pointerを返す。"""
        return 1

    def schedule_ensure_on_screen(_name: str, _window: qt.QWidget) -> None:
        """実画面の位置補正をbatch testでは省略する。"""
        return None

    def is_floating(_window: ChildSetDockWindow) -> bool:
        """代替workspaceControlの浮動状態を返す。"""
        return host.floating

    def find_floating_host(_name: str, _window: qt.QWidget) -> qt.QWidget:
        """内側controlとは寸法の異なる浮動枠を返す。"""
        return host.floating_host

    monkeypatch.setattr(MayaDockableWindow, "show", show_dockable)
    monkeypatch.setattr(workspace_control, "exists", exists)
    monkeypatch.setattr(workspace_control, "state_exists", no_state)
    monkeypatch.setattr(workspace_control, "restore", restore)
    monkeypatch.setattr(workspace_control, "delete", host.delete)
    monkeypatch.setattr(workspace_control, "current_parent", current_parent)
    monkeypatch.setattr(workspace_control, "attach", host.attach)
    monkeypatch.setattr(
        workspace_control,
        "schedule_ensure_on_screen",
        schedule_ensure_on_screen,
    )
    monkeypatch.setattr(
        maya_settings, "get_ui_settings_root", lambda: tmp_path
    )
    monkeypatch.setattr(ChildSetDockWindow, "_is_floating", is_floating)
    monkeypatch.setattr(
        workspace_control, "find_floating_host", find_floating_host
    )
    monkeypatch.setattr(
        ChildSetDockWindow, "_resize_floating_control", resize_control
    )
    child_set_ui.dispose()
    yield host
    child_set_ui.dispose()
    _process_events(qt_application)
    host.floating_host.deleteLater()


def test_translation_window_follows_selection_and_steps_with_one_undo(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """基準ノードだけを即時変更し、子のworld位置とUndoを維持する。"""
    del clean_scene
    first = cmds.createNode("transform", name="firstTarget")
    second = cmds.createNode("transform", name="secondTarget")
    child = cmds.createNode("transform", name="childTarget", parent=second)
    _set_xyz(first, "translate", (1.0, 2.0, 3.0))
    _set_xyz(second, "translate", (4.0, 5.0, 6.0))
    _set_xyz(child, "translate", (2.0, 3.0, 4.0))
    child_before = _matrix(child, world=True)
    cmds.select(first, replace=True)
    window = ChildCompensatedSetWindow(initial_target="translate")
    try:
        window.show()
        _process_events(qt_application)
        assert first in window.target_label.text()
        assert window.xyz_editor.value_spins[0].isEnabled()

        # 未確定の文字入力を次に選択したノードへ持ち越さない
        line_edit = window.xyz_editor.value_spins[0].lineEdit()
        line_edit.setText("99")
        line_edit.setModified(True)
        cmds.select(first, second, replace=True)
        _process_events(qt_application)
        assert second in window.target_label.text()
        _assert_close(_xyz(first, "translate"), (1.0, 2.0, 3.0))
        _assert_close(
            tuple(spin.value() for spin in window.xyz_editor.value_spins),
            (4.0, 5.0, 6.0),
        )

        window.xyz_editor.step_spins[0].setValue(2.0)
        assert window.xyz_editor.value_editors[0].singleStep() == 2.0
        assert window.xyz_editor.value_editors[1].singleStep() == 1.0
        _assert_close(_xyz(second, "translate"), (4.0, 5.0, 6.0))
        cmds.flushUndo()
        window.xyz_editor.value_spins[0].stepBy(1)
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (6.0, 5.0, 6.0))
        _assert_close(_xyz(first, "translate"), (1.0, 2.0, 3.0))
        _assert_close(_matrix(child, world=True), child_before)
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (4.0, 5.0, 6.0))
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)

        # 文字入力の確定も上下操作と同じコマンドへ即時に渡す
        value_spin = window.xyz_editor.value_spins[0]
        committed_edit = value_spin.lineEdit()
        committed_edit.setText("7")
        for kind in (
            qt.QEvent.Type.ShortcutOverride,
            qt.QEvent.Type.KeyPress,
            qt.QEvent.Type.KeyRelease,
        ):
            key_event = qt.QtGui.QKeyEvent(
                kind,
                qt.Qt.Key.Key_Return,
                qt.Qt.KeyboardModifier.NoModifier,
            )
            key_event.setAccepted(False)
            qt.QApplication.sendEvent(value_spin, key_event)
            assert key_event.isAccepted()
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (7.0, 5.0, 6.0))
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(second, "translate"), (4.0, 5.0, 6.0))

        cmds.select(clear=True)
        _process_events(qt_application)
        assert not window.xyz_editor.value_spins[0].isEnabled()
    finally:
        window.close()
        window.deleteLater()


def test_child_rotation_window_applies_active_target_and_keeps_child(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """子を維持する回転値の確定を現在ノードへ即時適用する。"""
    del clean_scene
    joint = cmds.createNode("joint", name="rotateTarget")
    child = cmds.createNode("joint", name="rotateChild", parent=joint)
    _set_xyz(joint, "rotate", (3.0, 4.0, 5.0))
    _set_xyz(child, "translate", (2.0, 3.0, 4.0))
    child_before = _matrix(child, world=True)
    cmds.select(joint, replace=True)
    window = ChildCompensatedSetWindow(initial_target="rotate")
    try:
        window.show()
        _process_events(qt_application)
        window.xyz_editor.value_spins[1].setValue(14.0)
        _process_events(qt_application)
        _assert_close(_xyz(joint, "rotate"), (3.0, 14.0, 5.0))
        _assert_close(_matrix(child, world=True), child_before)
        assert window.xyz_editor.value_spins[1].value() == 14.0

        assert window.target_combo is not None
        assert window.joint_child_combo is not None
        window.target_combo.setCurrentIndex(
            window.target_combo.findData("jointOrient")
        )
        window.joint_child_combo.setCurrentIndex(
            window.joint_child_combo.findData("jointOrient")
        )
        window.xyz_editor.value_spins[0].setValue(11.0)
        _process_events(qt_application)
        _assert_close(_xyz(joint, "jointOrient"), (11.0, 0.0, 0.0))
        _assert_close(_matrix(child, world=True), child_before)
    finally:
        window.close()
        window.deleteLater()


def test_translation_world_field_tracks_selection_and_preserves_child(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """World欄は現在選択の位置を表示し、入力は子の位置を保つ。"""
    del clean_scene
    parent = cmds.createNode("transform", name="worldParent")
    node = cmds.createNode("transform", name="worldTarget", parent=parent)
    child = cmds.createNode("transform", name="worldChild", parent=node)
    other = cmds.createNode("transform", name="otherWorldTarget")
    _set_xyz(parent, "translate", (10.0, 0.0, 0.0))
    _set_xyz(node, "translate", (4.0, 0.0, 0.0))
    _set_xyz(child, "translate", (2.0, 0.0, 0.0))
    _set_xyz(other, "translate", (30.0, 0.0, 0.0))
    child_before = _matrix(child, world=True)
    cmds.select(node, replace=True)
    window = ChildCompensatedSetWindow(initial_target="translate")
    try:
        window.show()
        window.space_combo.setCurrentIndex(
            window.space_combo.findData("world")
        )
        _process_events(qt_application)
        assert math.isclose(window.xyz_editor.value_spins[0].value(), 14.0)

        cmds.flushUndo()
        window.xyz_editor.value_spins[0].setValue(18.0)
        _process_events(qt_application)
        _assert_close(_xyz(node, "translate"), (8.0, 0.0, 0.0))
        _assert_close(_matrix(child, world=True), child_before)
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(node, "translate"), (4.0, 0.0, 0.0))

        cmds.select(other, replace=True)
        _process_events(qt_application)
        assert math.isclose(window.xyz_editor.value_spins[0].value(), 30.0)
    finally:
        window.close()
        window.deleteLater()


def test_pose_window_updates_options_when_selected_type_changes(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """Joint固有属性からTransformへ移ると有効な設定先へ切り替える。"""
    del clean_scene
    joint = cmds.createNode("joint", name="poseJoint")
    transform = cmds.createNode("transform", name="poseTransform")
    cmds.select(joint, replace=True)
    window = RotationSetWindow()
    try:
        window.show()
        window.set_initial_target("jointOrient")
        _process_events(qt_application)
        assert window.target() == "jointOrient"
        assert window.compensate_with() == "rotate"

        cmds.select(transform, replace=True)
        _process_events(qt_application)
        assert window.target() == "rotate"
        assert window.compensate_with() == "rotateAxis"
        original_matrix = _matrix(transform)
        cmds.flushUndo()
        window.xyz_editor.value_spins[0].setValue(25.0)
        _process_events(qt_application)
        _assert_close(_xyz(transform, "rotate"), (25.0, 0.0, 0.0))
        _assert_close(_matrix(transform), original_matrix)
        cmds.undo()
        _process_events(qt_application)
        _assert_close(_xyz(transform, "rotate"), (0.0, 0.0, 0.0))
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)

        cmds.select(joint, replace=True)
        _process_events(qt_application)
        assert window.target() == "rotate"
        assert window.compensate_with() == "jointOrient"
    finally:
        window.close()
        window.deleteLater()


def test_pose_window_uses_current_maya_angle_unit(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """Window表示中に角度単位が変わっても現単位で入力する。"""
    del clean_scene
    node = cmds.createNode("transform", name="angleUnitTarget")
    _set_xyz(node, "rotate", (90.0, 0.0, 0.0))
    original_matrix = _matrix(node)
    cmds.select(node, replace=True)
    window = RotationSetWindow()
    try:
        window.show()
        _process_events(qt_application)
        cmds.currentUnit(angle="rad")
        _process_events(qt_application)
        assert math.isclose(
            window.xyz_editor.value_spins[0].value(),
            math.pi / 2.0,
            abs_tol=1.0e-10,
        )
        window.xyz_editor.value_spins[0].setValue(math.pi / 3.0)
        _process_events(qt_application)
        cmds.currentUnit(angle="deg")
        _process_events(qt_application)
        assert math.isclose(_xyz(node, "rotate")[0], 60.0, abs_tol=1.0e-8)
        _assert_close(_matrix(node), original_matrix)
    finally:
        window.close()
        window.deleteLater()


def test_child_set_tabs_reuse_and_restore_floating_sizes(
    clean_scene: None,
    child_set_dock_host: _ChildSetDockHost,
    qt_application: qt.QApplication,
) -> None:
    """二つのメニューが同じdockを使い、タブ別の浮動サイズを復元する。"""
    del clean_scene
    node = cmds.createNode("transform", name="liveControllerTarget")
    cmds.select(node, replace=True)
    cmds.flushUndo()
    dock = child_translate_ui.show()
    _process_events(qt_application)
    assert dock is child_set_dock_host.window
    assert dock.tabs.currentIndex() == 0
    assert dock.size() == qt.QSize(
        child_set_dock_host.size.width() - 4,
        child_set_dock_host.size.height() - 4,
    )
    assert dock.translate_page.parentWidget() is not None
    assert not (dock.translate_page.windowFlags() & qt.Qt.WindowType.Window)
    assert dock.translate_page.space() == "local"
    assert [
        dock.translate_page.space_combo.itemText(index)
        for index in range(dock.translate_page.space_combo.count())
    ] == ["World", "Local"]
    _assert_step_fields_visible(dock.translate_page)
    assert _xyz_vertical_gaps(dock.translate_page) == (2, 2)

    child_set_dock_host.resize(qt.QSize(370, 240))
    _process_events(qt_application)
    assert _xyz_vertical_gaps(dock.translate_page) == (2, 2)
    assert child_translate_ui.show() is dock

    rotation = child_rotation_ui.show("rotateAxis")
    _process_events(qt_application)
    assert rotation is dock
    assert dock.tabs.currentIndex() == 1
    assert dock.rotation_page.target() == "rotateAxis"
    assert child_set_dock_host.size == qt.QSize(
        ROTATION_INITIAL_WIDTH, ROTATION_INITIAL_HEIGHT
    )
    _assert_step_fields_visible(dock.rotation_page)
    assert _xyz_vertical_gaps(dock.rotation_page) == (2, 2)
    assert dock.rotation_page.space() == "local"

    child_set_dock_host.resize(qt.QSize(390, 330))
    _process_events(qt_application)
    assert child_translate_ui.show() is dock
    _process_events(qt_application)
    assert dock.tabs.currentIndex() == 0
    assert child_set_dock_host.size == qt.QSize(370, 240)
    assert child_rotation_ui.show("rotate") is dock
    _process_events(qt_application)
    assert dock.rotation_page.target() == "rotate"
    assert child_set_dock_host.size == qt.QSize(390, 330)

    # 内側controlとの寸法差がタブ切替を繰り返しても累積しない
    for _ in range(10):
        dock.tabs.setCurrentIndex(0)
        _process_events(qt_application)
        assert child_set_dock_host.size == qt.QSize(370, 240)
        dock.tabs.setCurrentIndex(1)
        _process_events(qt_application)
        assert child_set_dock_host.size == qt.QSize(390, 330)

    # タブを変えずに手動変更した外枠の寸法もドック移動後へ引き継ぐ
    child_set_dock_host.resize(qt.QSize(405, 345))
    _process_events(qt_application)

    # ドック中はタブを変えても周囲のMayaパネル寸法を変えない
    child_set_dock_host.floating = False
    dock.floating_changed.emit(False)
    child_set_dock_host.resize(qt.QSize(480, 420))
    dock.tabs.setCurrentIndex(0)
    _process_events(qt_application)
    assert child_set_dock_host.size == qt.QSize(480, 420)
    child_set_dock_host.floating = True
    dock.floating_changed.emit(True)
    _process_events(qt_application)
    assert child_set_dock_host.size == qt.QSize(370, 240)

    dock.tabs.setCurrentIndex(1)
    _process_events(qt_application)
    assert child_set_dock_host.size == qt.QSize(405, 345)
    next_node = cmds.createNode("transform", name="nextControllerTarget")
    cmds.select(next_node, replace=True)
    _process_events(qt_application)
    assert next_node in dock.rotation_page.target_label.text()
    cmds.flushUndo()
    dock.tabs.setCurrentIndex(0)
    _process_events(qt_application)
    assert next_node in dock.translate_page.target_label.text()
    dock.tabs.setCurrentIndex(1)
    _process_events(qt_application)
    assert _xyz(node, "translate") == (0.0, 0.0, 0.0)
    assert _xyz(node, "rotate") == (0.0, 0.0, 0.0)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    child_set_ui.close()
    assert dock.is_disposed
    assert dock.translate_page.is_disposed
    assert dock.rotation_page.is_disposed
    assert child_set_dock_host.window is None
    reopened = child_set_ui.show()
    _process_events(qt_application)
    assert reopened is not dock
    assert reopened.tabs.currentIndex() == 1
    assert child_set_dock_host.size == qt.QSize(405, 345)
    child_translate_ui.show()
    _process_events(qt_application)
    assert reopened.tabs.currentIndex() == 0
    assert child_set_dock_host.size == qt.QSize(370, 240)


def test_child_set_rotation_first_keeps_unshown_translate_default(
    clean_scene: None,
    child_set_dock_host: _ChildSetDockHost,
    qt_application: qt.QApplication,
) -> None:
    """回転から初回起動しても未表示の移動タブの規定値を保持する。"""
    del clean_scene
    node = cmds.createNode("transform", name="rotationFirstTarget")
    cmds.select(node, replace=True)
    dock = child_rotation_ui.show("rotate")

    # 初期タブの確定前にMayaの浮動枠が回転ページの高さへ広がる
    child_set_dock_host.resize(
        qt.QSize(ROTATION_INITIAL_WIDTH, ROTATION_INITIAL_HEIGHT)
    )
    _process_events(qt_application)
    assert dock.tabs.currentIndex() == 1
    assert child_set_dock_host.size == qt.QSize(
        ROTATION_INITIAL_WIDTH, ROTATION_INITIAL_HEIGHT
    )

    dock.tabs.setCurrentIndex(0)
    _process_events(qt_application)
    assert child_set_dock_host.size == qt.QSize(
        TRANSLATE_INITIAL_WIDTH, TRANSLATE_INITIAL_HEIGHT
    )


def test_child_set_rotation_combo_order_and_selection_by_attribute(
    clean_scene: None,
    child_set_dock_host: _ChildSetDockHost,
    qt_application: qt.QApplication,
) -> None:
    """ノード別の候補順と属性名による選択・補償先の初期値を確認する。"""
    del clean_scene, child_set_dock_host
    transform = cmds.createNode("transform", name="comboOrderTransform")
    joint = cmds.createNode("joint", name="comboOrderJoint")
    cmds.select(transform, replace=True)
    dock = child_rotation_ui.show("rotateAxis")
    _process_events(qt_application)
    rotation = dock.rotation_page
    target = rotation.target_combo
    compensation = rotation.joint_child_combo
    assert target is not None
    assert compensation is not None
    assert tuple(
        target.itemData(index) for index in range(target.count())
    ) == (
        "rotate",
        "rotateAxis",
    )
    assert target.currentData() == "rotateAxis"
    assert tuple(
        compensation.itemData(index) for index in range(compensation.count())
    ) == ("jointOrient", "rotate")
    assert compensation.currentData() == "rotate"

    cmds.select(joint, replace=True)
    _process_events(qt_application)
    assert tuple(
        target.itemData(index) for index in range(target.count())
    ) == (
        "jointOrient",
        "rotate",
        "rotateAxis",
    )
    assert target.currentData() == "rotateAxis"
    assert compensation.currentData() == "rotate"

    child_rotation_ui.show("jointOrient")
    _process_events(qt_application)
    assert target.currentData() == "jointOrient"
    assert rotation.target() == "jointOrient"
    cmds.select(transform, replace=True)
    _process_events(qt_application)
    assert tuple(
        target.itemData(index) for index in range(target.count())
    ) == (
        "rotate",
        "rotateAxis",
    )
    assert target.currentData() == "rotate"
    assert rotation.target() == "rotate"


def test_child_set_options_restore_after_close(
    clean_scene: None,
    child_set_dock_host: _ChildSetDockHost,
    qt_application: qt.QApplication,
) -> None:
    """移動と回転の選択設定を保存し、再生成後も各タブへ復元する。"""
    del clean_scene
    node = cmds.createNode("joint", name="savedOptionsTarget")
    cmds.select(node, replace=True)
    cmds.flushUndo()
    dock = child_translate_ui.show()
    _process_events(qt_application)
    translate = dock.translate_page
    rotation = dock.rotation_page
    translate.space_combo.setCurrentIndex(
        translate.space_combo.findData("world")
    )
    rotation.space_combo.setCurrentIndex(
        rotation.space_combo.findData("world")
    )
    assert rotation.preservation_combo is not None
    rotation.preservation_combo.setCurrentIndex(
        rotation.preservation_combo.findData("orientation")
    )
    assert rotation.joint_child_combo is not None
    rotation.joint_child_combo.setCurrentIndex(
        rotation.joint_child_combo.findData("jointOrient")
    )
    child_rotation_ui.show("jointOrient")
    _process_events(qt_application)
    assert rotation.target() == "jointOrient"
    assert not rotation.compensate_child_translate()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    child_set_ui.close()
    assert child_set_dock_host.window is None
    reopened = child_set_ui.show()
    _process_events(qt_application)
    assert reopened is not dock
    assert reopened.translate_page.space() == "world"
    assert reopened.rotation_page.space() == "world"
    assert reopened.rotation_page.preservation_combo is not None
    assert (
        reopened.rotation_page.preservation_combo.currentData()
        == "orientation"
    )
    assert reopened.rotation_page.joint_child_compensation_attr() == (
        "jointOrient"
    )
    assert not reopened.rotation_page.compensate_child_translate()
    assert reopened.rotation_page.target() == "rotate"
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_pose_window_controller_reuses_and_disposes(
    clean_scene: None, qt_application: qt.QApplication
) -> None:
    """姿勢維持Windowの再利用と表示内容、監視終了を確認する。"""
    del clean_scene
    node = cmds.createNode("transform", name="poseControllerTarget")
    cmds.select(node, replace=True)
    pose = rotation_set_ui.show("rotateAxis")
    try:
        _process_events(qt_application)
        _assert_step_fields_visible(pose)
        assert _xyz_vertical_gaps(pose) == (2, 2)
        set_label = pose.target_attribute_label
        absorb_label = pose.compensation_attribute_label
        assert set_label.geometry().left() == absorb_label.geometry().left()
        assert pose.target_combo.geometry().left() == (
            pose.compensation_combo.geometry().left()
        )
        assert (
            set_label.geometry().center().y()
            < absorb_label.geometry().center().y()
        )
        for label, combo in (
            (set_label, pose.target_combo),
            (absorb_label, pose.compensation_combo),
        ):
            assert label.geometry().right() < combo.geometry().left()
            assert (
                abs(
                    label.geometry().center().y()
                    - combo.geometry().center().y()
                )
                <= 1
            )
        separator = pose.target_separator
        assert separator.frameShape() == qt.QFrame.Shape.HLine
        assert pose.target_label.geometry().bottom() < (
            separator.geometry().center().y()
        )
        assert separator.geometry().bottom() < set_label.geometry().top()
        assert rotation_set_ui.show("rotate") is pose
        assert pose.target() == "rotate"
    finally:
        rotation_set_ui.close()
    assert pose.is_disposed
    _process_events(qt_application)
