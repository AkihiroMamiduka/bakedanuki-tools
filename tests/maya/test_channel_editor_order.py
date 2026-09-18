# coding: utf-8
"""Channel Editorの属性優先順とフィルターを組み合わせたMaya統合検証。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.node.inspection import inspect_scalar_attributes
from bd_util.ui import qt

from bd_tools.channel_editor import config
from bd_tools.channel_editor.controller import ChannelEditorMode
from bd_tools.channel_editor.widget import ChannelEditorWidget

_PRIORITY_NAMES = (
    "visibility",
    "translateX",
    "translateY",
    "translateZ",
    "rotateX",
    "rotateY",
    "rotateZ",
    "scaleX",
    "scaleY",
    "scaleZ",
    "jointOrientX",
    "jointOrientY",
    "jointOrientZ",
    "rotateOrder",
    "rotateAxisX",
    "rotateAxisY",
    "rotateAxisZ",
    "shearXY",
    "shearXZ",
    "shearYZ",
    "rotatePivotX",
    "rotatePivotY",
    "rotatePivotZ",
    "rotatePivotTranslateX",
    "rotatePivotTranslateY",
    "rotatePivotTranslateZ",
    "scalePivotX",
    "scalePivotY",
    "scalePivotZ",
    "scalePivotTranslateX",
    "scalePivotTranslateY",
    "scalePivotTranslateZ",
)


def _events() -> None:
    """行の構築と遅延削除を処理して配置を確定する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelEditorWidget]:
    """空の専用sceneでWidgetを表示し、検証後に監視ごと解放する。"""
    assert qt_application is not None
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)
    widget = ChannelEditorWidget()
    widget.show()
    _events()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        _events()
        file_command(new=True, force=True)


@pytest.mark.parametrize("node_type", ["transform", "joint"])
@pytest.mark.parametrize("mode", ["values", "states"])
def test_transform_order_in_each_mode_and_filter(
    editor: ChannelEditorWidget, node_type: str, mode: ChannelEditorMode
) -> None:
    """指定順・RGB子・残りの安定順を全フィルターで保ち、sceneを変更しない。"""
    node = cmds.createNode(node_type)
    for name in ("customZ", "customA"):
        cmds.addAttr(node, longName=name, attributeType="double", keyable=True)
    cmds.setAttr(f"{node}.rotateOrder", keyable=False, channelBox=True)
    cmds.setAttr(f"{node}.translateY", keyable=False, channelBox=False)
    cmds.select(node, replace=True)
    _events()
    original = inspect_scalar_attributes(node)
    original_order = cmds.listAttr(node)
    original_values = [cmds.getAttr(f"{node}.{a.path}") for a in original]
    cmds.flushUndo()

    # Mayaが列挙した全属性を、仕様上の三グループへ独立に分けて期待順を作る
    by_name = {a.name: a for a in original}
    priority = [by_name[name] for name in _PRIORITY_NAMES if name in by_name]
    assert len(priority) == (32 if node_type == "joint" else 29)
    overrides = [a for a in original if a.path.startswith("drawOverride.")]
    assert "overrideColorR" in {a.name for a in overrides}
    assert "overrideColorG" in {a.name for a in overrides}
    assert "overrideColorB" in {a.name for a in overrides}
    assert "overrideColor" not in {a.name for a in original}
    overrides.remove(by_name["overrideEnabled"])
    overrides.insert(0, by_name["overrideEnabled"])
    remaining = [
        a for a in original if a not in priority and a not in overrides
    ]
    ordered = priority + overrides + remaining
    assert [a.name for a in remaining][-2:] == ["customZ", "customA"]

    # ComboBoxから切り替えても、表示対象だけを指定順から抜き出す
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData(mode))
    for selected in ("all", "visible", "keyable", "channel_box", "hidden"):
        editor.filter_combo.setCurrentIndex(
            editor.filter_combo.findData(selected)
        )
        _events()
        expected = [
            a.path
            for a in ordered
            if selected == "all"
            or (selected == "visible" and (a.keyable or a.channel_box))
            or (selected == "keyable" and a.keyable)
            or (selected == "channel_box" and not a.keyable and a.channel_box)
            or (selected == "hidden" and not a.keyable and not a.channel_box)
        ]
        assert [r.attribute.path for r in editor.controller.rows] == expected
        assert [r.row.attribute.path for r in editor.row_widgets] == expected
        positions = [r.y() for r in editor.row_widgets]
        assert positions == sorted(set(positions))
        editor.refresh()
        _events()
        assert [r.row.attribute.path for r in editor.row_widgets] == expected

    assert inspect_scalar_attributes(node) == original
    assert cmds.listAttr(node) == original_order
    assert [
        cmds.getAttr(f"{node}.{a.path}") for a in original
    ] == original_values
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("mode", ["values", "states"])
def test_priority_uses_full_paths_without_node_type_restriction(
    editor: ChannelEditorWidget, mode: ChannelEditorMode
) -> None:
    """通常nodeでも正式pathだけを優先し、類似名と別compound子を巻き込まない。"""
    node = cmds.createNode("network")
    cmds.addAttr(
        node, longName="customZ", attributeType="double", niceName="Visibility"
    )
    cmds.addAttr(
        node, longName="custom", attributeType="compound", numberOfChildren=2
    )
    cmds.addAttr(
        node, longName="translateX", parent="custom", attributeType="double"
    )
    cmds.addAttr(
        node, longName="overrideEnabled", parent="custom", attributeType="bool"
    )
    cmds.addAttr(
        node,
        longName="drawOverrideExtra",
        attributeType="compound",
        numberOfChildren=1,
    )
    cmds.addAttr(
        node,
        longName="extraEnabled",
        parent="drawOverrideExtra",
        attributeType="bool",
    )
    cmds.addAttr(
        node,
        longName="drawOverride",
        attributeType="compound",
        numberOfChildren=2,
    )
    cmds.addAttr(
        node, longName="lateZ", parent="drawOverride", attributeType="bool"
    )
    cmds.addAttr(
        node, longName="earlyA", parent="drawOverride", attributeType="bool"
    )
    cmds.addAttr(
        node, longName="rotateOrder", attributeType="enum", enumName="A:B"
    )
    cmds.addAttr(
        node,
        longName="visibility",
        attributeType="bool",
        niceName="Custom label",
    )
    cmds.select(node, replace=True)
    _events()
    original = inspect_scalar_attributes(node)
    expected_prefix = [
        "visibility",
        "rotateOrder",
        "drawOverride.lateZ",
        "drawOverride.earlyA",
    ]
    expected = expected_prefix + [
        a.path for a in original if a.path not in expected_prefix
    ]
    editor.controller.set_mode(mode)
    editor.controller.set_attribute_filter("all")
    _events()
    assert [r.row.attribute.path for r in editor.row_widgets] == expected
    assert expected.index("custom.translateX") > expected.index(
        "drawOverride.earlyA"
    )
    assert expected.index("drawOverrideExtra.extraEnabled") > expected.index(
        "drawOverride.earlyA"
    )


@pytest.mark.parametrize("mode", ["values", "states"])
def test_priority_config_is_applied_on_refresh(
    editor: ChannelEditorWidget,
    mode: ChannelEditorMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """設定で指定した属性だけを前へ移し、残りの相対順とsceneを保つ。"""
    node = cmds.createNode("joint")
    cmds.addAttr(node, longName="customWeight", attributeType="double")
    cmds.select(node, replace=True)
    editor.controller.set_mode(mode)
    editor.controller.set_attribute_filter("all")
    _events()
    before = [row.row.attribute.path for row in editor.row_widgets]
    scene_before = inspect_scalar_attributes(node)
    cmds.flushUndo()

    # 未存在・重複の指定を含めても、先頭へ移した属性以外の順序を維持する
    promoted = ("customWeight", "scale.scaleZ")
    monkeypatch.setattr(
        config,
        "ATTRIBUTE_PRIORITY_PATHS",
        (*promoted, "missingAttribute", *config.ATTRIBUTE_PRIORITY_PATHS),
    )
    editor.refresh()
    _events()
    expected = list(promoted) + [
        path for path in before if path not in promoted
    ]
    assert [row.row.attribute.path for row in editor.row_widgets] == expected
    assert inspect_scalar_attributes(node) == scene_before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
