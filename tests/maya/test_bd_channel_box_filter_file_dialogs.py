# coding: utf-8
"""フィルターのファイル名選択と、改名の入力検証を確認する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest

from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_dialogs as dialog_module

from bd_tools.bd_channel_box.custom_filter_dialogs import (
    create_registered_filter,
)
from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box import custom_filter_registry as registry_module
from bd_tools.bd_channel_box.custom_filters import (
    load_custom_filter,
    normalize_filter_path,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


@pytest.fixture
def editor(
    qt_application: qt.QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ChannelBoxWidget]:
    """入力ダイアログを検証するWidgetを作り、監視を確実に解除する。"""
    assert qt_application is not None
    unexpected_warnings: list[str] = []

    def cancel_unexpected_warning(
        *_args: object,
    ) -> qt.QMessageBox.StandardButton:
        """未想定の確認で待ち続けず、説明を検証結果へ残す。"""
        unexpected_warnings.append(str(_args[2]))
        return qt.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(qt.QMessageBox, "warning", cancel_unexpected_warning)
    widget = ChannelBoxWidget()
    yield widget
    widget.setup_panel.discard()
    widget.dispose()
    widget.close()
    widget.deleteLater()
    qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)
    assert not unexpected_warnings, unexpected_warnings


@pytest.mark.parametrize("duplicate", (False, True))
def test_creation_uses_only_save_dialog_and_selected_file_name(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duplicate: bool,
) -> None:
    """名前入力を挟まず、実ファイル名を表示名にしてnameなしJSONを作る。"""
    source = tmp_path / "source.json"
    create_custom_filter(source, "Original")
    destination = tmp_path / "Chosen.json"
    calls: list[Path] = []

    def choose(*args: object) -> tuple[str, str]:
        """初期pathを記録し、拡張子なしの保存先を返す。"""
        calls.append(Path(cast(str, args[2])))
        return str(destination.with_suffix("")), ""

    def reject_name_dialog(_dialog: qt.QDialog) -> int:
        """保存先以外の名前入力が表示された場合に失敗させる。"""
        raise AssertionError("名前入力ダイアログは不要です")

    monkeypatch.setattr(dialog_module, "get_save_file_name_near", choose)
    monkeypatch.setattr(qt.QDialog, "exec", reject_name_dialog)
    result = create_registered_filter(
        editor,
        editor.custom_filter_registry,
        source=str(source) if duplicate else None,
    )
    assert result == normalize_filter_path(destination)
    assert len(calls) == 1
    if duplicate:
        assert calls[0] == tmp_path / "source_copy.json"
    else:
        assert calls[0].name == "filter" and calls[0].is_dir()
        assert calls[0].parent.name == "custom_filter"
    assert load_custom_filter(destination).name == "Chosen"
    assert load_custom_filter(source).name == "source"
    for path in (source, destination):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 2
        assert "name" not in payload


@pytest.mark.parametrize("cancel", (False, True))
def test_existing_destination_is_preserved_and_can_be_reselected(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    """上書き確認後の既存pathも拒否し、再選択または取消を可能にする。"""
    existing = tmp_path / "Existing.json"
    create_custom_filter(existing, "Keep")
    before = existing.read_bytes()
    destination = tmp_path / "New.json"
    choices = iter((str(existing), "" if cancel else str(destination)))
    messages: list[str] = []

    def choose(*_args: object) -> tuple[str, str]:
        """既存pathの後に別pathまたはキャンセルを返す。"""
        return next(choices), ""

    def warn(_parent: qt.QWidget, _title: str, message: str) -> int:
        """上書き拒否の説明を記録し、再選択へ進める。"""
        messages.append(message)
        return 0

    monkeypatch.setattr(dialog_module, "get_save_file_name_near", choose)
    monkeypatch.setattr(qt.QMessageBox, "warning", warn)
    result = create_registered_filter(editor, editor.custom_filter_registry)
    assert existing.read_bytes() == before
    assert len(messages) == 1 and "存在" in messages[0]
    assert result == (None if cancel else normalize_filter_path(destination))
    assert len(editor.custom_filter_registry.entries) == (0 if cancel else 1)


def test_rename_validates_collision_inline_and_keeps_draft_until_saved(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """衝突・空欄・不正名でOKを無効にし、解消後の改名だけを保存する。"""
    source = tmp_path / "Original.json"
    collision = tmp_path / "Occupied.json"
    create_custom_filter(source, "Original")
    create_custom_filter(collision, "Occupied")
    original = source.read_bytes()
    occupied = collision.read_bytes()
    editor.custom_filter_registry.add_paths((source, collision))
    editor.custom_filter_registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))

    def inspect(dialog: qt.QDialog) -> int:
        """入力に応じた説明文とOKの有効状態をその場で検証する。"""
        field = dialog.findChild(qt.QLineEdit, "renameCustomFilterName")
        message = dialog.findChild(qt.QLabel, "renameCustomFilterError")
        buttons = dialog.findChild(qt.QDialogButtonBox)
        assert isinstance(field, qt.QLineEdit)
        assert isinstance(message, qt.QLabel)
        assert isinstance(buttons, qt.QDialogButtonBox)
        ok = buttons.button(qt.QDialogButtonBox.StandardButton.Ok)
        assert ok is not None and ok.isEnabled()
        field.setText("Occupied")
        assert (
            not ok.isEnabled() and "同名ファイルが存在します" in message.text()
        )
        for invalid in ("", "bad/name", "CON", "name."):
            field.setText(invalid)
            assert not ok.isEnabled() and message.text()
        field.setText("Renamed")
        assert ok.isEnabled() and not message.text()
        return int(qt.QDialog.DialogCode.Accepted)

    monkeypatch.setattr(qt.QDialog, "exec", inspect)
    cast(Callable[[], None], getattr(panel, "_rename_filter"))()
    assert panel.draft is not None and panel.draft.name == "Renamed"
    assert source.read_bytes() == original
    assert collision.read_bytes() == occupied
    assert not (tmp_path / "Renamed.json").exists()
    assert panel.save()
    assert not source.exists()
    assert load_custom_filter(tmp_path / "Renamed.json").name == "Renamed"
    assert "name" not in json.loads(
        (tmp_path / "Renamed.json").read_text(encoding="utf-8")
    )
    assert collision.read_bytes() == occupied
    assert panel.target_combo.currentData() == normalize_filter_path(
        tmp_path / "Renamed.json"
    )


def test_rename_rechecks_collision_created_after_dialog(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """入力確定後に作成された別ファイルも、保存時に上書きせず下書きを保つ。"""
    source = tmp_path / "Original.json"
    destination = tmp_path / "Later.json"
    create_custom_filter(source, "Original")
    original = source.read_bytes()
    editor.custom_filter_registry.add_paths((source,))
    editor.custom_filter_registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))

    def accept(dialog: qt.QDialog) -> int:
        """保存直前には空いている名前を改名予定にする。"""
        field = dialog.findChild(qt.QLineEdit, "renameCustomFilterName")
        assert isinstance(field, qt.QLineEdit)
        field.setText("Later")
        return int(qt.QDialog.DialogCode.Accepted)

    monkeypatch.setattr(qt.QDialog, "exec", accept)
    cast(Callable[[], None], getattr(panel, "_rename_filter"))()
    create_custom_filter(destination, "Other")
    occupied = destination.read_bytes()
    assert not panel.save()
    assert panel.draft is not None and panel.draft.is_dirty
    assert source.read_bytes() == original
    assert destination.read_bytes() == occupied
    panel.discard()
    assert panel.draft is not None and panel.draft.name == "Original"


def test_same_names_are_distinguished_in_setup_combo(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """同名の既存定義をファイル名と必要なフォルダーで見分けられるようにする。"""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    third = tmp_path / "sub" / "first.json"
    third.parent.mkdir()
    for path in (first, second, third):
        create_custom_filter(path, "Same")
    editor.custom_filter_registry.add_paths((first, second, third))
    editor.custom_filter_registry.save()
    panel = editor.setup_panel
    labels = [panel.target_combo.itemText(index) for index in range(1, 4)]
    assert len(set(labels)) == 3
    assert "first" in labels[0] and "first" in labels[2]
    assert labels[1] == "second"
    assert all("Same" not in label for label in labels)
    panel.set_target(str(first))
    assert (
        len({panel.target_combo.itemText(index) for index in range(1, 4)}) == 3
    )


def test_rename_transfers_saved_definition_without_second_file_read(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """改名成功後の再読込に依存せず、確定した定義と新pathを一緒に登録する。"""
    source = tmp_path / "Original.json"
    destination = tmp_path / "Renamed.json"
    create_custom_filter(source, "Original")
    registry = editor.custom_filter_registry
    registry.add_paths((source,))
    registry.save()
    editor.filter_combo.setCurrentIndex(5)
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    assert panel.draft is not None
    panel.draft.rename("Renamed")

    def reject_second_read(_path: str) -> None:
        """保存済み定義の引き継ぎ中に不要なファイル読込があれば失敗させる。"""
        raise AssertionError("改名済みJSONを再読込する必要はありません")

    with monkeypatch.context() as save_scope:
        save_scope.setattr(
            registry_module, "load_custom_filter", reject_second_read
        )
        assert panel.save()
    assert not source.exists() and destination.exists()
    assert registry.entries[0].path == normalize_filter_path(destination)
    assert registry.entries[0].definition == panel.draft.definition()
    assert not panel.draft.is_dirty
    assert panel.target_combo.currentData() == normalize_filter_path(
        destination
    )
