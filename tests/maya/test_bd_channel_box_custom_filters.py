# coding: utf-8
"""bdChannelBoxのユーザー定義表示フィルターをMaya上で検証する。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import MayaFloatPlugsBinding
from bd_util.maya.ui import settings as maya_settings
from bd_util.ui import qt

from bd_tools.bd_channel_box.controller import ChannelBoxMode, ChannelRow
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
    editor.custom_filter_registry.add_paths((str(path),))
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
        if editor.filter_combo.itemText(index) == "Custom: Rig"
    )
    editor.filter_combo.setCurrentIndex(index)
    _events()
    assert _paths(editor) == ("hiddenRig",)
    editor.mode_combo.setCurrentIndex(2)
    editor.mode_combo.setCurrentIndex(0)
    _events()
    assert editor.filter_combo.currentText() == "Custom: Rig"


def test_setup_splitter_and_bulk_actions_use_filtered_candidates(
    editor: ChannelBoxWidget, tmp_path: Path
) -> None:
    """分割幅と検索候補の一括操作をUIから確認し、候補外の定義を守る。"""
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
    editor.custom_filter_registry.add_paths((str(path),))
    cmds.flushUndo()

    editor.resize(640, 800)
    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("batch")
    _events()

    assert panel.list_splitter.orientation() == qt.Qt.Orientation.Vertical
    assert panel.list_splitter.count() == 2
    panel.list_splitter.setSizes([300, 80])
    _events()
    upper_large = panel.list_splitter.sizes()
    panel.list_splitter.setSizes([80, 300])
    _events()
    lower_large = panel.list_splitter.sizes()
    assert upper_large[0] > lower_large[0]
    assert upper_large[1] < lower_large[1]
    assert panel.candidate_scroll.verticalScrollBar().maximum() > 0

    panel.include_all_button.click()
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

    panel.exclude_all_button.click()
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


def test_setup_bulk_exclusion_saves_explicit_empty_type(
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
    editor.custom_filter_registry.add_paths((str(path),))
    cmds.flushUndo()

    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("bulkHidden")
    _events()
    panel.exclude_all_button.click()
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
        if editor.filter_combo.itemText(index) == "Custom: Empty Bulk"
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
    editor.custom_filter_registry.add_paths((str(path),))
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
    editor.custom_filter_registry.add_paths((str(path),))
    cmds.flushUndo()

    editor.resize(640, 800)
    editor.mode_combo.setCurrentIndex(2)
    _events()
    panel = editor.setup_panel
    panel.set_target(str(path))
    editor.filter_combo.setCurrentIndex(editor.filter_combo.findData("hidden"))
    panel.search_edit.setText("range")
    panel.list_splitter.setSizes([80, 500])
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
    editor.custom_filter_registry.add_paths((str(path),))
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
    path = tmp_path / "new-rig.json"

    def choose_path(*_args: object) -> tuple[str, str]:
        """保存ダイアログから検証用の新規pathを返す。"""
        return str(path), "JSON ファイル (*.json)"

    def accept_name() -> None:
        """名前入力ダイアログへ値を入力して確定する。"""
        active_modal = cast(
            Callable[[], qt.QWidget | None],
            getattr(qt.QApplication, "activeModalWidget"),
        )()
        assert isinstance(active_modal, qt.QDialog)
        layout = active_modal.layout()
        assert layout is not None
        field = layout.itemAt(1).widget()
        assert isinstance(field, qt.QLineEdit)
        field.setText("New Rig")
        active_modal.accept()

    monkeypatch.setattr(qt.QFileDialog, "getSaveFileName", choose_path)
    editor.manage_custom_filters_action.trigger()
    manager = editor.custom_filter_dialog
    assert manager is not None
    single_shot = cast(
        Callable[[int, Callable[[], None]], None],
        getattr(qt.QTimer, "singleShot"),
    )
    single_shot(0, accept_name)
    manager.new_button.click()
    _events()

    assert path.exists()
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
