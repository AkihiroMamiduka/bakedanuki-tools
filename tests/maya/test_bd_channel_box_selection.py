# coding: utf-8
"""属性行の選択と、明示的な一括数値入力・状態操作を検証する。"""

from collections.abc import Callable, Iterator
from math import isclose
from typing import cast

import pytest
from maya import cmds

from bd_util.maya.ui import (
    MayaScalarValueClipboard,
    MayaScalarValueTransfer,
    capture_scalar_node_values,
)
from bd_util.ui import (
    BoolCheckBox,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    qt,
)
from bd_tools.bd_channel_box.controller import ChannelAttributeFilter
from bd_tools.bd_channel_box.widget import AttributeRowWidget, ChannelBoxWidget


class _StaticValueClipboard:
    """OS clipboardを使わず固定した搬送値を返すtest用境界。"""

    def __init__(self, transfer: MayaScalarValueTransfer) -> None:
        """読み取る搬送値を保持する。"""
        self._transfer = transfer

    def contains(self) -> bool:
        """対応dataが常に存在すると返す。"""
        return True

    def read(self) -> MayaScalarValueTransfer:
        """固定した搬送値を返す。"""
        return self._transfer


def _events() -> None:
    """遅延同期と旧Widgetの破棄を完了する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _saved_clipboard() -> qt.QtCore.QMimeData:
    """現在のOS clipboardをtest後に復元できる形で複製する。"""
    saved = qt.QtCore.QMimeData()
    original = qt.QApplication.clipboard().mimeData()
    for mime_type in original.formats():
        saved.setData(mime_type, original.data(mime_type))
    return saved


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


def _wheel(widget: qt.QWidget) -> None:
    """マウスオーバー相当の1ノッチを、フォーカスを移さず送る。"""
    event = qt.QtGui.QWheelEvent(
        qt.QPointF(5, 5),
        qt.QPointF(5, 5),
        qt.QPoint(),
        qt.QPoint(0, 120),
        qt.Qt.MouseButton.NoButton,
        qt.Qt.KeyboardModifier.NoModifier,
        qt.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    qt.QApplication.sendEvent(widget, event)


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


def _show_row_menu(row: AttributeRowWidget) -> None:
    """実表示前と同じaboutToShow通知でaction状態を更新する。"""
    row.context_menu.aboutToShow.emit()


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


def test_step_wheel_without_focus_aligns_selected_rows(
    editor: ChannelBoxWidget,
) -> None:
    """Step欄のマウスオーバー中は、クリックせず選択行のStepを変更する。"""
    editor.wheel_editing_action.setChecked(True)
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    translate_x = _row(editor, "translateX").editor
    translate_y = _row(editor, "translateY").editor
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(translate_y, FloatValueStepSpinBox)
    editor.filter_combo.setFocus()
    _events()
    assert not translate_x.step_spin_box.hasFocus()

    _wheel(translate_x.step_spin_box)
    assert translate_x.singleStep() == 10.0
    assert translate_y.singleStep() == 10.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_wheel_menu_option_updates_value_and_step_fields(
    editor: ChannelBoxWidget,
) -> None:
    """設定メニューで未フォーカス時の数値欄・Step欄・enumを切り替える。"""
    translate_x = _row(editor, "translateX").editor
    limited = _row(editor, "limited").editor
    enum_mode = _row(editor, "mode").editor
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(limited, FloatSliderSpinBox)
    assert isinstance(enum_mode, EnumComboBox)
    assert editor.menu_bar is not None
    assert editor.settings_menu.title() == "設定"
    assert editor.wheel_editing_action.isCheckable()
    assert not editor.wheel_editing_action.isChecked()
    assert translate_x.spin_box.wheel_requires_focus()
    assert translate_x.step_spin_box.wheel_requires_focus()
    assert limited.spin_box.wheel_requires_focus()
    assert enum_mode.wheel_requires_focus()

    # OFFでは未フォーカスのホイールを全ての属性値で変更に使わない
    _set_value("multiA.mode", 1)
    _set_value("multiB.mode", 1)
    _events()
    cmds.flushUndo()
    editor.filter_combo.setFocus()
    _events()
    before_value = cmds.getAttr("multiA.translateX")
    before_step = translate_x.singleStep()
    _wheel(translate_x.spin_box)
    _wheel(translate_x.step_spin_box)
    _wheel(enum_mode)
    assert cmds.getAttr("multiA.translateX") == before_value
    assert translate_x.singleStep() == before_step
    assert cmds.getAttr("multiA.mode") == cmds.getAttr("multiB.mode") == 1

    # ONへ切り替えると全入力欄へ即時反映し、enumも未フォーカスで編集できる
    editor.wheel_editing_action.setChecked(True)
    assert not translate_x.spin_box.wheel_requires_focus()
    assert not translate_x.step_spin_box.wheel_requires_focus()
    assert not limited.spin_box.wheel_requires_focus()
    assert not enum_mode.wheel_requires_focus()
    editor.filter_combo.setFocus()
    _wheel(enum_mode)
    assert cmds.getAttr("multiA.mode") == cmds.getAttr("multiB.mode") == 0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.mode") == cmds.getAttr("multiB.mode") == 1

    # 行を再構築してもONを維持し、再度OFFにすると現在行へ即時反映する
    editor.refresh()
    _events()
    rebuilt = _row(editor, "translateX").editor
    rebuilt_limited = _row(editor, "limited").editor
    rebuilt_enum = _row(editor, "mode").editor
    assert isinstance(rebuilt, FloatValueStepSpinBox)
    assert isinstance(rebuilt_limited, FloatSliderSpinBox)
    assert isinstance(rebuilt_enum, EnumComboBox)
    assert not rebuilt.spin_box.wheel_requires_focus()
    assert not rebuilt.step_spin_box.wheel_requires_focus()
    assert not rebuilt_limited.spin_box.wheel_requires_focus()
    assert not rebuilt_enum.wheel_requires_focus()
    editor.wheel_editing_action.setChecked(False)
    assert rebuilt.spin_box.wheel_requires_focus()
    assert rebuilt.step_spin_box.wheel_requires_focus()
    assert rebuilt_limited.spin_box.wheel_requires_focus()
    assert rebuilt_enum.wheel_requires_focus()
    limited_before = (
        cmds.getAttr("multiA.limited"),
        cmds.getAttr("multiB.limited"),
    )
    editor.filter_combo.setFocus()
    _wheel(rebuilt_limited.spin_box)
    assert (
        cmds.getAttr("multiA.limited"),
        cmds.getAttr("multiB.limited"),
    ) == limited_before
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


def test_copy_all_values_uses_reference_node_and_does_not_write(
    editor: ChannelBoxWidget,
) -> None:
    """行選択に依存せず基準nodeの全対応値を保存し、sceneとUndoを変えない。"""
    clipboard = qt.QApplication.clipboard()
    saved = _saved_clipboard()
    try:
        _set_value("multiA.translateX", 5.25)
        _set_value("multiA.gain", 4.5)
        _set_value("multiA.mode", 2)
        selected = _keys(editor, "translateX")
        editor.table_view.select_keys(selected)
        row = _row(editor, "translateX")
        _show_row_menu(row)
        assert row.copy_menu.title() == "コピー"
        assert row.copy_all_values_action.isEnabled()
        assert row.copy_selected_values_action.isEnabled()
        assert row.paste_menu.title() == "ペースト"
        assert row.paste_copied_values_menu.title() == "コピー元と同じ属性"
        assert tuple(
            action.text()
            for action in row.paste_copied_values_actions.values()
        ) == (
            "全て",
            "keyable + channelbox",
            "keyable",
            "channelbox",
            "hide",
        )
        assert editor.edit_menu.title() == "編集"
        assert editor.copy_menu.title() == "コピー"
        assert editor.paste_menu.title() == "ペースト"
        editor.edit_menu.aboutToShow.emit()
        assert editor.copy_all_values_action.isEnabled()
        assert editor.copy_selected_values_action.isEnabled()
        cmds.flushUndo()

        editor.copy_all_values_action.trigger()
        transfer = MayaScalarValueClipboard().read()
        values = {
            snapshot.path: snapshot.value
            for snapshot in transfer.nodes[0].values
        }
        assert values["translate.translateX"] == 5.25
        assert values["gain"] == 4.5
        assert values["mode"] == 2
        assert "translate.translateY" in values
        assert len(values) > len(selected)
        assert len(transfer.nodes) == 1
        _show_row_menu(row)
        assert row.paste_copied_values_action.isEnabled()
        assert row.paste_selected_values_action.isEnabled()
        assert cmds.getAttr("multiB.translateX") == 9.0
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
        assert f"全{len(values)}属性" in editor.message_label.text()
    finally:
        clipboard.setMimeData(saved)


def test_single_copied_value_pastes_to_selected_paths_and_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """一つだけコピーした値を、コピー元pathに依存せず複数属性へ貼る。"""
    clipboard = qt.QApplication.clipboard()
    saved = _saved_clipboard()
    try:
        _set_value("multiA.translateX", 6.25)
        editor.table_view.select_keys(_keys(editor, "translateX"))
        source_row = _row(editor, "translateX")
        _show_row_menu(source_row)
        assert source_row.copy_selected_values_action.isEnabled()
        source_row.copy_selected_values_action.trigger()
        assert editor.controller.can_paste_single_value()

        editor.table_view.select_keys(
            _keys(editor, "translateY", "translateZ")
        )
        target_row = _row(editor, "translateY")
        _show_row_menu(target_row)
        assert target_row.paste_selected_values_action.isEnabled()
        assert "一つの値" in target_row.paste_selected_values_action.toolTip()
        editor.edit_menu.aboutToShow.emit()
        assert editor.paste_selected_values_action.isEnabled()
        cmds.flushUndo()

        editor.paste_selected_values_action.trigger()
        _events()
        for node in ("multiA", "multiB"):
            assert cmds.getAttr(node + ".translateY") == 6.25
            assert cmds.getAttr(node + ".translateZ") == 6.25
        assert cmds.getAttr("multiA.translateX") == 6.25
        assert cmds.getAttr("multiB.translateX") == 9.0
        assert not editor.message_label.isVisible()
        assert editor.message_label.text() == ""

        cmds.undo()
        _events()
        assert cmds.getAttr("multiA.translateX") == 6.25
        assert cmds.getAttr("multiB.translateX") == 9.0
        assert cmds.getAttr("multiA.translateY") == 1.0
        assert cmds.getAttr("multiB.translateY") == 3.0
        assert cmds.getAttr("multiA.translateZ") == 0.0
        assert cmds.getAttr("multiB.translateZ") == 0.0
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    finally:
        clipboard.setMimeData(saved)


def test_selected_values_paste_to_copied_paths_across_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """選択属性だけをコピーし、貼り付け先の行選択に依存せず同じpathへ貼る。"""
    clipboard = qt.QApplication.clipboard()
    saved = _saved_clipboard()
    try:
        _set_value("multiA.translateX", 5.25)
        _set_value("multiA.gain", 4.5)
        _set_value("multiA.mode", 2)
        editor.table_view.select_keys(
            _keys(editor, "translateX", "gain", "mode")
        )
        source_row = _row(editor, "translateX")
        _show_row_menu(source_row)
        source_row.copy_selected_values_action.trigger()
        transfer = MayaScalarValueClipboard().read()
        assert {snapshot.path for snapshot in transfer.nodes[0].values} == {
            "translate.translateX",
            "gain",
            "mode",
        }

        for node in ("multiA", "multiB"):
            _set_value(node + ".translateX", 0.0)
            _set_value(node + ".gain", 1.0)
            _set_value(node + ".mode", 0)
        editor.table_view.select_keys(_keys(editor, "rotateX"))
        target_row = _row(editor, "rotateX")
        _show_row_menu(target_row)
        assert target_row.paste_copied_values_action.isEnabled()
        cmds.flushUndo()

        target_row.paste_copied_values_action.trigger()
        _events()
        for node in ("multiA", "multiB"):
            assert cmds.getAttr(node + ".translateX") == 5.25
            assert cmds.getAttr(node + ".gain") == 4.5
            assert cmds.getAttr(node + ".mode") == 2
            assert cmds.getAttr(node + ".rotateX") == 0.0
        assert not editor.message_label.isVisible()
        assert editor.message_label.text() == ""

        cmds.undo()
        _events()
        for node in ("multiA", "multiB"):
            assert cmds.getAttr(node + ".translateX") == 0.0
            assert cmds.getAttr(node + ".gain") == 1.0
            assert cmds.getAttr(node + ".mode") == 0
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    finally:
        clipboard.setMimeData(saved)


def test_copied_path_paste_filters_by_reference_node_display_state(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """基準nodeの表示状態でCopy項目を絞り、同じpathを全選択nodeへ貼る。"""
    _set_value("multiA.gain", 4.5)
    _set_value("multiA.enabled", False)
    _set_value("multiA.limited", 3.5)
    attributes = tuple(
        _row(editor, name).row.attribute
        for name in ("gain", "enabled", "limited")
    )
    transfer = MayaScalarValueTransfer(
        (capture_scalar_node_values("multiA", attributes),)
    )
    monkeypatch.setattr(
        editor.controller,
        "_value_clipboard",
        _StaticValueClipboard(transfer),
    )

    # 基準nodeと後続nodeで表示状態を変え、基準側だけでpathを決める
    cmds.setAttr("multiA.gain", keyable=True)
    cmds.setAttr("multiA.enabled", keyable=False)
    cmds.setAttr("multiA.enabled", channelBox=True)
    cmds.setAttr("multiA.limited", keyable=False)
    cmds.setAttr("multiA.limited", channelBox=False)
    cmds.setAttr("multiB.gain", keyable=False)
    cmds.setAttr("multiB.gain", channelBox=False)
    cmds.setAttr("multiB.enabled", keyable=False)
    cmds.setAttr("multiB.enabled", channelBox=False)
    cmds.setAttr("multiB.limited", keyable=True)
    for node in ("multiA", "multiB"):
        _set_value(node + ".gain", 1.0)
        _set_value(node + ".enabled", True)
        _set_value(node + ".limited", 1.0)
    _events()
    editor.edit_menu.aboutToShow.emit()
    assert editor.paste_copied_values_menu.isEnabled()
    assert all(
        action.isEnabled()
        for action in editor.paste_copied_values_actions.values()
    )
    cmds.flushUndo()

    cases: tuple[
        tuple[
            ChannelAttributeFilter,
            tuple[float, bool, float],
        ],
        ...,
    ] = (
        ("keyable", (4.5, True, 1.0)),
        ("channel_box", (1.0, False, 1.0)),
        ("hidden", (1.0, True, 3.5)),
        ("visible", (4.5, False, 1.0)),
    )
    editor.message_label.setText("以前の操作通知")
    editor.message_label.show()
    for display_filter, expected in cases:
        editor.paste_copied_values_actions[display_filter].trigger()
        _events()
        for node in ("multiA", "multiB"):
            assert cmds.getAttr(node + ".gain") == expected[0]
            assert cmds.getAttr(node + ".enabled") is expected[1]
            assert cmds.getAttr(node + ".limited") == expected[2]
        assert not editor.message_label.isVisible()
        assert editor.message_label.text() == ""

        cmds.undo()
        _events()
        for node in ("multiA", "multiB"):
            assert cmds.getAttr(node + ".gain") == 1.0
            assert cmds.getAttr(node + ".enabled") is True
            assert cmds.getAttr(node + ".limited") == 1.0
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 一項目も条件に合わない場合は値とUndoを変更しない
    cmds.setAttr("multiA.enabled", channelBox=False)
    cmds.setAttr("multiA.enabled", keyable=True)
    cmds.setAttr("multiA.limited", keyable=True)
    cmds.flushUndo()
    editor.paste_copied_values_actions["channel_box"].trigger()
    assert not editor.message_label.isVisible()
    assert editor.message_label.text() == ""
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_paste_matches_only_selected_formal_paths_across_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """全属性clipboardから選択pathだけを貼り、除外理由を画面へ出さない。"""
    clipboard = qt.QApplication.clipboard()
    saved = _saved_clipboard()
    try:
        _set_value("multiA.translateX", 5.25)
        _set_value("multiA.gain", 4.5)
        _set_value("multiA.mode", 2)
        _set_value("multiA.enabled", True)
        source_row = _row(editor, "translateX")
        _show_row_menu(source_row)
        source_row.copy_all_values_action.trigger()

        for node, mode_definition in (
            ("pasteA", "A:B:C"),
            ("pasteB", "A:B:D"),
        ):
            cmds.createNode("transform", name=node)
            cmds.addAttr(
                node,
                longName="gain",
                attributeType="double",
                keyable=True,
            )
            cmds.addAttr(
                node,
                longName="mode",
                attributeType="enum",
                enumName=mode_definition,
                keyable=True,
            )
            cmds.addAttr(
                node,
                longName="enabled",
                attributeType="bool",
                keyable=False,
            )
            _set_value(node + ".gain", 1.0)
            _set_value(node + ".enabled", False)
        cmds.setAttr("pasteB.gain", lock=True)
        cmds.select("pasteA", "pasteB", replace=True)
        _events()
        assert not any(
            widget.row.attribute.name == "enabled"
            for widget in editor.row_widgets
        )
        cmds.flushUndo()

        target_row = _row(editor, "translateX")
        editor.table_view.select_keys(
            _keys(editor, "translateX", "gain", "mode")
        )
        _show_row_menu(target_row)
        assert target_row.paste_selected_values_action.isEnabled()
        assert (
            "同じ正式path" in target_row.paste_selected_values_action.toolTip()
        )
        target_row.paste_selected_values_action.trigger()
        _events()

        assert cmds.getAttr("pasteA.translateX") == 5.25
        assert cmds.getAttr("pasteB.translateX") == 5.25
        assert cmds.getAttr("pasteA.gain") == 4.5
        assert cmds.getAttr("pasteB.gain") == 1.0
        assert cmds.getAttr("pasteA.mode") == 2
        assert cmds.getAttr("pasteB.mode") == 0
        assert cmds.getAttr("pasteA.enabled") is False
        assert cmds.getAttr("pasteB.enabled") is False
        assert not editor.message_label.isVisible()
        assert editor.message_label.text() == ""

        cmds.undo()
        _events()
        assert cmds.getAttr("pasteA.translateX") == 0
        assert cmds.getAttr("pasteB.translateX") == 0
        assert cmds.getAttr("pasteA.gain") == 1.0
        assert cmds.getAttr("pasteA.mode") == 0
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    finally:
        clipboard.setMimeData(saved)


def test_invalid_clipboard_data_reports_error_without_writing(
    editor: ChannelBoxWidget,
) -> None:
    """識別済みでも壊れた外部JSONは画面へ通知し、値とUndoを変えない。"""
    clipboard = qt.QApplication.clipboard()
    saved = _saved_clipboard()
    try:
        mime_data = qt.QtCore.QMimeData()
        mime_data.setText("BAKEDANUKI_MAYA_SCALAR_VALUES/1\n{broken")
        clipboard.setMimeData(mime_data)
        row = _row(editor, "translateX")
        _show_row_menu(row)
        assert row.paste_copied_values_action.isEnabled()
        assert row.paste_selected_values_action.isEnabled()
        editor.message_label.setText("以前の操作通知")
        editor.message_label.show()
        before = tuple(
            cmds.getAttr(node + ".translateX") for node in ("multiA", "multiB")
        )
        cmds.flushUndo()

        row.paste_selected_values_action.trigger()
        assert (
            tuple(
                cmds.getAttr(node + ".translateX")
                for node in ("multiA", "multiB")
            )
            == before
        )
        assert editor.message_label.isVisible()
        assert "JSON" in editor.message_label.text()
        assert "以前の操作通知" not in editor.message_label.text()
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    finally:
        clipboard.setMimeData(saved)
