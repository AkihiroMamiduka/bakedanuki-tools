# coding: utf-8
"""ドッキング用公開APIと入力・監視のlifecycleを検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest
from maya import cmds

from bd_util.maya.ui import MayaDockableWindow
from bd_util.maya.ui.dock import workspace_control
from bd_util.ui import FloatValueStepSpinBox, qt

if TYPE_CHECKING:
    from bd_tools.bd_channel_box.ui import ChannelBoxWindow


class _WorkspaceHost:
    """batch Mayaで作れないworkspaceControlの格納・削除境界を置き換える。"""

    def __init__(self) -> None:
        """実Qt Windowを保持する格納先と配置削除の記録を初期化する。"""
        self.window: MayaDockableWindow | None = None
        self.state_removed = False

    def attach(self, window: MayaDockableWindow, _pointer: int = 0) -> None:
        """実Windowを格納し、Maya mixinを通さずQtで表示する。"""
        self.window = window
        qt.QWidget.setVisible(window, True)

    def delete(self, _name: str) -> None:
        """Mayaがcontrol配下のQt objectを削除する経路を再現する。"""
        window, self.window = self.window, None
        if window is not None:
            window.hide()
            window.deleteLater()

    def remove_state(self, _name: str) -> None:
        """保存配置の削除を記録する。"""
        self.state_removed = True


def _events() -> None:
    """遅延削除と選択通知を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _step_view(window: ChannelBoxWindow, path: str) -> FloatValueStepSpinBox:
    """公開Window内の属性pathからStep付き数値Viewを取得する。"""
    from bd_tools.bd_channel_box.widget import AttributeRowWidget

    widget = window.widget
    row = next(
        row
        for row in widget.row_widgets
        if isinstance(row, AttributeRowWidget)
        and row.row.attribute.path == path
    )
    assert isinstance(row.editor, FloatValueStepSpinBox)
    return row.editor


def _write_custom_filter(
    path: Path,
    name: str,
    node_types: dict[str, list[str]] | None = None,
) -> None:
    """管理画面の検証用に共有可能な最小のフィルター定義を書く。"""
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": name,
                "node_types": (
                    node_types
                    if node_types is not None
                    else {"transform": ["visibility"]}
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _select_registration_rows(
    tree: qt.QTreeWidget, indexes: tuple[int, ...]
) -> None:
    """指定した行を選択し、先頭の指定行を現在行にする。"""
    tree.clearSelection()
    if indexes:
        tree.setCurrentItem(tree.topLevelItem(indexes[0]))
        for index in indexes:
            tree.topLevelItem(index).setSelected(True)


def _selected_registration_paths(tree: qt.QTreeWidget) -> tuple[str, ...]:
    """選択された登録のパスを表示順に返す。"""
    return tuple(
        path
        for index in range(tree.topLevelItemCount())
        if (item := tree.topLevelItem(index)).isSelected()
        if isinstance(path := item.data(0, qt.Qt.ItemDataRole.UserRole), str)
    )


def _registration_eye_position(tree: qt.QTreeWidget, index: int) -> qt.QPoint:
    """表示されている登録行の目アイコン中央を返す。"""
    rect = tree.visualItemRect(tree.topLevelItem(index))
    return qt.QPoint(rect.left() + 12, rect.center().y())


def _send_registration_mouse(
    tree: qt.QTreeWidget,
    kind: qt.QEvent.Type,
    position: qt.QPoint,
    button: qt.Qt.MouseButton = qt.Qt.MouseButton.LeftButton,
) -> None:
    """登録一覧のviewportへ押下・移動・解放を個別に送る。"""
    viewport = tree.viewport()
    event = qt.QtGui.QMouseEvent(
        kind,
        qt.QPointF(position),
        qt.QPointF(viewport.mapToGlobal(position)),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseMove
            else button
        ),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseButtonRelease
            else button
        ),
        qt.Qt.KeyboardModifier.NoModifier,
    )
    qt.QApplication.sendEvent(viewport, event)


def _click_registration_eye(tree: qt.QTreeWidget, index: int) -> None:
    """登録行の目アイコンを実マウス入力で一度クリックする。"""
    position = _registration_eye_position(tree, index)
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonPress, position)
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonRelease, position)
    _events()


@pytest.fixture
def dock_host(
    qt_application: qt.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[_WorkspaceHost]:
    """実controller・入力UIを使い、Mayaの画面操作だけを置き換える。"""
    from bd_tools import bd_channel_box
    from bd_util.maya.ui import settings as maya_settings

    assert qt_application is not None
    host = _WorkspaceHost()

    def show_dockable(window: MayaDockableWindow, **_options: object) -> None:
        """controllerの初回表示をQtの格納先へ接続する。"""
        host.attach(window)

    # Mayaの画面を作らないqueryと配置操作にも具体的な型を与える
    exists: Callable[[str], bool] = lambda _n: host.window is not None
    restore: Callable[[str], None] = lambda _n: None
    state_exists: Callable[[str], bool] = lambda _n: True
    schedule: Callable[[str, qt.QWidget], None] = lambda _n, _w: None
    monkeypatch.setattr(MayaDockableWindow, "show", show_dockable)
    monkeypatch.setattr(workspace_control, "exists", exists)
    monkeypatch.setattr(workspace_control, "restore", restore)
    monkeypatch.setattr(workspace_control, "delete", host.delete)
    monkeypatch.setattr(workspace_control, "current_parent", lambda: 1)
    monkeypatch.setattr(workspace_control, "attach", host.attach)
    monkeypatch.setattr(workspace_control, "state_exists", state_exists)
    monkeypatch.setattr(workspace_control, "remove_state", host.remove_state)
    monkeypatch.setattr(
        workspace_control, "schedule_ensure_on_screen", schedule
    )
    monkeypatch.setattr(
        maya_settings, "get_ui_settings_root", lambda: tmp_path
    )
    cmds.select(clear=True)
    bd_channel_box.dispose()
    yield host
    # reloadした場合も最新moduleのcontrollerを終了する
    from bd_tools import bd_channel_box as current

    current.dispose()
    _events()


def test_dock_show_close_and_reload_release_bindings(
    dock_host: _WorkspaceHost,
) -> None:
    """重複表示せず、公開closeとreloadで入力controllerを即時に終了する。"""
    import bd_tools
    from bd_tools import bd_channel_box

    first = bd_channel_box.show()
    assert first is dock_host.window
    assert first.objectName() == "bdChannelBoxWindow"
    assert first.windowTitle() == "bdChannelBox"
    assert (
        bd_channel_box.WORKSPACE_CONTROL_NAME
        == "bdChannelBoxWindowWorkspaceControl"
    )
    assert bd_channel_box.show() is first
    bd_channel_box.close()
    assert first.widget.controller.is_disposed
    assert dock_host.window is None
    second = bd_channel_box.show()
    assert second is not first
    old_controller = second.widget.controller
    bd_tools.reload_package()
    assert old_controller.is_disposed
    from bd_tools import bd_channel_box as current

    reopened = dock_host.window
    assert reopened is not None
    assert reopened is not second
    assert current.show() is reopened
    _events()
    assert not qt.isValid(first)
    assert not qt.isValid(second)
    assert qt.isValid(reopened)


def test_closed_dock_is_not_reopened(dock_host: _WorkspaceHost) -> None:
    """ユーザーが閉じたtoolはreload後の表示対象に含めない。"""
    import bd_tools

    from bd_tools import bd_channel_box

    bd_channel_box.show()
    bd_channel_box.close()
    bd_tools.reload_package()
    assert dock_host.window is None


def test_maya_dock_close_signal_stops_selection_watch(
    dock_host: _WorkspaceHost,
) -> None:
    """Mayaのタイトルバーclose通知だけでも選択監視と入力を終了する。"""
    from bd_tools import bd_channel_box
    from bd_util.maya.ui import snapshot_open_tools

    window = bd_channel_box.show()
    window.dock_closed.emit()
    assert window.widget.controller.is_disposed
    assert not window.widget.controller.rows
    assert snapshot_open_tools("bd_tools") == ()
    # Qt削除より先に再表示しても、終了済みの入力UIを再利用しない
    replacement = bd_channel_box.show()
    assert replacement is not window
    assert replacement is dock_host.window
    assert not replacement.widget.controller.is_disposed


def test_ui_script_restore_and_layout_reset(dock_host: _WorkspaceHost) -> None:
    """復元入口の同一Window再利用と、統合resetによる再生成を確認する。"""
    from bd_tools import bd_channel_box
    from bd_util.maya.ui import restore_dockable
    from bd_util.maya.ui import snapshot_open_tools

    node = cmds.createNode("transform", name="channelBoxResetTarget")
    cmds.select(node, replace=True)
    window = restore_dockable("bd_tools.bd_channel_box.ui", "restore")
    assert isinstance(window, bd_channel_box.ChannelBoxWindow)
    assert window is dock_host.window
    assert snapshot_open_tools("bd_tools") == (
        ("bd_tools", "bd_channel_box", "bd_tools.bd_channel_box.ui", "show"),
    )
    assert bd_channel_box.show() is window
    assert (
        window.objectName() + "WorkspaceControl"
        == bd_channel_box.WORKSPACE_CONTROL_NAME
    )
    new_window = bd_channel_box.reset_layout()
    assert dock_host.state_removed
    assert window.widget.controller.is_disposed
    assert new_window is not window
    assert new_window is dock_host.window
    _events()
    assert new_window.widget.row_widgets
    assert qt.isValid(new_window.widget.table_view.viewport())
    new_window.widget.refresh()
    _events()
    assert new_window.widget.row_widgets


def test_wheel_preference_persists_and_layout_reset_keeps_it(
    dock_host: _WorkspaceHost,
) -> None:
    """ホイール設定を再生成後へ復元し、配置リセットでは削除しない。"""
    from bd_tools import bd_channel_box

    first = bd_channel_box.show()
    _events()
    assert not first.widget.wheel_editing_action.isChecked()
    first.widget.wheel_editing_action.setChecked(True)
    bd_channel_box.close()
    _events()

    reopened = bd_channel_box.show()
    _events()
    assert reopened.widget.wheel_editing_action.isChecked()
    reset = bd_channel_box.reset_layout()
    _events()
    assert reset is dock_host.window
    assert reset.widget.wheel_editing_action.isChecked()


def test_step_profile_persists_and_layout_reset_keeps_it(
    dock_host: _WorkspaceHost,
) -> None:
    """属性Stepをclose後へ復元し、配置リセットでも削除しない。"""
    from bd_tools import bd_channel_box

    node = cmds.createNode("transform", name="channelBoxStepTarget")
    cmds.addAttr(node, longName="count", attributeType="long", keyable=True)
    cmds.select(node, replace=True)
    first = bd_channel_box.show()
    _events()
    _step_view(first, "translate.translateX").setSingleStep(2.5)
    _step_view(first, "rotate.rotateY").setSingleStep(7.5)
    from bd_util.ui import IntValueStepSpinBox

    integer = next(
        row.editor
        for row in first.widget.row_widgets
        if row.row.attribute.path == "count"
    )
    assert isinstance(integer, IntValueStepSpinBox)
    integer.setSingleStep(15)
    assert len(first.widget.step_profile.entries) == 2
    cmds.flushUndo()
    bd_channel_box.close()
    _events()

    reopened = bd_channel_box.show()
    _events()
    assert _step_view(reopened, "translate.translateX").singleStep() == 2.5
    assert _step_view(reopened, "rotate.rotateY").singleStep() == 7.5
    integer = next(
        row.editor
        for row in reopened.widget.row_widgets
        if row.row.attribute.path == "count"
    )
    assert isinstance(integer, IntValueStepSpinBox)
    assert integer.singleStep() == 15
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    reset = bd_channel_box.reset_layout()
    _events()
    assert reset is dock_host.window
    assert _step_view(reset, "translate.translateX").singleStep() == 2.5
    assert _step_view(reset, "rotate.rotateY").singleStep() == 7.5
    integer = next(
        row.editor
        for row in reset.widget.row_widgets
        if row.row.attribute.path == "count"
    )
    assert isinstance(integer, IntValueStepSpinBox)
    assert integer.singleStep() == 15
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("visibility", ("never", "all_only", "always"))
def test_search_visibility_preference_persists_without_query(
    dock_host: _WorkspaceHost,
    visibility: Literal["never", "all_only", "always"],
) -> None:
    """検索欄の表示方針だけを再生成後へ復元し、検索文字列は破棄する。"""
    from bd_tools import bd_channel_box

    first = bd_channel_box.show()
    _events()
    assert first.widget.search_visibility == "all_only"
    first.widget.search_visibility_actions[visibility].setChecked(True)
    first.widget.search_edit.setText("translate")
    bd_channel_box.close()
    _events()

    reopened = bd_channel_box.show()
    _events()
    assert reopened.widget.search_visibility == visibility
    assert reopened.widget.search_edit.text() == ""
    reset = bd_channel_box.reset_layout()
    _events()
    assert reset is dock_host.window
    assert reset.widget.search_visibility == visibility
    assert reset.widget.search_edit.text() == ""


def test_custom_filter_manager_keeps_errors_and_controls_visibility(
    dock_host: _WorkspaceHost,
    tmp_path: Path,
) -> None:
    """旧表示名が同じJSONをファイル名で区別し、読込状態と一覧操作を確認する。"""
    from bd_tools import bd_channel_box
    from bd_tools.bd_channel_box.custom_filters import (
        CustomFilterSelection,
        normalize_filter_path,
    )

    first = tmp_path / "rig_first.json"
    second = tmp_path / "rig_second.json"
    broken = tmp_path / "broken.json"
    _write_custom_filter(first, "Rig")
    _write_custom_filter(second, "Rig")
    broken.write_text("{", encoding="utf-8")
    window = bd_channel_box.show()
    widget = window.widget
    paths = widget.custom_filter_registry.add_paths((first, second, broken))
    assert paths == tuple(
        normalize_filter_path(path) for path in (first, second, broken)
    )
    assert len(widget.custom_filter_registry.entries) == 3
    assert widget.custom_filter_registry.entries[2].error is not None
    assert widget.filter_combo.count() == 7
    assert widget.filter_combo.itemText(5) == f"Custom: {first.stem}"
    assert widget.filter_combo.itemText(6) == f"Custom: {second.stem}"
    first_selection = widget.filter_combo.itemData(5)
    assert isinstance(first_selection, CustomFilterSelection)
    assert widget.filter_combo.findData(first_selection) == 5
    with pytest.raises(ValueError):
        widget.custom_filter_registry.add_paths((tmp_path / "third.json", ""))
    assert len(widget.custom_filter_registry.entries) == 3

    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None and dialog.isVisible()
    tree = dialog.tree_widget
    assert tree.topLevelItemCount() == 3
    assert tree.columnCount() == 3
    assert not tree.rootIsDecorated()
    assert not tree.isSortingEnabled()
    assert tree.topLevelItem(0).text(0) == first.stem
    assert tree.topLevelItem(0).text(1) == paths[0]
    assert tree.topLevelItem(0).toolTip(1) == paths[0]
    assert tree.topLevelItem(0).text(2) == "済"
    assert tree.topLevelItem(2).text(2) == "読込エラー"
    read_error = widget.custom_filter_registry.entries[2].error
    assert read_error is not None
    assert read_error in tree.topLevelItem(2).toolTip(2)
    assert dialog.storage_error_label.isHidden()
    widget.filter_combo.setCurrentIndex(5)
    widget.mode_combo.setCurrentIndex(1)
    widget.filter_combo.setCurrentIndex(5)
    tree.topLevelItem(0).setCheckState(0, qt.Qt.CheckState.Unchecked)
    assert widget.controller.attribute_filter == "all"
    widget.mode_combo.setCurrentIndex(0)
    assert widget.controller.attribute_filter == "visible"
    assert widget.filter_combo.count() == 6
    assert widget.custom_filter_registry.entries[0].enabled is False

    widget.filter_combo.setCurrentIndex(5)
    selected = widget.controller.attribute_filter
    assert isinstance(selected, CustomFilterSelection)
    _select_registration_rows(tree, (1,))
    dialog.move_up_button.click()
    assert widget.custom_filter_registry.entries[0].path == paths[1]
    assert widget.filter_combo.itemData(5).path == paths[1]
    assert widget.controller.attribute_filter == selected
    assert widget.filter_combo.currentIndex() == 5
    _write_custom_filter(broken, "Fixed")
    _select_registration_rows(tree, (2,))
    widget.custom_filter_registry.save()
    dialog.reload_all_button.click()
    assert widget.custom_filter_registry.entries[2].error is None
    assert tree.topLevelItem(2).text(2) == "済"
    assert "読込エラー" not in tree.topLevelItem(2).toolTip(2)
    assert widget.filter_combo.count() == 7
    tree.topLevelItem(1).setCheckState(0, qt.Qt.CheckState.Checked)
    assert widget.filter_combo.count() == 8
    assert widget.filter_combo.itemData(6).path == paths[0]
    _select_registration_rows(tree, (1,))
    widget.custom_filter_registry.save()
    dialog.remove_button.click()
    assert first.is_file()
    assert tuple(
        entry.path for entry in widget.custom_filter_registry.entries
    ) == (paths[1], paths[2])


def test_custom_filter_manager_repositions_from_menu_and_setup_icon(
    dock_host: _WorkspaceHost,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """両入口の操作位置へ同じ画面を再配置し、手動サイズと選択を維持する。"""
    from bd_tools import bd_channel_box

    available = qt.QRect(100, 200, 1600, 1000)

    class Screen:
        """タスクバーを除く検証用のモニター領域を返す。"""

        def availableGeometry(self) -> qt.QRect:
            """モニターの作業領域を返す。"""
            return available

    screen = Screen()
    anchor = qt.QPoint(900, 700)
    queried: list[qt.QPoint] = []

    def cursor_position() -> qt.QPoint:
        """各入口を操作した時点のカーソル位置を返す。"""
        return qt.QPoint(anchor)

    def screen_at(position: qt.QPoint) -> Screen:
        """操作位置でモニターが選択されたことを記録する。"""
        queried.append(qt.QPoint(position))
        return screen

    monkeypatch.setattr(qt.QCursor, "pos", cursor_position)
    monkeypatch.setattr(qt.QtGui.QGuiApplication, "screenAt", screen_at)
    files = tuple(tmp_path / f"{name}.json" for name in "ABC")
    for path in files:
        _write_custom_filter(path, path.stem)
    widget = bd_channel_box.show().widget
    paths = widget.custom_filter_registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    _events()
    dialog = widget.custom_filter_dialog
    assert dialog is not None and dialog.isVisible()
    assert available.contains(dialog.frameGeometry())
    assert (dialog.frameGeometry().center() - anchor).manhattanLength() <= 2
    assert queried[-1] == anchor
    tree = dialog.tree_widget
    _select_registration_rows(tree, (1, 2))
    current = tree.currentItem()
    widget.custom_filter_registry.set_enabled(paths[0], False)
    enabled = tuple(
        entry.enabled for entry in widget.custom_filter_registry.entries
    )

    # 表示中の再操作でも歯車側の位置へ寄せ、変更済みのサイズを維持する
    dialog.resize(900, 520)
    _events()
    size = dialog.size()
    anchor = available.bottomRight()
    widget.mode_combo.setCurrentIndex(2)
    widget.setup_panel.manage_button.click()
    _events()
    assert widget.custom_filter_dialog is dialog
    assert dialog.size() == size
    assert available.contains(dialog.frameGeometry())
    assert dialog.frameGeometry().bottomRight() == available.bottomRight()
    assert queried[-1] == anchor
    assert _selected_registration_paths(tree) == (paths[1], paths[2])
    assert tree.currentItem() is current
    assert (
        tuple(entry.enabled for entry in widget.custom_filter_registry.entries)
        == enabled
    )

    # 閉じてからのメニュー操作でも再生成せず、今回の位置へ再配置する
    dialog.close()
    anchor = available.topLeft()
    widget.manage_custom_filters_action.trigger()
    _events()
    assert widget.custom_filter_dialog is dialog and dialog.isVisible()
    assert dialog.size() == size
    assert dialog.frameGeometry().topLeft() == available.topLeft()
    assert _selected_registration_paths(tree) == (paths[1], paths[2])
    assert tree.currentItem() is current


@pytest.mark.parametrize(
    "work_area",
    ((0, 0, 640, 360), (-1400, 40, 900, 500), (80, -850, 500, 300)),
)
def test_custom_filter_manager_shrinks_to_clicked_screen(
    dock_host: _WorkspaceHost,
    monkeypatch: pytest.MonkeyPatch,
    work_area: tuple[int, int, int, int],
) -> None:
    """負座標のモニターも含め、作業領域より大きい外枠を縮小して収める。"""
    from bd_tools import bd_channel_box

    available = qt.QRect(*work_area)
    queried: list[qt.QPoint] = []

    class Screen:
        """指定したモニターの作業領域を返す。"""

        def availableGeometry(self) -> qt.QRect:
            """負座標や狭い画面も含む作業領域を返す。"""
            return available

    def screen_at(position: qt.QPoint) -> Screen:
        """要求された操作位置を記録し、対象モニターを返す。"""
        queried.append(qt.QPoint(position))
        return Screen()

    monkeypatch.setattr(qt.QtGui.QGuiApplication, "screenAt", screen_at)
    widget = bd_channel_box.show().widget
    widget.manage_custom_filters_action.trigger()
    _events()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    border_tolerance = 0
    if available.left() < 0 or available.top() < 0:
        # offscreenは実在しない負座標へ枠の分だけずらすため、仮想画面では枠を外す
        # nativeのタイトルバーを含む補正はMaya本体の検証で確認する
        dialog.setWindowFlag(qt.Qt.WindowType.FramelessWindowHint, True)
        dialog.show()
        _events()
        border_tolerance = 4
    dialog.resize(1500, 1000)
    anchor = available.bottomRight()
    dialog.show_near(anchor)
    _events()
    assert queried[-1] == anchor
    assert available.contains(dialog.frameGeometry())
    assert (
        dialog.frameGeometry().bottomRight() - available.bottomRight()
    ).manhattanLength() <= border_tolerance
    fitted_size = dialog.size()
    assert fitted_size.width() < 1500 and fitted_size.height() < 1000
    dialog.show_near(available.topLeft())
    _events()
    assert dialog.size() == fitted_size
    assert available.contains(dialog.frameGeometry())
    assert (
        dialog.frameGeometry().topLeft() - available.topLeft()
    ).manhattanLength() <= border_tolerance


def test_custom_filter_manager_multiselection_reorders_reloads_and_removes(
    dock_host: _WorkspaceHost, tmp_path: Path
) -> None:
    """複数行の一括移動・登録解除と、表示チェックから独立した選択を保つ。"""
    from bd_tools import bd_channel_box

    files = tuple(tmp_path / f"{name}.json" for name in "ABCDE")
    for path in files:
        _write_custom_filter(path, path.stem)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None and dialog.isVisible()
    tree = dialog.tree_widget
    assert (
        tree.selectionMode()
        == qt.QAbstractItemView.SelectionMode.ExtendedSelection
    )
    assert (
        tree.selectionBehavior()
        == qt.QAbstractItemView.SelectionBehavior.SelectRows
    )

    # 離れた選択も元の相対順を保ち、端に達したら全体を動かさない
    _select_registration_rows(tree, (1, 3))
    assert _selected_registration_paths(tree) == (paths[1], paths[3])
    assert not dialog.duplicate_button.isEnabled()
    assert dialog.move_up_button.isEnabled()
    assert dialog.move_down_button.isEnabled()
    dialog.move_up_button.click()
    assert tuple(entry.path for entry in registry.entries) == (
        paths[1],
        paths[0],
        paths[3],
        paths[2],
        paths[4],
    )
    assert _selected_registration_paths(tree) == (paths[1], paths[3])
    assert not dialog.move_up_button.isEnabled()
    dialog.move_up_button.click()
    assert registry.entries[0].path == paths[1]
    dialog.move_down_button.click()
    assert tuple(entry.path for entry in registry.entries) == paths

    # チェックと全件再読込は、複数の操作対象と現在行を変更しない
    current_item = tree.currentItem()
    checkbox_item = tree.topLevelItem(4)
    checkbox_item.setCheckState(0, qt.Qt.CheckState.Unchecked)
    assert tree.topLevelItem(4) is checkbox_item
    assert tree.currentItem() is current_item
    assert not registry.entries[4].enabled
    assert _selected_registration_paths(tree) == (paths[1], paths[3])
    assert tree.currentItem().data(0, qt.Qt.ItemDataRole.UserRole) == paths[1]
    _write_custom_filter(files[1], "Updated B", {"transform": ["visibility"]})
    registry.save()
    dialog.reload_all_button.click()
    assert tree.currentItem() is current_item
    assert tree.topLevelItem(1).text(0) == "B"
    assert registry.entries[1].definition is not None
    assert registry.entries[1].definition.node_types == {
        "transform": ("visibility",)
    }
    assert not registry.entries[4].enabled
    assert _selected_registration_paths(tree) == (paths[1], paths[3])
    assert tree.currentItem().data(0, qt.Qt.ItemDataRole.UserRole) == paths[1]

    # 連続行もひとまとまりで移動し、複製は単一選択時だけ許可する
    _select_registration_rows(tree, (1,))
    assert dialog.duplicate_button.isEnabled()
    _select_registration_rows(tree, (1, 2))
    assert not dialog.duplicate_button.isEnabled()
    dialog.move_down_button.click()
    assert tuple(entry.path for entry in registry.entries) == (
        paths[0],
        paths[3],
        paths[1],
        paths[2],
        paths[4],
    )
    dialog.move_down_button.click()
    assert tuple(entry.path for entry in registry.entries) == (
        paths[0],
        paths[3],
        paths[4],
        paths[1],
        paths[2],
    )
    assert _selected_registration_paths(tree) == (paths[1], paths[2])
    assert not dialog.move_down_button.isEnabled()
    dialog.move_down_button.click()
    assert registry.entries[-1].path == paths[2]

    registry.save()
    dialog.remove_button.click()
    assert tuple(entry.path for entry in registry.entries) == (
        paths[0],
        paths[3],
        paths[4],
    )
    assert all(path.is_file() for path in files)
    tree.clearSelection()
    assert not dialog.duplicate_button.isEnabled()
    assert not dialog.remove_button.isEnabled()
    assert not dialog.move_up_button.isEnabled()
    assert not dialog.move_down_button.isEnabled()


def test_custom_filter_manager_visibility_click_preserves_selection_and_scroll(
    dock_host: _WorkspaceHost, tmp_path: Path
) -> None:
    """目だけの切替は複数選択・現在行・スクロールを保ち、個人設定へ保存する。"""
    from bd_tools import bd_channel_box

    files = tuple(tmp_path / f"filter_{index:02}.json" for index in range(24))
    for path in files:
        _write_custom_filter(path, path.stem)
    original_bytes = tuple(path.read_bytes() for path in files)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _select_registration_rows(tree, (20, 22))
    tree.scrollToItem(tree.topLevelItem(23))
    _events()
    scroll = tree.verticalScrollBar().value()
    assert scroll > 0
    current = tree.currentItem()
    item = tree.topLevelItem(21)
    assert tree.visualItemRect(item).intersects(tree.viewport().rect())
    position = _registration_eye_position(tree, 21)

    # 押下中は未確定とし、同じ目の上で解放して一件だけ変更する
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonPress, position)
    assert registry.entries[21].enabled
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonRelease, position)
    _events()
    assert tuple(entry.enabled for entry in registry.entries) == tuple(
        index != 21 for index in range(len(files))
    )
    assert item.checkState(0) == qt.Qt.CheckState.Unchecked
    assert _selected_registration_paths(tree) == (paths[20], paths[22])
    assert tree.currentItem() is current
    assert tree.verticalScrollBar().value() == scroll
    assert widget.filter_combo.count() == 5 + len(files) - 1
    assert tuple(path.read_bytes() for path in files) == original_bytes

    # Window再生成でも共通保存で確定した表示設定を復元する
    registry.save()
    bd_channel_box.close()
    _events()
    reopened = bd_channel_box.show().widget
    assert tuple(
        (entry.path, entry.enabled)
        for entry in reopened.custom_filter_registry.entries
    ) == tuple((path, index != 21) for index, path in enumerate(paths))
    assert reopened.filter_combo.count() == 5 + len(files) - 1


def test_custom_filter_manager_visibility_cancels_mouse_gestures(
    dock_host: _WorkspaceHost, tmp_path: Path
) -> None:
    """目以外への解放・ドラッグ・右クリックは表示状態を変更しない。"""
    from bd_tools import bd_channel_box

    files = tuple(tmp_path / f"{name}.json" for name in "ABC")
    for path in files:
        _write_custom_filter(path, path.stem)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _events()
    _select_registration_rows(tree, (1, 2))
    current = tree.currentItem()
    first = _registration_eye_position(tree, 0)
    second = _registration_eye_position(tree, 1)
    name = first + qt.QPoint(14, 0)

    # 同じ行でも名前部分の解放や別行の目への解放では確定しない
    for release in (name, second):
        _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonPress, first)
        _send_registration_mouse(tree, qt.QEvent.Type.MouseMove, release)
        _send_registration_mouse(
            tree, qt.QEvent.Type.MouseButtonRelease, release
        )
        assert all(entry.enabled for entry in registry.entries)
    assert _selected_registration_paths(tree) == (paths[1], paths[2])
    assert tree.currentItem() is current

    # 閾値を越えてドラッグした操作は元の目へ戻っても切り替えない
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonPress, first)
    _send_registration_mouse(tree, qt.QEvent.Type.MouseMove, name)
    _send_registration_mouse(tree, qt.QEvent.Type.MouseMove, first)
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonRelease, first)
    # 他のUIがマウスを取得した後の解放も、古い目の操作として確定しない
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonPress, first)
    qt.QApplication.sendEvent(
        tree.viewport(), qt.QEvent(qt.QEvent.Type.UngrabMouse)
    )
    _send_registration_mouse(tree, qt.QEvent.Type.MouseButtonRelease, first)
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        _send_registration_mouse(
            tree, kind, first, qt.Qt.MouseButton.RightButton
        )
    assert all(entry.enabled for entry in registry.entries)

    # 名前は従来の行選択、一覧の余白は通常の一覧操作だけを行う
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        _send_registration_mouse(tree, kind, name)
    assert _selected_registration_paths(tree) == (paths[0],)
    assert tree.currentItem() is tree.topLevelItem(0)
    blank = qt.QPoint(
        12, tree.visualItemRect(tree.topLevelItem(2)).bottom() + 25
    )
    assert tree.viewport().rect().contains(blank)
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        _send_registration_mouse(tree, kind, blank)
    _events()
    assert all(entry.enabled for entry in registry.entries)


@pytest.mark.parametrize("clicked_index", (0, 1))
def test_custom_filter_manager_visibility_aligns_selection(
    dock_host: _WorkspaceHost, tmp_path: Path, clicked_index: int
) -> None:
    """混在する選択を基準行の反対状態へ揃え、選択外の目は一件だけ切り替える。"""
    from bd_tools import bd_channel_box

    files = tuple(tmp_path / f"{name}.json" for name in "ABCDE")
    for path in files:
        _write_custom_filter(path, path.stem)
    original_bytes = tuple(path.read_bytes() for path in files)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    registry.set_enabled_many((paths[1], paths[3]), False)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _events()
    _select_registration_rows(tree, (0, 1, 3))
    current = tree.currentItem()
    scroll = tree.verticalScrollBar().value()
    selected = (paths[0], paths[1], paths[3])
    enabled = clicked_index == 1
    observed: list[tuple[bool, ...]] = []

    def record_change() -> None:
        """一括切替の中間状態が通知されないことを記録する。"""
        observed.append(tuple(entry.enabled for entry in registry.entries))

    registry.changed.connect(record_change)
    _click_registration_eye(tree, clicked_index)
    expected = (enabled, enabled, True, enabled, True)
    assert observed == [expected]
    assert tuple(entry.enabled for entry in registry.entries) == expected
    assert _selected_registration_paths(tree) == selected
    assert tree.currentItem() is current
    assert tree.verticalScrollBar().value() == scroll

    # 全件を揃えた後も基準行の反対へ切り替え、選択外の行は巻き込まない
    _click_registration_eye(tree, clicked_index)
    expected = (not enabled, not enabled, True, not enabled, True)
    assert observed[-1] == expected and len(observed) == 2
    _click_registration_eye(tree, 2)
    assert tuple(entry.enabled for entry in registry.entries) == (
        not enabled,
        not enabled,
        False,
        not enabled,
        True,
    )
    assert len(observed) == 3
    assert _selected_registration_paths(tree) == selected
    assert tree.currentItem() is current
    assert tuple(path.read_bytes() for path in files) == original_bytes


def test_custom_filter_manager_visibility_double_click_and_space(
    dock_host: _WorkspaceHost, tmp_path: Path
) -> None:
    """二重クリックの切替は一度とし、Spaceでは選択と表示設定を変更しない。"""
    from bd_tools import bd_channel_box

    files = tuple(tmp_path / f"{name}.json" for name in "ABC")
    for path in files:
        _write_custom_filter(path, path.stem)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _events()
    _select_registration_rows(tree, (0, 2))
    position = _registration_eye_position(tree, 1)
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
        qt.QEvent.Type.MouseButtonDblClick,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        _send_registration_mouse(tree, kind, position)
    assert tuple(entry.enabled for entry in registry.entries) == (
        True,
        False,
        True,
    )
    assert _selected_registration_paths(tree) == (paths[0], paths[2])
    assert tree.currentItem() is tree.topLevelItem(0)

    # 長押しを含むSpace入力をMaya側へ返し、一覧の選択も変更しない
    for kind, repeated in (
        (qt.QEvent.Type.KeyPress, False),
        (qt.QEvent.Type.KeyRelease, True),
        (qt.QEvent.Type.KeyPress, True),
        (qt.QEvent.Type.KeyRelease, True),
        (qt.QEvent.Type.KeyPress, True),
        (qt.QEvent.Type.KeyRelease, False),
    ):
        qt.QApplication.sendEvent(
            tree,
            qt.QtGui.QKeyEvent(
                kind,
                qt.Qt.Key.Key_Space,
                qt.Qt.KeyboardModifier.NoModifier,
                " ",
                repeated,
                1,
            ),
        )
    assert tuple(entry.enabled for entry in registry.entries) == (
        True,
        False,
        True,
    )
    assert _selected_registration_paths(tree) == (paths[0], paths[2])
    assert tree.currentItem() is tree.topLevelItem(0)


@pytest.mark.parametrize(
    "target_name",
    (
        "tree_widget",
        "new_button",
        "add_button",
        "duplicate_button",
        "remove_button",
        "move_up_button",
        "move_down_button",
        "reload_all_button",
    ),
)
def test_custom_filter_manager_space_passes_to_maya(
    dock_host: _WorkspaceHost, tmp_path: Path, target_name: str
) -> None:
    """一覧と全操作ボタンがSpaceを予約せず、押下・解放を受け流す。"""
    from bd_tools import bd_channel_box

    files = tuple(tmp_path / f"{name}.json" for name in "ABC")
    for path in files:
        _write_custom_filter(path, path.stem)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _select_registration_rows(tree, (1, 2))
    tree.setCurrentItem(
        tree.topLevelItem(0),
        0,
        qt.QItemSelectionModel.SelectionFlag.NoUpdate,
    )
    target = getattr(dialog, target_name)
    assert isinstance(target, qt.QWidget)
    target.setEnabled(True)
    clicked: list[bool] = []
    if isinstance(target, qt.QToolButton):
        target.clicked.connect(clicked.append)

    for modifiers in (
        qt.Qt.KeyboardModifier.NoModifier,
        qt.Qt.KeyboardModifier.ShiftModifier,
        qt.Qt.KeyboardModifier.ControlModifier,
    ):
        for kind, repeated in (
            (qt.QEvent.Type.ShortcutOverride, False),
            (qt.QEvent.Type.KeyPress, False),
            (qt.QEvent.Type.KeyPress, True),
            (qt.QEvent.Type.KeyRelease, False),
        ):
            event = qt.QtGui.QKeyEvent(
                kind, qt.Qt.Key.Key_Space, modifiers, " ", repeated, 1
            )
            assert not target.event(event)
            assert not event.isAccepted()
    assert not clicked
    assert _selected_registration_paths(tree) == (paths[1], paths[2])
    assert tree.currentItem() is tree.topLevelItem(0)
    assert all(entry.enabled for entry in registry.entries)


def test_custom_filter_manager_visibility_follows_registration_path_changes(
    dock_host: _WorkspaceHost, tmp_path: Path
) -> None:
    """並べ替え・再読込・削除・改名後も目が現在の登録パスだけを変更する。"""
    from bd_tools import bd_channel_box
    from bd_tools.bd_channel_box.custom_filters import normalize_filter_path

    files = tuple(tmp_path / f"{name}.json" for name in "ABCD")
    for path in files:
        _write_custom_filter(path, path.stem)
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    paths = registry.add_paths(files)
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _events()

    _select_registration_rows(tree, (1,))
    dialog.move_up_button.click()
    _click_registration_eye(tree, 0)
    assert tuple(
        (entry.path, entry.enabled) for entry in registry.entries
    ) == (
        (paths[1], False),
        (paths[0], True),
        (paths[2], True),
        (paths[3], True),
    )
    _write_custom_filter(files[1], "Updated B", {"transform": ["visibility"]})
    registry.save()
    dialog.reload_all_button.click()
    assert tree.topLevelItem(0).text(0) == "B"
    assert registry.entries[0].definition is not None
    assert registry.entries[0].definition.node_types == {
        "transform": ("visibility",)
    }
    _click_registration_eye(tree, 0)
    assert registry.entries[0].enabled

    _select_registration_rows(tree, (1,))
    registry.save()
    dialog.remove_button.click()
    _click_registration_eye(tree, 1)
    assert tuple(
        (entry.path, entry.enabled) for entry in registry.entries
    ) == (
        (paths[1], True),
        (paths[2], False),
        (paths[3], True),
    )

    renamed = tmp_path / "Renamed C.json"
    files[2].rename(renamed)
    renamed_path = normalize_filter_path(renamed)
    assert registry.replace_path(paths[2], renamed_path)
    assert (
        tree.topLevelItem(1).data(0, qt.Qt.ItemDataRole.UserRole)
        == renamed_path
    )
    _click_registration_eye(tree, 1)
    assert tuple(
        (entry.path, entry.enabled) for entry in registry.entries
    ) == (
        (paths[1], True),
        (renamed_path, True),
        (paths[3], True),
    )
    assert widget.filter_combo.count() == 8


def test_custom_filter_manager_visibility_is_independent_of_read_errors(
    dock_host: _WorkspaceHost, tmp_path: Path
) -> None:
    """読込エラーの行も表示設定を切り替え、JSONと読込結果はそのまま維持する。"""
    from bd_tools import bd_channel_box

    valid = tmp_path / "valid.json"
    broken = tmp_path / "broken.json"
    _write_custom_filter(valid, "Valid")
    broken.write_text("{", encoding="utf-8")
    original_bytes = broken.read_bytes()
    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    registry.add_paths((valid, broken))
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None
    tree = dialog.tree_widget
    _events()
    original_error = registry.entries[1].error
    assert original_error is not None
    assert widget.filter_combo.count() == 6

    for expected in (False, True):
        _click_registration_eye(tree, 1)
        assert registry.entries[1].enabled is expected
        assert registry.entries[1].error == original_error
        assert tree.topLevelItem(1).text(2) == "読込エラー"
        assert tree.topLevelItem(1).toolTip(2) == original_error
        assert widget.filter_combo.count() == 6
        assert broken.read_bytes() == original_bytes

    # 修復後の再読込はONを引き継ぎ、OFFにしても読込済み状態を維持する
    _write_custom_filter(broken, "Repaired")
    registry.save()
    dialog.reload_all_button.click()
    assert registry.entries[1].enabled
    assert registry.entries[1].error is None
    assert widget.filter_combo.count() == 7
    _click_registration_eye(tree, 1)
    assert not registry.entries[1].enabled
    assert tree.topLevelItem(1).text(2) == "済"
    assert widget.filter_combo.count() == 6


def test_custom_filter_manager_shows_only_registration_storage_errors(
    dock_host: _WorkspaceHost,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常な読込状態は各行へ表示し、登録設定のエラーだけを別途提示する。"""
    from bd_tools import bd_channel_box
    from bd_tools.bd_channel_box.custom_filter_registry import (
        CustomFilterRegistry,
    )

    widget = bd_channel_box.show().widget
    registry = widget.custom_filter_registry
    path = tmp_path / "rig.json"
    _write_custom_filter(path, "Rig")
    registry.add_paths((path,))
    widget.manage_custom_filters_action.trigger()
    dialog = widget.custom_filter_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.storage_error_label.isHidden()
    storage_failure: str | None = (
        "カスタムフィルター登録設定を保存できませんでした"
    )

    def storage_error(_registry: CustomFilterRegistry) -> str | None:
        """個人設定だけのエラーを再現する。"""
        return storage_failure

    monkeypatch.setattr(
        CustomFilterRegistry, "storage_error", property(storage_error)
    )
    registry.changed.emit()
    assert dialog.storage_error_label.isVisible()
    assert dialog.storage_error_label.text() == storage_failure
    assert dialog.tree_widget.topLevelItem(0).text(2) == "済"
    storage_failure = None
    registry.changed.emit()
    assert dialog.storage_error_label.isHidden()


def test_custom_filter_registrations_survive_reopen_reload_and_layout_reset(
    dock_host: _WorkspaceHost,
    tmp_path: Path,
) -> None:
    """保存済みプリセットのパス・順序・ON/OFFをWindow再生成後も維持する。"""
    import bd_tools

    from bd_tools import bd_channel_box

    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    _write_custom_filter(first, "One")
    _write_custom_filter(second, "Two")
    window = bd_channel_box.show()
    registry = window.widget.custom_filter_registry
    first_path, second_path = registry.add_paths((first, second))
    registry.move(second_path, -1)
    registry.set_enabled(first_path, False)
    registry.save()
    assert tuple(entry.path for entry in registry.entries) == (
        second_path,
        first_path,
    )
    assert window.widget.filter_combo.count() == 6

    bd_channel_box.close()
    _events()
    reopened = bd_channel_box.show()
    _events()
    assert tuple(
        (entry.path, entry.enabled)
        for entry in reopened.widget.custom_filter_registry.entries
    ) == ((second_path, True), (first_path, False))
    assert reopened.widget.filter_combo.itemText(5) == "Custom: two"
    reset = bd_channel_box.reset_layout()
    _events()
    assert tuple(
        entry.path for entry in reset.widget.custom_filter_registry.entries
    ) == (second_path, first_path)
    bd_channel_box.close()
    _events()
    bd_tools.reload_package()
    from bd_tools import bd_channel_box as current_module

    current = current_module.show()
    _events()
    assert tuple(
        (entry.path, entry.enabled)
        for entry in current.widget.custom_filter_registry.entries
    ) == ((second_path, True), (first_path, False))


def test_value_filter_survives_reopen_reload_and_reset_without_losing_ui_preferences(
    dock_host: _WorkspaceHost,
) -> None:
    """値編集の選択と既存の操作設定を、別モードで閉じても再生成後に保つ。"""
    import bd_tools

    from bd_tools import bd_channel_box

    window = bd_channel_box.show()
    _events()
    window.widget.controller.set_attribute_filter("hidden")
    window.widget.wheel_editing_action.setChecked(True)
    window.widget.controller.set_mode("states")
    window.widget.controller.set_attribute_filter("keyable")
    bd_channel_box.close()
    _events()
    reopened = bd_channel_box.show()
    _events()
    assert reopened.widget.controller.mode == "values"
    assert reopened.widget.controller.attribute_filter == "hidden"
    assert reopened.widget.filter_combo.currentData() == "hidden"
    assert reopened.widget.wheel_editing_action.isChecked()
    reset = bd_channel_box.reset_layout()
    _events()
    assert reset.widget.controller.attribute_filter == "hidden"
    bd_channel_box.close()
    _events()
    bd_tools.reload_package()
    from bd_tools import bd_channel_box as reloaded

    current = reloaded.show()
    _events()
    assert current.widget.filter_combo.currentData() == "hidden"
    assert current.widget.wheel_editing_action.isChecked()


def test_custom_filter_reload_updates_selection_and_fallback_notice(
    dock_host: _WorkspaceHost,
    tmp_path: Path,
) -> None:
    """型未定義の案内、正常再読込、読込失敗時の既定復帰を確認する。"""
    from bd_tools import bd_channel_box
    from bd_tools.bd_channel_box.custom_filters import CustomFilterSelection

    source = tmp_path / "reload.json"
    _write_custom_filter(source, "Rig", {"joint": ["visibility"]})
    node = cmds.createNode("transform", name="customFilterReloadBase")
    cmds.select(node, replace=True)
    window = bd_channel_box.show()
    widget = window.widget
    (path,) = widget.custom_filter_registry.add_paths((source,))
    widget.filter_combo.setCurrentIndex(5)
    _events()
    assert isinstance(
        widget.controller.attribute_filter, CustomFilterSelection
    )
    assert not widget.filter_fallback_label.isHidden()
    fallback_text = widget.filter_fallback_label.text()
    assert "transform" in fallback_text
    assert "keyable + channelbox" in fallback_text
    assert "未定義" in fallback_text

    _write_custom_filter(source, "Rig", {"transform": ["visibility"]})
    widget.custom_filter_registry.reload(path)
    _events()
    assert isinstance(
        widget.controller.attribute_filter, CustomFilterSelection
    )
    assert widget.filter_combo.currentIndex() == 5
    assert (
        widget.filter_combo.findData(widget.controller.attribute_filter) == 5
    )
    assert widget.filter_fallback_label.isHidden()
    assert tuple(row.attribute.path for row in widget.controller.rows) == (
        "visibility",
    )

    source.write_text("{", encoding="utf-8")
    widget.custom_filter_registry.reload(path)
    _events()
    assert widget.controller.attribute_filter == "visible"
    assert widget.filter_combo.count() == 5
    assert widget.filter_combo.currentData() == "visible"
    assert widget.custom_filter_registry.entries[0].error is not None
    assert widget.filter_fallback_label.isHidden()
    assert source.is_file()
