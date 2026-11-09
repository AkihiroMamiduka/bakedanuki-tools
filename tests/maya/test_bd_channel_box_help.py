# coding: utf-8
"""オンラインヘルプの明示起動、失敗通知、sceneの不変を検証する。"""

from __future__ import annotations

import importlib
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt

from bd_tools.bd_channel_box.widget import ChannelBoxWidget


class _HelpLauncher:
    """ブラウザーを開かず、公開ヘルプAPIへの依頼を記録する。"""

    def __init__(self) -> None:
        """呼び出し履歴と、既定の起動成功を用意する。"""
        self.calls: list[str] = []
        self.outcome: bool | Exception = True

    def __call__(self, page_id: str) -> bool:
        """指定ページを記録し、設定された成否または例外を返す。"""
        self.calls.append(page_id)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@dataclass(frozen=True)
class _SceneState:
    """ヘルプ操作の前後で維持するsceneとUndoの状態。"""

    transforms: tuple[str, ...]
    selection: tuple[str, ...]
    value: float
    modified: bool
    undo_empty: bool
    redo_empty: bool
    undo_name: str


def _new_scene() -> None:
    """前の選択とUndoを破棄し、テスト用sceneを初期化する。"""
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)


def _events() -> None:
    """選択監視とWidgetの遅延処理を完了させる。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _prepare_undo() -> None:
    """ヘルプ操作で失ってはいけないUndoを1件だけ残す。"""
    cmds.flushUndo()
    set_attr = cast(Callable[[str, float], None], cmds.setAttr)
    set_attr("helpTarget.translateX", 2.5)
    file_command = cast(Callable[..., object], cmds.file)
    file_command(modified=False)
    _events()


def _scene_state() -> _SceneState:
    """値・選択・scene変更フラグとUndoキューを比較用に読み取る。"""
    file_command = cast(Callable[..., object], cmds.file)
    return _SceneState(
        transforms=tuple(cmds.ls(type="transform", long=True) or []),
        selection=tuple(cmds.ls(selection=True, long=True) or []),
        value=cast(float, cmds.getAttr("helpTarget.translateX")),
        modified=bool(file_command(query=True, modified=True)),
        undo_empty=bool(cmds.undoInfo(query=True, undoQueueEmpty=True)),
        redo_empty=bool(cmds.undoInfo(query=True, redoQueueEmpty=True)),
        undo_name=cast(str, cmds.undoInfo(query=True, undoName=True)),
    )


def _assert_original_undo_remains() -> None:
    """ヘルプ以前の値変更が、余分なUndoなしで1回で戻ることを確認する。"""
    cmds.undo()
    _events()
    assert cmds.getAttr("helpTarget.translateX") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.fixture
def help_launcher(monkeypatch: pytest.MonkeyPatch) -> _HelpLauncher:
    """Widget生成前から公開APIを差し替え、実ブラウザー起動を防ぐ。"""
    launcher = _HelpLauncher()
    # 先行テストによるreload後の公開モジュールを差し替える
    current_help = importlib.import_module("bd_tools.help")
    monkeypatch.setattr(current_help, "open_page", launcher)
    return launcher


@pytest.fixture
def editor_factory(
    qt_application: qt.QApplication,
    help_launcher: _HelpLauncher,
) -> Iterator[Callable[[], ChannelBoxWidget]]:
    """同じsceneを表示するWidgetを作り、全てのMaya監視を解放する。"""
    assert qt_application is not None
    assert not help_launcher.calls
    _new_scene()
    node = cmds.createNode("transform", name="helpTarget")
    cmds.select(node, replace=True)
    widgets: list[ChannelBoxWidget] = []

    def create() -> ChannelBoxWidget:
        """選択ノードのWidgetを表示し、イベント処理を完了する。"""
        widget = ChannelBoxWidget()
        widgets.append(widget)
        widget.show()
        _events()
        return widget

    yield create
    for widget in widgets:
        widget.setup_panel.discard()
        widget.dispose()
        widget.close()
        widget.deleteLater()
    _events()
    _new_scene()


def test_help_menu_opens_the_registered_page_without_scene_changes(
    editor_factory: Callable[[], ChannelBoxWidget],
    help_launcher: _HelpLauncher,
) -> None:
    """メニューバーの公開アクションから登録ページを1回だけ開く。"""
    editor = editor_factory()
    assert editor.help_menu.title() == "ヘルプ"
    assert editor.help_menu.menuAction() in editor.menu_bar.actions()
    assert editor.open_help_action.text() == "オンラインヘルプ"
    assert editor.open_help_action in editor.help_menu.actions()
    assert editor.open_help_action.isEnabled()
    assert not help_launcher.calls
    _prepare_undo()
    before = _scene_state()

    editor.open_help_action.trigger()
    _events()

    assert help_launcher.calls == ["bd_channel_box"]
    assert editor.message_label.isHidden()
    assert _scene_state() == before
    _assert_original_undo_remains()


def test_help_launch_failure_is_reported_without_scene_changes(
    editor_factory: Callable[[], ChannelBoxWidget],
    help_launcher: _HelpLauncher,
) -> None:
    """起動依頼がFalseの場合は既存の通知欄へ失敗を表示する。"""
    editor = editor_factory()
    help_launcher.outcome = False
    _prepare_undo()
    before = _scene_state()

    editor.open_help_action.trigger()
    _events()

    assert help_launcher.calls == ["bd_channel_box"]
    assert not editor.message_label.isHidden()
    assert "オンラインヘルプ" in editor.message_label.text()
    assert "変更できませんでした" not in editor.message_label.text()
    assert _scene_state() == before
    _assert_original_undo_remains()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("ヘルプのURL形式が不正です"),
        KeyError("bd_channel_box"),
        OSError("既定ブラウザーを起動できません"),
        webbrowser.Error("ブラウザーの制御に失敗しました"),
    ],
)
def test_help_errors_are_reported_without_scene_changes(
    editor_factory: Callable[[], ChannelBoxWidget],
    help_launcher: _HelpLauncher,
    error: Exception,
) -> None:
    """URL情報やブラウザーの例外をscene編集の失敗と混同せず通知する。"""
    editor = editor_factory()
    help_launcher.outcome = error
    _prepare_undo()
    before = _scene_state()

    editor.open_help_action.trigger()
    _events()

    assert help_launcher.calls == ["bd_channel_box"]
    assert not editor.message_label.isHidden()
    assert str(error) in editor.message_label.text()
    assert "変更できませんでした" not in editor.message_label.text()
    assert _scene_state() == before
    _assert_original_undo_remains()


def test_show_mode_changes_and_recreation_do_not_open_help_automatically(
    editor_factory: Callable[[], ChannelBoxWidget],
    help_launcher: _HelpLauncher,
) -> None:
    """表示・Mode切替・再生成では無起動で、各明示操作が1回だけ届く。"""
    first = editor_factory()
    _prepare_undo()
    before = _scene_state()
    for mode in ("states", "custom_filter_setup", "values"):
        index = first.mode_combo.findData(mode)
        assert index >= 0
        first.mode_combo.setCurrentIndex(index)
        first.hide()
        first.show()
        _events()
        assert not help_launcher.calls

    first.open_help_action.trigger()
    _events()
    assert help_launcher.calls == ["bd_channel_box"]

    first.hide()
    first.show()
    _events()
    assert help_launcher.calls == ["bd_channel_box"]
    first.open_help_action.trigger()
    _events()
    assert help_launcher.calls == ["bd_channel_box"] * 2

    second = editor_factory()
    assert help_launcher.calls == ["bd_channel_box"] * 2
    second.open_help_action.trigger()
    _events()
    assert help_launcher.calls == ["bd_channel_box"] * 3
    assert _scene_state() == before
    _assert_original_undo_remains()
