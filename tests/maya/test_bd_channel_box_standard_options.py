# coding: utf-8
"""標準属性の追加条件を設定画面から編集し、保存と通常表示へつなぐ。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import qt

from bd_tools.bd_channel_box.custom_filter_editor import CustomFilterDraft
from bd_tools.bd_channel_box.custom_filter_setup import CustomFilterSetupPanel
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterSelection,
    StandardAttributeOptions,
    load_custom_filter,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


def _events() -> None:
    """選択変更と画面更新の遅延通知を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _new_scene() -> None:
    """各検証のsceneと選択を分離する。"""
    cast(Callable[..., str], cmds.file)(new=True, force=True)


@pytest.fixture
def standard_editor(
    qt_application: qt.QApplication, tmp_path: Path
) -> Iterator[tuple[ChannelBoxWidget, Path, str]]:
    """旧形式の定義と各表示状態の属性を持つ設定画面を作る。"""
    assert qt_application is not None
    _new_scene()
    node = cmds.createNode("transform", name="standardFilterBase")
    for path in ("rigManual", "rigStandard", "rigChannel", "rigHidden"):
        cmds.addAttr(node, longName=path, attributeType="double")
    cmds.setAttr(f"{node}.rigStandard", keyable=True)
    cmds.setAttr(f"{node}.rigChannel", channelBox=True)
    cmds.select(node, replace=True)
    source = tmp_path / "standard-rig.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "node_types": {
                    "transform": ["rigManual", "visibility"],
                    "joint": [],
                },
            }
        ),
        encoding="utf-8",
    )
    editor = ChannelBoxWidget()
    editor.custom_filter_registry.create_group(tmp_path / "Group.json")
    editor.custom_filter_registry.create_preset(tmp_path / "Preset.json")
    editor.custom_filter_registry.add_paths((source,))
    editor.custom_filter_registry.save()
    editor.controller.set_mode("custom_filter_setup")
    editor.setup_panel.set_target(str(source))
    editor.resize(640, 720)
    editor.show()
    _events()
    cmds.flushUndo()
    try:
        yield editor, source, node
    finally:
        editor.dispose()
        editor.close()
        editor.deleteLater()
        _events()
        _new_scene()


def _choose(combo: qt.QComboBox, value: str) -> None:
    """表示名に依存せず設定値で候補を選ぶ。"""
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)
    _events()


def _draft(panel: CustomFilterSetupPanel) -> CustomFilterDraft:
    """編集中の定義があることを確認して返す。"""
    assert panel.draft is not None
    return panel.draft


def test_standard_controls_restore_legacy_defaults_and_require_context(
    standard_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """旧形式を変更せず追加OFFを示し、対象のない操作を無効にする。"""
    editor, source, _node = standard_editor
    panel = editor.setup_panel
    before = source.read_bytes()
    assert panel.standard_enabled_checkbox.isEnabled()
    assert not panel.standard_enabled_checkbox.isChecked()
    assert not panel.standard_filter_combo.isEnabled()
    assert not panel.standard_position_combo.isEnabled()
    assert panel.standard_filter_combo.currentData() == "visible"
    assert panel.standard_position_combo.currentData() == "last"
    assert _draft(panel).standard_options("transform") == (
        StandardAttributeOptions()
    )
    assert not panel.is_dirty
    assert source.read_bytes() == before

    # フィルター未選択と基準未選択では設定を変更できない
    panel.target_combo.setCurrentIndex(0)
    _events()
    assert not panel.standard_enabled_checkbox.isEnabled()
    panel.set_target(str(source))
    cmds.select(clear=True)
    _events()
    assert not panel.standard_enabled_checkbox.isEnabled()
    _choose(panel.node_type_combo, "joint")
    assert panel.standard_enabled_checkbox.isEnabled()
    assert not panel.standard_enabled_checkbox.isChecked()
    assert source.read_bytes() == before


def test_standard_options_are_independent_per_type_and_discard_together(
    standard_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """型ごとの未保存設定を切替で保持し、破棄時は全型を元へ戻す。"""
    editor, source, node = standard_editor
    panel = editor.setup_panel
    before = source.read_bytes()
    node_names = cmds.ls(long=True)
    panel.standard_enabled_checkbox.click()
    _choose(panel.standard_filter_combo, "keyable")
    _choose(panel.standard_position_combo, "first")
    transform_options = StandardAttributeOptions(True, "keyable", "first")
    assert _draft(panel).standard_options("transform") == transform_options
    assert panel.standard_filter_combo.isEnabled()
    assert panel.standard_position_combo.isEnabled()
    assert panel.save_button.isEnabled()
    assert panel.target_combo.currentText().endswith(" *")

    # 別型へ切り替えて異なる条件を設定しても前の型へ波及させない
    _choose(panel.node_type_combo, "joint")
    assert not panel.standard_enabled_checkbox.isChecked()
    panel.standard_enabled_checkbox.click()
    _choose(panel.standard_filter_combo, "channel_box")
    joint_options = StandardAttributeOptions(True, "channel_box", "last")
    assert _draft(panel).standard_options("joint") == joint_options
    _choose(panel.node_type_combo, "transform")
    assert panel.standard_enabled_checkbox.isChecked()
    assert panel.standard_filter_combo.currentData() == "keyable"
    assert panel.standard_position_combo.currentData() == "first"
    assert _draft(panel).standard_options("joint") == joint_options
    assert source.read_bytes() == before
    assert cmds.ls(long=True) == node_names
    assert not cmds.getAttr(f"{node}.rigManual", keyable=True)
    assert cmds.getAttr(f"{node}.rigStandard", keyable=True)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    panel.discard_button.click()
    _events()
    assert not panel.standard_enabled_checkbox.isChecked()
    assert panel.standard_filter_combo.currentData() == "visible"
    assert panel.standard_position_combo.currentData() == "last"
    assert _draft(panel).standard_options("transform") == (
        StandardAttributeOptions()
    )
    assert (
        _draft(panel).standard_options("joint") == StandardAttributeOptions()
    )
    assert not panel.is_dirty
    assert source.read_bytes() == before


def test_standard_options_save_and_removed_manual_attribute_auto_returns(
    standard_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """手動から外した標準属性を追加し、保存した条件を通常表示へ反映する。"""
    editor, source, _node = standard_editor
    panel = editor.setup_panel
    panel.standard_enabled_checkbox.click()
    _choose(panel.standard_position_combo, "first")
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()
    find_radios = cast(
        Callable[[type[qt.QRadioButton]], list[qt.QRadioButton]],
        getattr(panel, "findChildren"),
    )
    visibility_exclude = next(
        radio
        for radio in find_radios(qt.QRadioButton)
        if radio.text() == "含めない"
        and radio.toolTip().splitlines()[0] == "visibility"
    )
    visibility_exclude.click()
    _events()
    assert _draft(panel).paths("transform") == ("rigManual",)
    panel.save_button.click()
    _events()
    saved = CustomFilterDraft(source)
    assert saved.standard_options("transform") == StandardAttributeOptions(
        True, "visible", "first"
    )
    assert saved.paths("transform") == ("rigManual",)
    assert not panel.is_dirty

    # 保存済み定義から作る通常表示に標準属性と隠れた手動属性を合成する
    editor.controller.set_mode("values")
    editor.controller.set_attribute_filter(
        CustomFilterSelection(str(source), load_custom_filter(source))
    )
    _events()
    paths = tuple(row.attribute.path for row in editor.controller.rows)
    assert paths[0] == "visibility"
    assert paths[-1] == "rigManual"
    assert paths.count("visibility") == 1
    assert "rigStandard" in paths
    assert "rigChannel" in paths
    assert "rigHidden" not in paths
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_standard_only_type_survives_manual_removal_and_clear_removes_rule(
    standard_editor: tuple[ChannelBoxWidget, Path, str],
) -> None:
    """手動0件でも標準追加を残し、型削除だけが条件全体を除く。"""
    editor, source, _node = standard_editor
    panel = editor.setup_panel
    panel.standard_enabled_checkbox.click()
    panel.tool_box.setCurrentWidget(panel.order_page)
    panel.order_list.selectAll()
    _events()
    panel.remove_button.click()
    _events()
    assert _draft(panel).has_node_type("transform")
    assert _draft(panel).paths("transform") == ()
    assert _draft(panel).standard_options("transform").enabled
    panel.save_button.click()
    _events()
    assert CustomFilterDraft(source).standard_options("transform").enabled
    assert load_custom_filter(source).node_types["transform"] == ()

    panel.clear_type_button.click()
    _events()
    assert not _draft(panel).has_node_type("transform")
    assert not panel.standard_enabled_checkbox.isChecked()
    assert _draft(panel).standard_options("transform") == (
        StandardAttributeOptions()
    )
    panel.save_button.click()
    _events()
    assert "transform" not in load_custom_filter(source).node_types
    assert not CustomFilterDraft(source).standard_options("transform").enabled
