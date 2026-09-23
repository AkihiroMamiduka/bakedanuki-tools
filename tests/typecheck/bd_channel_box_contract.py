# coding: utf-8
"""bdChannelBoxの公開入口とWindow内容の型契約。"""

from typing import Literal, assert_type

from bd_util.maya.ui import (
    ChannelDisplayState,
    MayaEditSession,
    MayaUiStateTracker,
)
from bd_util.ui import (
    BoolCheckBox,
    CheckBoxSweep,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatStepProfile,
    FloatValueStepSpinBox,
    RadioButtonSweep,
    UiStateManager,
    qt,
)

from bd_tools import bd_channel_box
from bd_tools.bd_channel_box.controller import (
    ChannelAttributeFilter,
    ChannelRow,
    ChannelStateRow,
)
from bd_tools.bd_channel_box.widget import (
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelBoxWidget,
)
from bd_tools.bd_channel_box.table import ChannelTableView

assert_type(bd_channel_box.show(), bd_channel_box.ChannelBoxWindow)
assert_type(bd_channel_box.config.ATTRIBUTE_PRIORITY_PATHS, tuple[str, ...])
assert_type(bd_channel_box.show().widget, ChannelBoxWidget)
assert_type(bd_channel_box.show().ui_state, UiStateManager)
assert_type(bd_channel_box.show().ui_state_tracker, MayaUiStateTracker)
row = bd_channel_box.show().widget.row_widgets[0]
assert_type(row, AttributeRowWidget | AttributeStateRowWidget)
if isinstance(row, AttributeRowWidget):
    assert_type(row.row, ChannelRow)
    assert_type(
        row.editor,
        BoolCheckBox
        | EnumComboBox
        | FloatSliderSpinBox
        | FloatValueStepSpinBox,
    )
    assert_type(row.align_action, qt.QAction)
    assert_type(row.copy_menu, qt.QMenu)
    assert_type(row.copy_all_values_action, qt.QAction)
    assert_type(row.copy_selected_values_action, qt.QAction)
    assert_type(row.paste_menu, qt.QMenu)
    assert_type(row.paste_copied_values_menu, qt.QMenu)
    assert_type(
        row.paste_copied_values_actions,
        dict[ChannelAttributeFilter, qt.QAction],
    )
    assert_type(row.paste_copied_values_action, qt.QAction)
    assert_type(row.paste_selected_values_action, qt.QAction)
    assert_type(row.default_single_step(), float)
    assert_type(row.set_wheel_editing_without_focus(True), None)
else:
    assert_type(row.row, ChannelStateRow)
    assert_type(row.editor, qt.QWidget)
    assert_type(
        row.display_buttons, dict[ChannelDisplayState, qt.QRadioButton]
    )
    assert_type(row.lock_check_box, qt.QCheckBox)
    assert_type(row.set_locked(True), None)
assert_type(bd_channel_box.dispose(), None)
assert_type(bd_channel_box.close(), None)
assert_type(bd_channel_box.restore(), bd_channel_box.ChannelBoxWindow)
assert_type(bd_channel_box.reset_layout(), bd_channel_box.ChannelBoxWindow)
assert_type(bd_channel_box.WORKSPACE_CONTROL_NAME, str)
assert_type(bd_channel_box.show().widget.refresh_action, qt.QAction)
assert_type(bd_channel_box.show().widget.menu_bar, qt.QMenuBar)
assert_type(bd_channel_box.show().widget.edit_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.copy_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.copy_all_values_action, qt.QAction)
assert_type(
    bd_channel_box.show().widget.copy_selected_values_action, qt.QAction
)
assert_type(bd_channel_box.show().widget.paste_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.paste_copied_values_menu, qt.QMenu)
assert_type(
    bd_channel_box.show().widget.paste_copied_values_actions,
    dict[ChannelAttributeFilter, qt.QAction],
)
assert_type(
    bd_channel_box.show().widget.paste_copied_values_action, qt.QAction
)
assert_type(
    bd_channel_box.show().widget.paste_selected_values_action, qt.QAction
)
assert_type(bd_channel_box.show().widget.settings_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.wheel_editing_action, qt.QAction)
assert_type(bd_channel_box.show().widget.step_profile, FloatStepProfile)
assert_type(bd_channel_box.show().widget.step_settings_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.reset_all_steps_action, qt.QAction)
assert_type(
    bd_channel_box.show().widget.reset_selected_steps_action, qt.QAction
)
assert_type(bd_channel_box.show().widget.search_visibility_menu, qt.QMenu)
assert_type(
    bd_channel_box.show().widget.search_visibility_group, qt.QActionGroup
)
assert_type(
    bd_channel_box.show().widget.search_visibility_actions,
    dict[Literal["never", "all_only", "always"], qt.QAction],
)
assert_type(
    bd_channel_box.show().widget.search_visibility,
    Literal["never", "all_only", "always"],
)
assert_type(bd_channel_box.show().widget.mode_combo, qt.QComboBox)
assert_type(bd_channel_box.show().widget.filter_combo, qt.QComboBox)
assert_type(bd_channel_box.show().widget.search_edit, qt.QLineEdit)
assert_type(bd_channel_box.show().widget.mode_label, qt.QLabel)
assert_type(bd_channel_box.show().widget.filter_label, qt.QLabel)
assert_type(bd_channel_box.show().widget.search_label, qt.QLabel)
assert_type(bd_channel_box.show().widget.state_sweep, RadioButtonSweep)
assert_type(bd_channel_box.show().widget.lock_sweep, CheckBoxSweep)
assert_type(
    bd_channel_box.show().widget.controller.state_edit_session,
    MayaEditSession,
)
assert_type(bd_channel_box.show().widget.controller.begin_state_edit(), None)
assert_type(
    bd_channel_box.show().widget.controller.attribute_filter,
    ChannelAttributeFilter,
)
assert_type(
    bd_channel_box.show().widget.controller.set_attribute_filter("hidden"),
    None,
)
assert_type(
    bd_channel_box.show().widget.controller.mode, Literal["values", "states"]
)
assert_type(bd_channel_box.show().widget.controller.set_mode("states"), None)
assert_type(bd_channel_box.show().widget.row_widgets[0].context_menu, qt.QMenu)
table = bd_channel_box.show().widget.table_view
assert_type(table, ChannelTableView)
assert_type(table.selected_keys(), tuple[tuple[str, str], ...])
keys = (("translate.translateX", "distance"), ("rotate.rotateX", "angle"))
assert_type(table.select_keys(keys), None)
assert_type(table.set_visible_keys(keys), int)
assert_type(table.set_visible_keys(None), int)
controller = bd_channel_box.show().widget.controller
assert_type(controller.apply_numeric_values(keys, 5.0), bool)
assert_type(controller.offset_numeric_values(keys, 1.0), bool)
assert_type(controller.apply_bool_values(keys, True), bool)
assert_type(controller.apply_enum_values(keys, keys[0], 1), bool)
assert_type(controller.begin_value_edit(), None)
assert_type(controller.finish_value_edit(), None)
assert_type(controller.align_selected_values(keys), bool)
assert_type(controller.set_selected_locked(keys, True), bool)
assert_type(controller.can_paste_values(), bool)
assert_type(controller.can_paste_single_value(), bool)
assert_type(controller.copy_all_values(), int)
assert_type(controller.copy_selected_values(keys), int)
assert_type(controller.paste_copied_values(), bool)
assert_type(controller.paste_copied_values("keyable"), bool)
assert_type(controller.paste_copied_values_to_selected(keys), bool)
assert_type(controller.set_selected_display(keys, "hidden"), bool)
assert_type(controller.rows[0].target_names, tuple[str, ...])
