# coding: utf-8
"""出力前の保存確認で、保存成功以外は編集を保持して中止する契約を検証する。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_dialogs as dialog_module
from bd_tools.bd_channel_box import custom_filter_setup as setup_panel_module
from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterError,
    load_custom_filter,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """設定画面の保存と確認を検証し、監視を確実に解除する。"""
    assert qt_application is not None
    widget = ChannelBoxWidget()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.mark.parametrize(
    "choice",
    (
        qt.QMessageBox.StandardButton.Save,
        qt.QMessageBox.StandardButton.Cancel,
        qt.QMessageBox.StandardButton.NoButton,
    ),
)
def test_export_confirmation_has_only_save_and_cancel(
    qt_application: qt.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    choice: qt.QMessageBox.StandardButton,
) -> None:
    """明示した二つの日本語ボタンで確認し、保存だけを続行として返す。"""
    assert qt_application is not None
    parent = qt.QWidget()
    origin = qt.QPoint(123, 234)
    calls: list[qt.QPoint] = []

    def inspect(dialog: qt.QDialog, anchor: qt.QPoint) -> int:
        """ボタンの構成と起点を確認し、指定した応答を返す。"""
        assert isinstance(dialog, qt.QMessageBox)
        assert dialog.standardButtons() == (
            qt.QMessageBox.StandardButton.Save
            | qt.QMessageBox.StandardButton.Cancel
        )
        save_button = dialog.button(qt.QMessageBox.StandardButton.Save)
        cancel_button = dialog.button(qt.QMessageBox.StandardButton.Cancel)
        assert save_button is not None
        assert cancel_button is not None
        assert save_button.text() == "保存してエクスポート"
        assert cancel_button.text() == "キャンセル"
        calls.append(qt.QPoint(anchor))
        return choice.value

    monkeypatch.setattr(dialog_module, "exec_dialog_near", inspect)
    try:
        assert dialog_module.confirm_export_save(parent, origin) is (
            choice == qt.QMessageBox.StandardButton.Save
        )
        assert calls == [origin]
    finally:
        parent.deleteLater()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("save", (False, True))
@pytest.mark.parametrize("fail", (False, True))
def test_export_requires_a_successful_save_of_the_editing_draft(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    save: bool,
    fail: bool,
) -> None:
    """取消・保存失敗はJSONと編集を維持し、保存成功時だけ出力を許可する。"""
    source = tmp_path / "Filter.json"
    path = create_custom_filter(source)
    registry = editor.custom_filter_registry
    registry.add_paths((path,))
    registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(path)
    draft = panel.draft
    assert draft is not None
    draft.set_included("transform", "visibility", True)
    original = source.read_bytes()
    origin = qt.QPoint(123, 234)
    calls: list[qt.QPoint] = []

    def choose(_parent: qt.QWidget, anchor: qt.QPoint) -> bool:
        """確認位置を記録し、保存またはキャンセルを返す。"""
        calls.append(qt.QPoint(anchor))
        return save

    def refuse_save(*_args: object) -> None:
        """共有先に保存できない状況を再現する。"""
        raise CustomFilterError("保存先へ書き込めません")

    monkeypatch.setattr(setup_panel_module, "confirm_export_save", choose)
    if fail:
        monkeypatch.setattr(registry, "save", refuse_save)
    assert panel.confirm_export(origin) is (save and not fail)
    assert calls == [origin]
    if save and not fail:
        assert not panel.is_dirty
        assert load_custom_filter(source).node_types["transform"] == (
            "visibility",
        )
    else:
        assert panel.is_dirty
        assert panel.draft is draft
        assert source.read_bytes() == original


def test_clean_export_skips_save_confirmation(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未保存変更が無い場合は確認せず、そのまま保存先選択へ進める。"""
    editor.setup_panel.discard()

    def refuse_confirmation(*_args: object) -> bool:
        """不要な保存確認を表示した場合に失敗させる。"""
        raise AssertionError("保存済みの内容に確認は不要です")

    monkeypatch.setattr(
        setup_panel_module, "confirm_export_save", refuse_confirmation
    )
    assert editor.setup_panel.confirm_export(qt.QPoint(123, 234))
