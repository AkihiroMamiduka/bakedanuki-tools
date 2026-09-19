# coding: utf-8
"""属性行の選択と、明示的な一括数値入力・状態操作を検証する。"""

from collections.abc import Callable, Iterator
from math import isclose
from typing import cast

import pytest
from maya import cmds

from bd_util.ui import (
    BoolCheckBox,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    qt,
)
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


def _events() -> None:
    """遅延同期と旧Widgetの破棄を完了する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _set_value(path: str, value: float) -> None:
    """Mayaの値設定だけを型付きの小さな境界で扱う。"""
    cast(Callable[[str, float], None], cmds.setAttr)(path, value)


@pytest.fixture
def editor(qt_application: qt.QApplication) -> Iterator[ChannelBoxWidget]:
    """複数行と複数ノードの元値が異なる検証sceneを作る。"""
    del qt_application
    cast(Callable[..., str], cmds.file)(new=True, force=True)
    cmds.currentUnit(linear="cm", angle="deg")
    for index, (node, tx, ty) in enumerate(
        (("multiA", 5.0, 1.0), ("multiB", 9.0, 3.0))
    ):
        cmds.createNode("transform", name=node)
        _set_value(node + ".translateX", tx)
        _set_value(node + ".translateY", ty)
        cmds.addAttr(
            node,
            longName="gain",
            attributeType="double",
            minValue=0,
            maxValue=10,
            keyable=True,
        )
        cmds.addAttr(
            node,
            longName="limited",
            attributeType="double",
            minValue=0.0,
            maxValue=5.0,
            defaultValue=1.0,
            keyable=True,
        )
        cmds.addAttr(
            node,
            longName="mode",
            attributeType="enum",
            enumName="A:B:C",
            keyable=True,
        )
        cmds.addAttr(
            node,
            longName="quality",
            attributeType="enum",
            enumName="A:B:C",
            keyable=True,
        )
        cmds.addAttr(
            node,
            longName="variant",
            attributeType="enum",
            enumName="A:B:D",
            keyable=True,
        )
        cmds.addAttr(
            node,
            longName="enabled",
            attributeType="bool",
            defaultValue=index == 1,
            keyable=True,
        )
    cmds.select("multiA", "multiB", replace=True)
    widget = ChannelBoxWidget()
    widget.resize(380, 650)
    widget.show()
    _events()
    cmds.flushUndo()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()
    cmds.currentUnit(linear="cm", angle="deg")
    cast(Callable[..., str], cmds.file)(new=True, force=True)


def _row(editor: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """正式属性名に対応する値編集行を取得する。"""
    row = next(
        row for row in editor.row_widgets if row.row.attribute.name == name
    )
    assert isinstance(row, AttributeRowWidget)
    return row


def _keys(
    editor: ChannelBoxWidget, *names: str
) -> tuple[tuple[str, str], ...]:
    """表示名でなく正式pathと型で選択識別子を作る。"""
    return tuple(
        (
            _row(editor, name).row.attribute.path,
            _row(editor, name).row.attribute.kind,
        )
        for name in names
    )


def _spin(editor: ChannelBoxWidget, name: str) -> qt.QDoubleSpinBox:
    """数値行の値欄だけを取得し、StepやSliderを区別する。"""
    view = _row(editor, name).editor
    assert isinstance(view, (FloatValueStepSpinBox, FloatSliderSpinBox))
    return view.spin_box


def _key(
    widget: qt.QWidget,
    key: qt.Qt.Key,
    text: str = "",
    modifiers: qt.Qt.KeyboardModifier = qt.Qt.KeyboardModifier.NoModifier,
) -> None:
    """実際のキーイベントで入力と確定を要求する。"""
    for kind in (qt.QEvent.Type.KeyPress, qt.QEvent.Type.KeyRelease):
        qt.QApplication.sendEvent(
            widget, qt.QtGui.QKeyEvent(kind, key, modifiers, text)
        )


def _begin_input(
    editor: ChannelBoxWidget, text: str = "5", name: str = "translateX"
) -> qt.QLineEdit:
    """複数選択した値欄の直接入力から、一括入力欄を開く。"""
    spin = _spin(editor, name)
    spin.setFocus()
    _key(spin, qt.Qt.Key.Key_5, text)
    focused = cast(
        Callable[[], qt.QWidget | None],
        getattr(qt.QApplication, "focusWidget"),
    )()
    assert isinstance(focused, qt.QLineEdit)
    assert focused.objectName() == "channel_batch_numeric_editor"
    return focused


def _click(
    widget: qt.QWidget,
    modifiers: qt.Qt.KeyboardModifier = qt.Qt.KeyboardModifier.NoModifier,
) -> None:
    """修飾キー付きのクリックを既存の名前欄へ送る。"""
    position = widget.rect().center()
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(position),
            qt.QPointF(widget.mapToGlobal(position)),
            qt.Qt.MouseButton.LeftButton,
            (
                qt.Qt.MouseButton.LeftButton
                if kind == qt.QEvent.Type.MouseButtonPress
                else qt.Qt.MouseButton.NoButton
            ),
            modifiers,
        )
        qt.QApplication.sendEvent(widget, event)


def test_control_shift_selection_only_reads(editor: ChannelBoxWidget) -> None:
    """Ctrlで離れた行、Shiftで範囲を選択し、sceneとUndoを変更しない。"""
    assert isinstance(editor.table_view, qt.QTableView)
    _click(_row(editor, "translateX").name_label)
    _click(
        _row(editor, "rotateY").name_label,
        qt.Qt.KeyboardModifier.ControlModifier,
    )
    assert set(editor.table_view.selected_keys()) == set(
        _keys(editor, "translateX", "rotateY")
    )
    _click(_row(editor, "translateX").name_label)
    _click(
        _row(editor, "translateZ").name_label,
        qt.Qt.KeyboardModifier.ShiftModifier,
    )
    assert editor.table_view.selected_keys() == _keys(
        editor, "translateX", "translateY", "translateZ"
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_rows_use_current_viewport_after_host_replacement(
    editor: ChannelBoxWidget,
) -> None:
    """hostがviewportを交換しても、古い親を再利用せず属性行を表示する。"""
    cmds.select(clear=True)
    _events()
    old_viewport = editor.table_view.viewport()
    editor.table_view.setViewport(qt.QWidget())
    _events()
    assert not qt.isValid(old_viewport)
    cmds.select("multiA", "multiB", replace=True)
    _events()
    assert _row(editor, "translateX").isVisible()
    editor.refresh()
    _events()
    assert _row(editor, "gain").isVisible()


def test_direct_same_value_input_groups_rows_and_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """現在値と同じ5の明示入力でも他の行とnodeへ適用し、一Undoで元へ戻す。"""
    selected = _keys(editor, "translateX", "translateY", "rotateY")
    editor.table_view.select_keys(selected)
    field = _begin_input(editor)
    assert cmds.getAttr("multiA.translateY") == 1.0
    _key(field, qt.Qt.Key.Key_Return)
    assert editor.table_view.selected_keys() == selected
    _events()
    assert editor.table_view.selected_keys() == selected
    for node in ("multiA", "multiB"):
        for attr in ("translateX", "translateY", "rotateY"):
            assert cmds.getAttr(f"{node}.{attr}") == 5.0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.translateY") == 1.0
    assert cmds.getAttr("multiB.translateY") == 3.0
    assert cmds.getAttr("multiB.rotateY") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert editor.table_view.selected_keys() == selected
    cmds.redo()
    _events()
    assert cmds.getAttr("multiB.rotateY") == 5.0


def test_selection_refresh_and_unedited_focus_never_align(
    editor: ChannelBoxWidget,
) -> None:
    """選択・未編集のEnter・表示更新は値を揃えず選択だけを維持する。"""
    selected = _keys(editor, "translateX", "translateY")
    editor.table_view.select_keys(selected)
    spin = _spin(editor, "translateX")
    spin.setFocus()
    _key(spin, qt.Qt.Key.Key_Return)
    editor.filter_combo.setFocus()
    editor.refresh()
    _events()
    assert editor.table_view.selected_keys() == selected
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.translateY") == 1.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("action", ["escape", "selection", "dispose"])
def test_pending_input_cancels_for_old_targets(
    editor: ChannelBoxWidget, action: str
) -> None:
    """Escapeと対象・寿命の変更では未確定文字を旧属性へ書き込まない。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    field = _begin_input(editor, "7")
    if action == "escape":
        _key(field, qt.Qt.Key.Key_Escape)
    elif action == "selection":
        cmds.select("multiB", replace=True)
    else:
        editor.dispose()
    _events()
    assert cmds.getAttr("multiA.translateY") == 1.0
    assert cmds.getAttr("multiB.translateY") == 3.0
    if action == "selection":
        assert not editor.table_view.selected_keys()


def test_mode_change_commits_to_frozen_selection(
    editor: ChannelBoxWidget,
) -> None:
    """モード切替は明示入力を旧選択へ確定してから行を再構築する。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    _begin_input(editor, "8")
    editor.mode_combo.setCurrentIndex(1)
    _events()
    assert cmds.getAttr("multiA.translateY") == 8.0
    assert cmds.getAttr("multiB.translateX") == 8.0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.translateY") == 1.0


@pytest.mark.parametrize("origin", ["translateX", "gain"])
def test_limits_reject_all_rows_without_clamping(
    editor: ChannelBoxWidget,
    origin: str,
) -> None:
    """後の行の範囲外入力でも先の行を変更せず、値を黙って丸めない。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "gain"))
    field = _begin_input(editor, "20", origin)
    _key(field, qt.Qt.Key.Key_Return)
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.gain") == 0.0
    assert editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("move_focus", [False, True])
def test_mode_change_preserves_numeric_rejection(
    editor: ChannelBoxWidget, move_focus: bool
) -> None:
    """モード切替に伴う確定で入力を拒否した理由を画面に残す。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "gain"))
    _begin_input(editor, "20")
    if move_focus:
        editor.mode_combo.setFocus()
        _events()
    editor.mode_combo.setCurrentIndex(1)
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiA.gain") == 0.0
    assert editor.message_label.isVisible()
    assert "変更できませんでした" in editor.message_label.text()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_display_units_are_converted_per_selected_row(
    editor: ChannelBoxWidget,
) -> None:
    """mとradの表示数値5を、それぞれの公開単位へ変換して適用する。"""
    cmds.currentUnit(linear="m", angle="rad")
    _events()
    selected = _keys(editor, "translateX", "rotateY")
    editor.controller.apply_numeric_values(selected, 5.0)
    assert isclose(cmds.getAttr("multiB.translateX"), 5.0)
    assert isclose(cmds.getAttr("multiB.rotateY"), 5.0)


def test_readonly_and_nonnumeric_rows_are_reported_and_skipped(
    editor: ChannelBoxWidget,
) -> None:
    """編集不可の代表行とboolを除外し、編集可能な行だけを変更する。"""
    cmds.setAttr("multiA.translateY", lock=True)
    cmds.setAttr("multiB.translateX", lock=True)
    _events()
    cmds.flushUndo()
    editor.controller.apply_numeric_values(
        _keys(editor, "translateX", "translateY", "visibility"), 2.0
    )
    assert cmds.getAttr("multiA.translateX") == 2.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.translateY") == 1.0
    assert cmds.getAttr("multiB.translateY") == 3.0
    assert cmds.getAttr("multiA.visibility") is True
    assert "対象外" in editor.message_label.text()


def test_step_setting_aligns_selected_rows_and_value_arrow_uses_common_step(
    editor: ChannelBoxWidget,
) -> None:
    """同じ表示Stepを対応行へ反映し、その刻みで選択数値を増減する。"""
    editor.table_view.select_keys(
        _keys(
            editor,
            "translateX",
            "translateY",
            "rotateY",
            "gain",
            "visibility",
        )
    )
    translate_x = _row(editor, "translateX").editor
    translate_y = _row(editor, "translateY").editor
    rotate_y = _row(editor, "rotateY").editor
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(translate_y, FloatValueStepSpinBox)
    assert isinstance(rotate_y, FloatValueStepSpinBox)
    assert translate_x.step_spin_box.stepMode() == "multiplicative"
    assert rotate_y.step_spin_box.stepMode() == "additive"

    translate_x.step_spin_box.setValue(2.0)
    assert translate_x.singleStep() == 2.0
    assert translate_y.singleStep() == 2.0
    assert rotate_y.singleStep() == 2.0
    assert translate_x.step_spin_box.stepMode() == "multiplicative"
    assert rotate_y.step_spin_box.stepMode() == "additive"
    assert editor.message_label.isVisible()
    assert "Step欄なし" in editor.message_label.text()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 再構築後も、同期した各属性のWindow内キャッシュを復元する
    editor.refresh()
    _events()
    translate_x = _row(editor, "translateX").editor
    translate_y = _row(editor, "translateY").editor
    rotate_y = _row(editor, "rotateY").editor
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(translate_y, FloatValueStepSpinBox)
    assert isinstance(rotate_y, FloatValueStepSpinBox)
    assert translate_x.singleStep() == 2.0
    assert translate_y.singleStep() == 2.0
    assert rotate_y.singleStep() == 2.0

    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    translate_x.spin_box.stepUp()
    _events()
    assert cmds.getAttr("multiA.translateX") == 7.0
    assert cmds.getAttr("multiB.translateX") == 11.0
    assert cmds.getAttr("multiA.translateY") == 3.0
    assert cmds.getAttr("multiB.translateY") == 5.0


def test_step_setting_on_unselected_row_stays_local(
    editor: ChannelBoxWidget,
) -> None:
    """選択外のStep欄は、その属性だけの設定として変更する。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    rotate_z = _row(editor, "rotateZ").editor
    translate_x = _row(editor, "translateX").editor
    translate_y = _row(editor, "translateY").editor
    assert isinstance(rotate_z, FloatValueStepSpinBox)
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(translate_y, FloatValueStepSpinBox)

    rotate_z.step_spin_box.setValue(3.0)
    assert rotate_z.singleStep() == 3.0
    assert translate_x.singleStep() == 1.0
    assert translate_y.singleStep() == 1.0
    assert not editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_value_arrows_add_source_step_to_each_selected_value(
    editor: ChannelBoxWidget,
) -> None:
    """値欄の上下操作は操作元のStepを全選択数値の現在値へ加える。"""
    selected = _keys(editor, "translateX", "translateY", "rotateZ")
    editor.table_view.select_keys(selected)
    view = _row(editor, "translateX").editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.setSingleStep(0.5)
    cmds.flushUndo()
    view.spin_box.stepUp()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.5
    assert cmds.getAttr("multiB.translateX") == 9.5
    assert cmds.getAttr("multiA.translateY") == 1.5
    assert cmds.getAttr("multiB.translateY") == 3.5
    assert cmds.getAttr("multiA.rotateZ") == 0.5
    assert cmds.getAttr("multiB.rotateZ") == 0.5
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiB.translateY") == 3.0
    assert cmds.getAttr("multiA.rotateZ") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_value_arrow_range_error_rejects_every_selected_row(
    editor: ChannelBoxWidget,
) -> None:
    """共通増減後に一行でも範囲を超える場合は全数値行を変更しない。"""
    _set_value("multiA.gain", 9.0)
    _set_value("multiB.gain", 9.0)
    _events()
    editor.table_view.select_keys(_keys(editor, "translateX", "gain"))
    view = _row(editor, "translateX").editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.setSingleStep(2.0)
    cmds.flushUndo()
    view.spin_box.stepUp()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.gain") == 9.0
    assert editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_slider_aligns_selected_numeric_rows_in_one_continuous_undo(
    editor: ChannelBoxWidget,
) -> None:
    """Sliderの連続値を選択数値へ揃え、押下から解放までを一Undoにする。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "gain"))
    view = _row(editor, "gain").editor
    assert isinstance(view, FloatSliderSpinBox)
    cmds.flushUndo()
    view.slider.sliderPressed.emit()
    view.slider.setValue(view.slider.maximum() // 2)
    view.slider.setValue(view.slider.maximum() * 7 // 10)
    view.slider.sliderReleased.emit()
    _events()
    assert cmds.getAttr("multiA.translateX") == 7.0
    assert cmds.getAttr("multiB.translateX") == 7.0
    assert cmds.getAttr("multiA.gain") == 7.0
    assert cmds.getAttr("multiB.gain") == 7.0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.gain") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_slider_range_error_stops_continuous_edit_without_writing(
    editor: ChannelBoxWidget,
) -> None:
    """選択数値の範囲違反ではSlider操作を終了し、全対象を変更しない。"""
    editor.table_view.select_keys(_keys(editor, "gain", "limited"))
    view = _row(editor, "gain").editor
    assert isinstance(view, FloatSliderSpinBox)
    cmds.flushUndo()
    view.slider.setSliderDown(True)
    view.slider.setValue(view.slider.maximum() * 7 // 10)
    _events()
    assert cmds.getAttr("multiA.gain") == 0.0
    assert cmds.getAttr("multiB.gain") == 0.0
    assert cmds.getAttr("multiA.limited") == 1.0
    assert cmds.getAttr("multiB.limited") == 1.0
    assert not view.slider.isSliderDown()
    assert not editor.controller.value_edit_session.is_editing
    assert editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_bool_input_aligns_selected_bool_rows(
    editor: ChannelBoxWidget,
) -> None:
    """CheckBox操作は選択中のbool属性だけを同じ状態へ揃える。"""
    editor.table_view.select_keys(
        _keys(editor, "visibility", "enabled", "translateX")
    )
    view = _row(editor, "visibility").editor
    assert isinstance(view, BoolCheckBox)
    cmds.flushUndo()
    view.click()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(f"{node}.visibility") is False
        assert cmds.getAttr(f"{node}.enabled") is False
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert "対象外" in editor.message_label.text()
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.visibility") is True
    assert cmds.getAttr("multiB.enabled") is True
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_enum_input_aligns_only_matching_definitions(
    editor: ChannelBoxWidget,
) -> None:
    """ComboBox操作は操作元と定義が一致する選択enumだけへ適用する。"""
    editor.table_view.select_keys(_keys(editor, "mode", "quality", "variant"))
    view = _row(editor, "mode").editor
    assert isinstance(view, EnumComboBox)
    cmds.flushUndo()
    view.setCurrentIndex(2)
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(f"{node}.mode") == 2
        assert cmds.getAttr(f"{node}.quality") == 2
        assert cmds.getAttr(f"{node}.variant") == 0
    assert "enum定義" in editor.message_label.text()
    cmds.undo()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(f"{node}.mode") == 0
        assert cmds.getAttr(f"{node}.quality") == 0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_selected_menu_lock_hide_and_alignment(
    editor: ChannelBoxWidget,
) -> None:
    """選択内の右クリックは集合を保ち、状態変更と各行の代表値揃えを行う。"""
    selected = _keys(editor, "translateX", "translateY")
    editor.table_view.select_keys(selected)
    row = _row(editor, "translateX")
    position = row.name_label.rect().center()
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        row.name_label.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(row.name_label, event)
    _events()
    assert editor.table_view.selected_keys() == selected
    assert row.align_action.isEnabled()
    row.align_action.trigger()
    row.context_menu.close()
    _events()
    assert cmds.getAttr("multiB.translateX") == 5.0
    assert cmds.getAttr("multiB.translateY") == 1.0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiB.translateY") == 3.0
    row = _row(editor, "translateX")
    lock_action = next(
        action
        for action in row.context_menu.actions()
        if action.objectName() == "selected_lock"
    )
    lock_action.trigger()
    for node in ("multiA", "multiB"):
        for attr in ("translateX", "translateY"):
            assert cmds.getAttr(f"{node}.{attr}", lock=True)
    cmds.undo()
    _events()
    editor.controller.set_selected_display(selected, "hidden")
    _events()
    assert not set(selected).intersection(editor.table_view.selected_keys())
    assert not any(
        row.row.attribute.name in ("translateX", "translateY")
        for row in editor.row_widgets
    )
    for node in ("multiA", "multiB"):
        assert not cmds.getAttr(node + ".translateY", keyable=True)
    cmds.undo()
    _events()
    assert _row(editor, "translateY")


def test_state_batch_stops_and_restores_when_controller_closes(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """状態書込み中の終了要求で残りの旧対象を変更せず、先行変更も復旧する。"""
    selected = _keys(editor, "translateX", "translateY")
    original = cast(Callable[..., None], cmds.setAttr)
    interrupted = False

    def set_and_close(*args: object, **kwargs: object) -> None:
        """最初の実書込み直後にWindow controllerの終了を発生させる。"""
        nonlocal interrupted
        original(*args, **kwargs)
        if not interrupted:
            interrupted = True
            editor.controller.dispose()

    monkeypatch.setattr(cmds, "setAttr", set_and_close)
    with pytest.raises(RuntimeError):
        editor.controller.set_selected_locked(selected, True)
    for node in ("multiA", "multiB"):
        for attr in ("translateX", "translateY"):
            assert not cmds.getAttr(f"{node}.{attr}", lock=True)


@pytest.mark.parametrize("numeric", [False, True])
def test_drag_across_attributes_selects_without_writing(
    editor: ChannelBoxWidget, numeric: bool
) -> None:
    """名前欄と値欄の縦ドラッグで途中の属性を含めて選択する。"""
    first = (
        _spin(editor, "translateX")
        if numeric
        else _row(editor, "translateX").name_label
    )
    last = (
        _spin(editor, "rotateZ")
        if numeric
        else _row(editor, "rotateZ").name_label
    )
    for kind in (
        qt.QEvent.Type.MouseButtonPress,
        qt.QEvent.Type.MouseMove,
        qt.QEvent.Type.MouseButtonRelease,
    ):
        target = first if kind == qt.QEvent.Type.MouseButtonPress else last
        position = target.mapToGlobal(target.rect().center())
        event = qt.QtGui.QMouseEvent(
            kind,
            qt.QPointF(first.mapFromGlobal(position)),
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
        qt.QApplication.sendEvent(first, event)
    assert editor.table_view.selected_keys() == _keys(
        editor,
        "translateX",
        "translateY",
        "translateZ",
        "rotateX",
        "rotateY",
        "rotateZ",
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert cmds.getAttr("multiB.translateX") == 9.0


@pytest.mark.parametrize("text", ["e", "1e309", "--1"])
def test_invalid_numeric_input_does_not_write(
    editor: ChannelBoxWidget, text: str
) -> None:
    """不完全な数式や無限値を一括入力として受理しない。"""
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    field = _begin_input(editor, text)
    _key(field, qt.Qt.Key.Key_Return)
    _events()
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiA.translateY") == 1.0
    assert editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_slider_bool_enum_apply_to_selected_compatible_rows(
    editor: ChannelBoxWidget,
) -> None:
    """Slider、bool、enumは選択中の互換属性へ入力を揃える。"""
    editor.table_view.select_keys(
        _keys(editor, "translateX", "gain", "visibility", "mode")
    )
    slider = _row(editor, "gain").editor
    checkbox = _row(editor, "visibility").editor
    combo = _row(editor, "mode").editor
    assert isinstance(slider, FloatSliderSpinBox)
    assert isinstance(checkbox, BoolCheckBox)
    assert isinstance(combo, EnumComboBox)
    slider.slider.setValue(slider.slider.maximum())
    checkbox.click()
    combo.setCurrentIndex(2)
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(node + ".gain") == 10.0
        assert cmds.getAttr(node + ".visibility") is False
        assert cmds.getAttr(node + ".mode") == 2
    assert cmds.getAttr("multiA.translateX") == 10.0
    assert cmds.getAttr("multiB.translateX") == 10.0
