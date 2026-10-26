# coding: utf-8
"""bdChannelBoxの公開入口とWindow内容の型契約。"""

from pathlib import Path
from typing import Literal, assert_type

from bd_util.maya.node.inspection import ScalarAttributeInfo
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
    IntValueStepSpinBox,
    IntSliderSpinBox,
    IntStepProfile,
    PathLineEdit,
    RadioButtonSweep,
    StringLineEdit,
    UiStateManager,
    qt,
)

from bd_tools import bd_channel_box
from bd_tools.bd_channel_box.custom_filter_dialogs import (
    CustomFilterExportCompleteDialog,
    confirm_export_save,
    initial_filter_directory,
)
from bd_tools.bd_channel_box.custom_filter_export import (
    export_custom_filter_files,
)
from bd_tools.bd_channel_box.controller import (
    ChannelAttributeFilter,
    ChannelDisplayFilter,
    ChannelRow,
    ChannelStateRow,
    RoundTransformKind,
)
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterDefinition,
    CustomFilterSelection,
)
from bd_tools.bd_channel_box.custom_filter_editor import (
    CustomFilterDraft,
    duplicate_custom_filter,
    filter_file_name,
)
from bd_tools.bd_channel_box.custom_filter_registry import (
    CustomFilterRegistry,
    PresetRegistration,
)
from bd_tools.bd_channel_box.custom_filter_setup import CustomFilterSetupPanel
from bd_tools.bd_channel_box.filter_preferences import ValueFilterPreferences
from bd_tools.bd_channel_box.widget import (
    AttributeRowMenu,
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelBoxWidget,
)
from bd_tools.bd_channel_box.table import ChannelTableView

assert_type(bd_channel_box.show(), bd_channel_box.ChannelBoxWindow)
assert_type(
    CustomFilterExportCompleteDialog(Path("C:/work"), qt.QWidget()).path_edit,
    PathLineEdit,
)
assert_type(bd_channel_box.config.ATTRIBUTE_PRIORITY_PATHS, tuple[str, ...])
assert_type(bd_channel_box.config.EXPORT_DIRECTORY_DIALOG_WIDTH, int)
assert_type(bd_channel_box.config.EXPORT_DIRECTORY_DIALOG_HEIGHT, int)
assert_type(bd_channel_box.show().widget, ChannelBoxWidget)
manager = bd_channel_box.show().widget.custom_filter_dialog
if manager is not None:
    assert_type(manager.show_near(qt.QPoint(100, 100)), None)
    assert_type(manager.tree_widget, qt.QTreeWidget)
    assert_type(manager.group_tree_widget, qt.QTreeWidget)
    assert_type(manager.preset_tree_widget, qt.QTreeWidget)
    assert_type(manager.save_button, qt.QToolButton)
    assert_type(manager.discard_button, qt.QToolButton)
    assert_type(manager.storage_error_label, qt.QLabel)
    assert_type(manager.new_button, qt.QToolButton)
    assert_type(manager.add_button, qt.QToolButton)
    assert_type(manager.duplicate_button, qt.QToolButton)
    assert_type(manager.remove_button, qt.QToolButton)
    assert_type(manager.move_up_button, qt.QToolButton)
    assert_type(manager.move_down_button, qt.QToolButton)
    assert_type(manager.reload_all_button, qt.QToolButton)
    assert_type(manager.group_export_button, qt.QToolButton)
    assert_type(manager.preset_export_button, qt.QToolButton)
    assert_type(manager.export_button, qt.QToolButton)
assert_type(
    export_custom_filter_files("filter", [Path("Filter.json")], Path("out")),
    Path,
)
assert_type(confirm_export_save(qt.QWidget(), qt.QPoint(10, 20)), bool)
assert_type(
    bd_channel_box.show().widget.setup_panel.confirm_export(qt.QPoint(10, 20)),
    bool,
)
assert_type(bd_channel_box.show().widget.setup_panel, CustomFilterSetupPanel)
assert_type(bd_channel_box.show().widget.setup_panel.confirm_leave(), bool)
assert_type(
    bd_channel_box.show().widget.setup_panel.confirm_leave(qt.QPoint(10, 20)),
    bool,
)
assert_type(bd_channel_box.show().widget.preset_combo, qt.QComboBox)
assert_type(
    bd_channel_box.show().widget.setup_panel.preset_combo, qt.QComboBox
)
assert_type(
    bd_channel_box.show().widget.setup_panel.preset_new_button, qt.QToolButton
)
assert_type(
    bd_channel_box.show().widget.setup_panel.preset_rename_button,
    qt.QToolButton,
)
assert_type(bd_channel_box.show().widget.setup_panel.is_dirty, bool)
assert_type(
    bd_channel_box.show().widget.setup_panel.tool_box, qt.QtWidgets.QToolBox
)
assert_type(bd_channel_box.show().widget.setup_panel.order_page, qt.QWidget)
assert_type(
    bd_channel_box.show().widget.setup_panel.candidate_page, qt.QWidget
)
assert_type(
    bd_channel_box.show().widget.setup_panel.node_type_combo, qt.QComboBox
)
assert_type(
    bd_channel_box.show().widget.setup_panel.new_button, qt.QToolButton
)
assert_type(bd_channel_box.show().widget.header_separator, qt.QFrame)
assert_type(
    bd_channel_box.show().widget.setup_panel.order_context_menu, qt.QMenu
)
assert_type(
    bd_channel_box.show().widget.setup_panel.remove_order_action, qt.QAction
)
assert_type(
    bd_channel_box.show().widget.setup_panel.rename_button, qt.QToolButton
)
assert_type(
    bd_channel_box.show().widget.setup_panel.save_button, qt.QToolButton
)
assert_type(
    bd_channel_box.show().widget.setup_panel.discard_button, qt.QToolButton
)
assert_type(
    bd_channel_box.show().widget.setup_panel.manage_button, qt.QToolButton
)
assert_type(
    bd_channel_box.show().widget.setup_panel.clear_type_button, qt.QToolButton
)
assert_type(
    bd_channel_box.show().widget.controller.values_attribute_filter,
    ChannelDisplayFilter,
)
assert_type(
    bd_channel_box.show().widget.value_filter_preferences,
    ValueFilterPreferences,
)
assert_type(ValueFilterPreferences().restore({}), ChannelDisplayFilter)
assert_type(ValueFilterPreferences().save("all"), bool)
assert_type(bd_channel_box.show().widget.setup_panel.up_button, qt.QToolButton)
assert_type(duplicate_custom_filter("rig.json", "copy.json", "Rig_copy"), str)
assert_type(filter_file_name("Rig.json"), str)
assert_type(initial_filter_directory("filter", Path("rig.json")), Path)
assert_type(CustomFilterDraft("rig.json").destination_path, str)
assert_type(CustomFilterDraft("rig.json").rename("Renamed"), None)
assert_type(CustomFilterRegistry().replace_path("old.json", "new.json"), bool)
assert_type(CustomFilterRegistry().groups, tuple[PresetRegistration, ...])
assert_type(CustomFilterRegistry().presets, tuple[PresetRegistration, ...])
assert_type(CustomFilterRegistry().active_group, str | None)
assert_type(CustomFilterRegistry().active_preset, str | None)
assert_type(CustomFilterRegistry().select_group(None), bool)
assert_type(CustomFilterRegistry().select_preset(None), bool)
assert_type(CustomFilterRegistry().is_dirty, bool)
assert_type(CustomFilterRegistry().save(), None)
assert_type(CustomFilterRegistry().discard(), None)
assert_type(CustomFilterRegistry().remove_many(("one.json", "two.json")), bool)
assert_type(
    CustomFilterRegistry().set_enabled_many(("one.json", "two.json"), False),
    bool,
)
assert_type(
    CustomFilterRegistry().move_many(("one.json", "two.json"), -1), bool
)
assert_type(
    bd_channel_box.show().widget.controller.replace_custom_filter(
        CustomFilterSelection("new.json", CustomFilterDefinition("New", {})),
        previous_path="old.json",
    ),
    None,
)
assert_type(CustomFilterDraft("rig.json").move_many("joint", ("a",), -1), bool)
assert_type(CustomFilterDraft("rig.json").remove_many("joint", ("a",)), None)
assert_type(
    bd_channel_box.show().widget.setup_panel.selected_candidate_paths(),
    tuple[str, ...],
)
assert_type(
    bd_channel_box.show().widget.controller.setup_attributes,
    tuple[ScalarAttributeInfo, ...],
)
assert_type(bd_channel_box.show().widget.node_name_edit, StringLineEdit | None)
assert_type(bd_channel_box.show().ui_state, UiStateManager)
assert_type(bd_channel_box.show().ui_state_tracker, MayaUiStateTracker)
row = bd_channel_box.show().widget.row_widgets[0]
assert_type(row, AttributeRowWidget | AttributeStateRowWidget)
if isinstance(row, AttributeRowWidget):
    assert_type(row.row, ChannelRow)
    assert_type(row.context_menu, AttributeRowMenu)
    assert_type(
        row.editor,
        BoolCheckBox
        | EnumComboBox
        | FloatSliderSpinBox
        | FloatValueStepSpinBox
        | IntValueStepSpinBox
        | IntSliderSpinBox
        | StringLineEdit,
    )
    assert_type(row.context_menu.align_action, qt.QAction)
    assert_type(row.context_menu.mute_menu, qt.QMenu)
    assert_type(row.context_menu.mute_selected_action, qt.QAction)
    assert_type(row.context_menu.mute_all_animation_action, qt.QAction)
    assert_type(row.context_menu.unmute_menu, qt.QMenu)
    assert_type(row.context_menu.unmute_selected_action, qt.QAction)
    assert_type(row.context_menu.unmute_all_animation_action, qt.QAction)
    assert_type(row.context_menu.animation_copy_menu, qt.QMenu)
    assert_type(row.context_menu.animation_copy_selected_action, qt.QAction)
    assert_type(row.context_menu.animation_copy_all_action, qt.QAction)
    assert_type(row.context_menu.animation_paste_menu, qt.QMenu)
    assert_type(row.context_menu.animation_paste_same_action, qt.QAction)
    assert_type(row.context_menu.animation_paste_selected_action, qt.QAction)
    assert_type(row.context_menu.animation_cut_menu, qt.QMenu)
    assert_type(row.context_menu.animation_cut_selected_action, qt.QAction)
    assert_type(row.context_menu.animation_cut_all_action, qt.QAction)
    assert_type(row.context_menu.animation_delete_menu, qt.QMenu)
    assert_type(row.context_menu.animation_delete_selected_action, qt.QAction)
    assert_type(row.context_menu.animation_delete_all_action, qt.QAction)
    assert_type(row.context_menu.copy_menu, qt.QMenu)
    assert_type(row.context_menu.copy_all_values_action, qt.QAction)
    assert_type(row.context_menu.copy_selected_values_action, qt.QAction)
    assert_type(row.context_menu.paste_menu, qt.QMenu)
    assert_type(
        row.context_menu.paste_copied_values_actions,
        dict[ChannelAttributeFilter, qt.QAction],
    )
    assert_type(row.context_menu.paste_copied_values_action, qt.QAction)
    assert_type(row.context_menu.paste_selected_values_action, qt.QAction)
    assert_type(row.context_menu.round_menu, qt.QMenu | None)
    assert_type(row.context_menu.child_set_action, qt.QAction | None)
    assert_type(row.round_decimal_limit(), int)
    assert_type(row.context_menu.rotation_menu, qt.QMenu | None)
    assert_type(row.context_menu.freeze_menu, qt.QMenu)
    assert_type(row.freeze_separator_action, qt.QAction)
    assert_type(row.context_menu.freeze_translate_action, qt.QAction)
    assert_type(row.context_menu.freeze_rotate_action, qt.QAction)
    assert_type(row.context_menu.freeze_scale_action, qt.QAction)
    assert_type(row.context_menu.freeze_all_action, qt.QAction)
    assert_type(row.default_single_step(), int | float)
    assert_type(row.set_wheel_editing_without_focus(True), None)
else:
    assert_type(row.row, ChannelStateRow)
    assert_type(row.editor, qt.QWidget)
    assert_type(
        row.display_buttons, dict[ChannelDisplayState, qt.QRadioButton]
    )
    assert_type(row.lock_check_box, qt.QCheckBox)
    assert_type(row.set_locked(True), None)
    assert_type(row.set_display_state("hidden"), None)
assert_type(bd_channel_box.dispose(), None)
assert_type(bd_channel_box.close(), None)
assert_type(bd_channel_box.restore(), bd_channel_box.ChannelBoxWindow)
assert_type(bd_channel_box.reset_layout(), bd_channel_box.ChannelBoxWindow)
assert_type(bd_channel_box.WORKSPACE_CONTROL_NAME, str)
assert_type(bd_channel_box.show().widget.refresh(), None)
assert_type(bd_channel_box.show().widget.menu_bar, qt.QMenuBar)
assert_type(bd_channel_box.show().widget.edit_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.copy_menu, qt.QMenu)
assert_type(bd_channel_box.show().widget.copy_all_values_action, qt.QAction)
assert_type(
    bd_channel_box.show().widget.copy_selected_values_action, qt.QAction
)
assert_type(bd_channel_box.show().widget.paste_menu, qt.QMenu)
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
assert_type(bd_channel_box.show().widget.int_step_profile, IntStepProfile)
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
    ChannelDisplayFilter,
)
assert_type(
    bd_channel_box.show().widget.controller.custom_filter_fallback_node_type,
    str | None,
)
assert_type(
    bd_channel_box.show().widget.controller.set_attribute_filter("hidden"),
    None,
)
custom_filter = CustomFilterSelection(
    "C:/filters/rig.json",
    CustomFilterDefinition("Rig", {"joint": ("rotateOrder",)}),
)
assert_type(
    bd_channel_box.show().widget.controller.set_attribute_filter(
        custom_filter
    ),
    None,
)
assert_type(
    bd_channel_box.show().widget.controller.replace_custom_filter(
        custom_filter
    ),
    None,
)
assert_type(
    bd_channel_box.show().widget.controller.clear_custom_filter(
        custom_filter.path
    ),
    None,
)
assert_type(
    bd_channel_box.show().widget.controller.mode,
    Literal["values", "states", "custom_filter_setup"],
)
assert_type(bd_channel_box.show().widget.controller.set_mode("states"), None)
table = bd_channel_box.show().widget.table_view
assert_type(table, ChannelTableView)
assert_type(table.selected_keys(), tuple[tuple[str, str], ...])
keys = (("translate.translateX", "distance"), ("rotate.rotateX", "angle"))
assert_type(table.select_keys(keys), None)
assert_type(table.set_visible_keys(keys), int)
assert_type(table.set_visible_keys(None), int)
controller = bd_channel_box.show().widget.controller
assert_type(controller.representative_node_name, str | None)
assert_type(controller.apply_numeric_values(keys, 5.0), bool)
assert_type(controller.offset_numeric_values(keys, 1.0), bool)
assert_type(controller.apply_bool_values(keys, True), bool)
assert_type(controller.apply_enum_values(keys, keys[0], 1), bool)
assert_type(controller.begin_value_edit(), None)
assert_type(controller.finish_value_edit(), None)
assert_type(controller.align_selected_values(keys), bool)
assert_type(controller.round_selected_values(keys, 2), bool)
assert_type(controller.round_filtered_values("visible", 2), bool)
round_kind: RoundTransformKind = "rotate"
assert_type(
    controller.round_transform_xyz(
        round_kind,
        2,
        compensate_child_translate=True,
        joint_child_compensation_attr="jointOrient",
    ),
    int,
)
assert_type(controller.consolidate_rotation("rotate"), int)
assert_type(controller.can_set_rotation_preserving_pose(), bool)
assert_type(controller.can_set_child_compensated_value(), bool)
assert_type(controller.set_selected_locked(keys, True), bool)
assert_type(
    controller.set_selected_locked(
        keys, True, edit_session=controller.state_edit_session
    ),
    bool,
)
assert_type(controller.can_paste_values(), bool)
assert_type(controller.can_paste_single_value(), bool)
assert_type(controller.copy_all_values(), int)
assert_type(controller.copy_selected_values(keys), int)
assert_type(controller.paste_copied_values(), bool)
assert_type(controller.paste_copied_values("keyable"), bool)
assert_type(controller.paste_copied_values_to_selected(keys), bool)
assert_type(controller.has_transform_context(), bool)
assert_type(controller.can_freeze_translation(), bool)
assert_type(controller.freeze_transforms("all"), int)
assert_type(controller.set_selected_display(keys, "hidden"), bool)
assert_type(
    controller.set_selected_display(
        keys, "hidden", edit_session=controller.state_edit_session
    ),
    bool,
)
assert_type(controller.set_muted_selected(keys, muted=True), int)
assert_type(controller.set_muted_all_visible(muted=False), int)
assert_type(controller.can_paste_animation_curves(), bool)
assert_type(controller.copy_animation_curves_selected(keys), int)
assert_type(controller.copy_animation_curves_all_visible(), int)
assert_type(controller.cut_animation_curves_selected(keys), int)
assert_type(controller.cut_animation_curves_all_visible(), int)
assert_type(controller.paste_animation_curves_same_attributes(), int)
assert_type(controller.paste_animation_curves_to_selected(keys), int)
assert_type(controller.delete_animation_curves_selected(keys), int)
assert_type(controller.delete_animation_curves_all_visible(), int)
assert_type(controller.rows[0].target_names, tuple[str, ...])
