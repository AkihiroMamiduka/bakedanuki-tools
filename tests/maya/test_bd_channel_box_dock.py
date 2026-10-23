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
    """同名登録、読込エラー、管理画面の切替と並べ替えを確認する。"""
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
    assert first.name in widget.filter_combo.itemText(5)
    assert second.name in widget.filter_combo.itemText(6)
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
    assert tree.topLevelItem(0).text(0) == "Rig"
    assert tree.topLevelItem(0).text(1) == paths[0]
    assert tree.topLevelItem(0).toolTip(1) == paths[0]
    assert tree.topLevelItem(0).text(2) == "読込済み"
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
    dialog.reload_all_button.click()
    assert widget.custom_filter_registry.entries[2].error is None
    assert tree.topLevelItem(2).text(2) == "読込済み"
    assert "読込エラー" not in tree.topLevelItem(2).toolTip(2)
    assert widget.filter_combo.count() == 7
    tree.topLevelItem(1).setCheckState(0, qt.Qt.CheckState.Checked)
    assert widget.filter_combo.count() == 8
    assert widget.filter_combo.itemData(6).path == paths[0]
    _select_registration_rows(tree, (1,))
    dialog.remove_button.click()
    assert first.is_file()
    assert tuple(
        entry.path for entry in widget.custom_filter_registry.entries
    ) == (paths[1], paths[2])


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
    _write_custom_filter(files[1], "Updated B")
    dialog.reload_all_button.click()
    assert tree.currentItem() is current_item
    assert tree.topLevelItem(1).text(0) == "Updated B"
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
    assert dialog.tree_widget.topLevelItem(0).text(2) == "読込済み"
    storage_failure = None
    registry.changed.emit()
    assert dialog.storage_error_label.isHidden()


def test_custom_filter_registrations_survive_reopen_reload_and_layout_reset(
    dock_host: _WorkspaceHost,
    tmp_path: Path,
) -> None:
    """個人設定のパス・順序・ON/OFFをWindow再生成後も維持する。"""
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
    assert reopened.widget.filter_combo.itemText(5) == "Custom: Two"
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
