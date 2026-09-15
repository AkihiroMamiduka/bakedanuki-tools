# coding: utf-8
"""ドッキング用公開APIと入力・監視のlifecycleを検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from maya import cmds

from bd_util.maya.ui import MayaDockableWindow
from bd_util.maya.ui.dock import workspace_control
from bd_util.ui import qt


class _WorkspaceHost:
    """batch Mayaで作れないworkspaceControlの格納・削除境界を置き換える。"""

    def __init__(self) -> None:
        """実Qt Windowを保持する格納先と配置削除の記録を初期化する。"""
        self.window: MayaDockableWindow | None = None
        self.state_removed = False

    def attach(self, window: MayaDockableWindow, _pointer: int = 0) -> None:
        """実Windowを格納し、Maya mixinを通さずQtで表示する。"""
        self.window = window
        qt.QWidget.show(window)

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


@pytest.fixture
def dock_host(
    qt_application: qt.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[_WorkspaceHost]:
    """実controller・入力UIを使い、Mayaの画面操作だけを置き換える。"""
    from bd_tools import channel_editor
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
    channel_editor.dispose()
    yield host
    # reloadした場合も最新moduleのcontrollerを終了する
    from bd_tools import channel_editor as current

    current.dispose()
    _events()


def test_dock_show_close_and_reload_release_bindings(
    dock_host: _WorkspaceHost,
) -> None:
    """重複表示せず、公開closeとreloadで入力controllerを即時に終了する。"""
    import bd_tools
    from bd_tools import channel_editor

    first = channel_editor.show()
    assert first is dock_host.window
    assert channel_editor.show() is first
    channel_editor.close()
    assert first.widget.controller.is_disposed
    assert dock_host.window is None
    second = channel_editor.show()
    assert second is not first
    old_controller = second.widget.controller
    bd_tools.reload_package()
    assert old_controller.is_disposed
    assert dock_host.window is None
    _events()
    assert not qt.isValid(first)
    assert not qt.isValid(second)


def test_maya_dock_close_signal_stops_selection_watch(
    dock_host: _WorkspaceHost,
) -> None:
    """Mayaのタイトルバーclose通知だけでも選択監視と入力を終了する。"""
    from bd_tools import channel_editor

    window = channel_editor.show()
    window.dock_closed.emit()
    assert window.widget.controller.is_disposed
    assert not window.widget.controller.rows
    # Qt削除より先に再表示しても、終了済みの入力UIを再利用しない
    replacement = channel_editor.show()
    assert replacement is not window
    assert replacement is dock_host.window
    assert not replacement.widget.controller.is_disposed


def test_ui_script_restore_and_layout_reset(dock_host: _WorkspaceHost) -> None:
    """復元入口の同一Window再利用と、統合resetによる再生成を確認する。"""
    from bd_tools import channel_editor
    from bd_util.maya.ui import restore_dockable

    window = restore_dockable("bd_tools.channel_editor.ui", "restore")
    assert isinstance(window, channel_editor.ChannelEditorWindow)
    assert window is dock_host.window
    assert channel_editor.show() is window
    assert (
        window.objectName() + "WorkspaceControl"
        == channel_editor.WORKSPACE_CONTROL_NAME
    )
    new_window = channel_editor.reset_layout()
    assert dock_host.state_removed
    assert window.widget.controller.is_disposed
    assert new_window is not window
    assert new_window is dock_host.window
