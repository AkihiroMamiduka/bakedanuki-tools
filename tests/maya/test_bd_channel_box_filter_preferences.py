# coding: utf-8
"""値編集フィルターの永続化と、ほかのモードからの独立性を検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from maya import cmds

from bd_util.maya.ui import get_ui_settings_file
from bd_util.ui import qt

from bd_tools.bd_channel_box.controller import (
    ChannelAttributeFilter,
    ChannelBoxMode,
)
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterError,
    CustomFilterSelection,
    normalize_filter_path,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


@pytest.fixture
def editor_factory(
    qt_application: qt.QApplication,
) -> Iterator[Callable[[], ChannelBoxWidget]]:
    """同じ個人設定を読む新しいWidgetを作り、各controllerを確実に解放する。"""
    assert qt_application is not None
    cmds.select(clear=True)
    widgets: list[ChannelBoxWidget] = []

    def create() -> ChannelBoxWidget:
        """設定を新しく読み込むWidgetを作成する。"""
        widget = ChannelBoxWidget()
        widgets.append(widget)
        return widget

    yield create
    for widget in widgets:
        widget.dispose()
        widget.close()
        widget.deleteLater()
    qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _write_filter(path: Path, name: str) -> None:
    """同名のフィルターも作れる最小の共有JSONを書き出す。"""
    path.write_text(
        json.dumps(
            {"schema_version": 1, "name": name, "node_types": {"network": []}}
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "value", ("all", "visible", "keyable", "channel_box", "hidden")
)
def test_standard_filter_restores_to_new_widget(
    editor_factory: Callable[[], ChannelBoxWidget],
    value: ChannelAttributeFilter,
) -> None:
    """標準5項目の選択を新しいWidgetのComboBoxとcontrollerへ同時に復元する。"""
    first = editor_factory()
    first.filter_combo.setCurrentIndex(first.filter_combo.findData(value))
    second = editor_factory()
    assert second.controller.mode == "values"
    assert second.controller.attribute_filter == value
    assert second.filter_combo.currentData() == value


@pytest.mark.parametrize("mode", ("states", "custom_filter_setup"))
def test_other_modes_do_not_overwrite_value_filter(
    editor_factory: Callable[[], ChannelBoxWidget], mode: ChannelBoxMode
) -> None:
    """ほかのモードを表示したまま終了しても値編集の選択だけを復元する。"""
    first = editor_factory()
    first.controller.set_attribute_filter("hidden")
    first.controller.set_mode(mode)
    first.controller.set_attribute_filter("keyable")
    first.dispose()

    second = editor_factory()
    assert second.controller.mode == "values"
    assert second.controller.values_attribute_filter == "hidden"
    assert second.filter_combo.currentData() == "hidden"
    second.controller.set_mode(mode)
    assert second.controller.attribute_filter == "all"


def test_custom_filter_restores_by_path_after_rename_and_reordering(
    editor_factory: Callable[[], ChannelBoxWidget], tmp_path: Path
) -> None:
    """改名・同名・並べ替え後もpathで復元し、型未定義時も選択を維持する。"""
    first = editor_factory()
    source = tmp_path / "one.json"
    other = tmp_path / "two.json"
    _write_filter(source, "Same")
    _write_filter(other, "Same")
    path, _other_path = first.custom_filter_registry.add_paths((source, other))
    first.filter_combo.setCurrentIndex(5)
    first.custom_filter_registry.move(path, 1)
    _write_filter(source, "Renamed")
    first.custom_filter_registry.reload(path)
    assert first.filter_combo.currentIndex() == 6

    second = editor_factory()
    selection = second.controller.attribute_filter
    assert isinstance(selection, CustomFilterSelection)
    assert selection.path == path
    assert selection.definition.name == "Renamed"
    assert second.filter_combo.currentText() == "Custom: Renamed"
    node = cmds.createNode("transform", skipSelect=True)
    try:
        cmds.select(node, replace=True)
        second.controller.refresh()
        assert (
            second.controller.custom_filter_fallback_node_type == "transform"
        )
        assert second.controller.attribute_filter == selection
    finally:
        cmds.delete(node)


@pytest.mark.parametrize(
    "unavailable", ("off", "removed", "missing", "invalid")
)
def test_unavailable_custom_filter_restores_visible_default(
    editor_factory: Callable[[], ChannelBoxWidget],
    tmp_path: Path,
    unavailable: str,
) -> None:
    """起動時に使えないカスタム選択を標準表示へ戻し、誤った別項目を選ばない。"""
    first = editor_factory()
    source = tmp_path / "rig.json"
    _write_filter(source, "Rig")
    (path,) = first.custom_filter_registry.add_paths((source,))
    first.filter_combo.setCurrentIndex(5)
    first.dispose()
    if unavailable == "off":
        first.custom_filter_registry.set_enabled(path, False)
    elif unavailable == "removed":
        first.custom_filter_registry.remove(path)
    elif unavailable == "missing":
        source.unlink()
    else:
        source.write_text("{}", encoding="utf-8")

    second = editor_factory()
    assert second.controller.attribute_filter == "visible"
    assert second.filter_combo.currentData() == "visible"


def test_registry_fallback_updates_values_preference_while_other_mode_is_open(
    editor_factory: Callable[[], ChannelBoxWidget], tmp_path: Path
) -> None:
    """別モードでカスタムをOFFにした後、再度ONにしても値編集の既定復帰を維持する。"""
    first = editor_factory()
    source = tmp_path / "rig.json"
    _write_filter(source, "Rig")
    (path,) = first.custom_filter_registry.add_paths((source,))
    first.filter_combo.setCurrentIndex(5)
    first.controller.set_mode("states")
    first.custom_filter_registry.set_enabled(path, False)
    first.custom_filter_registry.set_enabled(path, True)
    second = editor_factory()
    assert second.controller.values_attribute_filter == "visible"
    assert second.filter_combo.currentData() == "visible"


@pytest.mark.parametrize(
    "identifier", ("", "invalid", "custom:", "custom:C:/missing.json")
)
def test_invalid_saved_identifier_uses_default(
    editor_factory: Callable[[], ChannelBoxWidget], identifier: str
) -> None:
    """不正な保存値と未登録pathを受け入れず、従来の標準表示で起動する。"""
    first = editor_factory()
    first.controller.set_attribute_filter("hidden")
    settings = qt.QSettings(
        str(get_ui_settings_file("bd_channel_box/preferences/main")),
        qt.QSettings.Format.IniFormat,
    )
    settings.setValue("preferences/main/values_attribute_filter", identifier)
    settings.sync()
    second = editor_factory()
    assert second.controller.values_attribute_filter == "visible"


@pytest.mark.parametrize("mode", ("values", "states", "custom_filter_setup"))
def test_file_rename_migrates_both_mode_selections_and_saved_path(
    editor_factory: Callable[[], ChannelBoxWidget],
    tmp_path: Path,
    mode: ChannelBoxMode,
) -> None:
    """別モードを表示中でも両方の保持選択と次回復元先を改名先へ移す。"""
    first = editor_factory()
    source = tmp_path / "before.json"
    destination = tmp_path / "after.json"
    _write_filter(source, "Before")
    (old_path,) = first.custom_filter_registry.add_paths((source,))
    selected = first.filter_combo.itemData(5)
    assert isinstance(selected, CustomFilterSelection)
    first.controller.set_attribute_filter(selected)
    first.controller.set_mode("states")
    first.controller.set_attribute_filter(selected)
    first.controller.set_mode(mode)

    # 保存後の実ファイル改名を登録へ通知する
    source.rename(destination)
    _write_filter(destination, "After")
    new_path = normalize_filter_path(destination)
    assert first.custom_filter_registry.replace_path(old_path, new_path)
    assert len(first.custom_filter_registry.entries) == 1
    assert first.custom_filter_registry.entries[0].path == new_path
    assert not source.exists()

    target_modes: tuple[ChannelBoxMode, ...] = ("values", "states")
    for target_mode in target_modes:
        first.controller.set_mode(target_mode)
        actual = first.controller.attribute_filter
        assert isinstance(actual, CustomFilterSelection)
        assert actual.path == new_path
        assert actual.definition.name == "After"
        assert first.filter_combo.currentText() == "Custom: After"
        assert first.filter_combo.count() == 6

    restored = editor_factory()
    actual = restored.controller.values_attribute_filter
    assert isinstance(actual, CustomFilterSelection)
    assert actual.path == new_path
    assert restored.filter_combo.currentText() == "Custom: After"


def test_rename_preserves_unselected_registration_order_and_disabled_state(
    editor_factory: Callable[[], ChannelBoxWidget], tmp_path: Path
) -> None:
    """非選択のOFF登録だけを同じ位置で改名し、選択中の別定義を維持する。"""
    first = editor_factory()
    sources = tuple(tmp_path / name for name in ("a.json", "b.json", "c.json"))
    for source in sources:
        _write_filter(source, source.stem)
    first_path, old_path, last_path = first.custom_filter_registry.add_paths(
        sources
    )
    first.filter_combo.setCurrentIndex(5)
    first.custom_filter_registry.set_enabled(old_path, False)
    events: list[str] = []

    def on_path_changed(old: str, new: str) -> None:
        """一般の一覧更新より先に改名が通知されたことを記録する。"""
        assert old == old_path
        assert new == new_path
        events.append("path")

    def on_changed() -> None:
        """一般の一覧更新通知を記録する。"""
        events.append("changed")

    first.custom_filter_registry.path_changed.connect(on_path_changed)
    first.custom_filter_registry.changed.connect(on_changed)
    destination = tmp_path / "renamed.json"
    sources[1].rename(destination)
    new_path = normalize_filter_path(destination)
    assert first.custom_filter_registry.replace_path(old_path, new_path)
    assert events == ["path", "changed"]
    entries = first.custom_filter_registry.entries
    assert tuple(entry.path for entry in entries) == (
        first_path,
        new_path,
        last_path,
    )
    assert tuple(entry.enabled for entry in entries) == (True, False, True)
    selected = first.controller.values_attribute_filter
    assert isinstance(selected, CustomFilterSelection)
    assert selected.path == first_path

    restored = editor_factory()
    assert tuple(
        entry.path for entry in restored.custom_filter_registry.entries
    ) == (first_path, new_path, last_path)
    assert not restored.custom_filter_registry.entries[1].enabled
    selected = restored.controller.values_attribute_filter
    assert isinstance(selected, CustomFilterSelection)
    assert selected.path == first_path


@pytest.mark.parametrize("failure", ("registered", "missing", "invalid"))
def test_rename_rejects_unreadable_or_registered_destination(
    editor_factory: Callable[[], ChannelBoxWidget],
    tmp_path: Path,
    failure: str,
) -> None:
    """登録宛先の衝突や読込失敗を明示し、元の登録と保持選択を変更しない。"""
    widget = editor_factory()
    source = tmp_path / "original.json"
    destination = tmp_path / "destination.json"
    _write_filter(source, "Original")
    (old_path,) = widget.custom_filter_registry.add_paths((source,))
    widget.filter_combo.setCurrentIndex(5)
    if failure == "registered":
        _write_filter(destination, "Existing")
        widget.custom_filter_registry.add_paths((destination,))
    elif failure == "invalid":
        destination.write_text("{}", encoding="utf-8")
    previous = widget.custom_filter_registry.entries
    with pytest.raises(CustomFilterError):
        widget.custom_filter_registry.replace_path(old_path, str(destination))
    assert widget.custom_filter_registry.entries == previous
    selected = widget.controller.values_attribute_filter
    assert isinstance(selected, CustomFilterSelection)
    assert selected.path == old_path
    assert source.exists()
