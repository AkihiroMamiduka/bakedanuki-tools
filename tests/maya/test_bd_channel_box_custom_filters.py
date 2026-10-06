# coding: utf-8
"""bdChannelBoxのユーザー定義表示フィルターをMaya上で検証する。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.maya.ui import settings as maya_settings
from bd_util.ui import qt

from bd_tools.bd_channel_box.controller import ChannelBoxMode, ChannelRow
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterDefinition,
    CustomFilterSelection,
)
from bd_tools.bd_channel_box.widget import ChannelBoxWidget


def _events() -> None:
    """遅延した選択・表示更新とWidget破棄を処理する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _new_scene() -> None:
    """Maya commandの可変引数境界を閉じて空sceneを作る。"""
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def _selection(
    node_types: dict[str, tuple[str, ...]], *, name: str = "Rig"
) -> CustomFilterSelection:
    """ファイル管理に依存しない表示フィルター選択を作る。"""
    return CustomFilterSelection(
        "C:/filters/rig.json",
        CustomFilterDefinition(name, node_types),
    )


def _paths(editor: ChannelBoxWidget) -> tuple[str, ...]:
    """表示基準ノードから構築された行の正式pathを返す。"""
    return tuple(row.attribute.path for row in editor.controller.rows)


@pytest.fixture
def editor(
    qt_application: qt.QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[ChannelBoxWidget]:
    """空sceneに選択監視付きのbdChannelBoxを作り、終了時に解放する。"""
    assert qt_application is not None

    def settings_root() -> Path:
        """各テストの個人設定を専用の一時ディレクトリへ分離する。"""
        return tmp_path

    monkeypatch.setattr(maya_settings, "get_ui_settings_root", settings_root)
    _new_scene()
    widget = ChannelBoxWidget()
    widget.show()
    _events()
    try:
        yield widget
    finally:
        widget.dispose()
        widget.close()
        widget.deleteLater()
        _events()
        _new_scene()


def test_custom_filter_uses_json_order_and_edits_hidden_scalar(
    editor: ChannelBoxWidget,
) -> None:
    """正式path順と表示フラグ非依存の行を使い、選択だけでは書き込まない。"""
    node = cmds.createNode("transform", name="customBase")
    for name in ("hiddenA", "hiddenB"):
        cmds.addAttr(node, longName=name, attributeType="double")
    cmds.select(node, replace=True)
    _events()
    cmds.flushUndo()

    selection = _selection(
        {
            "transform": (
                "hiddenB",
                "translate.translateX",
                "missingAttribute",
                "hiddenA",
                "hiddenB",
            )
        }
    )
    editor.controller.set_attribute_filter(selection)
    _events()
    assert editor.controller.custom_filter_fallback_node_type is None
    assert _paths(editor) == (
        "hiddenB",
        "translate.translateX",
        "hiddenA",
    )
    assert cmds.getAttr(f"{node}.hiddenB", keyable=True) is False
    assert cmds.getAttr(f"{node}.hiddenB", channelBox=True) is False
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    row = next(
        row
        for row in editor.controller.rows
        if row.attribute.path == "hiddenB"
    )
    assert isinstance(row, ChannelRow)
    assert isinstance(row.binding, MayaFloatPlugsBinding)
    row.binding.set_value(1.25)
    _events()
    assert cmds.getAttr(f"{node}.hiddenB") == 1.25
    assert cmds.getAttr(f"{node}.hiddenB", keyable=True) is False
    assert cmds.getAttr(f"{node}.hiddenB", channelBox=True) is False
    cmds.undo()
    _events()
    assert cmds.getAttr(f"{node}.hiddenB") == 0.0


@pytest.mark.parametrize("mode", ("values", "states"))
def test_custom_filter_without_node_type_uses_visible_fallback(
    editor: ChannelBoxWidget,
    mode: ChannelBoxMode,
) -> None:
    """基準ノードの型が未定義なら既定の表示状態と優先順を使う。"""
    node = cmds.createNode("transform", name="fallbackBase")
    cmds.addAttr(node, longName="shown", attributeType="double", keyable=True)
    cmds.addAttr(node, longName="hidden", attributeType="double")
    cmds.select(node, replace=True)
    _events()
    editor.controller.set_mode(mode)
    editor.controller.set_attribute_filter("visible")
    expected = _paths(editor)
    assert "shown" in expected
    assert "hidden" not in expected
    cmds.flushUndo()

    editor.controller.set_attribute_filter(_selection({"joint": ("hidden",)}))
    _events()
    assert editor.controller.custom_filter_fallback_node_type == "transform"
    assert _paths(editor) == expected
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("paths", ((), ("missingAttribute",)))
def test_explicit_node_type_with_no_existing_paths_stays_empty(
    editor: ChannelBoxWidget,
    paths: tuple[str, ...],
) -> None:
    """型が定義済みなら空配列や全欠落pathでもfallbackしない。"""
    node = cmds.createNode("transform", name="emptyCustomBase")
    cmds.select(node, replace=True)
    _events()
    cmds.flushUndo()

    editor.controller.set_attribute_filter(_selection({"transform": paths}))
    _events()
    assert editor.controller.custom_filter_fallback_node_type is None
    assert _paths(editor) == ()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_optional_leading_dot_matches_root_attribute_once(
    editor: ChannelBoxWidget,
) -> None:
    """先頭ドット付きpathを受理し、同じ属性への重複指定を一行にする。"""
    node = cmds.createNode("transform", name="dottedPathBase")
    cmds.select(node, replace=True)
    _events()
    cmds.flushUndo()

    editor.controller.set_attribute_filter(
        _selection({"transform": (".visibility", "visibility")})
    )
    _events()
    assert _paths(editor) == ("visibility",)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_custom_filter_uses_last_selected_node_type_and_shared_paths(
    editor: ChannelBoxWidget,
) -> None:
    """異種ノードでも基準型で行を選び、同path・同種だけ一括対象にする。"""
    transform = cmds.createNode("transform", name="mixedTransform")
    joint = cmds.createNode("joint", name="mixedJoint")
    for node in (transform, joint):
        cmds.addAttr(
            node, longName="shared", attributeType="double", keyable=True
        )
    cmds.addAttr(joint, longName="jointOnly", attributeType="double")
    selection = _selection(
        {
            "transform": ("shared",),
            "joint": ("jointOnly", "shared"),
        }
    )

    cmds.select(transform, joint, replace=True)
    _events()
    cmds.flushUndo()
    editor.controller.set_attribute_filter(selection)
    _events()
    assert _paths(editor) == ("jointOnly", "shared")
    joint_only, shared = editor.controller.rows
    assert joint_only.target_names == ("|mixedJoint",)
    assert shared.target_names == ("|mixedJoint", "|mixedTransform")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    cmds.select(joint, transform, replace=True)
    _events()
    assert _paths(editor) == ("shared",)
    assert editor.controller.rows[0].target_names == (
        "|mixedTransform",
        "|mixedJoint",
    )


def test_custom_filter_replace_and_clear_update_both_modes(
    editor: ChannelBoxWidget,
) -> None:
    """定義再読込と無効化を両モードへ反映し、既定値へ戻す。"""
    node = cmds.createNode("transform", name="managedBase")
    cmds.addAttr(node, longName="first", attributeType="double", keyable=True)
    cmds.addAttr(node, longName="second", attributeType="double")
    cmds.select(node, replace=True)
    _events()
    cmds.flushUndo()
    original = _selection({"transform": ("first",)})
    updated = _selection({"transform": ("second",)})

    editor.controller.set_attribute_filter(original)
    editor.controller.set_mode("states")
    editor.controller.set_attribute_filter(original)
    editor.controller.replace_custom_filter(updated)
    _events()
    assert editor.controller.attribute_filter == updated
    assert _paths(editor) == ("second",)
    editor.controller.set_mode("values")
    _events()
    assert editor.controller.attribute_filter == updated
    assert _paths(editor) == ("second",)

    editor.controller.clear_custom_filter(original.path)
    _events()
    assert editor.controller.attribute_filter == "visible"
    assert "second" not in _paths(editor)
    editor.controller.set_mode("states")
    _events()
    assert editor.controller.attribute_filter == "all"
    assert "second" in _paths(editor)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
