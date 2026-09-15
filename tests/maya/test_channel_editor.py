# coding: utf-8
"""Channel Editorの入力境界・選択追従・寿命のMaya統合検証。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from math import isclose
from typing import cast
import pytest
from maya import cmds

from bd_util.maya.ui import MayaBoolPlugsBinding, MayaFloatPlugsBinding
from bd_util.ui import (
    BoolComboBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    qt,
)

from bd_tools.channel_editor.widget import (
    AttributeRowWidget,
    ChannelEditorWidget,
)


def _new_scene() -> None:
    """fileコマンドの可変flag境界を閉じて、一時sceneを初期化する。"""
    file_command = cast(Callable[..., str], cmds.file)
    file_command(new=True, force=True)


def _set_value(name: str, value: float | bool) -> None:
    """setAttrの値引数だけを補正し、指定scalarへ値を設定する。"""
    set_attr = cast(Callable[[str, float | bool], None], cmds.setAttr)
    set_attr(name, value)


def _events() -> None:
    """遅延同期と削除通知を処理して、最新のUI状態へ進める。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _row(widget: ChannelEditorWidget, name: str) -> AttributeRowWidget:
    """正式な属性名に対応する表示行を返す。"""
    return next(w for w in widget.row_widgets if w.row.attribute.name == name)


def _open_context_menu(widget: qt.QWidget) -> None:
    """右クリック通知を送り、子Widgetからの伝播も含めてメニューを開く。"""
    position = widget.rect().center()
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        widget.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(widget, event)
    _events()


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelEditorWidget]:
    """異なる値を持つ2ノードを、値を揃えずに表示する。"""
    assert qt_application is not None
    _new_scene()
    for name, value in (("channelA", 0.25), ("channelB", 0.75)):
        cmds.createNode("transform", name=name)
        cmds.addAttr(
            name,
            longName="weight",
            attributeType="double",
            minValue=0,
            maxValue=1,
            keyable=True,
        )
        _set_value(f"{name}.weight", value)
    _set_value("channelB.visibility", False)
    cmds.addAttr("channelA", longName="lowerOnly", minValue=0, keyable=True)
    cmds.addAttr("channelA", longName="shown", attributeType="double")
    cmds.setAttr("channelA.shown", channelBox=True)
    cmds.addAttr("channelA", longName="hidden", attributeType="double")
    cmds.addAttr(
        "channelA", longName="integer", attributeType="long", keyable=True
    )
    cmds.select("channelA", "channelB", replace=True)
    cmds.flushUndo()
    widget = ChannelEditorWidget()
    widget.show()
    _events()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    _new_scene()


def test_selection_and_refresh_only_read_values(
    editor: ChannelEditorWidget,
) -> None:
    """選択直後・再描画・未編集確定が値とUndo履歴を変更しない。"""
    row = _row(editor, "weight")
    assert isinstance(row.editor, FloatSliderSpinBox)
    assert row.row.binding.is_mixed
    assert row.editor.spin_box.value() == 0.25
    row.editor.spin_box.setFocus()
    row.editor.spin_box.editingFinished.emit()
    editor.header_label.setFocus()
    editor.refresh_action.trigger()
    _events()
    assert cmds.getAttr("channelA.weight") == 0.25
    assert cmds.getAttr("channelB.weight") == 0.75
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_supported_types_flags_and_view_selection(
    editor: ChannelEditorWidget,
) -> None:
    """OR条件・scalar子・対応型・hard両側範囲でViewを選べる。"""
    names = {w.row.attribute.name for w in editor.row_widgets}
    assert {"translateX", "rotateY", "scaleZ", "visibility", "shown"} <= names
    assert {"hidden", "integer", "translate"}.isdisjoint(names)
    assert isinstance(_row(editor, "visibility").editor, BoolComboBox)
    assert isinstance(_row(editor, "lowerOnly").editor, FloatValueStepSpinBox)
    assert isinstance(_row(editor, "weight").editor, FloatSliderSpinBox)


def test_enter_does_not_activate_context_actions(
    editor: ChannelEditorWidget,
) -> None:
    """数値確定のEnterが更新・揃えるを実行せず、入力行を維持する。"""
    dialog = qt.QDialog()
    layout = qt.QVBoxLayout(dialog)
    layout.addWidget(editor)
    dialog.show()
    _events()
    row = _row(editor, "weight")
    assert isinstance(row.editor, FloatSliderSpinBox)
    spin_box = row.editor.spin_box
    spin_box.setFocus()
    event = qt.QtGui.QKeyEvent(
        qt.QEvent.Type.KeyPress,
        qt.Qt.Key.Key_Return,
        qt.Qt.KeyboardModifier.NoModifier,
    )
    qt.QApplication.sendEvent(spin_box, event)
    _events()
    assert _row(editor, "weight") is row
    assert not row.row.binding.is_disposed
    assert cmds.getAttr("channelB.weight") == 0.75
    editor.setParent(None)
    dialog.close()
    dialog.deleteLater()


def test_numeric_input_updates_all_targets_with_one_undo(
    editor: ChannelEditorWidget,
) -> None:
    """数値を変更したときだけ一括適用し、Undoで各元値を復元する。"""
    view = _row(editor, "weight").editor
    assert isinstance(view, FloatSliderSpinBox)
    view.spin_box.setValue(0.6)
    assert cmds.getAttr("channelA.weight") == 0.6
    assert cmds.getAttr("channelB.weight") == 0.6
    cmds.undo()
    _events()
    assert cmds.getAttr("channelA.weight") == 0.25
    assert cmds.getAttr("channelB.weight") == 0.75
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bool_input_and_explicit_alignment(
    editor: ChannelEditorWidget,
) -> None:
    """bool選択と明示的な揃える操作を、表示更新から分離する。"""
    row = _row(editor, "visibility")
    assert isinstance(row.editor, BoolComboBox)
    assert isinstance(row.row.binding, MayaBoolPlugsBinding)
    assert row.editor.currentText() == "on"
    assert cmds.getAttr("channelB.visibility") is False
    row.align_action.trigger()
    assert cmds.getAttr("channelA.visibility") is True
    assert cmds.getAttr("channelB.visibility") is True
    row.editor.setCurrentIndex(0)
    assert cmds.getAttr("channelA.visibility") is False
    assert cmds.getAttr("channelB.visibility") is False


@pytest.mark.parametrize("surface", ["attribute", "background"])
def test_context_menu_refresh_only_reads_values(
    editor: ChannelEditorWidget, surface: str
) -> None:
    """属性名と余白から更新でき、値・Undo・変更済みstepを維持する。"""
    _value_step(editor, "translateX").setSingleStep(0.01)
    row = _row(editor, "weight")
    if surface == "attribute":
        target = row.name_label
        menu = row.context_menu
        action = row.refresh_action
    else:
        target = editor.scroll_area.widget()
        assert target is not None
        menu = editor.context_menu
        action = editor.refresh_action
    _open_context_menu(target)
    assert menu.isVisible()
    assert action in menu.actions()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    menu.close()
    action.trigger()
    _events()
    assert _row(editor, "weight") is not row
    assert _value_step(editor, "translateX").singleStep() == 0.01
    assert cmds.getAttr("channelA.weight") == 0.25
    assert cmds.getAttr("channelB.weight") == 0.75
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_context_alignment_preserves_unrounded_value_and_one_undo(
    editor: ChannelEditorWidget,
) -> None:
    """メニューを開くだけでは変更せず、明示操作で未丸めの代表値へ揃える。"""
    value = 0.123456789
    _set_value("channelA.weight", value)
    _events()
    cmds.flushUndo()
    row = _row(editor, "weight")
    assert isinstance(row.editor, FloatSliderSpinBox)
    row.editor.spin_box.setDecimals(3)
    _open_context_menu(row.name_label)
    assert row.context_menu.isVisible()
    assert row.align_action.isEnabled()
    assert cmds.getAttr("channelB.weight") == 0.75
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    row.context_menu.close()
    row.align_action.trigger()
    _events()
    assert cmds.getAttr("channelA.weight") == value
    assert cmds.getAttr("channelB.weight") == value
    assert not row.align_action.isEnabled()
    assert not row.name_label.text().startswith("• ")
    cmds.undo()
    _events()
    assert cmds.getAttr("channelA.weight") == value
    assert cmds.getAttr("channelB.weight") == 0.75
    assert _row(editor, "weight").name_label.text().startswith("• ")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_selection_change_closes_attribute_menu(
    editor: ChannelEditorWidget,
) -> None:
    """メニューを開いたまま選択が変わっても、旧対象の操作を残さない。"""
    row = _row(editor, "weight")
    menu = row.context_menu
    _open_context_menu(row.name_label)
    assert menu.isVisible()
    cmds.select("channelB", replace=True)
    _events()
    assert row.row.binding.is_disposed
    assert not qt.isValid(menu)
    assert cmds.getAttr("channelB.weight") == 0.75


def test_external_change_does_not_propagate(
    editor: ChannelEditorWidget,
) -> None:
    """Mayaからの値変更は表示だけへ反映し、別ノードへ転送しない。"""
    _set_value("channelA.weight", 0.9)
    _events()
    row = _row(editor, "weight")
    assert row.row.binding.value == 0.9
    assert row.row.binding.is_mixed
    assert cmds.getAttr("channelB.weight") == 0.75


def test_selection_switch_stops_old_binding(
    editor: ChannelEditorWidget,
) -> None:
    """選択を切り替えた直後に旧入力を無効化し、新しい代表へ切り替える。"""
    old = _row(editor, "weight").row.binding
    assert isinstance(old, MayaFloatPlugsBinding)
    cmds.select("channelB", replace=True)
    assert old.is_disposed
    with pytest.raises(RuntimeError):
        old.set_value(0.1)
    _events()
    assert editor.controller.node_names == ("|channelB",)
    assert _row(editor, "weight").row.binding.value == 0.75
    assert cmds.getAttr("channelA.weight") == 0.25


def test_visibility_flag_and_attribute_removal_refresh_rows(
    editor: ChannelEditorWidget,
) -> None:
    """channelBox切替と属性削除・Undoに追従して行を再構築する。"""
    cmds.setAttr("channelA.hidden", channelBox=True)
    _events()
    assert _row(editor, "hidden")
    cmds.deleteAttr("channelA.weight")
    _events()
    assert "weight" not in {r.row.attribute.name for r in editor.row_widgets}
    cmds.undo()
    _events()
    assert _row(editor, "weight").row.binding.value == 0.25


def test_locked_secondary_is_reported_and_excluded(
    editor: ChannelEditorWidget,
) -> None:
    """編集不可の対象をtooltipへ示し、残りの対応属性だけを更新する。"""
    cmds.setAttr("channelB.weight", lock=True)
    _events()
    row = _row(editor, "weight")
    assert row.row.binding.writable_count == 1
    assert "1/2" in row.name_label.toolTip()
    assert "channelB" in row.name_label.toolTip()
    binding = row.row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    binding.set_value(0.5)
    assert cmds.getAttr("channelA.weight") == 0.5
    assert cmds.getAttr("channelB.weight") == 0.75


def test_dispose_prevents_selection_updates(
    editor: ChannelEditorWidget,
) -> None:
    """終了後は選択変更によって入力Bindingが再生成されない。"""
    editor.dispose()
    cmds.select(clear=True)
    _events()
    assert editor.controller.is_disposed
    assert not editor.controller.rows


def test_range_rejection_is_visible_and_leaves_all_targets_unchanged(
    editor: ChannelEditorWidget,
) -> None:
    """他対象の狭い範囲で拒否した入力を画面へ通知し、部分適用を残さない。"""
    cmds.addAttr("channelB.weight", edit=True, maxValue=0.8)
    editor.refresh()
    binding = _row(editor, "weight").row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    with pytest.raises(ValueError):
        binding.set_value(0.9)
    assert cmds.getAttr("channelA.weight") == 0.25
    assert cmds.getAttr("channelB.weight") == 0.75
    assert not editor.message_label.isHidden()
    assert editor.message_label.text()


def test_selection_change_finishes_drag_undo(
    editor: ChannelEditorWidget,
) -> None:
    """選択変更でドラッグを終了し、選択Undoと値Undoを混ぜない。"""
    binding = _row(editor, "weight").row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    view_model = binding.view_model
    owner = qt.QObject(editor)
    view_model.begin_edit(owner)
    binding.set_value(0.4)
    binding.set_value(0.6)
    cmds.select("channelB", replace=True)
    _events()
    assert binding.is_disposed
    cmds.undo()
    _events()
    cmds.undo()
    _events()
    assert cmds.getAttr("channelA.weight") == 0.25
    assert cmds.getAttr("channelB.weight") == 0.75


def test_animated_representative_remains_read_only(
    editor: ChannelEditorWidget,
) -> None:
    """キー付き代表属性の値は時刻へ追従し、一括入力を許可しない。"""
    cmds.setKeyframe("channelA.weight", time=1, value=0.2)
    cmds.setKeyframe("channelA.weight", time=10, value=0.8)
    cmds.currentTime(10)
    _events()
    binding = _row(editor, "weight").row.binding
    assert isinstance(binding, MayaFloatPlugsBinding)
    assert isclose(binding.value, 0.8, rel_tol=0, abs_tol=1e-12)
    assert not binding.view_model.set_value_command.can_execute
    assert not _row(editor, "weight").align_action.isEnabled()
    assert not binding.set_value(0.5)
    assert cmds.getAttr("channelB.weight") == 0.75


def test_missing_and_incompatible_attributes_are_excluded(
    editor: ChannelEditorWidget,
) -> None:
    """同名でも型・単位が異なる属性は対象から除き、理由を表示する。"""
    cmds.deleteAttr("channelB.weight")
    cmds.addAttr(
        "channelB",
        longName="weight",
        attributeType="doubleAngle",
        keyable=True,
    )
    _events()
    row = _row(editor, "weight")
    assert row.row.binding.target_count == 1
    assert "型・単位" in row.name_label.toolTip()
    cmds.deleteAttr("channelB.weight")
    _events()
    row = _row(editor, "weight")
    assert "対応する属性なし" in row.name_label.toolTip()


def _value_step(
    widget: ChannelEditorWidget, name: str
) -> FloatValueStepSpinBox:
    """指定した属性行から値とstepの複合Viewを返す。"""
    view = _row(widget, name).editor
    assert isinstance(view, FloatValueStepSpinBox)
    return view


@pytest.mark.parametrize(
    "name,step,mode,increment",
    [
        ("translateX", 1, "multiplicative", 1),
        ("rotateY", 15, "additive", 15),
        ("scaleZ", 1, "multiplicative", 1),
        ("lowerOnly", 1, "multiplicative", 1),
    ],
)
def test_step_defaults_by_attribute_kind(
    editor: ChannelEditorWidget,
    name: str,
    step: float,
    mode: str,
    increment: float,
) -> None:
    """単位種別に応じたstepと、step欄自身の増減幅を設定する。"""
    view = _value_step(editor, name)
    assert view.singleStep() == view.step_spin_box.value() == step
    assert view.step_spin_box.stepMode() == mode
    assert view.step_spin_box.singleStep() == increment
    view.step_spin_box.stepUp()
    assert view.singleStep() == (step * 10 if mode == "multiplicative" else 30)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("kind", ["double", "doubleLinear", "doubleAngle"])
@pytest.mark.parametrize("bounded", [False, True])
def test_radius_override_respects_slider_priority(
    editor: ChannelEditorWidget,
    kind: str,
    bounded: bool,
) -> None:
    """radiusは型より優先し、Sliderのある行は元の構成を維持する。"""
    cmds.addAttr(
        "channelA", longName="radius", attributeType=kind, keyable=True
    )
    if bounded:
        cmds.addAttr("channelA.radius", edit=True, minValue=0, maxValue=10)
    _events()
    view = _row(editor, "radius").editor
    if bounded:
        assert isinstance(view, FloatSliderSpinBox)
    else:
        assert isinstance(view, FloatValueStepSpinBox)
        assert view.singleStep() == 0.1
        assert view.step_spin_box.stepMode() == "multiplicative"


def test_step_survives_value_undo_refresh_and_selection(
    editor: ChannelEditorWidget,
) -> None:
    """混在した値だけをUndoし、同属性のstepは再構築を越えて保持する。"""
    _set_value("channelB.scaleX", 2)
    _events()
    cmds.flushUndo()
    view = _value_step(editor, "scaleX")
    view.step_spin_box.setValue(0.1)
    assert cmds.getAttr("channelA.scaleX") == 1
    assert cmds.getAttr("channelB.scaleX") == 2
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    view.spin_box.stepUp()
    assert isclose(float(cmds.getAttr("channelA.scaleX")), 1.1)
    assert isclose(float(cmds.getAttr("channelB.scaleX")), 1.1)
    cmds.undo()
    _events()
    assert cmds.getAttr("channelA.scaleX") == 1
    assert cmds.getAttr("channelB.scaleX") == 2
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert _value_step(editor, "scaleX").singleStep() == 0.1
    editor.refresh()
    assert _value_step(editor, "scaleX").singleStep() == 0.1
    assert _value_step(editor, "scaleY").singleStep() == 1
    cmds.select(clear=True)
    _events()
    cmds.select("channelB", replace=True)
    _events()
    assert _value_step(editor, "scaleX").singleStep() == 0.1


def test_step_cache_is_separate_by_kind_and_window(
    editor: ChannelEditorWidget,
) -> None:
    """同名でも型が変われば既定値を使い、新規Windowは前回のstepを引き継がない。"""
    _value_step(editor, "shown").setSingleStep(0.01)
    cmds.deleteAttr("channelA.shown")
    cmds.addAttr(
        "channelA", longName="shown", attributeType="doubleAngle", keyable=True
    )
    _events()
    assert _value_step(editor, "shown").singleStep() == 15
    _value_step(editor, "translateX").setSingleStep(10)
    other = ChannelEditorWidget()
    try:
        assert _value_step(other, "translateX").singleStep() == 1
    finally:
        other.dispose()
        other.deleteLater()
        _events()


def test_step_tracks_display_units_without_converting_numeric_step(
    editor: ChannelEditorWidget,
) -> None:
    """表示単位の変更はstepの数値を維持し、step欄の単位を揃える。"""
    original = str(cmds.currentUnit(query=True, linear=True))
    view = _value_step(editor, "translateX")
    view.setSingleStep(2.5)
    try:
        cmds.currentUnit(linear="m")
        _events()
        view = _value_step(editor, "translateX")
        assert view.singleStep() == view.step_spin_box.value() == 2.5
        assert view.step_spin_box.suffix() == view.spin_box.suffix() == " m"
        editor.refresh()
        assert _value_step(editor, "translateX").singleStep() == 2.5
    finally:
        cmds.currentUnit(linear=original)
        _events()
