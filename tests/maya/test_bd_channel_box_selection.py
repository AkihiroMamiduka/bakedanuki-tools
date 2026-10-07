# coding: utf-8
"""属性行の選択と、明示的な一括数値入力・状態操作を検証する。"""

from collections.abc import Callable, Iterator
from math import isclose
from typing import Literal, NoReturn, cast

import pytest
from maya import cmds

from bd_util.maya.ui import (
    MayaCallbackRegistry,
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
import bd_tools.bd_channel_box.controller as controller_module
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


class _MemoryValueClipboard:
    """OS clipboardを使わずCopyした搬送値を検査する。"""

    def __init__(self) -> None:
        """まだコピー値がない状態を作る。"""
        self.transfer: MayaScalarValueTransfer | None = None

    def contains(self) -> bool:
        """値が記録済みか返す。"""
        return self.transfer is not None

    def read(self) -> MayaScalarValueTransfer:
        """最後に記録した値を返す。"""
        if self.transfer is None:
            raise RuntimeError("コピー値がありません")
        return self.transfer

    def write(self, transfer: MayaScalarValueTransfer) -> None:
        """Copy結果を保持する。"""
        self.transfer = transfer


def _events() -> None:
    """遅延同期と旧Widgetの破棄を完了する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


def _saved_clipboard() -> qt.QtCore.QMimeData:
    """現在のOS clipboardをtest後に復元できる形で複製する。"""
    saved = qt.QtCore.QMimeData()
    original = cast(
        qt.QtCore.QMimeData | None, qt.QApplication.clipboard().mimeData()
    )
    if original is not None:
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
    auto_key = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
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
    cmds.select("multiB", "multiA", replace=True)
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
    cmds.autoKeyframe(state=auto_key)


def _row(editor: ChannelBoxWidget, name: str) -> AttributeRowWidget:
    """正式属性名に対応する値編集行を取得する。"""
    row = next(
        row for row in editor.row_widgets if row.row.attribute.name == name
    )
    assert isinstance(row, AttributeRowWidget)
    return row


def _open_row_menu(row: AttributeRowWidget) -> None:
    """属性名の右クリックで値編集行メニューを表示する。"""
    position = row.name_label.rect().center()
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        row.name_label.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(row.name_label, event)
    _events()


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


def _has_breakdown(path: str, time: float) -> bool:
    """指定時刻にBreakdownキーがあるかMayaの抽出結果で判定する。"""
    return bool(
        cmds.keyframe(path, query=True, time=(time, time), breakdown=True)
    )


def _animation_layer_attributes(layer: str) -> set[str]:
    """レイヤに登録された属性名を返す。"""
    return set(
        cast(
            list[str] | None, cmds.animLayer(layer, query=True, attribute=True)
        )
        or ()
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


def test_batch_input_opens_origin_row_menu(
    editor: ChannelBoxWidget,
) -> None:
    """一括入力中の右クリックは元の行メニューを開いて値を確定する。"""
    selected = _keys(editor, "translateX", "translateY")
    editor.table_view.select_keys(selected)
    field = _begin_input(editor, "7")
    row = _row(editor, "translateX")
    position = field.rect().center()
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        field.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(field, event)
    _events()
    assert row.context_menu.isVisible()
    assert editor.table_view.selected_keys() == selected
    assert cmds.getAttr("multiA.translateY") == 7.0
    assert cmds.getAttr("multiB.translateX") == 7.0
    row.context_menu.close()


def test_locked_value_field_opens_row_context_menu(
    editor: ChannelBoxWidget,
) -> None:
    """入力不能の数値欄からもロック解除などの属性操作を開ける。"""
    cmds.setAttr("multiA.translateX", lock=True)
    cmds.setAttr("multiB.translateX", lock=True)
    _events()
    row = _row(editor, "translateX")
    field = _spin(editor, "translateX")
    assert not field.isEnabled()
    position = field.rect().center()
    event = qt.QtGui.QContextMenuEvent(
        qt.QtGui.QContextMenuEvent.Reason.Mouse,
        position,
        field.mapToGlobal(position),
    )
    qt.QApplication.sendEvent(field, event)
    _events()
    assert row.context_menu.isVisible()
    row.context_menu.close()


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


def _palette_colors(
    widget: qt.QWidget,
) -> tuple[qt.QtGui.QColor, qt.QtGui.QColor, qt.QtGui.QColor, qt.QtGui.QColor]:
    """選択表示で維持するWidgetの主要なpalette色を返す。"""
    palette = widget.palette()
    return (
        palette.color(qt.QPalette.ColorRole.Window),
        palette.color(qt.QPalette.ColorRole.Base),
        palette.color(qt.QPalette.ColorRole.WindowText),
        palette.color(qt.QPalette.ColorRole.Text),
    )


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


def test_selection_highlights_only_attribute_names(
    editor: ChannelBoxWidget,
) -> None:
    """複数属性の選択色を名前欄だけへ適用し、各入力部品の配色を維持する。"""
    rows = tuple(
        _row(editor, name)
        for name in ("translateX", "gain", "enabled", "mode")
    )
    value_step = rows[0].editor
    slider = rows[1].editor
    check_box = rows[2].editor
    combo_box = rows[3].editor
    assert isinstance(value_step, FloatValueStepSpinBox)
    assert isinstance(slider, FloatSliderSpinBox)
    assert isinstance(check_box, BoolCheckBox)
    assert isinstance(combo_box, EnumComboBox)
    inputs: tuple[qt.QWidget, ...] = (
        value_step.spin_box,
        value_step.step_spin_box,
        slider.spin_box,
        slider.slider,
        check_box,
        combo_box,
    )
    input_states = tuple(
        (_palette_colors(widget), widget.autoFillBackground())
        for widget in inputs
    )
    name_states = tuple(
        (_palette_colors(row.name_label), row.name_label.autoFillBackground())
        for row in rows
    )
    assert all(row.name_label.contentsMargins().right() == 4 for row in rows)

    editor.table_view.select_keys(
        tuple((row.row.attribute.path, row.row.attribute.kind) for row in rows)
    )
    highlight = editor.table_view.palette().color(
        qt.QPalette.ColorRole.Highlight
    )
    highlighted_text = editor.table_view.palette().color(
        qt.QPalette.ColorRole.HighlightedText
    )
    for row in rows:
        palette = row.name_label.palette()
        assert palette.color(qt.QPalette.ColorRole.Window) == highlight
        assert palette.color(qt.QPalette.ColorRole.Base) == highlight
        assert (
            palette.color(qt.QPalette.ColorRole.WindowText) == highlighted_text
        )
        assert palette.color(qt.QPalette.ColorRole.Text) == highlighted_text
        assert row.name_label.autoFillBackground()
    assert (
        tuple(
            (_palette_colors(widget), widget.autoFillBackground())
            for widget in inputs
        )
        == input_states
    )

    editor.table_view.clearSelection()
    assert (
        tuple(
            (
                _palette_colors(row.name_label),
                row.name_label.autoFillBackground(),
            )
            for row in rows
        )
        == name_states
    )
    assert (
        tuple(
            (_palette_colors(widget), widget.autoFillBackground())
            for widget in inputs
        )
        == input_states
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def _indicator_color(
    row: AttributeRowWidget,
    position: Literal["top", "center", "bottom"] = "center",
) -> str:
    """表示中の細い帯から指定位置の中央画素を取得する。"""
    indicator = row.input_indicator
    image = indicator.grab().toImage()
    y = {
        "top": 0,
        "center": image.height() // 2,
        "bottom": image.height() - 1,
    }[position]
    return image.pixelColor(image.width() // 2, y).name().upper()


def test_connection_indicators_match_maya_colors(
    editor: ChannelBoxWidget,
) -> None:
    """接続種類とロックの色を上下1px空けて表示する。"""
    cmds.currentTime(5)
    cmds.setKeyframe("multiA.translateX", time=5, value=5)
    cmds.setKeyframe("multiA.translateY", time=1, value=1)
    cmds.connectAttr("multiB.translateZ", "multiA.translateZ")
    _events()
    blank = _row(editor, "rotateX").input_indicator
    assert _indicator_color(_row(editor, "rotateX")) == (
        blank.palette().color(qt.QPalette.ColorRole.Window).name().upper()
    )
    blend = cmds.createNode("pairBlend")
    constraint = cmds.createNode("scaleConstraint")
    cmds.connectAttr(blend + ".outRotate", "multiA.rotate")
    cmds.connectAttr(constraint + ".constraintScale", "multiA.scale")
    cmds.setAttr("multiA.visibility", lock=True)
    cmds.select("multiB", "multiA", replace=True)
    _events()
    expected = (
        ("translateX", "keyed", "#CD2729"),
        ("translateY", "animated", "#DD727A"),
        ("translateZ", "connected", "#F1F1A5"),
        ("rotateX", "pair_blend", "#ACF1AC"),
        ("rotateY", "pair_blend", "#ACF1AC"),
        ("rotateZ", "pair_blend", "#ACF1AC"),
        ("scaleX", "constraint", "#A3CBF0"),
        ("scaleY", "constraint", "#A3CBF0"),
        ("scaleZ", "constraint", "#A3CBF0"),
        ("visibility", "locked", "#5C6874"),
    )
    for name, state, color in expected:
        row = _row(editor, name)
        background = (
            row.input_indicator.palette()
            .color(qt.QPalette.ColorRole.Window)
            .name()
            .upper()
        )
        assert row.input_indicator.width() == 6
        assert row.input_indicator.input_state == state, (
            name,
            row.row.binding.target_states,
        )
        assert _indicator_color(row) == (
            background if color is None else color
        )
        assert _indicator_color(row, "top") == background
        assert _indicator_color(row, "bottom") == background
        assert row.row.binding.target_states[0].input_state == (
            "unconnected" if state == "locked" else state
        )
    assert (
        "ロックされています"
        in _row(editor, "visibility").input_indicator.toolTip()
    )
    assert (
        "ロック状態は選択ノード間で混在"
        in _row(editor, "visibility").input_indicator.toolTip()
    )
    assert (
        "接続状態は選択ノード間で混在"
        in _row(editor, "translateX").input_indicator.toolTip()
    )
    cmds.flushUndo()
    _click(_row(editor, "translateX").input_indicator)
    assert editor.table_view.selected_keys() == _keys(editor, "translateX")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_indicator_tracks_equal_value_keys_time_lock_and_selection(
    editor: ChannelBoxWidget,
) -> None:
    """値と編集可否が変わらなくてもキー色を更新し、選択色と分離する。"""
    cmds.setKeyframe("multiA.translateX", time=1, value=5)
    cmds.currentTime(5)
    _events()
    row = _row(editor, "translateX")
    assert _indicator_color(row) == "#DD727A"
    cmds.setKeyframe("multiA.translateX", time=5, value=5)
    _events()
    assert _indicator_color(row) == "#CD2729"
    editor.table_view.select_keys(_keys(editor, "translateX"))
    assert _indicator_color(row) == "#CD2729"
    cmds.setAttr("multiA.translateX", lock=True)
    _events()
    assert not row.row.binding.view_model.set_value_command.can_execute
    assert _indicator_color(row) == "#5C6874"
    assert row.row.binding.target_states[0].input_state == "keyed"
    assert "現在時刻にキーあり" in row.input_indicator.toolTip()
    cmds.setAttr("multiA.translateX", lock=False)
    _events()
    assert _indicator_color(row) == "#CD2729"
    cmds.cutKey("multiA.translateX", time=(5, 5), clear=True)
    _events()
    assert _indicator_color(row) == "#DD727A"
    cmds.currentTime(1)
    _events()
    assert _indicator_color(row) == "#CD2729"
    assert cmds.getAttr("multiA.translateX") == 5


def test_additional_maya_input_colors_follow_actual_plug_states(
    editor: ChannelBoxWidget,
) -> None:
    """追加した七種の状態を実接続と現在値から色分けする。"""
    cmds.select("multiA", replace=True)
    cmds.currentTime(1)
    cmds.setKeyframe("multiA.scaleX", time=1, value=1)
    cmds.setKeyframe("multiA.scaleX", time=10, value=2)
    cmds.timeEditorComposition("ProbeComposition", createTrack=True)
    cmds.timeEditorClip(
        "ProbeClip",
        addSelectedObjects=True,
        type=["animCurveTU"],
        track="ProbeComposition:0",
    )
    driver = cmds.createNode("transform")
    cmds.addAttr(
        driver, longName="control", attributeType="double", keyable=True
    )
    cmds.setDrivenKeyframe(
        "multiA.translateX", currentDriver=driver + ".control", value=5
    )
    cmds.expression(string=f"multiA.translateY = {driver}.translateY * 2;")
    cmds.setKeyframe("multiA.translateZ", time=1, value=1)
    cmds.mute("multiA.translateZ")
    layer = cast(
        str, cmds.animLayer("ProbeLayer", attribute=["multiA.rotateZ"])
    )
    cmds.setKeyframe("multiA.rotateZ", time=1, value=5, animLayer=layer)
    cmds.setAttr("multiA.rotateY", keyable=False, channelBox=True)
    cmds.setKeyframe("multiA.scaleY", time=1, value=2)
    _set_value("multiA.scaleY", 5)
    cmds.select("multiA", replace=True)
    _events()

    expected = (
        ("translateX", "driven_key", "#5099DA"),
        ("translateY", "expression", "#CBA5F1"),
        ("translateZ", "muted", "#BFA182"),
        ("rotateZ", "animation_layer", "#4DB6AC"),
        ("rotateY", "nonkeyable", "#949494"),
        ("scaleX", "animation_clip", "#FFCC80"),
        ("scaleY", "key_altered", "#FDCBC4"),
    )
    for name, state, color in expected:
        row = _row(editor, name)
        assert row.row.binding.target_states[0].input_state == state, (
            name,
            row.row.binding.target_states,
            cmds.listConnections(
                "multiA." + name, source=True, destination=False, plugs=True
            ),
            cmds.ls(selection=True),
        )
        assert row.input_indicator.input_state == state
        assert _indicator_color(row) == color
        background = (
            row.input_indicator.palette()
            .color(qt.QPalette.ColorRole.Window)
            .name()
            .upper()
        )
        assert _indicator_color(row, "top") == background
        assert _indicator_color(row, "bottom") == background

    cmds.setAttr("multiA.translateX", lock=True)
    _events()
    row = _row(editor, "translateX")
    assert row.row.binding.target_states[0].input_state == "driven_key"
    assert row.input_indicator.input_state == "locked"
    assert _indicator_color(row) == "#5C6874"


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


def test_selection_reordering_closes_old_row_menu(
    editor: ChannelBoxWidget,
) -> None:
    """同じノードの順序変更でも旧基準の行メニューを破棄する。"""
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    row = _row(editor, "translateX")
    _open_row_menu(row)
    assert row.context_menu.isVisible()

    cmds.select("multiB", "multiA", replace=True)
    _events()
    assert not qt.isValid(row.context_menu) or not row.context_menu.isVisible()
    assert editor.node_name_edit is not None
    assert editor.node_name_edit.text() == "multiA"


def test_selection_reordering_discards_pending_numeric_input(
    editor: ChannelBoxWidget,
) -> None:
    """同じノードの順序変更では旧基準へ未確定数値を書き込まない。"""
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    _begin_input(editor, "7")

    cmds.select("multiB", "multiA", replace=True)
    _events()
    assert editor.table_view.selected_keys() == ()
    assert editor.node_name_edit is not None
    assert editor.node_name_edit.text() == "multiA"
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiA.translateY") == 1.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.getAttr("multiB.translateY") == 3.0


def test_selection_limit_skips_inspection_and_recovers_in_all_modes(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """50ノード以上では属性取得を止め、全モードで案内と復帰を確認する。"""
    nodes = tuple(
        cmds.createNode("network", name=f"selectionLimit{index}")
        for index in range(51)
    )
    expected_message = (
        "対象ノードが50個以上あります。\n"
        "多数のノードを対象にすると、処理が重くレスポンスが悪い為、"
        "bdChannelBoxの表示・編集を休止しています。\n"
        "49個以下に減らすと再開します。"
    )
    cmds.select(*nodes[:49], replace=True)
    _events()
    assert not editor.controller.selection_limit_exceeded
    assert len(editor.controller.node_names) == 49
    callbacks = cast(
        MayaCallbackRegistry, getattr(editor.controller, "_nodes")
    )
    assert not callbacks.is_disposed

    original_inspect = controller_module.inspect_scalar_attributes

    def reject_inspection(_name: str) -> NoReturn:
        """上限時の属性取得を検出する。"""
        raise AssertionError("上限時に属性を取得しました")

    monkeypatch.setattr(
        controller_module, "inspect_scalar_attributes", reject_inspection
    )
    cmds.select(*nodes[:50], replace=True)
    _events()
    assert editor.controller.selection_limit_exceeded
    assert editor.controller.node_names == ()
    assert editor.controller.node_ids == ()
    assert editor.controller.rows == ()
    assert callbacks.is_disposed
    assert editor.row_widgets == ()
    assert editor.node_name_edit is None
    assert editor.empty_label.text() == expected_message
    assert editor.empty_label.isVisible()
    assert not editor.table_view.isVisible()
    assert not editor.copy_all_values_action.isEnabled()

    for mode in ("states", "custom_filter_setup", "values"):
        editor.controller.set_mode(mode)
        _events()
        assert editor.empty_label.text() == expected_message
        assert editor.empty_label.isVisible()
        assert not editor.table_view.isVisible()
        assert not editor.setup_panel.isVisible()
    editor.refresh()
    cmds.select(*nodes, replace=True)
    _events()
    assert editor.controller.selection_limit_exceeded
    assert editor.empty_label.text() == expected_message

    monkeypatch.setattr(
        controller_module, "inspect_scalar_attributes", original_inspect
    )
    cmds.select(*nodes[:49], replace=True)
    _events()
    assert not editor.controller.selection_limit_exceeded
    assert len(editor.controller.node_names) == 49
    assert editor.table_view.isVisible()
    assert editor.empty_label.text() != expected_message

    cmds.select("multiA", "multiB", replace=True)
    _events()
    assert len(editor.controller.node_names) == 2
    assert editor.row_widgets
    assert editor.node_name_edit is not None
    assert editor.copy_all_values_action.isEnabled()


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


def test_step_reset_context_menu_resets_selected_then_all(
    editor: ChannelBoxWidget,
) -> None:
    """右クリックのStep設定から、選択属性と全属性を既定値へ戻す。"""
    translate_x_row = _row(editor, "translateX")
    rotate_y_row = _row(editor, "rotateY")
    translate_x = translate_x_row.editor
    rotate_y = rotate_y_row.editor
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(rotate_y, FloatValueStepSpinBox)
    assert (
        editor.step_settings_menu.menuAction() in editor.context_menu.actions()
    )
    assert editor.step_settings_menu.menuAction() in (
        translate_x_row.context_menu.actions()
    )
    assert tuple(
        action.text() for action in editor.step_settings_menu.actions()
    ) == (
        "初期値に戻す: 選択属性",
        "初期値に戻す: 全ての属性",
    )

    editor.context_menu.aboutToShow.emit()
    assert not editor.reset_all_steps_action.isEnabled()
    assert not editor.reset_selected_steps_action.isEnabled()
    translate_x.setSingleStep(2.0)
    rotate_y.setSingleStep(3.0)
    editor.step_profile.set_single_step("offscreenWeight", "number", 4.0)
    assert len(editor.step_profile.entries) == 3
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    editor.table_view.select_keys(_keys(editor, "translateX"))
    translate_x_row.context_menu.aboutToShow.emit()
    assert editor.reset_all_steps_action.isEnabled()
    assert editor.reset_selected_steps_action.isEnabled()
    editor.reset_selected_steps_action.trigger()
    assert translate_x.singleStep() == 1.0
    assert rotate_y.singleStep() == 3.0
    assert tuple(entry.key for entry in editor.step_profile.entries) == (
        "offscreenWeight",
        "rotate.rotateY",
    )
    assert not editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    editor.context_menu.aboutToShow.emit()
    assert editor.reset_all_steps_action.isEnabled()
    assert not editor.reset_selected_steps_action.isEnabled()
    editor.reset_all_steps_action.trigger()
    assert translate_x.singleStep() == 1.0
    assert rotate_y.singleStep() == 15.0
    assert editor.step_profile.entries == ()
    assert not editor.reset_all_steps_action.isEnabled()
    assert not editor.reset_selected_steps_action.isEnabled()
    assert not editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_returning_step_to_default_removes_saved_override(
    editor: ChannelBoxWidget,
) -> None:
    """Stepを属性固有の初期値へ戻した場合はprofileへ保存しない。"""
    translate_x = _row(editor, "translateX").editor
    rotate_y = _row(editor, "rotateY").editor
    assert isinstance(translate_x, FloatValueStepSpinBox)
    assert isinstance(rotate_y, FloatValueStepSpinBox)
    translate_x.setSingleStep(2.0)
    rotate_y.setSingleStep(30.0)
    assert len(editor.step_profile.entries) == 2
    translate_x.setSingleStep(1.0)
    rotate_y.setSingleStep(15.0)
    assert editor.step_profile.entries == ()
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


@pytest.mark.parametrize("operation", ["direct", "step", "align"])
@pytest.mark.parametrize("auto_key", [False, True])
def test_animated_numeric_rows_mix_keyed_and_static_targets(
    editor: ChannelBoxWidget, operation: str, auto_key: bool
) -> None:
    """全入力経路でAuto Keyを尊重し、一時値と通常値も一Undoにする。"""
    animated = ("multiA.translateX", "multiB.translateY")
    for path, value in zip(animated, (5.0, 3.0)):
        cmds.setKeyframe(path, time=1, value=value)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    selected = _keys(editor, "translateX", "translateY")
    editor.table_view.select_keys(selected)
    view = _row(editor, "translateX").editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.setSingleStep(1.0)
    cmds.flushUndo()

    # 各入力経路で現在時刻のキーと未接続値を同時に編集する
    if operation == "direct":
        view.spin_box.setValue(8.0)
        expected = (8.0, 8.0, 8.0, 8.0)
    elif operation == "step":
        view.spin_box.stepUp()
        expected = (6.0, 2.0, 10.0, 4.0)
    else:
        assert editor.controller.align_selected_values(selected)
        expected = (5.0, 1.0, 5.0, 1.0)
    _events()
    paths = tuple(
        f"{node}.{attribute}"
        for node in ("multiA", "multiB")
        for attribute in ("translateX", "translateY")
    )
    assert tuple(cmds.getAttr(path) for path in paths) == expected
    assert cmds.keyframe(
        animated[0], query=True, time=(5, 5), keyframeCount=True
    ) == (1 if auto_key and operation != "align" else 0)
    assert cmds.keyframe(
        animated[1], query=True, time=(5, 5), keyframeCount=True
    ) == int(auto_key)
    for path in ("multiA.translateY", "multiB.translateX"):
        assert not cmds.listConnections(path, source=True)

    # 一回のUndoで新設キーを除去し、通常値と既存キーを復元する
    cmds.undo()
    _events()
    assert tuple(cmds.getAttr(path) for path in paths) == (5.0, 1.0, 9.0, 3.0)
    for path in animated:
        assert cmds.keyframe(path, query=True, keyframeCount=True) == 1
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()
    assert tuple(cmds.getAttr(path) for path in paths) == expected


@pytest.mark.parametrize("auto_key", [False, True])
def test_animated_slider_follows_auto_key_and_groups_drag_undo(
    editor: ChannelBoxWidget, auto_key: bool
) -> None:
    """Slider通知のAuto Key有無を切り替え、一ドラッグを一Undoにする。"""
    cmds.setKeyframe("multiA.gain", time=1, value=2.0)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    editor.table_view.select_keys(_keys(editor, "gain", "translateX"))
    view = _row(editor, "gain").editor
    assert isinstance(view, FloatSliderSpinBox)
    cmds.flushUndo()
    view.slider.sliderPressed.emit()
    for numerator in (3, 7):
        view.slider.setValue(view.slider.maximum() * numerator // 10)
        assert cmds.getAttr("multiA.gain") == float(numerator)
        assert _row(editor, "gain").row.binding.value == float(numerator)
        assert cmds.keyframe(
            "multiA.gain", query=True, time=(5, 5), keyframeCount=True
        ) == int(auto_key)
    view.slider.sliderReleased.emit()
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.gain") == 2.0
    assert cmds.getAttr("multiB.gain") == 0.0
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.getAttr("multiB.translateX") == 9.0
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True) == 1
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("auto_key", [False, True])
def test_animated_bool_input_follows_auto_key_for_changed_targets(
    editor: ChannelBoxWidget, auto_key: bool
) -> None:
    """boolの選択入力もAuto Keyに従い、同値のキー付き対象は変更しない。"""
    cmds.setKeyframe("multiA.visibility", time=1, value=1)
    cmds.setKeyframe("multiA.enabled", time=1, value=0)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    editor.table_view.select_keys(_keys(editor, "visibility", "enabled"))
    view = _row(editor, "visibility").editor
    assert isinstance(view, BoolCheckBox)
    assert view.isEnabled()
    cmds.flushUndo()
    view.click()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(node + ".visibility") is False
        assert cmds.getAttr(node + ".enabled") is False
    assert cmds.keyframe(
        "multiA.visibility", query=True, time=(5, 5), keyframeCount=True
    ) == int(auto_key)
    assert (
        cmds.keyframe(
            "multiA.enabled", query=True, time=(5, 5), keyframeCount=True
        )
        == 0
    )
    assert not cmds.listConnections("multiB.visibility", source=True)
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.visibility") is True
    assert cmds.getAttr("multiB.enabled") is True
    assert (
        cmds.keyframe("multiA.visibility", query=True, keyframeCount=True) == 1
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_time_change_stops_animated_drag_before_a_new_frame(
    editor: ChannelBoxWidget,
) -> None:
    """時刻変更でSliderを確定終了し、押下中の古い移動からキーを打たない。"""
    cmds.setKeyframe("multiA.gain", time=1, value=0.0)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=True)
    _events()
    view = _row(editor, "gain").editor
    assert isinstance(view, FloatSliderSpinBox)
    cmds.flushUndo()
    view.slider.setSliderDown(True)
    view.slider.setValue(view.slider.maximum() * 3 // 10)
    assert editor.controller.value_edit_session.is_editing
    cmds.currentTime(6)
    _events()
    assert not editor.controller.value_edit_session.is_editing
    assert not view.slider.isSliderDown()

    # マウスを離す前の旧操作を送っても、新しい時刻には入力しない
    position = view.slider.rect().topRight()
    qt.QApplication.sendEvent(
        view.slider,
        qt.QtGui.QMouseEvent(
            qt.QEvent.Type.MouseMove,
            qt.QPointF(position),
            qt.QPointF(view.slider.mapToGlobal(position)),
            qt.Qt.MouseButton.NoButton,
            qt.Qt.MouseButton.LeftButton,
            qt.Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert cmds.keyframe("multiA.gain", query=True, timeChange=True) == [
        1.0,
        5.0,
    ]
    assert cmds.getAttr("multiA.gain") == 3.0
    # currentTimeコマンド自身のUndoと、旧時刻の編集Undoを分離する
    cmds.undo()
    _events()
    assert cmds.currentTime(query=True) == 5.0
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True) == 2
    cmds.undo()
    _events()
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True) == 1
    assert cmds.getAttr("multiA.gain") == 0.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize("auto_key", [False, True])
def test_time_change_discards_pending_animated_numeric_input(
    editor: ChannelBoxWidget, multiple: bool, auto_key: bool
) -> None:
    """時刻をまたいだ未確定数値を破棄し、どちらの時刻にも打鍵しない。"""
    cmds.setKeyframe("multiA.gain", time=1, value=0.0)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    names = ("gain", "limited") if multiple else ("gain",)
    editor.table_view.select_keys(_keys(editor, *names))
    cmds.flushUndo()
    if multiple:
        pending = _begin_input(editor, "4", "gain")
    else:
        spin = _spin(editor, "gain")
        spin.setFocus()
        spin.selectAll()
        _key(spin, qt.Qt.Key.Key_4, "4")
        pending = cast(
            Callable[[type[qt.QLineEdit]], list[qt.QLineEdit]],
            getattr(spin, "findChildren"),
        )(qt.QLineEdit)[0]
        assert pending.text() == "4"
    assert pending.isVisible()
    cmds.currentTime(6)
    _events()
    if multiple:
        assert not qt.isValid(pending)
    else:
        assert qt.isValid(pending)
        assert float(pending.text()) == 0.0
        _key(_spin(editor, "gain"), qt.Qt.Key.Key_Return)
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True) == 1
    assert cmds.getAttr("multiA.gain") == 0.0
    assert cmds.getAttr("multiB.gain") == 0.0
    cmds.undo()
    _events()
    assert cmds.currentTime(query=True) == 5.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("auto_key", [False, True])
def test_animated_same_value_and_invalid_batch_create_no_keys(
    editor: ChannelBoxWidget, auto_key: bool
) -> None:
    """同値入力と全件検証で拒否した入力はキーもUndo項目も作らない。"""
    cmds.setKeyframe("multiA.gain", time=1, value=0.0)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    cmds.flushUndo()
    assert not editor.controller.apply_numeric_values(
        _keys(editor, "gain"), 0.0
    )
    with pytest.raises(ValueError):
        editor.controller.apply_numeric_values(
            _keys(editor, "gain", "limited"), 7.0
        )
    assert cmds.getAttr("multiA.gain") == 0.0
    assert cmds.getAttr("multiB.gain") == 0.0
    assert cmds.getAttr("multiA.limited") == 1.0
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True) == 1
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("auto_key", [False, True])
def test_driven_key_input_changes_only_temporary_value(
    editor: ChannelBoxWidget, auto_key: bool
) -> None:
    """SDKは入力を許可し、Auto Keyによらず既存のドライバーキーを維持する。"""
    driver = cmds.createNode("transform", name="sdkDriver")
    cmds.setDrivenKeyframe(
        "multiA.gain", currentDriver=driver + ".translateX", value=1
    )
    _set_value(driver + ".translateX", 10)
    cmds.setDrivenKeyframe(
        "multiA.gain", currentDriver=driver + ".translateX", value=5
    )
    _set_value(driver + ".translateX", 0)
    cmds.select("multiB", "multiA", replace=True)
    cmds.autoKeyframe(state=auto_key)
    _events()
    row = _row(editor, "gain")
    assert row.row.binding.writable_count == 2
    assert row.row.binding.target_states[0].edit_description
    before = cmds.keyframe("multiA.gain", query=True, valueChange=True)
    cmds.flushUndo()

    # 通常値の後続ノードも一緒に編集し、SDKカーブには書き込まない
    editor.controller.apply_numeric_values(_keys(editor, "gain"), 4)
    assert cmds.getAttr("multiA.gain") == 4
    assert cmds.getAttr("multiB.gain") == 4
    assert cmds.keyframe("multiA.gain", query=True, valueChange=True) == before
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.gain") == 1
    assert cmds.getAttr("multiB.gain") == 0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 再入力後もドライバーを動かせばSDKの評価値へ戻る
    editor.controller.apply_numeric_values(_keys(editor, "gain"), 4)
    _set_value(driver + ".translateX", 10)
    assert cmds.getAttr("multiA.gain") == 5
    assert cmds.keyframe("multiA.gain", query=True, valueChange=True) == before


@pytest.mark.parametrize("auto_key", [False, True])
def test_layer_input_uses_native_key_target_and_one_undo(
    editor: ChannelBoxWidget, auto_key: bool
) -> None:
    """Layerの値入力と通常値を同時に編集し、選択レイヤへの保存だけを切り替える。"""
    cmds.setKeyframe("multiA.gain", time=1, value=1)
    layer = cast(
        str, cmds.animLayer("valueEditLayer", attribute="multiA.gain")
    )
    cmds.setKeyframe("multiA.gain", time=1, value=3, animLayer=layer)
    root = cast(str, cmds.animLayer(query=True, root=True))
    cmds.animLayer(root, edit=True, selected=False)
    cmds.animLayer(layer, edit=True, selected=True, preferred=True)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    row = _row(editor, "gain")
    assert row.row.binding.writable_count == 2
    assert layer in row.name_label.toolTip()
    curves = (
        cast(
            list[str] | None,
            cmds.animLayer(layer, query=True, animCurves=True),
        )
        or []
    )
    assert len(curves) == 1
    original = cmds.getAttr("multiA.gain")
    cmds.flushUndo()

    # Mayaが解決する現在レイヤへキーを保存し、合成された入力値を表示する
    editor.controller.apply_numeric_values(_keys(editor, "gain"), 4)
    assert cmds.getAttr("multiA.gain") == 4
    assert cmds.getAttr("multiB.gain") == 4
    assert cmds.keyframe(
        curves[0], query=True, time=(5, 5), keyframeCount=True
    ) == int(auto_key)
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.gain") == original
    assert cmds.getAttr("multiB.gain") == 0
    assert cmds.keyframe(curves[0], query=True, keyframeCount=True) == 1
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("layered", [False, True])
def test_constraint_driven_targets_stay_excluded_from_value_and_key_edits(
    editor: ChannelBoxWidget, layered: bool
) -> None:
    """Layer内に隠れたconstraintも通常接続も対象外とし、基準だけを編集する。"""
    driver = cmds.createNode("transform", name="constraintDriver")
    cmds.pointConstraint(driver, "multiB", maintainOffset=True)
    if layered:
        layer = cast(
            str,
            cmds.animLayer("constrainedLayer", attribute="multiB.translateX"),
        )
        cmds.animLayer(layer, edit=True, selected=True, preferred=True)
    cmds.select("multiB", "multiA", replace=True)
    _events()
    row = _row(editor, "translateX")
    assert row.row.binding.writable_count == 1
    assert row.row.binding.target_states[1].reason
    before = cmds.getAttr("multiB.translateX")
    cmds.autoKeyframe(state=True)
    cmds.flushUndo()
    editor.controller.apply_numeric_values(_keys(editor, "translateX"), 12)
    assert cmds.getAttr("multiB.translateX") == before
    assert cmds.getAttr("multiA.translateX") == 12
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    assert (
        editor.controller.set_keyframes_selected(_keys(editor, "translateX"))
        == 1
    )
    assert not cmds.keyframe(
        "multiB.translateX", query=True, keyframeCount=True
    )


def test_last_selected_node_filters_alignment_from_row_menu(
    editor: ChannelBoxWidget,
) -> None:
    """行メニューの状態別整列は末尾ノードの状態と実値を使う。"""
    _set_value("multiB.gain", 7.0)
    _set_value("multiA.gain", 1.0)
    cmds.setAttr("multiA.gain", keyable=False)
    cmds.setAttr("multiA.gain", channelBox=False)
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    cmds.flushUndo()

    row = _row(editor, "translateX")
    _open_row_menu(row)
    row.align_filtered_actions["keyable"].trigger()
    row.context_menu.close()
    _events()
    assert cmds.getAttr("multiA.gain") == 7.0
    assert cmds.getAttr("multiB.gain") == 7.0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.gain") == 1.0


def test_last_selected_node_is_value_copy_source(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """メニューの選択属性と全属性Copyは末尾ノードから値を取得する。"""
    memory = _MemoryValueClipboard()
    monkeypatch.setattr(editor.controller, "_value_clipboard", memory)
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "translateX"))

    row = _row(editor, "translateX")
    _open_row_menu(row)
    row.copy_selected_values_action.trigger()
    row.context_menu.close()
    transfer = memory.read()
    assert len(transfer.nodes[0].values) == 1
    assert transfer.nodes[0].values[0].value == 9.0

    editor.edit_menu.aboutToShow.emit()
    editor.copy_all_values_action.trigger()
    values = {
        snapshot.path: snapshot.value
        for snapshot in memory.read().nodes[0].values
    }
    assert values["translate.translateX"] == 9.0
    assert values["enabled"] is True


@pytest.mark.parametrize(
    "operation", ["all", "keyable", "selected_single", "selected_multiple"]
)
@pytest.mark.parametrize("auto_key", [False, True])
def test_animated_paste_follows_auto_key_in_one_undo(
    editor: ChannelBoxWidget,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    auto_key: bool,
) -> None:
    """各Paste経路もAuto Keyに従い、接続値と通常値を一Undoにまとめる。"""
    copied = (
        ("gain", "limited") if operation == "selected_multiple" else ("gain",)
    )
    for name in copied:
        _set_value("multiA." + name, 4.0)
    transfer = MayaScalarValueTransfer(
        (
            capture_scalar_node_values(
                "multiA",
                tuple(_row(editor, name).row.attribute for name in copied),
            ),
        )
    )
    monkeypatch.setattr(
        editor.controller, "_value_clipboard", _StaticValueClipboard(transfer)
    )
    _set_value("multiA.gain", 0.0)
    _set_value("multiA.limited", 1.0)
    cmds.setKeyframe("multiA.gain", time=1, value=0.0)
    cmds.currentTime(5)
    cmds.autoKeyframe(state=auto_key)
    _events()
    selected = _keys(editor, "gain", "limited")
    editor.table_view.select_keys(selected)
    editor.edit_menu.aboutToShow.emit()
    cmds.flushUndo()

    # UIのactionから経路を選び、各Paste APIへ編集方針を渡すことを確認する
    if operation.startswith("selected_"):
        editor.paste_selected_values_action.trigger()
    else:
        editor.paste_copied_values_actions[
            "all" if operation == "all" else "keyable"
        ].trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(node + ".gain") == 4.0
        assert cmds.getAttr(node + ".limited") == (
            4.0 if operation.startswith("selected_") else 1.0
        )
    values = cmds.keyframe(
        "multiA.gain", query=True, time=(5, 5), valueChange=True
    )
    assert (values or []) == ([4.0] if auto_key else [])
    assert not cmds.listConnections("multiB.gain", source=True)
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(node + ".gain") == 0.0
        assert cmds.getAttr(node + ".limited") == 1.0
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True) == 1
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
    selection_menus = [
        submenu
        for action in row.context_menu.actions()
        if isinstance(submenu := action.menu(), qt.QMenu)
    ]
    assert [menu.title() for menu in selection_menus] == [
        "キーフレーム",
        "ブレイクダウンフレーム",
        "ミュート",
        "ミュート解除",
        "アニメーションカーブ：コピー",
        "アニメーションカーブ：ペースト",
        "アニメーションカーブ：カット",
        "アニメーションカーブ：削除",
        "アニメーションレイヤ：追加",
        "アニメーションレイヤ：除去",
        "表示ノードの値に揃える",
        "コピー",
        "ペースト",
        "小数点の四捨五入",
        "フリーズ",
        "Step設定",
        "ロック",
        "表示",
    ]
    assert not any(
        action.objectName().startswith("selected_")
        for action in row.context_menu.actions()
    )
    assert [
        (action.text(), action.isSeparator())
        for action in row.context_menu.actions()[:17]
    ] == [
        ("キーフレーム", False),
        ("ブレイクダウンフレーム", False),
        ("ミュート", False),
        ("ミュート解除", False),
        ("", True),
        ("アニメーションカーブ：コピー", False),
        ("アニメーションカーブ：ペースト", False),
        ("アニメーションカーブ：カット", False),
        ("アニメーションカーブ：削除", False),
        ("", True),
        ("アニメーションレイヤ：追加", False),
        ("アニメーションレイヤ：除去", False),
        ("", True),
        ("表示ノードの値に揃える", False),
        ("コピー", False),
        ("ペースト", False),
        ("小数点の四捨五入", False),
    ]
    assert [
        (action.text(), action.isSeparator())
        for action in row.context_menu.actions()[17:]
    ] == [
        ("", True),
        ("フリーズ", False),
        ("", True),
        ("Step設定", False),
        ("", True),
        ("ロック", False),
        ("表示", False),
    ]
    assert [action.text() for action in row.align_menu.actions()] == [
        "選択属性",
        "全て",
        "Keyable + ChannelBox",
        "Keyable",
        "ChannelBox",
        "Hide",
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.keyframe_menu.actions()
    ] == [
        ("選択属性", "set_key_selected"),
        ("全 Keyable", "set_key_all_keyable"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.breakdown_menu.actions()
    ] == [
        ("選択属性", "set_breakdown_selected"),
        ("全 Keyable", "set_breakdown_all_keyable"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.mute_menu.actions()
    ] == [
        ("選択属性", "mute_selected"),
        ("全アニメーション属性", "mute_all_animation"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.unmute_menu.actions()
    ] == [
        ("選択属性", "unmute_selected"),
        ("全アニメーション属性", "unmute_all_animation"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.animation_copy_menu.actions()
    ] == [
        ("選択属性", "animation_copy_selected"),
        ("全アニメーション属性", "animation_copy_all"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.animation_paste_menu.actions()
    ] == [
        ("選択属性", "animation_paste_selected"),
        ("コピー元と同じ属性", "animation_paste_same"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.animation_cut_menu.actions()
    ] == [
        ("選択属性", "animation_cut_selected"),
        ("全アニメーション属性", "animation_cut_all"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.freeze_menu.actions()
    ] == [
        ("移動", "freeze_translate"),
        ("回転", "freeze_rotate"),
        ("スケール", "freeze_scale"),
        ("全て", "freeze_all"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.animation_delete_menu.actions()
    ] == [
        ("選択属性", "animation_delete_selected"),
        ("全アニメーション属性", "animation_delete_all"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.animation_layer_add_menu.actions()
    ] == [
        ("選択属性", "animation_layer_add_selected"),
        ("全 Keyable", "animation_layer_add_all_keyable"),
    ]
    assert [
        (action.text(), action.objectName())
        for action in row.animation_layer_remove_menu.actions()
    ] == [
        ("選択属性", "animation_layer_remove_selected"),
        ("全 Keyable", "animation_layer_remove_all_keyable"),
    ]
    assert row.animation_layer_remove_menu.toolTipsVisible()
    assert "キーも削除" in row.animation_layer_remove_selected_action.toolTip()
    lock_menu, display_menu = selection_menus[-2:]
    assert [action.text() for action in lock_menu.actions()] == [
        "ロック",
        "解除",
    ]
    assert [action.text() for action in display_menu.actions()] == [
        "Keyable",
        "ChannelBox",
        "Hide",
    ]
    assert [action.objectName() for action in lock_menu.actions()] == [
        "selected_lock",
        "selected_unlock",
    ]
    assert [action.objectName() for action in display_menu.actions()] == [
        "selected_keyable",
        "selected_channel_box",
        "selected_hidden",
    ]
    lock_action = next(
        action
        for action in lock_menu.actions()
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


@pytest.mark.parametrize(
    "display_filter, expected",
    (
        ("all", (4.5, False, 3.5, 2)),
        ("visible", (4.5, False, 1.0, 2)),
        ("keyable", (4.5, True, 1.0, 2)),
        ("channel_box", (1.0, False, 1.0, 0)),
        ("hidden", (1.0, True, 3.5, 0)),
    ),
)
def test_align_filtered_values_uses_display_node_and_one_undo(
    editor: ChannelBoxWidget,
    display_filter: ChannelAttributeFilter,
    expected: tuple[float, bool, float, int],
) -> None:
    """非表示行も表示ノードの状態で選び、値とUndoを一括処理する。"""
    _set_value("multiA.gain", 4.5)
    _set_value("multiB.gain", 1.0)
    _set_value("multiA.limited", 3.5)
    _set_value("multiA.mode", 2)
    cmds.setAttr("multiA.enabled", keyable=False)
    cmds.setAttr("multiA.enabled", channelBox=True)
    cmds.setAttr("multiA.limited", keyable=False)
    cmds.setAttr("multiA.limited", channelBox=False)
    cmds.setAttr("multiB.gain", keyable=False)
    cmds.setAttr("multiB.gain", channelBox=False)
    cmds.setAttr("multiB.enabled", keyable=True)
    cmds.setAttr("multiB.limited", keyable=True)
    _events()
    editor.controller.set_attribute_filter("keyable")
    _events()
    assert all(
        row.row.attribute.name not in ("enabled", "limited")
        for row in editor.row_widgets
    )
    row = _row(editor, "translateX")
    _open_row_menu(row)
    assert editor.table_view.selected_keys() == _keys(editor, "translateX")
    assert row.align_filtered_actions[display_filter].isEnabled()
    row.context_menu.close()

    clipboard = qt.QApplication.clipboard()
    saved = _saved_clipboard()
    try:
        clipboard.setText("align clipboard sentinel")
        cmds.flushUndo()
        row.align_filtered_actions[display_filter].trigger()
        _events()
        assert clipboard.text() == "align clipboard sentinel"
        assert (
            cmds.getAttr("multiB.gain"),
            cmds.getAttr("multiB.enabled"),
            cmds.getAttr("multiB.limited"),
            cmds.getAttr("multiB.mode"),
        ) == expected
        assert editor.table_view.selected_keys() == _keys(editor, "translateX")
        cmds.undo()
        _events()
        assert (
            cmds.getAttr("multiB.gain"),
            cmds.getAttr("multiB.enabled"),
            cmds.getAttr("multiB.limited"),
            cmds.getAttr("multiB.mode"),
        ) == (1.0, True, 1.0, 0)
        assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    finally:
        clipboard.setMimeData(saved)


def test_align_menu_is_disabled_for_one_node(
    editor: ChannelBoxWidget,
) -> None:
    """揃える先がない場合はメニューとUndoを増やさない。"""
    cmds.select("multiA", replace=True)
    _events()
    row = _row(editor, "translateX")
    _open_row_menu(row)
    assert not row.align_menu.isEnabled()
    row.context_menu.close()
    cmds.flushUndo()
    assert not editor.controller.align_filtered_values("all")
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_round_menu_uses_current_row_precision_until_refresh(
    editor: ChannelBoxWidget,
) -> None:
    """桁数候補は表示中の行と一致し、更新後にMaya設定へ追従する。"""
    row = _row(editor, "translateX")
    assert row.round_menu is not None
    assert _row(editor, "enabled").round_menu is None
    assert all(not menu.actions() for menu in row.round_scope_menus.values())
    view = row.editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setDecimals(3)
    existed = cmds.optionVar(exists="channelsPrecision")
    previous = (
        cast(int, cmds.optionVar(query="channelsPrecision"))
        if existed
        else None
    )
    try:
        cmds.optionVar(intValue=("channelsPrecision", 15))
        row.round_menu.aboutToShow.emit()
        assert [
            action.text()
            for action in row.round_scope_menus["selected"].actions()
        ] == [
            "0（整数）",
            "0.1",
            "0.12",
            "0.123",
        ]
        editor.refresh()
        _events()
        refreshed = _row(editor, "translateX")
        assert refreshed.round_menu is not None
        assert refreshed.round_decimal_limit() == 15
        refreshed.round_menu.aboutToShow.emit()
        actions = refreshed.round_scope_menus["selected"].actions()
        assert len(actions) == 16
        assert actions[-1].text() == "0.123456789012345"
    finally:
        if existed:
            assert previous is not None
            cmds.optionVar(intValue=("channelsPrecision", previous))
        else:
            cmds.optionVar(remove="channelsPrecision")


def test_round_selected_values_preserves_each_node_and_one_undo(
    editor: ChannelBoxWidget,
) -> None:
    """混在した非数値行を除き、選択数値の各実値を独立に丸める。"""
    before = (1.245, -1.245, 2.345, 3.456)
    for path, value in zip(
        (
            "multiA.translateX",
            "multiB.translateX",
            "multiA.translateY",
            "multiB.translateY",
        ),
        before,
    ):
        _set_value(path, value)
    _events()
    selected = _keys(editor, "translateX", "translateY", "enabled")
    editor.table_view.select_keys(selected)
    row = _row(editor, "translateX")
    view = row.editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setDecimals(3)
    _open_row_menu(row)
    assert editor.table_view.selected_keys() == selected
    row.context_menu.close()
    assert row.round_menu is not None
    row.round_menu.aboutToShow.emit()
    cmds.flushUndo()
    row.round_scope_menus["selected"].actions()[2].trigger()
    _events()
    assert tuple(
        cmds.getAttr(path)
        for path in (
            "multiA.translateX",
            "multiB.translateX",
            "multiA.translateY",
            "multiB.translateY",
        )
    ) == (1.25, -1.25, 2.35, 3.46)
    cmds.undo()
    _events()
    assert (
        tuple(
            cmds.getAttr(path)
            for path in (
                "multiA.translateX",
                "multiB.translateX",
                "multiA.translateY",
                "multiB.translateY",
            )
        )
        == before
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize(
    "scope, rounded",
    (
        ("all", (True, True, True)),
        ("visible", (True, True, False)),
        ("keyable", (True, False, False)),
        ("channel_box", (False, True, False)),
        ("hidden", (False, False, True)),
    ),
)
def test_round_filter_uses_display_node_flags_outside_current_rows(
    editor: ChannelBoxWidget,
    scope: ChannelAttributeFilter,
    rounded: tuple[bool, bool, bool],
) -> None:
    """表示ノードで範囲を選び、隠れた属性も各ノードの値から丸める。"""
    names = ("translateX", "gain", "limited")
    for name, values in zip(
        names, ((1.245, 2.345), (3.245, 4.345), (1.245, 2.345))
    ):
        for node, value in zip(("multiA", "multiB"), values):
            _set_value(f"{node}.{name}", value)
    cmds.setAttr("multiA.gain", keyable=False)
    cmds.setAttr("multiA.gain", channelBox=True)
    cmds.setAttr("multiA.limited", keyable=False)
    cmds.setAttr("multiA.limited", channelBox=False)
    cmds.setAttr("multiB.gain", keyable=False)
    cmds.setAttr("multiB.gain", channelBox=False)
    editor.controller.set_attribute_filter("keyable")
    _events()
    assert "gain" not in {row.row.attribute.name for row in editor.row_widgets}
    row = _row(editor, "translateX")
    assert row.round_menu is not None
    view = row.editor
    assert isinstance(view, FloatValueStepSpinBox)
    view.spin_box.setDecimals(3)
    row.round_menu.aboutToShow.emit()
    cmds.flushUndo()
    row.round_scope_menus[scope].actions()[2].trigger()
    _events()
    for name, original, after, should_round in zip(
        names,
        ((1.245, 2.345), (3.245, 4.345), (1.245, 2.345)),
        ((1.25, 2.35), (3.25, 4.35), (1.25, 2.35)),
        rounded,
    ):
        expected = after if should_round else original
        assert (
            tuple(
                cmds.getAttr(f"{node}.{name}") for node in ("multiA", "multiB")
            )
            == expected
        )
    cmds.undo()
    _events()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_layer_selected_adds_to_all_selected_layers_and_undoes(
    editor: ChannelBoxWidget,
) -> None:
    """非Keyable数値も含む選択属性を全選択ノード・レイヤへ追加する。"""
    for node in ("multiA", "multiB"):
        cmds.setAttr(f"{node}.gain", keyable=False, channelBox=True)
        cmds.addAttr(node, longName="tag", dataType="string")
        cmds.setAttr(f"{node}.tag", channelBox=True)
    first = cast(str, cmds.animLayer("membershipA"))
    second = cast(str, cmds.animLayer("membershipB"))
    root = cast(str, cmds.animLayer(query=True, root=True))
    cmds.animLayer(first, edit=True, selected=False)
    cmds.animLayer(second, edit=True, selected=False)
    cmds.animLayer(root, edit=True, selected=True)
    editor.refresh()
    _events()
    row = _row(editor, "gain")
    _open_row_menu(row)
    assert not row.animation_layer_add_menu.isEnabled()
    row.context_menu.close()

    cmds.animLayer(first, edit=True, selected=True)
    cmds.animLayer(second, edit=True, selected=True)
    editor.refresh()
    _events()
    editor.table_view.select_keys(_keys(editor, "translateX", "gain", "tag"))
    row = _row(editor, "gain")
    _open_row_menu(row)
    assert row.animation_layer_add_menu.isEnabled()
    row.context_menu.close()
    cmds.flushUndo()

    row.animation_layer_add_selected_action.trigger()
    _events()
    expected = {
        f"{node}.{attribute}"
        for node in ("multiA", "multiB")
        for attribute in ("translateX", "gain")
    }
    for layer in (first, second):
        assert _animation_layer_attributes(layer) == expected
    assert not editor.message_label.isVisible()
    _row(editor, "gain").animation_layer_add_selected_action.trigger()
    _events()
    cmds.undo()
    _events()
    for layer in (first, second):
        assert not _animation_layer_attributes(layer)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_layer_all_keyable_uses_each_node_flags(
    editor: ChannelBoxWidget,
) -> None:
    """全Keyableは画面の選択・フィルターによらずノード別フラグを使う。"""
    cmds.setAttr("multiA.gain", keyable=False, channelBox=True)
    layer = cast(str, cmds.animLayer("keyableLayer"))
    cmds.animLayer(layer, edit=True, selected=True)
    editor.controller.set_attribute_filter("channel_box")
    _events()
    row = _row(editor, "gain")
    assert "translateX" not in {
        item.row.attribute.name for item in editor.row_widgets
    }
    cmds.flushUndo()

    row.animation_layer_add_all_keyable_action.trigger()
    _events()
    members = _animation_layer_attributes(layer)
    assert "multiB.gain" in members
    assert "multiA.gain" not in members
    assert "multiA.translateX" in members
    assert "multiB.translateX" in members
    cmds.undo()
    _events()
    assert not _animation_layer_attributes(layer)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # 非Keyableでも明示登録した属性は全Keyableの除去では残す
    for name in ("multiA.gain", "multiB.gain", "multiA.translateX"):
        cmds.animLayer(layer, edit=True, attribute=name)
    _events()
    cmds.flushUndo()
    _row(editor, "gain").animation_layer_remove_all_keyable_action.trigger()
    _events()
    assert _animation_layer_attributes(layer) == {"multiA.gain"}
    cmds.undo()
    _events()
    assert _animation_layer_attributes(layer) == {
        "multiA.gain",
        "multiB.gain",
        "multiA.translateX",
    }
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_layer_remove_deletes_layer_keys_and_undo_restores(
    editor: ChannelBoxWidget,
) -> None:
    """選択レイヤからの除去はそのレイヤのキーも失わせUndoで戻す。"""
    cmds.setKeyframe("multiA.translateX", time=1, value=5)
    layer = cast(str, cmds.animLayer("keyedLayer"))
    cmds.animLayer(layer, edit=True, attribute="multiA.translateX")
    cmds.setKeyframe("multiA.translateX", time=5, value=11, animLayer=layer)
    cmds.animLayer(layer, edit=True, selected=True)
    editor.refresh()
    _events()
    curves = cast(
        list[str] | None, cmds.animLayer(layer, query=True, animCurves=True)
    )
    assert curves
    assert any(
        cmds.keyframe(curve, query=True, time=(5, 5), keyframeCount=True)
        for curve in curves
    )
    cmds.flushUndo()

    _row(editor, "translateX").animation_layer_remove_selected_action.trigger()
    _events()
    assert "multiA.translateX" not in _animation_layer_attributes(layer)
    assert (
        cmds.keyframe(
            "multiA.translateX", query=True, time=(1, 1), keyframeCount=True
        )
        == 1
    )
    assert not cmds.keyframe(
        "multiA.translateX", query=True, time=(5, 5), keyframeCount=True
    )
    cmds.undo()
    _events()
    assert "multiA.translateX" in _animation_layer_attributes(layer)
    assert any(
        cmds.keyframe(curve, query=True, time=(5, 5), keyframeCount=True)
        for curve in curves
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize(
    ("component", "expected"),
    (
        ("translate", (0.0, 45.0, 2.0)),
        ("rotate", (3.0, 0.0, 2.0)),
        ("scale", (3.0, 45.0, 1.0)),
        ("all", (0.0, 0.0, 1.0)),
    ),
)
def test_freeze_transforms_preserves_shape_and_undoes_once(
    editor: ChannelBoxWidget,
    component: Literal["translate", "rotate", "scale", "all"],
    expected: tuple[float, float, float],
) -> None:
    """指定成分だけフリーズし、形状の配置を保って一度のUndoで戻す。"""
    cube = cast(list[str], cmds.polyCube(name="freezeCube"))[0]
    _set_value(f"{cube}.translateX", 3.0)
    _set_value(f"{cube}.rotateY", 45.0)
    _set_value(f"{cube}.scaleX", 2.0)
    before = tuple(
        float(value)
        for value in cmds.pointPosition(f"{cube}.vtx[0]", world=True)
    )
    cmds.select(cube, replace=True)
    editor.refresh()
    row = _row(editor, "translateX")
    actions = {
        "translate": row.freeze_translate_action,
        "rotate": row.freeze_rotate_action,
        "scale": row.freeze_scale_action,
        "all": row.freeze_all_action,
    }
    cmds.flushUndo()

    actions[component].trigger()
    _events()
    for attribute, value in zip(("translateX", "rotateY", "scaleX"), expected):
        assert isclose(cmds.getAttr(f"{cube}.{attribute}"), value)
    after = tuple(
        float(value)
        for value in cmds.pointPosition(f"{cube}.vtx[0]", world=True)
    )
    assert all(isclose(a, b, abs_tol=1e-5) for a, b in zip(after, before))
    assert not editor.message_label.isVisible()

    cmds.undo()
    _events()
    for attribute, value in (
        ("translateX", 3.0),
        ("rotateY", 45.0),
        ("scaleX", 2.0),
    ):
        assert isclose(cmds.getAttr(f"{cube}.{attribute}"), value)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_freeze_menu_uses_base_transform_and_skips_other_node_types(
    editor: ChannelBoxWidget,
) -> None:
    """基準がtransform系の時だけ表示し、混合選択の非transformを除く。"""
    other = cmds.createNode("network", name="freezeNetwork")
    cmds.addAttr(
        other,
        longName="gain",
        attributeType="double",
        defaultValue=7.0,
        keyable=True,
    )
    cmds.select("multiA", other, replace=True)
    editor.refresh()
    row = _row(editor, "gain")
    _open_row_menu(row)
    assert not row.freeze_menu.menuAction().isVisible()
    assert not row.freeze_separator_action.isVisible()
    actions = row.context_menu.actions()
    following = actions[actions.index(row.freeze_menu.menuAction()) + 1]
    assert following.isSeparator()
    assert following.isVisible()
    row.context_menu.close()

    cmds.select(other, "multiA", replace=True)
    editor.refresh()
    row = _row(editor, "translateX")
    _open_row_menu(row)
    assert row.freeze_menu.menuAction().isVisible()
    assert row.freeze_separator_action.isVisible()
    assert row.freeze_translate_action.isEnabled()
    row.context_menu.close()
    cmds.flushUndo()
    row.freeze_translate_action.trigger()
    _events()
    assert cmds.getAttr("multiA.translateX") == 0.0
    assert cmds.getAttr(f"{other}.gain") == 7.0
    cmds.undo()
    _events()
    assert cmds.getAttr("multiA.translateX") == 5.0
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("transform_reference", (True, False))
def test_freeze_separator_tracks_regenerated_qt_action(
    editor: ChannelBoxWidget, transform_reference: bool
) -> None:
    """Qtが区切りを再生成しても現行メニューの表示状態を更新する。"""
    if transform_reference:
        row = _row(editor, "translateX")
    else:
        other = cmds.createNode("network", name="freezeMenuNetwork")
        cmds.addAttr(
            other, longName="gain", attributeType="double", keyable=True
        )
        cmds.select("multiA", other, replace=True)
        editor.refresh()
        row = _row(editor, "gain")

    menu = row.context_menu
    old_separator = row.freeze_separator_action
    menu.removeAction(old_separator)
    old_separator.deleteLater()
    qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)
    assert not qt.isValid(old_separator)
    with pytest.raises(RuntimeError):
        _ = row.freeze_separator_action

    replacement = menu.insertSeparator(row.freeze_menu.menuAction())
    actions = menu.actions()
    freeze_index = actions.index(row.freeze_menu.menuAction())
    assert actions[freeze_index - 1] == replacement
    assert row.freeze_separator_action == replacement
    replacement.setVisible(not transform_reference)
    _show_row_menu(row)
    assert replacement.isVisible() is transform_reference
    assert row.freeze_menu.menuAction().isVisible() is transform_reference


def test_freeze_joint_keeps_translation_and_disables_move(
    editor: ChannelBoxWidget,
) -> None:
    """jointのみでは移動を無効にし、全ては回転・スケールへ適用する。"""
    cmds.select(clear=True)
    joint = cast(str, cmds.joint(name="freezeJoint", position=(1, 0, 0)))
    _set_value(f"{joint}.rotateY", 45.0)
    _set_value(f"{joint}.scaleX", 2.0)
    cmds.select(joint, replace=True)
    editor.refresh()
    row = _row(editor, "translateX")
    _open_row_menu(row)
    assert row.freeze_menu.menuAction().isVisible()
    assert not row.freeze_translate_action.isEnabled()
    row.context_menu.close()
    cmds.flushUndo()

    row.freeze_all_action.trigger()
    _events()
    assert isclose(cmds.getAttr(f"{joint}.translateX"), 1.0)
    assert isclose(cmds.getAttr(f"{joint}.rotateY"), 0.0)
    assert isclose(cmds.getAttr(f"{joint}.scaleX"), 1.0)
    assert isclose(cmds.getAttr(f"{joint}.jointOrientY"), 45.0)
    cmds.undo()
    _events()
    assert isclose(cmds.getAttr(f"{joint}.rotateY"), 45.0)
    assert isclose(cmds.getAttr(f"{joint}.scaleX"), 2.0)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_freeze_reports_maya_error_without_removing_animation(
    editor: ChannelBoxWidget,
) -> None:
    """キー付き成分はMayaの拒否を表示し、入力カーブを保持する。"""
    cmds.setKeyframe("multiA.translateX", time=1, value=5)
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "translateX").freeze_translate_action.trigger()
    _events()
    assert cmds.keyframe("multiA.translateX", query=True, keyframeCount=True)
    assert editor.message_label.isVisible()
    assert "Freeze Transform" in editor.message_label.text()


@pytest.mark.parametrize("breakdown", (False, True))
def test_set_key_all_keyable_uses_each_selected_node(
    editor: ChannelBoxWidget, breakdown: bool
) -> None:
    """全Keyableは画面の行選択に依存せず各ノード自身へ指定種別を打つ。"""
    for node in ("multiA", "multiB"):
        cmds.addAttr(
            node,
            longName="hiddenCount",
            attributeType="long",
            keyable=True,
        )
    cmds.setAttr("multiA.translateX", keyable=False, channelBox=True)
    cmds.setAttr("multiB.translateX", lock=True)
    cmds.currentTime(7)
    _events()
    editor.controller.set_attribute_filter("keyable")
    editor.table_view.select_keys(_keys(editor, "translateY"))
    assert not any(
        row.row.attribute.name == "hiddenCount" for row in editor.row_widgets
    )
    cmds.flushUndo()

    row = _row(editor, "translateY")
    action = (
        row.set_breakdown_all_keyable_action
        if breakdown
        else row.set_key_all_keyable_action
    )
    action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        for attribute in ("translateY", "hiddenCount"):
            assert (
                cmds.keyframe(
                    f"{node}.{attribute}",
                    query=True,
                    time=(7, 7),
                    keyframeCount=True,
                )
                == 1
            )
            assert _has_breakdown(f"{node}.{attribute}", 7) is breakdown
    for node in ("multiA", "multiB"):
        assert not cmds.keyframe(
            f"{node}.translateX",
            query=True,
            keyframeCount=True,
        )
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    assert not cmds.keyframe(
        "multiA.hiddenCount", query=True, keyframeCount=True
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("breakdown", (False, True))
def test_set_key_selected_skips_unavailable_plugs_silently(
    editor: ChannelBoxWidget, breakdown: bool
) -> None:
    """選択属性は指定種別で、非Keyableも対象にし不可属性は静かに除外する。"""
    for node in ("multiA", "multiB"):
        cmds.addAttr(node, longName="note", dataType="string")
        cmds.setAttr(f"{node}.note", "memo", type="string")
        cmds.setAttr(f"{node}.note", channelBox=True)
    cmds.setAttr("multiA.translateX", keyable=False, channelBox=True)
    cmds.setAttr("multiB.translateX", lock=True)
    driver = cmds.createNode("transform", name="driver")
    cmds.connectAttr(f"{driver}.translateX", "multiA.translateY")
    cmds.currentTime(7)
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    _events()
    selected = _keys(editor, "translateX", "translateY", "note")
    editor.table_view.select_keys(selected)
    cmds.flushUndo()

    row = _row(editor, "translateX")
    action = (
        row.set_breakdown_selected_action
        if breakdown
        else row.set_key_selected_action
    )
    action.trigger()
    _events()
    for node, attribute in (
        ("multiA", "translateX"),
        ("multiB", "translateY"),
    ):
        assert (
            cmds.keyframe(
                f"{node}.{attribute}",
                query=True,
                time=(7, 7),
                keyframeCount=True,
            )
            == 1
        )
        assert _has_breakdown(f"{node}.{attribute}", 7) is breakdown
    for node, attribute in (
        ("multiB", "translateX"),
        ("multiA", "translateY"),
        ("multiA", "note"),
        ("multiB", "note"),
    ):
        assert not cmds.keyframe(
            f"{node}.{attribute}", query=True, keyframeCount=True
        )
    assert cmds.listConnections(
        "multiA.translateY", source=True, destination=False, plugs=True
    ) == ["driver.translateX"]
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    assert not cmds.keyframe(
        "multiA.translateX", query=True, keyframeCount=True
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("breakdown", (False, True))
def test_set_key_selected_uses_active_animation_layer(
    editor: ChannelBoxWidget, breakdown: bool
) -> None:
    """選択属性の指定種別は現在選択中のAnimation Layerへ設定する。"""
    layer = cast(str, cmds.animLayer("keyLayer"))
    cmds.animLayer(layer, edit=True, attribute="multiA.translateX")
    cmds.animLayer(layer, edit=True, selected=True)
    cmds.currentTime(7)
    editor.refresh()
    cmds.flushUndo()

    row = _row(editor, "translateX")
    action = (
        row.set_breakdown_selected_action
        if breakdown
        else row.set_key_selected_action
    )
    action.trigger()
    _events()
    curves = (
        cast(
            list[str] | None,
            cmds.animLayer(layer, query=True, animCurves=True),
        )
        or ()
    )
    assert curves
    assert any(
        cmds.keyframe(curve, query=True, time=(7, 7), keyframeCount=True) == 1
        for curve in curves
    )
    assert any(_has_breakdown(curve, 7) is breakdown for curve in curves)
    cmds.undo()
    _events()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("breakdown", (False, True))
def test_set_key_selected_with_no_keyable_targets_is_noop(
    editor: ChannelBoxWidget, breakdown: bool
) -> None:
    """キー不可の選択属性だけなら両種別とも通知やUndo項目を作らない。"""
    for node in ("multiA", "multiB"):
        cmds.setAttr(f"{node}.translateX", lock=True)
    _events()
    cmds.flushUndo()

    row = _row(editor, "translateX")
    action = (
        row.set_breakdown_selected_action
        if breakdown
        else row.set_key_selected_action
    )
    action.trigger()
    _events()
    assert not editor.message_label.isVisible()
    for node in ("multiA", "multiB"):
        assert not cmds.keyframe(
            f"{node}.translateX", query=True, keyframeCount=True
        )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_set_key_and_breakdown_convert_existing_key(
    editor: ChannelBoxWidget,
) -> None:
    """現在時刻の既存キーを指定種別へ切り替え、各操作をUndoできる。"""
    cmds.currentTime(7)
    cmds.setKeyframe("multiA.translateX")
    cmds.setAttr("multiB.translateX", lock=True)
    _events()
    cmds.flushUndo()

    _row(editor, "translateX").set_breakdown_selected_action.trigger()
    assert _has_breakdown("multiA.translateX", 7)
    assert cmds.keyframe(
        "multiA.translateX", query=True, time=(7, 7), valueChange=True
    ) == [5.0]
    assert (
        cmds.keyframe("multiA.translateX", query=True, keyframeCount=True) == 1
    )
    cmds.undo()
    _events()
    assert not _has_breakdown("multiA.translateX", 7)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    cmds.setKeyframe("multiA.translateX", breakdown=True)
    cmds.flushUndo()
    _row(editor, "translateX").set_key_selected_action.trigger()
    assert not _has_breakdown("multiA.translateX", 7)
    cmds.undo()
    _events()
    assert _has_breakdown("multiA.translateX", 7)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("muted", (True, False))
def test_mute_selected_includes_hidden_attributes_and_undoes_together(
    editor: ChannelBoxWidget, muted: bool
) -> None:
    """選択属性はHideでも全選択ノードへ適用し、未接続行を静かに除外する。"""
    for node in ("multiA", "multiB"):
        cmds.setKeyframe(f"{node}.translateX", time=1)
        cmds.setAttr(f"{node}.translateX", keyable=False, channelBox=False)
    if not muted:
        cmds.mute("multiA.translateX", "multiB.translateX")
    editor.controller.set_attribute_filter("all")
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    cmds.flushUndo()

    row = _row(editor, "translateX")
    action = row.mute_selected_action if muted else row.unmute_selected_action
    action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.mute(f"{node}.translateX", query=True) is muted
        assert not cmds.listConnections(
            f"{node}.translateY", source=True, destination=False, type="mute"
        )
    assert (
        _row(editor, "translateX").input_indicator.input_state == "muted"
    ) is muted
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.mute(f"{node}.translateX", query=True) is not muted
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


@pytest.mark.parametrize("muted", (True, False))
def test_mute_all_uses_visible_flags_independent_of_filter(
    editor: ChannelBoxWidget, muted: bool
) -> None:
    """全アニメーション属性は各ノードの表示フラグで選び、Hideは残す。"""
    for node in ("multiA", "multiB"):
        for attribute in ("translateX", "translateY", "translateZ"):
            cmds.setKeyframe(f"{node}.{attribute}", time=1)
        cmds.setAttr(f"{node}.translateY", keyable=False, channelBox=True)
        cmds.setAttr(f"{node}.translateZ", keyable=False, channelBox=False)
    if not muted:
        cmds.mute(
            *(
                f"{node}.{attribute}"
                for node in ("multiA", "multiB")
                for attribute in ("translateX", "translateY", "translateZ")
            )
        )
    editor.controller.set_attribute_filter("keyable")
    assert not any(
        row.row.attribute.name in ("translateY", "translateZ")
        for row in editor.row_widgets
    )
    cmds.flushUndo()

    row = _row(editor, "translateX")
    action = (
        row.mute_all_animation_action
        if muted
        else row.unmute_all_animation_action
    )
    action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.mute(f"{node}.translateX", query=True) is muted
        assert cmds.mute(f"{node}.translateY", query=True) is muted
        assert cmds.mute(f"{node}.translateZ", query=True) is not muted
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.mute(f"{node}.translateX", query=True) is not muted
        assert cmds.mute(f"{node}.translateY", query=True) is not muted
        assert cmds.mute(f"{node}.translateZ", query=True) is not muted
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mute_all_without_connections_is_noop(
    editor: ChannelBoxWidget,
) -> None:
    """未接続属性しかない全操作ではmuteノードもUndo項目も作らない。"""
    cmds.flushUndo()
    _row(editor, "translateX").mute_all_animation_action.trigger()
    _events()
    assert not cmds.ls(type="mute")
    assert not editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_mute_all_covers_visible_noncurve_inputs(
    editor: ChannelBoxWidget,
) -> None:
    """Maya標準同様、表示中なら通常接続とExpressionもミュートする。"""
    driver = cmds.createNode("transform", name="muteDriver")
    cmds.connectAttr(f"{driver}.translateX", "multiA.rotateX")
    cmds.expression(string=f"multiB.rotateX = {driver}.translateY * 2;")
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "rotateX").mute_all_animation_action.trigger()
    _events()
    assert cmds.mute("multiA.rotateX", query=True) is True
    assert cmds.mute("multiB.rotateX", query=True) is True
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    assert cmds.listConnections(
        "multiA.rotateX",
        source=True,
        destination=False,
        plugs=True,
        skipConversionNodes=True,
    ) == [f"{driver}.translateX"]
    assert cmds.mute("multiB.rotateX", query=True) is False
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_unmute_selected_preserves_animated_mute_node(
    editor: ChannelBoxWidget,
) -> None:
    """ミュート状態にキーがある場合は解除してもそのキーを削除しない。"""
    cmds.setKeyframe("multiA.translateX", time=1)
    mute_node = cmds.mute("multiA.translateX")[0]
    cmds.setKeyframe(f"{mute_node}.mute", time=1, value=1)
    cmds.setKeyframe(f"{mute_node}.mute", time=10, value=1)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "translateX").unmute_selected_action.trigger()
    _events()
    assert cmds.mute("multiA.translateX", query=True) is False
    assert cmds.objExists(mute_node)
    assert (
        cmds.keyframe(f"{mute_node}.mute", query=True, keyframeCount=True) == 2
    )
    cmds.undo()
    _events()
    assert cmds.mute("multiA.translateX", query=True) is True
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_cut_selected_updates_both_clipboards_and_undoes_once(
    editor: ChannelBoxWidget,
) -> None:
    """選択属性をカットし、Maya標準と画面の貼り付けへ渡してUndoする。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    for time, value in ((1, 2), (10, 5)):
        cmds.setKeyframe("multiA.translateX", time=time, value=value)
    cmds.setKeyframe("multiA.translateY", time=1, value=8)
    cmds.flushUndo()

    _row(editor, "translateX").animation_cut_selected_action.trigger()
    _events()
    assert not cmds.keyframe(
        "multiA.translateX", query=True, keyframeCount=True
    )
    assert cmds.keyframe("multiA.translateY", query=True, keyframeCount=True)
    assert editor.controller.can_paste_animation_curves()
    assert not editor.message_label.isVisible()
    _row(editor, "translateX").animation_cut_selected_action.trigger()
    _events()
    cmds.undo()
    _events()
    assert (
        cmds.keyframe("multiA.translateX", query=True, keyframeCount=True) == 2
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.redo()
    _events()

    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    assert (
        cmds.pasteKey(
            "multiB.translateY",
            clipboard="anim",
            animation="objects",
            time=(20, 20),
            option="insert",
        )
        == 1
    )
    assert cmds.keyframe("multiB.translateY", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]
    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    assert cmds.keyframe("multiB.translateX", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]


def test_animation_curve_cut_all_uses_visible_flags_and_preserves_noop_copy(
    editor: ChannelBoxWidget,
) -> None:
    """全属性カットは表示フラグに従い、対象なしならコピーを保持する。"""
    cmds.select("multiA", replace=True)
    for attribute in ("translateX", "translateY", "translateZ"):
        cmds.setKeyframe(f"multiA.{attribute}", time=1, value=2)
    cmds.setAttr("multiA.translateY", keyable=False, channelBox=True)
    cmds.setAttr("multiA.translateZ", keyable=False, channelBox=False)
    editor.refresh()
    editor.controller.set_attribute_filter("keyable")
    cmds.flushUndo()

    _row(editor, "translateX").animation_cut_all_action.trigger()
    _events()
    for attribute in ("translateX", "translateY"):
        assert not cmds.keyframe(
            f"multiA.{attribute}", query=True, keyframeCount=True
        )
    assert cmds.keyframe("multiA.translateZ", query=True, keyframeCount=True)
    cmds.flushUndo()
    _row(editor, "translateX").animation_cut_all_action.trigger()
    _events()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    for attribute in ("translateX", "translateY"):
        assert cmds.keyframe(
            f"multiB.{attribute}", query=True, keyframeCount=True
        )
    assert not cmds.keyframe(
        "multiB.translateZ", query=True, keyframeCount=True
    )


def test_animation_curve_cut_selected_includes_other_type_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """異なる型の同じ正式pathもコピーと削除の同一対象にする。"""
    cmds.addAttr(
        "multiA", longName="transfer", attributeType="double", keyable=True
    )
    cmds.addAttr(
        "multiB", longName="transfer", attributeType="bool", keyable=True
    )
    for node in ("multiA", "multiB"):
        cmds.setKeyframe(f"{node}.transfer", time=1, value=1)
    editor.refresh()
    row = _row(editor, "transfer")
    assert len(row.row.target_names) == 1
    cmds.flushUndo()

    row.animation_cut_selected_action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert not cmds.keyframe(
            f"{node}.transfer", query=True, keyframeCount=True
        )
    cmds.currentTime(20)
    _row(editor, "transfer").animation_paste_same_action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.keyframe(
            f"{node}.transfer", query=True, timeChange=True
        ) == [20.0]


def test_animation_curve_cut_skips_shared_curve_and_keeps_copy_aligned(
    editor: ChannelBoxWidget,
) -> None:
    """共有曲線を除外し、削除した独立曲線だけを貼り付け対象にする。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=2)
    cmds.setKeyframe("multiA.translateY", time=1, value=3)
    curves = cmds.keyframe("multiA.translateX", query=True, name=True)
    assert isinstance(curves, list) and len(curves) == 1
    cmds.connectAttr(f"{curves[0]}.output", "multiB.translateX", force=True)
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    cmds.flushUndo()

    _row(editor, "translateX").animation_cut_selected_action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.keyframe(
            f"{node}.translateX", query=True, keyframeCount=True
        )
    assert not cmds.keyframe(
        "multiA.translateY", query=True, keyframeCount=True
    )
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    _row(editor, "translateY").animation_paste_same_action.trigger()
    _events()
    assert cmds.keyframe("multiB.translateY", query=True, timeChange=True) == [
        20.0
    ]


def test_animation_curve_delete_selected_includes_hidden_and_undoes_once(
    editor: ChannelBoxWidget,
) -> None:
    """選択属性の全キーをHide込みで削除し、全ノードを一度にUndoする。"""
    for node in ("multiA", "multiB"):
        for attribute in ("translateX", "translateY", "translateZ"):
            cmds.setKeyframe(f"{node}.{attribute}", time=1, value=1)
            cmds.setKeyframe(f"{node}.{attribute}", time=10, value=4)
        cmds.setAttr(f"{node}.translateZ", keyable=False, channelBox=False)
    cmds.currentTime(5)
    before = cmds.getAttr("multiA.translateX")
    editor.refresh()
    editor.controller.set_attribute_filter("all")
    editor.table_view.select_keys(_keys(editor, "translateX", "translateZ"))
    cmds.flushUndo()

    _row(editor, "translateX").animation_delete_selected_action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        for attribute in ("translateX", "translateZ"):
            assert not cmds.keyframe(
                f"{node}.{attribute}", query=True, keyframeCount=True
            )
        assert (
            cmds.keyframe(f"{node}.translateY", query=True, keyframeCount=True)
            == 2
        )
    assert isclose(cmds.getAttr("multiA.translateX"), before)
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    for node in ("multiA", "multiB"):
        for attribute in ("translateX", "translateZ"):
            assert (
                cmds.keyframe(
                    f"{node}.{attribute}", query=True, keyframeCount=True
                )
                == 2
            )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_delete_all_uses_visible_flags_not_filter(
    editor: ChannelBoxWidget,
) -> None:
    """全属性削除は各ノードの表示フラグで選び、画面絞込とHideを区別する。"""
    cmds.select("multiA", replace=True)
    for attribute in ("translateX", "translateY", "translateZ"):
        cmds.setKeyframe(f"multiA.{attribute}", time=1, value=2)
    cmds.setAttr("multiA.translateY", keyable=False, channelBox=True)
    cmds.setAttr("multiA.translateZ", keyable=False, channelBox=False)
    driver = cmds.createNode("transform", name="deleteDriver")
    cmds.connectAttr(f"{driver}.translateX", "multiA.rotateX")
    cmds.select("multiA", replace=True)
    editor.refresh()
    editor.controller.set_attribute_filter("keyable")
    assert not any(
        row.row.attribute.name in ("translateY", "translateZ")
        for row in editor.row_widgets
    )
    cmds.flushUndo()

    _row(editor, "translateX").animation_delete_all_action.trigger()
    _events()
    for attribute in ("translateX", "translateY"):
        assert not cmds.keyframe(
            f"multiA.{attribute}", query=True, keyframeCount=True
        )
    assert cmds.keyframe("multiA.translateZ", query=True, keyframeCount=True)
    assert cmds.listConnections(
        "multiA.rotateX",
        source=True,
        destination=False,
        plugs=True,
        skipConversionNodes=True,
    ) == [f"{driver}.translateX"]
    cmds.undo()
    _events()
    for attribute in ("translateX", "translateY"):
        assert (
            cmds.keyframe(
                f"multiA.{attribute}", query=True, keyframeCount=True
            )
            == 1
        )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_delete_selected_keeps_copied_keys(
    editor: ChannelBoxWidget,
) -> None:
    """削除してもコピー済みカーブを別ノードへ貼り付けられる。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=2)
    cmds.setKeyframe("multiA.translateX", time=10, value=5)
    row = _row(editor, "translateX")
    row.animation_copy_selected_action.trigger()
    row.animation_delete_selected_action.trigger()
    _events()
    assert not cmds.keyframe(
        "multiA.translateX", query=True, keyframeCount=True
    )
    assert editor.controller.can_paste_animation_curves()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    assert (
        cmds.pasteKey(
            "multiB.translateY",
            clipboard="anim",
            animation="objects",
            time=(20, 20),
            option="insert",
        )
        == 1
    )
    assert cmds.keyframe("multiB.translateY", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]

    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    assert cmds.keyframe("multiB.translateX", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]


def test_animation_curve_delete_skips_shared_curve_without_undo(
    editor: ChannelBoxWidget,
) -> None:
    """同じ曲線が別属性も駆動する場合は何も変更しない。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=2)
    cmds.setKeyframe("multiA.translateX", time=10, value=5)
    curves = cmds.keyframe("multiA.translateX", query=True, name=True)
    assert isinstance(curves, list) and len(curves) == 1
    cmds.connectAttr(f"{curves[0]}.output", "multiB.translateX", force=True)
    cmds.flushUndo()

    _row(editor, "translateX").animation_delete_selected_action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert (
            cmds.keyframe(f"{node}.translateX", query=True, keyframeCount=True)
            == 2
        )
    assert not editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_delete_selected_covers_muted_and_driven_keys(
    editor: ChannelBoxWidget,
) -> None:
    """Maya標準同様にミュート中とDriven Keyの全曲線も削除する。"""
    cmds.setKeyframe("multiA.translateX", time=1, value=2)
    mute_node = cmds.mute("multiA.translateX")[0]
    driver = cmds.createNode("transform", name="deleteDriver")
    _set_value(f"{driver}.translateX", 0.0)
    cmds.setDrivenKeyframe(
        "multiA.gain", currentDriver=f"{driver}.translateX", value=1
    )
    _set_value(f"{driver}.translateX", 2.0)
    cmds.setDrivenKeyframe(
        "multiA.gain", currentDriver=f"{driver}.translateX", value=3
    )
    cmds.select("multiA", replace=True)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "translateX", "gain"))
    cmds.flushUndo()

    _row(editor, "translateX").animation_delete_selected_action.trigger()
    _events()
    assert not cmds.keyframe(
        "multiA.translateX", query=True, keyframeCount=True
    )
    assert not cmds.keyframe("multiA.gain", query=True, keyframeCount=True)
    assert not cmds.objExists(mute_node)
    cmds.undo()
    _events()
    assert cmds.keyframe("multiA.translateX", query=True, keyframeCount=True)
    assert cmds.keyframe("multiA.gain", query=True, keyframeCount=True)
    assert cmds.objExists(mute_node)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_delete_selected_includes_other_type_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """値編集から外れた同名異種型ノードの曲線も削除する。"""
    cmds.addAttr(
        "multiA", longName="transfer", attributeType="double", keyable=True
    )
    cmds.addAttr(
        "multiB", longName="transfer", attributeType="bool", keyable=True
    )
    for node in ("multiA", "multiB"):
        cmds.setKeyframe(f"{node}.transfer", time=1, value=1)
    editor.refresh()
    row = _row(editor, "transfer")
    assert len(row.row.target_names) == 1

    row.animation_delete_selected_action.trigger()
    _events()
    for node in ("multiA", "multiB"):
        assert not cmds.keyframe(
            f"{node}.transfer", query=True, keyframeCount=True
        )


def test_animation_curve_copy_selected_and_paste_same_attributes(
    editor: ChannelBoxWidget,
) -> None:
    """選択属性の全キーを現在時刻へ接続挿入し、コピーと貼付のUndoを分ける。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=1)
    cmds.setKeyframe("multiA.translateX", time=10, value=4)
    cmds.flushUndo()

    row = _row(editor, "translateX")
    row.animation_copy_selected_action.trigger()
    _events()
    assert (
        editor.controller.can_paste_animation_curves()
    ), editor.message_label.text()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "translateY").animation_paste_same_action.trigger()
    _events()
    assert cmds.keyframe("multiB.translateX", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]
    assert cmds.keyframe(
        "multiB.translateX", query=True, valueChange=True
    ) == [1.0, 4.0]
    assert not cmds.keyframe(
        "multiB.translateY", query=True, keyframeCount=True
    )
    assert not editor.message_label.isVisible()
    cmds.undo()
    _events()
    assert not cmds.keyframe(
        "multiB.translateX", query=True, keyframeCount=True
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_copy_all_uses_visible_flags_not_filter(
    editor: ChannelBoxWidget,
) -> None:
    """全カーブコピーは各ノードの表示属性を扱い、Hideと画面の絞込を分ける。"""
    cmds.select("multiA", replace=True)
    for attribute in ("translateX", "translateY", "translateZ"):
        cmds.setKeyframe(f"multiA.{attribute}", time=1, value=2)
    cmds.setAttr("multiA.translateY", keyable=False, channelBox=True)
    cmds.setAttr("multiA.translateZ", keyable=False, channelBox=False)
    editor.refresh()
    editor.controller.set_attribute_filter("keyable")
    assert not any(
        row.row.attribute.name in ("translateY", "translateZ")
        for row in editor.row_widgets
    )

    _row(editor, "translateX").animation_copy_all_action.trigger()
    _events()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    assert (
        cmds.keyframe("multiB.translateX", query=True, keyframeCount=True) == 1
    )
    assert (
        cmds.keyframe("multiB.translateY", query=True, keyframeCount=True) == 1
    )
    assert not cmds.keyframe(
        "multiB.translateZ", query=True, keyframeCount=True
    )


def test_animation_curve_paste_selected_one_curve_fans_out(
    editor: ChannelBoxWidget,
) -> None:
    """一曲線なら複数選択属性へ展開する。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=1)
    cmds.setKeyframe("multiA.translateX", time=10, value=4)
    _row(editor, "translateX").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    cmds.flushUndo()

    _row(editor, "translateY").animation_paste_selected_action.trigger()
    _events()
    for attribute in ("translateX", "translateY"):
        path = f"multiB.{attribute}"
        assert cmds.keyframe(path, query=True, timeChange=True) == [
            20.0,
            29.0,
        ]
        assert cmds.keyframe(path, query=True, valueChange=True) == [
            1.0,
            4.0,
        ]
    cmds.undo()
    _events()
    assert not cmds.keyframe(
        "multiB.translateX", query=True, keyframeCount=True
    )
    assert not cmds.keyframe(
        "multiB.translateY", query=True, keyframeCount=True
    )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_paste_selected_across_scalar_types(
    editor: ChannelBoxWidget,
) -> None:
    """数値カーブを単位・bool・enumへ貼り、時刻と生のキー値を保つ。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.gain", time=1, value=0.25)
    cmds.setKeyframe("multiA.gain", time=10, value=1.75)
    _row(editor, "gain").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    editor.table_view.select_keys(
        _keys(editor, "gain", "translateX", "rotateX", "enabled", "mode")
    )
    cmds.flushUndo()

    _row(editor, "gain").animation_paste_selected_action.trigger()
    _events()
    for attribute in ("gain", "translateX", "rotateX", "enabled", "mode"):
        assert cmds.keyframe(
            f"multiB.{attribute}", query=True, timeChange=True
        ) == [20.0, 29.0]
    assert cmds.keyframe("multiB.enabled", query=True, valueChange=True) == [
        0.25,
        1.75,
    ]
    assert cmds.getAttr("multiB.enabled", time=20) == 0
    assert cmds.getAttr("multiB.enabled", time=29) == 1
    assert isclose(cmds.getAttr("multiB.rotateX", time=20), 0.25)
    assert isclose(cmds.getAttr("multiB.rotateX", time=29), 1.75)
    cmds.undo()
    _events()
    assert not cmds.keyframe("multiB.enabled", query=True, keyframeCount=True)
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_paste_selected_angle_to_number(
    editor: ChannelBoxWidget,
) -> None:
    """角度から単位なし数値へ貼っても表示数値とキー間隔を保つ。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.rotateX", time=1, value=0.25)
    cmds.setKeyframe("multiA.rotateX", time=10, value=1.75)
    _row(editor, "rotateX").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "gain"))

    _row(editor, "gain").animation_paste_selected_action.trigger()
    _events()
    assert cmds.keyframe("multiB.gain", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]
    assert cmds.keyframe("multiB.gain", query=True, valueChange=True) == [
        0.25,
        1.75,
    ]


def test_animation_curve_paste_same_path_across_types(
    editor: ChannelBoxWidget,
) -> None:
    """同名属性ならコピー元と貼付先の型が異なっても貼る。"""
    cmds.addAttr(
        "multiA", longName="transfer", attributeType="double", keyable=True
    )
    cmds.addAttr(
        "multiB", longName="transfer", attributeType="bool", keyable=True
    )
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.transfer", time=1, value=0.25)
    cmds.setKeyframe("multiA.transfer", time=10, value=1.75)
    _row(editor, "transfer").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()

    _row(editor, "transfer").animation_paste_same_action.trigger()
    _events()
    assert cmds.keyframe("multiB.transfer", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]
    assert cmds.keyframe("multiB.transfer", query=True, valueChange=True) == [
        0.25,
        1.75,
    ]


def test_animation_curve_paste_selected_includes_other_type_nodes(
    editor: ChannelBoxWidget,
) -> None:
    """値編集から外れる異種型ノードも選択属性の曲線貼付では扱う。"""
    cmds.addAttr(
        "multiA", longName="transfer", attributeType="double", keyable=True
    )
    cmds.addAttr(
        "multiB", longName="transfer", attributeType="bool", keyable=True
    )
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.transfer", time=1, value=0.25)
    cmds.setKeyframe("multiA.transfer", time=10, value=1.75)
    _row(editor, "transfer").animation_copy_selected_action.trigger()
    cmds.select("multiA", "multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    row = _row(editor, "transfer")
    assert len(row.row.target_names) == 1
    editor.table_view.select_keys(_keys(editor, "transfer"))

    row.animation_paste_selected_action.trigger()
    _events()
    assert cmds.keyframe("multiB.transfer", query=True, timeChange=True) == [
        20.0,
        29.0,
    ]
    assert cmds.keyframe("multiB.transfer", query=True, valueChange=True) == [
        0.25,
        1.75,
    ]


def test_animation_curve_paste_selected_multiple_curves_match_paths(
    editor: ChannelBoxWidget,
) -> None:
    """複数カーブの未一致分を選択順で別属性へ貼り付けない。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    for attribute in ("translateX", "translateY"):
        cmds.setKeyframe(f"multiA.{attribute}", time=1, value=1)
    editor.table_view.select_keys(_keys(editor, "translateX", "translateY"))
    _row(editor, "translateX").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "translateY", "translateZ"))

    _row(editor, "translateY").animation_paste_selected_action.trigger()
    _events()
    assert not cmds.keyframe(
        "multiB.translateX", query=True, keyframeCount=True
    )
    assert (
        cmds.keyframe("multiB.translateY", query=True, keyframeCount=True) == 1
    )
    assert not cmds.keyframe(
        "multiB.translateZ", query=True, keyframeCount=True
    )


@pytest.mark.parametrize(
    "source_order, destination_values",
    (
        (("multiA", "multiB"), ((1.0, 4.0), (2.0, 8.0))),
        (("multiB", "multiA"), ((2.0, 8.0), (1.0, 4.0))),
    ),
)
def test_animation_curve_copy_multiple_nodes_maps_by_selection_order(
    editor: ChannelBoxWidget,
    source_order: tuple[str, str],
    destination_values: tuple[tuple[float, float], tuple[float, float]],
) -> None:
    """複数コピー元を同数の貼付先へ選択順で対応させ、一度でUndoする。"""
    cmds.select(*source_order, replace=True)
    editor.refresh()
    representative = editor.controller.representative_node_name
    assert representative is not None
    assert representative.rsplit("|", 1)[-1] == source_order[-1]
    for node, values in (
        ("multiA", (1.0, 4.0)),
        ("multiB", (2.0, 8.0)),
    ):
        cmds.setKeyframe(f"{node}.translateX", time=1, value=values[0])
        cmds.setKeyframe(f"{node}.translateX", time=10, value=values[1])
    _row(editor, "translateX").animation_copy_selected_action.trigger()
    for node in ("targetA", "targetB"):
        cmds.createNode("transform", name=node)
    cmds.select("targetA", "targetB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    for node, values in zip(
        ("targetA", "targetB"), destination_values, strict=True
    ):
        assert cmds.keyframe(
            f"{node}.translateX", query=True, timeChange=True
        ) == [20.0, 29.0]
        assert cmds.keyframe(
            f"{node}.translateX", query=True, valueChange=True
        ) == list(values)
    cmds.undo()
    _events()
    for node in ("targetA", "targetB"):
        assert not cmds.keyframe(
            f"{node}.translateX", query=True, keyframeCount=True
        )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)

    # Maya標準のキー用clipboardでも選択順の対応を維持する
    assert (
        cmds.pasteKey(
            "targetA.translateX",
            "targetB.translateX",
            clipboard="anim",
            animation="objects",
            time=(20, 20),
            option="insert",
        )
        == 2
    )
    for node, values in zip(
        ("targetA", "targetB"), destination_values, strict=True
    ):
        assert cmds.keyframe(
            f"{node}.translateX", query=True, timeChange=True
        ) == [20.0, 29.0]
        assert cmds.keyframe(
            f"{node}.translateX", query=True, valueChange=True
        ) == list(values)
    cmds.undo()
    _events()
    for node in ("targetA", "targetB"):
        assert not cmds.keyframe(
            f"{node}.translateX", query=True, keyframeCount=True
        )
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_paste_inserts_and_connects_to_existing_curve(
    editor: ChannelBoxWidget,
) -> None:
    """既存カーブには標準Channel Box同様に現在時刻へ接続挿入する。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=1)
    cmds.setKeyframe("multiA.translateX", time=10, value=4)
    _row(editor, "translateX").animation_copy_selected_action.trigger()
    cmds.setKeyframe("multiB.translateX", time=15, value=10)
    cmds.setKeyframe("multiB.translateX", time=25, value=20)
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    times = cmds.keyframe("multiB.translateX", query=True, timeChange=True)
    values = cmds.keyframe("multiB.translateX", query=True, valueChange=True)
    assert times == [15.0, 20.0, 29.0, 34.0]
    assert isinstance(values, list)
    assert values[1:3] == [15.0, 18.0]
    cmds.undo()
    _events()
    assert cmds.keyframe("multiB.translateX", query=True, timeChange=True) == [
        15.0,
        25.0,
    ]
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_copy_selected_includes_hidden_attribute(
    editor: ChannelBoxWidget,
) -> None:
    """明示したHide属性のカーブは選択属性でコピーできる。"""
    cmds.setKeyframe("multiA.translateZ", time=1, value=2)
    cmds.setAttr("multiA.translateZ", keyable=False, channelBox=False)
    cmds.select("multiA", replace=True)
    editor.refresh()
    editor.controller.set_attribute_filter("all")
    _row(editor, "translateZ").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()

    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    assert cmds.keyframe("multiB.translateZ", query=True, timeChange=True) == [
        20.0
    ]


def test_animation_curve_paste_skips_locked_attribute_without_undo(
    editor: ChannelBoxWidget,
) -> None:
    """貼り付け不能な属性だけならSceneとUndo履歴を変えない。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.translateX", time=1, value=2)
    _row(editor, "translateX").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.setAttr("multiB.translateX", lock=True)
    editor.refresh()
    cmds.flushUndo()

    _row(editor, "translateX").animation_paste_same_action.trigger()
    _events()
    assert not cmds.keyframe(
        "multiB.translateX", query=True, keyframeCount=True
    )
    assert not editor.message_label.isVisible()
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


def test_animation_curve_paste_selected_ignores_enum_definition(
    editor: ChannelBoxWidget,
) -> None:
    """キー時刻の転写ではenum項目名の差異で曲線を除外しない。"""
    cmds.select("multiA", replace=True)
    editor.refresh()
    cmds.setKeyframe("multiA.mode", time=1, value=1)
    _row(editor, "mode").animation_copy_selected_action.trigger()
    cmds.select("multiB", replace=True)
    cmds.currentTime(20)
    editor.refresh()
    editor.table_view.select_keys(_keys(editor, "quality", "variant"))

    _row(editor, "quality").animation_paste_selected_action.trigger()
    _events()
    assert cmds.keyframe("multiB.quality", query=True, keyframeCount=True) == 1
    assert cmds.keyframe("multiB.variant", query=True, keyframeCount=True) == 1


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
        assert [action.text() for action in row.copy_menu.actions()] == [
            "選択属性",
            "全属性",
        ]
        assert row.copy_all_values_action.isEnabled()
        assert row.copy_selected_values_action.isEnabled()
        assert row.paste_menu.title() == "ペースト"
        assert [action.text() for action in row.paste_menu.actions()] == [
            "選択属性",
            "コピー元と同じ属性：全て",
            "コピー元と同じ属性：Keyable + ChannelBox",
            "コピー元と同じ属性：Keyable",
            "コピー元と同じ属性：ChannelBox",
            "コピー元と同じ属性：Hide",
        ]
        assert all(
            action.menu() is None for action in row.paste_menu.actions()
        )
        assert editor.edit_menu.title() == "編集"
        assert editor.copy_menu.title() == "コピー"
        assert [action.text() for action in editor.copy_menu.actions()] == [
            "選択属性",
            "全属性",
        ]
        assert editor.paste_menu.title() == "ペースト"
        assert [action.text() for action in editor.paste_menu.actions()] == [
            action.text() for action in row.paste_menu.actions()
        ]
        assert all(
            action.menu() is None for action in editor.paste_menu.actions()
        )
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


def test_filtered_paste_uses_last_selected_node_from_row_menu(
    editor: ChannelBoxWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """右クリックの状態別Pasteは末尾ノードでpathを決め全選択へ適用する。"""
    _set_value("multiA.gain", 4.5)
    _set_value("multiA.enabled", False)
    attributes = tuple(
        _row(editor, name).row.attribute for name in ("gain", "enabled")
    )
    transfer = MayaScalarValueTransfer(
        (capture_scalar_node_values("multiA", attributes),)
    )
    monkeypatch.setattr(
        editor.controller, "_value_clipboard", _StaticValueClipboard(transfer)
    )
    for node in ("multiA", "multiB"):
        _set_value(node + ".gain", 1.0)
        _set_value(node + ".enabled", True)
    cmds.setAttr("multiA.enabled", keyable=False)
    cmds.setAttr("multiA.enabled", channelBox=False)
    cmds.setAttr("multiB.enabled", keyable=False)
    cmds.setAttr("multiB.enabled", channelBox=True)
    cmds.setAttr("multiB.gain", keyable=False)
    cmds.setAttr("multiB.gain", channelBox=False)
    cmds.select("multiA", "multiB", replace=True)
    editor.refresh()
    cmds.flushUndo()

    row = _row(editor, "translateX")
    _open_row_menu(row)
    action = row.paste_copied_values_actions["channel_box"]
    assert action.isEnabled()
    action.trigger()
    row.context_menu.close()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(node + ".gain") == 1.0
        assert cmds.getAttr(node + ".enabled") is False
    cmds.undo()
    _events()
    for node in ("multiA", "multiB"):
        assert cmds.getAttr(node + ".enabled") is True
    assert cmds.undoInfo(query=True, undoQueueEmpty=True)


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
