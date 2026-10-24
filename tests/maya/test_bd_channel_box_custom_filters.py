# coding: utf-8
"""bdChannelBoxのユーザー定義表示フィルターをMaya上で検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.node.inspection import ScalarAttributeInfo
from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.maya.ui import settings as maya_settings
from bd_util.ui import qt
from bd_tools.bd_channel_box import custom_filter_dialogs as dialog_module

from bd_tools.bd_channel_box.controller import ChannelBoxMode, ChannelRow
from bd_tools.bd_channel_box import controller as controller_module
from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.custom_filter_setup import CustomFilterSetupPanel
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


def _register_saved_filter(editor: ChannelBoxWidget, path: Path) -> None:
    """共有定義を登録して構成を保存し、内容編集前の基準を確定する。"""
    editor.custom_filter_registry.add_paths((path,))
    editor.custom_filter_registry.save()


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


def _candidate_label(panel: CustomFilterSetupPanel, path: str) -> qt.QLabel:
    """正式pathに対応する設定候補の属性名欄を取得する。"""
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()
    find_labels = cast(
        Callable[[type[qt.QLabel]], list[qt.QLabel]],
        getattr(panel, "findChildren"),
    )
    return next(
        label for label in find_labels(qt.QLabel) if label.toolTip() == path
    )


def _candidate_radio(
    panel: CustomFilterSetupPanel, path: str, included: bool
) -> qt.QRadioButton:
    """正式pathと所属方向に対応する候補のラジオを取得する。"""
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()
    find_radios = cast(
        Callable[[type[qt.QRadioButton]], list[qt.QRadioButton]],
        getattr(panel, "findChildren"),
    )
    text = "含める" if included else "含めない"
    return next(
        radio
        for radio in find_radios(qt.QRadioButton)
        if radio.toolTip().splitlines()[0] == path and radio.text() == text
    )


def _mouse_candidate(
    widget: qt.QWidget,
    modifiers: qt.Qt.KeyboardModifier = qt.Qt.KeyboardModifier.NoModifier,
    *,
    end_global: qt.QPoint | None = None,
) -> None:
    """属性名へクリックまたは縦ドラッグ相当のマウス入力を送る。"""
    start = widget.rect().center()
    start_global = widget.mapToGlobal(start)
    events = [
        (
            qt.QEvent.Type.MouseButtonPress,
            start_global,
            qt.Qt.MouseButton.LeftButton,
        )
    ]
    if end_global is not None:
        events.append(
            (
                qt.QEvent.Type.MouseMove,
                end_global,
                qt.Qt.MouseButton.LeftButton,
            )
        )
    events.append(
        (
            qt.QEvent.Type.MouseButtonRelease,
            end_global if end_global is not None else start_global,
            qt.Qt.MouseButton.NoButton,
        )
    )
    for kind, global_position, buttons in events:
        button = (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseMove
            else qt.Qt.MouseButton.LeftButton
        )
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(widget.mapFromGlobal(global_position)),
            qt.QPointF(global_position),
            button,
            buttons,
            modifiers,
        )
        qt.QApplication.sendEvent(widget, event)
    _events()


def _mouse_order_item(
    panel: CustomFilterSetupPanel,
    index: int,
    modifiers: qt.Qt.KeyboardModifier = qt.Qt.KeyboardModifier.NoModifier,
) -> None:
    """表示順一覧の項目を修飾キー付きでクリックする。"""
    panel.tool_box.setCurrentWidget(panel.order_page)
    _events()
    order = panel.order_list
    item = order.item(index)
    order.scrollToItem(item)
    _events()
    viewport = order.viewport()
    position = order.visualItemRect(item).center()
    for kind, buttons in (
        (qt.QEvent.Type.MouseButtonPress, qt.Qt.MouseButton.LeftButton),
        (qt.QEvent.Type.MouseButtonRelease, qt.Qt.MouseButton.NoButton),
    ):
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(position),
            qt.QPointF(viewport.mapToGlobal(position)),
            qt.Qt.MouseButton.LeftButton,
            buttons,
            modifiers,
        )
        qt.QApplication.sendEvent(viewport, event)
    _events()


def _radio_position(button: qt.QRadioButton) -> qt.QPoint:
    """余白を避け、ラジオの丸印中央に対応する画面座標を返す。"""
    return button.mapToGlobal(qt.QPoint(8, button.height() // 2))


def _send_radio_mouse(
    origin: qt.QRadioButton, kind: qt.QEvent.Type, position: qt.QPoint
) -> None:
    """押下元へ実Qtマウス入力を送り、なぞり途中の状態も検査可能にする。"""
    event = qt.QtGui.QMouseEvent(
        kind,
        qt.QPointF(origin.mapFromGlobal(position)),
        qt.QPointF(position),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseMove
            else qt.Qt.MouseButton.LeftButton
        ),
        (
            qt.Qt.MouseButton.NoButton
            if kind == qt.QEvent.Type.MouseButtonRelease
            else qt.Qt.MouseButton.LeftButton
        ),
        qt.Qt.KeyboardModifier.NoModifier,
    )
    qt.QApplication.sendEvent(origin, event)


def _setup_radio_sweep(
    editor: ChannelBoxWidget, tmp_path: Path
) -> tuple[CustomFilterSetupPanel, str, Path]:
    """既存・欠落・他型の定義を持つ、なぞり検証用の候補画面を作る。"""
    node = cmds.createNode("transform", name="sweepSetupBase")
    for name in ("sweepA", "sweepB", "sweepC", "sweepD"):
        cmds.addAttr(node, longName=name, attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "sweep-rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Sweep Rig",
                "node_types": {
                    "transform": ["legacyMissing"],
                    "joint": ["jointOnly"],
                },
            }
        ),
        encoding="utf-8",
    )
    _register_saved_filter(editor, path)
    editor.resize(640, 800)
    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("sweep")
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()
    cmds.flushUndo()
    return panel, node, path


def _selected_order_paths(panel: CustomFilterSetupPanel) -> tuple[str, ...]:
    """表示順一覧の選択項目を現在の並び順で取得する。"""
    order = panel.order_list
    return tuple(
        path
        for index in range(order.count())
        if order.item(index).isSelected()
        if isinstance(
            path := order.item(index).data(qt.Qt.ItemDataRole.UserRole), str
        )
    )


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
    unexpected_warnings: list[str] = []

    def cancel_unexpected_warning(
        *_args: object,
    ) -> qt.QMessageBox.StandardButton:
        """未想定の確認で停止せず、テスト終了時に理由付きで失敗させる。"""
        unexpected_warnings.append(str(_args[2]))
        return qt.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(qt.QMessageBox, "warning", cancel_unexpected_warning)
    _new_scene()
    widget = ChannelBoxWidget()
    widget.show()
    _events()
    try:
        yield widget
    finally:
        widget.setup_panel.discard()
        widget.dispose()
        widget.close()
        widget.deleteLater()
        _events()
        _new_scene()
        assert not unexpected_warnings, unexpected_warnings


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


@pytest.mark.parametrize("count", (1, 49, 50, 1000))
def test_setup_inspects_only_reference_and_restores_full_value_selection(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    """選択数によらず設定は基準だけを調べ、値編集では元の全選択へ戻る。"""
    editor.controller.set_mode("custom_filter_setup")
    others = tuple(
        cmds.createNode("network", name=f"setupOther{index}", skipSelect=True)
        for index in range(count - 1)
    )
    reference = cmds.createNode(
        "transform", name="setupReference", skipSelect=True
    )
    cmds.addAttr(reference, longName="referenceOnly", attributeType="double")
    if others:
        cmds.addAttr(others[0], longName="otherOnly", attributeType="double")
    inspected: list[str] = []
    original = controller_module.inspect_scalar_attributes

    def inspect(name: str) -> tuple[ScalarAttributeInfo, ...]:
        """設定用の属性取得が基準ノードだけに限定されているか記録する。"""
        inspected.append(name)
        return original(name)

    monkeypatch.setattr(
        controller_module, "inspect_scalar_attributes", inspect
    )
    cmds.select(*others, reference, replace=True)
    _events()
    expected_selection = [*others, f"|{reference}"]
    assert cmds.ls(selection=True, long=True) == expected_selection
    assert inspected == [f"|{reference}"]
    assert editor.controller.node_names == (f"|{reference}",)
    assert len(editor.controller.node_ids) == 1
    assert not editor.controller.selection_limit_exceeded
    assert editor.controller.rows == ()
    assert editor.setup_panel.isVisible()
    assert not editor.empty_label.isVisible()
    assert editor.setup_panel.node_label.text() == (
        f"基準: |{reference}（transform 型）"
    )
    paths = tuple(a.path for a in editor.controller.setup_attributes)
    assert "referenceOnly" in paths
    assert "otherOnly" not in paths

    editor.controller.set_mode("values")
    _events()
    assert len(editor.controller.node_names) == count
    assert inspected == [f"|{reference}", f"|{reference}"]
    assert cmds.ls(selection=True, long=True) == expected_selection


def test_setup_watches_reference_structure_name_and_removal_only(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非基準の変更で再構築せず、基準の属性・名前・削除へ追従する。"""
    other = cmds.createNode("network", name="unwatchedSetup", skipSelect=True)
    reference = cmds.createNode(
        "network", name="watchedSetup", skipSelect=True
    )
    cmds.select(other, reference, replace=True)
    editor.controller.set_mode("custom_filter_setup")
    _events()
    inspected: list[str] = []
    original = controller_module.inspect_scalar_attributes

    def inspect(name: str) -> tuple[ScalarAttributeInfo, ...]:
        """構成変更後に属性情報を再取得した対象を記録する。"""
        inspected.append(name)
        return original(name)

    monkeypatch.setattr(
        controller_module, "inspect_scalar_attributes", inspect
    )
    cmds.addAttr(other, longName="ignoredAttribute", attributeType="double")
    other = cmds.rename(other, "renamedUnwatchedSetup")
    _events()
    assert inspected == []
    cmds.addAttr(
        reference, longName="watchedAttribute", attributeType="double"
    )
    _events()
    assert inspected == [reference]
    assert "watchedAttribute" in (
        a.path for a in editor.controller.setup_attributes
    )
    reference = cmds.rename(reference, "renamedWatchedSetup")
    _events()
    assert inspected[-1] == reference
    assert editor.controller.node_names == (reference,)
    assert reference in editor.setup_panel.node_label.text()
    cmds.deleteAttr(f"{reference}.watchedAttribute")
    _events()
    assert "watchedAttribute" not in (
        a.path for a in editor.controller.setup_attributes
    )
    cmds.delete(reference)
    _events()
    assert editor.controller.node_names == (other,)
    cmds.select(clear=True)
    _events()
    assert editor.controller.node_names == ()
    assert editor.controller.setup_attributes == ()
    assert (
        editor.setup_panel.node_label.text() == "Maya ノードを選択してください"
    )


def test_setup_reference_type_switch_preserves_unsaved_definitions(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """混在選択の基準を切り替えても型別の未保存定義と既存pathを保持する。"""
    joint = cmds.createNode("joint", name="setupJoint", skipSelect=True)
    network = cmds.createNode("network", name="setupNetwork", skipSelect=True)
    cmds.addAttr(joint, longName="jointOnly", attributeType="double")
    cmds.addAttr(network, longName="networkOnly", attributeType="double")
    path = tmp_path / "reference-types.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Reference Types",
                "node_types": {
                    "joint": ["missingJoint"],
                    "transform": ["unchangedTransform"],
                },
            }
        ),
        encoding="utf-8",
    )
    original_json = path.read_bytes()
    _register_saved_filter(editor, path)
    cmds.select(network, joint, replace=True)
    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    _events()
    draft = panel.draft
    assert draft is not None
    assert editor.controller.node_names == (f"|{joint}",)
    assert "networkOnly" not in (
        a.path for a in editor.controller.setup_attributes
    )
    _candidate_radio(panel, "jointOnly", True).click()
    _events()
    assert draft.paths("joint") == ("missingJoint", "jointOnly")
    cmds.select(joint, network, replace=True)
    _events()
    assert panel.draft is draft and draft.is_dirty
    assert editor.controller.node_names == (network,)
    assert "network 型" in panel.node_label.text()
    assert "jointOnly" not in (
        a.path for a in editor.controller.setup_attributes
    )
    cmds.flushUndo()
    _candidate_radio(panel, "networkOnly", True).click()
    _events()
    assert path.read_bytes() == original_json
    assert draft.paths("joint") == ("missingJoint", "jointOnly")
    assert draft.paths("transform") == ("unchangedTransform",)
    panel.save_button.click()
    _events()
    assert json.loads(path.read_text(encoding="utf-8"))["node_types"] == {
        "joint": ["missingJoint", "jointOnly"],
        "network": ["networkOnly"],
        "transform": ["unchangedTransform"],
    }
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert cmds.ls(selection=True, long=True) == [f"|{joint}", network]


def test_setup_mode_saves_hidden_attribute_without_scene_edit(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """設定モードの2択と保存がJSONのみを更新し、通常表示へ反映する。"""
    node = cmds.createNode("transform", name="setupBase")
    cmds.addAttr(node, longName="hiddenRig", attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "setup-rig.json"
    create_custom_filter(path, "Rig")
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    _events()
    assert editor.filter_combo.count() == 5
    assert editor.controller.mode == "custom_filter_setup"
    assert not editor.header_label.isVisible()
    assert "transform 型" in panel.node_label.text()
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    _events()
    assert "hiddenRig" in (
        attribute.path for attribute in editor.controller.setup_attributes
    )
    assert "translate.translateX" not in (
        attribute.path for attribute in editor.controller.setup_attributes
    )
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("all"))
    _events()
    find_buttons = cast(
        Callable[[type[qt.QRadioButton]], list[qt.QRadioButton]],
        getattr(panel, "findChildren"),
    )
    include = next(
        button
        for button in find_buttons(qt.QRadioButton)
        if button.toolTip().splitlines()[0] == "hiddenRig"
        and button.text() == "含める"
    )
    include.click()
    _events()
    assert json.loads(path.read_text(encoding="utf-8"))["node_types"] == {}
    assert panel.draft is not None and panel.draft.is_dirty
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    panel.save_button.click()
    _events()
    assert json.loads(path.read_text(encoding="utf-8"))["node_types"] == {
        "transform": ["hiddenRig"]
    }
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    editor.mode_combo.setCurrentIndex(0)
    _events()
    index = next(
        index
        for index in range(editor.filter_combo.count())
        if editor.filter_combo.itemText(index) == "Custom: setup-rig"
    )
    editor.filter_combo.setCurrentIndex(index)
    _events()
    assert _paths(editor) == ("hiddenRig",)
    editor.mode_combo.setCurrentIndex(2)
    editor.mode_combo.setCurrentIndex(0)
    _events()
    assert editor.filter_combo.currentText() == "Custom: setup-rig"


def test_setup_order_multi_selection_moves_and_removes_as_one_action(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """上段の連続・非連続選択を保持して移動し、全選択を除外する。"""
    node = cmds.createNode("joint", name="multiOrderBase")
    for name in ("orderA", "orderB", "orderC", "orderD"):
        cmds.addAttr(node, longName=name, attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "order-rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Order Rig",
                "node_types": {
                    "joint": [
                        "missingOld",
                        "orderA",
                        "orderB",
                        "orderC",
                        "orderD",
                    ],
                    "transform": ["other"],
                },
            }
        ),
        encoding="utf-8",
    )
    source = path.read_bytes()
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    _events()
    assert panel.order_list.selectionMode() == (
        qt.QAbstractItemView.SelectionMode.ExtendedSelection
    )
    _mouse_order_item(panel, 1)
    assert _selected_order_paths(panel) == ("orderA",)
    panel.order_list.setFocus()
    for kind in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
        qt.QApplication.sendEvent(
            panel.order_list,
            qt.QtGui.QKeyEvent(
                kind,
                qt.Qt.Key.Key_Down,
                qt.Qt.KeyboardModifier.ShiftModifier,
            ),
        )
    _events()
    assert _selected_order_paths(panel) == ("orderA", "orderB")
    _mouse_order_item(panel, 4, qt.Qt.KeyboardModifier.ControlModifier)
    assert _selected_order_paths(panel) == ("orderA", "orderB", "orderD")
    assert panel.up_button.isEnabled()
    assert not panel.down_button.isEnabled()

    panel.up_button.click()
    _events()
    assert panel.draft is not None
    assert panel.draft.paths("joint") == (
        "orderA",
        "orderB",
        "missingOld",
        "orderD",
        "orderC",
    )
    assert _selected_order_paths(panel) == ("orderA", "orderB", "orderD")
    assert not panel.up_button.isEnabled()
    assert panel.down_button.isEnabled()
    panel.down_button.click()
    _events()
    assert panel.draft.paths("joint") == (
        "missingOld",
        "orderA",
        "orderB",
        "orderC",
        "orderD",
    )
    assert _selected_order_paths(panel) == ("orderA", "orderB", "orderD")
    assert not panel.down_button.isEnabled()
    assert not panel.draft.is_dirty

    _mouse_order_item(panel, 4, qt.Qt.KeyboardModifier.ControlModifier)
    assert _selected_order_paths(panel) == ("orderA", "orderB")
    panel.remove_button.click()
    _events()
    assert panel.draft.paths("joint") == (
        "missingOld",
        "orderC",
        "orderD",
    )
    assert _selected_order_paths(panel) == ()
    _mouse_order_item(panel, 0)
    _mouse_order_item(panel, 1, qt.Qt.KeyboardModifier.ControlModifier)
    panel.remove_button.click()
    _events()
    assert panel.draft.paths("joint") == ("orderD",)
    assert panel.draft.paths("transform") == ("other",)
    assert path.read_bytes() == source
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    panel.save_button.click()
    _events()
    assert json.loads(path.read_text(encoding="utf-8"))["node_types"] == {
        "joint": ["orderD"],
        "transform": ["other"],
    }
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_setup_toolbox_and_selected_candidates_keep_other_definitions(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """作業ページを切り替えて選択とスクロールを保ち、候補外の定義を守る。"""
    node = cmds.createNode("transform", name="bulkSetupBase")
    batch_paths = tuple(f"batch{index:02d}" for index in range(30))
    for path in (*batch_paths, "hiddenOther"):
        cmds.addAttr(node, longName=path, attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "bulk-rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Bulk Rig",
                "node_types": {
                    "transform": ["legacyMissing", "hiddenOther", "batch20"],
                    "joint": ["jointOnly"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original_json = path.read_bytes()
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.resize(640, 800)
    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("batch")
    _events()

    assert panel.tool_box.count() == 2
    assert panel.tool_box.itemText(0) == "フィルターの表示順"
    assert panel.tool_box.itemText(1) == "属性をフィルターに含める"
    assert panel.tool_box.currentWidget() is panel.candidate_page
    assert panel.candidate_scroll.isVisible()
    assert not panel.order_list.isVisible()
    assert panel.candidate_scroll.verticalScrollBar().maximum() > 0

    first = _candidate_label(panel, batch_paths[0])
    last = _candidate_label(panel, batch_paths[-1])
    panel.candidate_scroll.ensureWidgetVisible(first)
    _events()
    _mouse_candidate(first)
    panel.candidate_scroll.ensureWidgetVisible(last)
    _events()
    _mouse_candidate(last, qt.Qt.KeyboardModifier.ShiftModifier)
    assert panel.selected_candidate_paths() == batch_paths
    _candidate_radio(panel, batch_paths[-1], True).click()
    _events()
    assert panel.draft is not None
    assert panel.draft.paths("transform") == (
        "legacyMissing",
        "hiddenOther",
        "batch20",
        *(candidate for candidate in batch_paths if candidate != "batch20"),
    )
    assert panel.draft.paths("joint") == ("jointOnly",)
    assert path.read_bytes() == original_json
    assert cmds.getAttr(f"{node}.batch00") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 切替だけでは下書き・検索・候補選択・各一覧の位置を描き直さない
    draft = panel.draft
    candidate_position = panel.candidate_scroll.verticalScrollBar().value()
    panel.tool_box.setCurrentWidget(panel.order_page)
    _events()
    assert panel.order_list.isVisible()
    assert not panel.candidate_scroll.isVisible()
    assert panel.target_combo.isVisible() and panel.node_type_combo.isVisible()
    panel.order_list.setCurrentRow(2)
    panel.order_list.verticalScrollBar().setValue(
        panel.order_list.verticalScrollBar().maximum()
    )
    order_position = panel.order_list.verticalScrollBar().value()
    selected_order = _selected_order_paths(panel)
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()
    assert panel.draft is draft
    assert panel.search_edit.text() == "batch"
    assert panel.selected_candidate_paths() == batch_paths
    assert (
        panel.candidate_scroll.verticalScrollBar().value()
        == candidate_position
    )
    panel.tool_box.setCurrentWidget(panel.order_page)
    _events()
    assert _selected_order_paths(panel) == selected_order
    assert panel.order_list.verticalScrollBar().value() == order_position
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()

    _candidate_radio(panel, batch_paths[-1], False).click()
    _events()
    assert panel.draft.paths("transform") == ("legacyMissing", "hiddenOther")
    assert panel.draft.paths("joint") == ("jointOnly",)
    assert path.read_bytes() == original_json
    panel.save_button.click()
    _events()
    assert json.loads(path.read_text(encoding="utf-8"))["node_types"] == {
        "transform": ["legacyMissing", "hiddenOther"],
        "joint": ["jointOnly"],
    }
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_setup_radio_exclusion_saves_explicit_empty_type(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """候補をすべて除外しても空の型定義を保存し、標準表示へ戻さない。"""
    node = cmds.createNode("transform", name="emptyBulkBase")
    cmds.addAttr(node, longName="bulkHidden", attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "empty-bulk.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Empty Bulk",
                "node_types": {"transform": ["bulkHidden"]},
            }
        ),
        encoding="utf-8",
    )
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("bulkHidden")
    _events()
    _candidate_radio(panel, "bulkHidden", False).click()
    _events()
    assert panel.draft is not None
    assert panel.draft.has_node_type("transform")
    assert panel.draft.paths("transform") == ()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    panel.save_button.click()
    _events()
    assert json.loads(path.read_text(encoding="utf-8"))["node_types"] == {
        "transform": []
    }
    editor.mode_combo.setCurrentIndex(0)
    _events()
    index = next(
        index
        for index in range(editor.filter_combo.count())
        if editor.filter_combo.itemText(index) == "Custom: empty-bulk"
    )
    editor.filter_combo.setCurrentIndex(index)
    _events()
    assert _paths(editor) == ()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_setup_selected_radio_applies_once_to_selected_attributes(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """選択中のラジオは選択全体へ、選択外のラジオは一行だけへ適用する。"""
    node = cmds.createNode("transform", name="selectedSetupBase")
    for name in ("selectA", "selectB", "selectC", "selectD"):
        cmds.addAttr(node, longName=name, attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "selected-rig.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Selected Rig",
                "node_types": {
                    "transform": ["legacyMissing", "selectA"],
                    "joint": ["jointOnly"],
                },
            }
        ),
        encoding="utf-8",
    )
    source = path.read_bytes()
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("select")
    _events()
    _mouse_candidate(_candidate_label(panel, "selectA"))
    _mouse_candidate(
        _candidate_label(panel, "selectC"),
        qt.Qt.KeyboardModifier.ControlModifier,
    )
    assert panel.selected_candidate_paths() == ("selectA", "selectC")
    assert panel.draft is not None and not panel.draft.is_dirty
    assert (
        "選択中の属性すべて"
        in _candidate_radio(panel, "selectA", True).toolTip()
    )

    # 既にONのラジオも選択した別の属性へ適用する
    _candidate_radio(panel, "selectA", True).click()
    _events()
    assert panel.draft.paths("transform") == (
        "legacyMissing",
        "selectA",
        "selectC",
    )
    _candidate_radio(panel, "selectB", True).click()
    _events()
    assert panel.draft.paths("transform") == (
        "legacyMissing",
        "selectA",
        "selectC",
        "selectB",
    )
    assert panel.selected_candidate_paths() == ("selectA", "selectC")
    _candidate_radio(panel, "selectA", False).click()
    _events()
    assert panel.draft.paths("transform") == ("legacyMissing", "selectB")
    assert panel.draft.paths("joint") == ("jointOnly",)
    assert path.read_bytes() == source
    assert cmds.getAttr(f"{node}.selectA") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    panel.search_edit.setText("selectA")
    _events()
    assert panel.selected_candidate_paths() == ("selectA",)
    panel.search_edit.clear()
    _events()
    assert panel.selected_candidate_paths() == ("selectA",)
    _mouse_candidate(panel.candidate_container)
    assert panel.selected_candidate_paths() == ()


def test_setup_radio_sweep_preserves_selection_and_batches_display(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通過順・同列・一回適用を守り、終了時だけ表示順を同期する。"""
    panel, node, path = _setup_radio_sweep(editor, tmp_path)
    source = path.read_bytes()
    draft = panel.draft
    assert draft is not None
    _mouse_candidate(_candidate_label(panel, "sweepA"))
    _mouse_candidate(
        _candidate_label(panel, "sweepD"),
        qt.Qt.KeyboardModifier.ControlModifier,
    )
    applied: list[tuple[tuple[str, ...], bool]] = []
    refreshes = {"order": 0, "status": 0}
    original_apply = draft.set_many_included
    original_order = cast(Callable[[], None], getattr(panel, "_refresh_order"))
    original_status = cast(
        Callable[[], None], getattr(panel, "_refresh_target_label")
    )

    def record_apply(
        node_type: str, paths: Iterable[str], included: bool
    ) -> None:
        """実際にdraftへ渡された行と順序を記録する。"""
        items = tuple(paths)
        applied.append((items, included))
        original_apply(node_type, items, included)

    def refresh_order() -> None:
        """表示順の再構築回数を数える。"""
        refreshes["order"] += 1
        original_order()

    def refresh_status() -> None:
        """未保存状態の表示更新回数を数える。"""
        refreshes["status"] += 1
        original_status()

    monkeypatch.setattr(draft, "set_many_included", record_apply)
    monkeypatch.setattr(panel, "_refresh_order", refresh_order)
    monkeypatch.setattr(panel, "_refresh_target_label", refresh_status)
    include_a = _candidate_radio(panel, "sweepA", True)
    include_c = _candidate_radio(panel, "sweepC", True)
    exclude_a = _candidate_radio(panel, "sweepA", False)
    exclude_d = _candidate_radio(panel, "sweepD", False)
    start = _radio_position(include_c)
    _send_radio_mouse(include_c, qt.QEvent.Type.MouseButtonPress, start)
    for button in (include_a, exclude_a, exclude_d, exclude_a, include_c):
        _send_radio_mouse(
            include_c, qt.QEvent.Type.MouseMove, _radio_position(button)
        )
    assert panel.radio_sweep.is_active
    assert draft.paths("transform") == (
        "legacyMissing",
        "sweepC",
        "sweepB",
        "sweepA",
    )
    assert applied == [
        (("sweepC",), True),
        (("sweepB",), True),
        (("sweepA",), True),
    ]
    assert refreshes == {"order": 0, "status": 0}
    assert panel.order_list.count() == 1
    assert include_a.isChecked() and include_c.isChecked()
    assert not _candidate_radio(panel, "sweepD", True).isChecked()
    assert panel.selected_candidate_paths() == ("sweepA", "sweepD")
    _send_radio_mouse(include_c, qt.QEvent.Type.MouseButtonRelease, start)
    assert not panel.radio_sweep.is_active
    assert refreshes == {"order": 1, "status": 1}
    assert panel.order_list.count() == 4
    assert panel.save_button.isEnabled() and draft.is_dirty
    assert _candidate_radio(panel, "sweepC", True) is include_c
    assert draft.paths("joint") == ("jointOnly",)
    assert path.read_bytes() == source
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 含めない側も通過行だけを外し、欠落定義と候補選択を保持する
    exclude_c = _candidate_radio(panel, "sweepC", False)
    _send_radio_mouse(
        exclude_c, qt.QEvent.Type.MouseButtonPress, _radio_position(exclude_c)
    )
    _send_radio_mouse(
        exclude_c, qt.QEvent.Type.MouseMove, _radio_position(exclude_a)
    )
    _send_radio_mouse(
        exclude_c,
        qt.QEvent.Type.MouseButtonRelease,
        _radio_position(exclude_a),
    )
    assert draft.paths("transform") == ("legacyMissing",)
    assert panel.selected_candidate_paths() == ("sweepA", "sweepD")
    assert not draft.is_dirty
    for name in ("sweepA", "sweepB", "sweepC", "sweepD"):
        plug = f"{node}.{name}"
        assert cmds.getAttr(plug) == 0.0
        assert cmds.getAttr(plug, keyable=True) is False
        assert cmds.getAttr(plug, channelBox=True) is False
        assert cmds.getAttr(plug, lock=True) is False
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize(
    "interruption", ("search", "reference", "json", "hide", "save", "page")
)
def test_setup_radio_sweep_finishes_before_context_changes(
    editor: ChannelBoxWidget, tmp_path: Path, interruption: str
) -> None:
    """設定対象や表示の変更でなぞりを閉じ、古い入力を次の候補へ持ち越さない。"""
    panel, node, path = _setup_radio_sweep(editor, tmp_path)
    draft = panel.draft
    assert draft is not None
    source = path.read_bytes()
    origin = _candidate_radio(panel, "sweepB", True)
    end = _candidate_radio(panel, "sweepA", True)
    end_position = _radio_position(end)
    _send_radio_mouse(
        origin, qt.QEvent.Type.MouseButtonPress, _radio_position(origin)
    )
    _send_radio_mouse(origin, qt.QEvent.Type.MouseMove, end_position)
    assert panel.radio_sweep.is_active
    assert draft.paths("transform") == ("legacyMissing", "sweepB", "sweepA")
    assert panel.order_list.count() == 1
    if interruption == "search":
        panel.search_edit.setText("sweepA")
    elif interruption == "reference":
        panel.set_node(None, None, ())
    elif interruption == "json":
        panel.discard()
    elif interruption == "hide":
        panel.hide()
    elif interruption == "page":
        panel.tool_box.setCurrentWidget(panel.order_page)
    else:
        assert panel.save()
    assert not panel.radio_sweep.is_active
    if qt.isValid(origin):
        _send_radio_mouse(
            origin, qt.QEvent.Type.MouseButtonRelease, end_position
        )
    _events()
    if interruption == "json":
        assert panel.draft is not draft
        assert panel.draft is not None and not panel.draft.is_dirty
        assert panel.draft.paths("transform") == ("legacyMissing",)
    elif interruption == "save":
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["node_types"] == {
            "transform": ["legacyMissing", "sweepB", "sweepA"],
            "joint": ["jointOnly"],
        }
        assert not draft.is_dirty
    else:
        assert draft.is_dirty
        assert path.read_bytes() == source
    if interruption == "search":
        # 検索で隠れた行の位置を通過しても、見える候補だけを除外する
        visible = _candidate_radio(panel, "sweepA", False)
        hidden = _candidate_radio(panel, "sweepB", False)
        assert not hidden.isVisible()
        finish = _radio_position(hidden)
        _send_radio_mouse(
            visible, qt.QEvent.Type.MouseButtonPress, _radio_position(visible)
        )
        _send_radio_mouse(visible, qt.QEvent.Type.MouseMove, finish)
        _send_radio_mouse(visible, qt.QEvent.Type.MouseButtonRelease, finish)
        assert draft.paths("transform") == ("legacyMissing", "sweepB")
    assert cmds.getAttr(f"{node}.sweepA") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_setup_name_range_drag_and_offscreen_selection(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """名前の範囲ドラッグと画面外への選択保持を確認する。"""
    node = cmds.createNode("transform", name="rangeSetupBase")
    paths = tuple(f"range{index:02d}" for index in range(30))
    for name in paths:
        cmds.addAttr(node, longName=name, attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "range-rig.json"
    create_custom_filter(path, "Range Rig")
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.resize(640, 800)
    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("range")
    panel.tool_box.setCurrentWidget(panel.candidate_page)
    _events()
    _mouse_candidate(_candidate_label(panel, "range01"))
    _mouse_candidate(
        _candidate_label(panel, "range03"),
        qt.Qt.KeyboardModifier.ShiftModifier,
    )
    assert panel.selected_candidate_paths() == paths[1:4]
    _mouse_candidate(
        _candidate_label(panel, "range02"),
        qt.Qt.KeyboardModifier.ControlModifier,
    )
    assert panel.selected_candidate_paths() == ("range01", "range03")

    start = _candidate_label(panel, "range00")
    end = _candidate_label(panel, "range04")
    _mouse_candidate(start, end_global=end.mapToGlobal(end.rect().center()))
    assert panel.selected_candidate_paths() == paths[:5]
    assert panel.draft is not None and not panel.draft.is_dirty
    assert panel.candidate_scroll.verticalScrollBar().maximum() > 0

    _mouse_candidate(_candidate_label(panel, "range00"))
    last = _candidate_label(panel, "range29")
    panel.candidate_scroll.ensureWidgetVisible(last)
    _events()
    _mouse_candidate(last, qt.Qt.KeyboardModifier.ControlModifier)
    assert panel.selected_candidate_paths() == ("range00", "range29")
    first = _candidate_label(panel, "range00")
    panel.candidate_scroll.ensureWidgetVisible(first)
    _events()
    _candidate_radio(panel, "range00", True).click()
    _events()
    assert panel.draft.paths("transform") == ("range00", "range29")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    editor.filter_combo.setCurrentIndex(
        editor.filter_combo.findData("keyable")
    )
    _events()
    assert panel.selected_candidate_paths() == ()
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    _events()
    assert panel.selected_candidate_paths() == ()


def test_setup_checked_exclude_is_noop_for_undefined_type(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """未定義型で既に除外中のラジオを押しても空定義を作らない。"""
    node = cmds.createNode("transform", name="undefinedSetupBase")
    cmds.addAttr(node, longName="onlyHidden", attributeType="double")
    cmds.select(node, replace=True)
    _events()
    path = tmp_path / "undefined-rig.json"
    create_custom_filter(path, "Undefined Rig")
    _register_saved_filter(editor, path)
    cmds.flushUndo()

    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("onlyHidden")
    _events()
    _mouse_candidate(_candidate_label(panel, "onlyHidden"))
    _candidate_radio(panel, "onlyHidden", False).click()
    _events()
    assert panel.draft is not None
    assert not panel.draft.has_node_type("transform")
    assert not panel.draft.is_dirty
    _candidate_radio(panel, "onlyHidden", True).click()
    _candidate_radio(panel, "onlyHidden", False).click()
    _events()
    assert panel.draft.has_node_type("transform")
    assert panel.draft.paths("transform") == ()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_manager_creates_and_selects_new_filter(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理画面の新規作成が登録末尾と設定モードの対象に反映する。"""
    path = tmp_path / "New Rig.json"

    def choose_path(*_args: object) -> tuple[str, str]:
        """保存ダイアログから検証用の新規pathを返す。"""
        assert Path(cast(str, _args[2])) == (
            tmp_path / "bd_channel_box" / "custom_filter" / "filter"
        )
        assert Path(cast(str, _args[2])).is_dir()
        return str(path), "JSON ファイル (*.json)"

    monkeypatch.setattr(dialog_module, "get_save_file_name_near", choose_path)
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None and manager.isVisible()
    manager.new_button.click()
    _events()

    assert path.exists()
    assert manager.isVisible()
    assert manager.tree_widget.topLevelItemCount() == 1
    created_item = manager.tree_widget.topLevelItem(0)
    assert manager.tree_widget.currentItem() is created_item
    assert created_item.isSelected()
    assert created_item.data(0, qt.Qt.ItemDataRole.UserRole) == (
        editor.custom_filter_registry.entries[-1].path
    )
    assert editor.custom_filter_registry.entries[-1].definition is not None
    assert (
        editor.custom_filter_registry.entries[-1].definition.name == "New Rig"
    )
    assert editor.controller.mode == "custom_filter_setup"
    assert editor.setup_panel.draft is not None
    assert (
        editor.setup_panel.draft.path
        == editor.custom_filter_registry.entries[-1].path
    )


def _queue_filter_name(
    expected: str,
    replacement: str | None = None,
    *,
    field_name: str = "newCustomFilterName",
    accepted: bool = True,
) -> None:
    """次の名前ダイアログの初期値を確認し、指定名で確定する。"""

    def accept() -> None:
        """表示された名前欄を検証し、必要なら変更して確定する。"""
        active = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "activeModalWidget"),
        )()
        assert isinstance(active, qt.QDialog)
        field = active.findChild(qt.QLineEdit, field_name)
        assert isinstance(field, qt.QLineEdit)
        assert field.text() == expected
        if replacement is not None:
            field.setText(replacement)
        if accepted:
            active.accept()
        else:
            active.reject()

    cast(
        Callable[[int, Callable[[], None]], None],
        getattr(qt.QTimer, "singleShot"),
    )(0, accept)


def test_setup_creates_filter_without_opening_manager(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未登録・ノード未選択でも設定画面から新規作成して編集を始める。"""
    editor.controller.set_mode("custom_filter_setup")
    destination = tmp_path / "From Setup.json"

    def choose_path(*_args: object) -> tuple[str, str]:
        """設定画面で新規JSONの保存先を選択する。"""
        assert Path(cast(str, _args[2])) == (
            tmp_path / "bd_channel_box" / "custom_filter" / "filter"
        )
        return str(destination), ""

    monkeypatch.setattr(dialog_module, "get_save_file_name_near", choose_path)
    editor.setup_panel.new_button.click()
    _events()

    assert editor.custom_filter_dialog is None
    assert editor.setup_panel.draft is not None
    assert editor.setup_panel.draft.name == "From Setup"
    assert editor.custom_filter_registry.entries[-1].enabled
    assert (
        json.loads(destination.read_text(encoding="utf-8"))["node_types"] == {}
    )


def test_setup_rename_is_draft_only_until_save_and_can_be_discarded(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """名前だけの編集を選択欄へ表示し、保存・破棄と他型の保持を確認する。"""
    source = tmp_path / "Rig.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Rig",
                "node_types": {"transform": ["visibility"], "joint": []},
            }
        ),
        encoding="utf-8",
    )
    _register_saved_filter(editor, source)
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    before = source.read_bytes()
    cmds.flushUndo()
    assert panel.rename_button.isEnabled()
    assert not panel.save_button.isEnabled()
    _queue_filter_name("Rig", "Renamed", field_name="renameCustomFilterName")
    panel.rename_button.click()
    assert panel.target_combo.currentText() == "Renamed *"
    assert panel.save_button.isEnabled() and panel.discard_button.isEnabled()
    assert source.read_bytes() == before
    assert editor.custom_filter_registry.entries[0].definition is not None
    assert editor.custom_filter_registry.entries[0].definition.name == "Rig"
    # 登録一覧を再構築しても、下書きの表示名と未保存印を維持する
    panel.refresh_entries()
    assert panel.target_combo.currentText() == "Renamed *"
    panel.discard_button.click()
    assert panel.target_combo.currentText() == "Rig"
    assert not panel.save_button.isEnabled()
    _queue_filter_name("Rig", " Saved ", field_name="renameCustomFilterName")
    panel.rename_button.click()
    panel.save_button.click()
    assert panel.target_combo.currentText() == "Saved"
    assert not panel.save_button.isEnabled()
    assert not panel.discard_button.isEnabled()
    destination = tmp_path / "Saved.json"
    assert not source.exists()
    saved = json.loads(destination.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2 and "name" not in saved
    assert saved["node_types"] == {"transform": ["visibility"], "joint": []}
    assert tuple(tmp_path.glob("*.json")) == (destination,)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize(
    ("replacement", "accepted"),
    (("Cancelled", False), ("", True), ("Rig", True)),
)
def test_setup_rename_cancel_invalid_and_unchanged_keep_clean_draft(
    editor: ChannelBoxWidget, tmp_path: Path, replacement: str, accepted: bool
) -> None:
    """取消・不正入力・同名確定はJSONと未保存状態を変更しない。"""
    source = tmp_path / "Rig.json"
    create_custom_filter(source, "Rig")
    _register_saved_filter(editor, source)
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    before = source.read_bytes()
    _queue_filter_name(
        "Rig",
        replacement,
        field_name="renameCustomFilterName",
        accepted=accepted,
    )
    panel.rename_button.click()
    assert panel.draft is not None and panel.draft.name == "Rig"
    assert not panel.draft.is_dirty
    assert panel.target_combo.currentText() == "Rig"
    assert not panel.save_button.isEnabled()
    assert source.read_bytes() == before
    if accepted and not replacement:
        assert editor.message_label.text()


def test_manager_duplicates_saved_changes_and_all_types_with_copy_suffix(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保存を選んだ変更を含め、OFFの元定義を_copy名で全型複製する。"""
    source = tmp_path / "source.json"
    create_custom_filter(source, "Rig")
    registry = editor.custom_filter_registry
    registry.add_paths((source,))
    registry.set_enabled(registry.entries[0].path, False)
    registry.save()
    panel = editor.setup_panel
    editor.controller.set_mode("custom_filter_setup")
    panel.set_target(str(source))
    assert panel.draft is not None
    panel.draft.set_many_included("joint", ("visibility", "rigMode"), True)
    panel.draft.ensure_node_type("network")
    panel.draft.set_many_included("transform", ("rotateOrder",), True)
    _queue_filter_name(
        "source", "Updated Rig", field_name="renameCustomFilterName"
    )
    panel.rename_button.click()
    destination = tmp_path / "Updated Rig_copy.json"

    def save_changes(*_args: object) -> qt.QMessageBox.StandardButton:
        """複製元の未保存変更を先に確定する。"""
        return qt.QMessageBox.StandardButton.Save

    def choose_path(*args: object) -> tuple[str, str]:
        """複製先の初期フォルダーと_copy名を確認して保存先を返す。"""
        assert Path(cast(str, args[2])) == tmp_path / "Updated Rig_copy.json"
        return str(destination), ""

    monkeypatch.setattr(qt.QMessageBox, "warning", save_changes)
    monkeypatch.setattr(dialog_module, "get_save_file_name_near", choose_path)
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None and manager.isVisible()
    assert manager.duplicate_button.isEnabled()
    manager.duplicate_button.click()
    _events()

    assert manager.isVisible()
    assert manager.tree_widget.topLevelItemCount() == 2
    duplicated_item = manager.tree_widget.topLevelItem(1)
    assert manager.tree_widget.currentItem() is duplicated_item
    assert duplicated_item.isSelected()
    assert len(manager.tree_widget.selectedItems()) == 1
    assert duplicated_item.data(0, qt.Qt.ItemDataRole.UserRole) == (
        registry.entries[-1].path
    )
    assert not source.exists()
    original = json.loads(
        (tmp_path / "Updated Rig.json").read_text(encoding="utf-8")
    )
    copied = json.loads(destination.read_text(encoding="utf-8"))
    assert original["schema_version"] == copied["schema_version"] == 2
    assert "name" not in original and "name" not in copied
    assert copied["node_types"] == original["node_types"]
    assert copied["node_types"]["network"] == []
    assert registry.entries[-1].enabled
    assert not registry.entries[0].enabled
    assert panel.draft is not None and panel.draft.name == "Updated Rig_copy"


@pytest.mark.parametrize("operation", ("new", "duplicate", "setup"))
def test_creation_cancelled_before_dialogs_keeps_draft_and_registration(
    editor: ChannelBoxWidget,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """未保存確認のキャンセル時はファイル選択を開かず旧編集だけを維持する。"""
    source = tmp_path / "source.json"
    create_custom_filter(source, "Rig")
    registry = editor.custom_filter_registry
    registry.add_paths((source,))
    registry.save()
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    _queue_filter_name(
        "source", "Unsaved", field_name="renameCustomFilterName"
    )
    panel.rename_button.click()
    before = source.read_bytes()

    def cancel(*_args: object) -> qt.QMessageBox.StandardButton:
        """対象を離れる前の確認を中止する。"""
        return qt.QMessageBox.StandardButton.Cancel

    def reject_dialog(_dialog: qt.QDialog) -> int:
        """確認を中止した後に作成ダイアログが開いたら失敗させる。"""
        raise AssertionError("作成ダイアログが開きました")

    monkeypatch.setattr(qt.QMessageBox, "warning", cancel)

    def reject_file_dialog(*_args: object) -> tuple[str, str]:
        """未保存確認を中止した後に保存先選択が開いたら失敗させる。"""
        raise AssertionError("保存先ダイアログが開きました")

    monkeypatch.setattr(qt.QDialog, "exec", reject_dialog)
    monkeypatch.setattr(
        dialog_module, "get_save_file_name_near", reject_file_dialog
    )
    if operation == "setup":
        panel.new_button.click()
    else:
        editor.manage_custom_filters_action.trigger()
        manager = editor.custom_filter_dialog
        assert manager is not None
        button = (
            manager.new_button
            if operation == "new"
            else manager.duplicate_button
        )
        button.click()
    assert len(registry.entries) == 1
    assert tuple(tmp_path.glob("*.json")) == (source,)
    assert source.read_bytes() == before
    assert panel.draft is not None and panel.draft.is_dirty
    assert panel.draft.name == "Unsaved"
    assert panel.target_combo.currentText() == "Unsaved *"


def test_setup_type_editor_works_without_nodes_and_preserves_saved_candidates(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """ノードなしで標準・保存済み候補を追加除外し、他型を保持して保存する。"""
    source = tmp_path / "types.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Types",
                "node_types": {
                    "transform": ["rigMode", "visibility"],
                    "joint": ["visibility", "jointOrient.jointOrientX"],
                    "network": [],
                },
            }
        ),
        encoding="utf-8",
    )
    _register_saved_filter(editor, source)
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    before = cmds.ls(long=True)
    cmds.flushUndo()
    panel.node_type_combo.setCurrentIndex(
        panel.node_type_combo.findData("transform")
    )
    assert panel.draft is not None
    _candidate_radio(panel, "translate.translateX", True).click()
    _candidate_radio(panel, "rigMode", False).click()
    assert panel.draft.paths("transform") == (
        "visibility",
        "translate.translateX",
    )
    _candidate_radio(panel, "rigMode", True).click()
    assert panel.draft.paths("transform")[-1] == "rigMode"
    panel.node_type_combo.setCurrentIndex(
        panel.node_type_combo.findData("joint")
    )
    panel.order_list.setCurrentRow(1)
    panel.up_button.click()
    assert panel.draft.paths("joint") == (
        "jointOrient.jointOrientX",
        "visibility",
    )
    panel.node_type_combo.setCurrentIndex(
        panel.node_type_combo.findData("network")
    )
    panel.clear_type_button.click()
    assert panel.node_type_combo.findData("network") == -1
    assert panel.node_type_combo.currentIndex() == 0
    assert panel.save()
    saved = json.loads(source.read_text(encoding="utf-8"))["node_types"]
    assert saved["transform"] == [
        "visibility",
        "translate.translateX",
        "rigMode",
    ]
    assert saved["joint"] == ["jointOrient.jointOrientX", "visibility"]
    assert "network" not in saved
    assert cmds.ls(long=True) == before
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_fixed_type_ignores_selection_and_uses_standard_filter_flags(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """型の固定中は選択変更で対象を変えず、型既定のフラグで候補を絞る。"""
    source = tmp_path / "types.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Types",
                "node_types": {
                    "transform": ["visibility", "rigMode"],
                    "joint": [],
                },
            }
        ),
        encoding="utf-8",
    )
    _register_saved_filter(editor, source)
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    panel.node_type_combo.setCurrentIndex(
        panel.node_type_combo.findData("transform")
    )
    joint = cmds.createNode("joint")
    cmds.select(joint)
    editor.controller.refresh()
    _events()
    assert "transform 型" in panel.node_label.text()
    assert panel.node_type_combo.currentData() == "transform"
    editor.controller.set_attribute_filter("keyable")
    _events()
    assert _candidate_label(panel, "translate.translateX")
    panel.search_edit.setText("rigMode")
    assert panel.selected_candidate_paths() == ()
    assert not _candidate_label(panel, "translate.translateX").isVisible()
    editor.controller.set_attribute_filter("all")
    _events()
    assert _candidate_label(panel, "rigMode").isVisible()
    panel.node_type_combo.setCurrentIndex(0)
    assert "joint 型" in panel.node_label.text()


def test_unknown_type_keeps_saved_paths_editable_without_loading_plugin(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """未ロード型でも保存済みpathを再追加でき、別型の定義を保つ。"""
    source = tmp_path / "types.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Types",
                "node_types": {
                    "bdUnavailablePluginType": ["mode", "amount"],
                    "transform": [],
                },
            }
        ),
        encoding="utf-8",
    )
    _register_saved_filter(editor, source)
    editor.controller.set_mode("custom_filter_setup")
    panel = editor.setup_panel
    panel.set_target(str(source))
    panel.node_type_combo.setCurrentIndex(1)
    _candidate_radio(panel, "mode", False).click()
    _candidate_radio(panel, "mode", True).click()
    assert panel.draft is not None
    assert panel.draft.paths("bdUnavailablePluginType") == ("amount", "mode")
    assert "型の情報を取得できない" in editor.message_label.text()
    assert panel.save()
    saved = json.loads(source.read_text(encoding="utf-8"))["node_types"]
    assert saved == {
        "bdUnavailablePluginType": ["amount", "mode"],
        "transform": [],
    }


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
    assert shared.target_names == ("|mixedJoint",)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    cmds.select(joint, transform, replace=True)
    _events()
    assert _paths(editor) == ("shared",)
    assert editor.controller.rows[0].target_names == ("|mixedTransform",)


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
