# coding: utf-8
"""Channel Editorの公開入口とWindow内容の型契約。"""

from typing import Literal, assert_type

from bd_util.maya.ui import ChannelDisplayState, MayaEditSession
from bd_util.ui import (
    BoolCheckBox,
    CheckBoxSweep,
    EnumComboBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    RadioButtonSweep,
    qt,
)

from bd_tools import channel_editor
from bd_tools.channel_editor.controller import (
    ChannelAttributeFilter,
    ChannelRow,
    ChannelStateRow,
)
from bd_tools.channel_editor.widget import (
    AttributeRowWidget,
    AttributeStateRowWidget,
    ChannelEditorWidget,
)

assert_type(channel_editor.show(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.config.ATTRIBUTE_PRIORITY_PATHS, tuple[str, ...])
assert_type(channel_editor.show().widget, ChannelEditorWidget)
row = channel_editor.show().widget.row_widgets[0]
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
else:
    assert_type(row.row, ChannelStateRow)
    assert_type(row.editor, qt.QWidget)
    assert_type(
        row.display_buttons, dict[ChannelDisplayState, qt.QRadioButton]
    )
    assert_type(row.lock_check_box, qt.QCheckBox)
    assert_type(row.set_locked(True), None)
assert_type(channel_editor.dispose(), None)
assert_type(channel_editor.close(), None)
assert_type(channel_editor.restore(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.reset_layout(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.WORKSPACE_CONTROL_NAME, str)
assert_type(channel_editor.show().widget.refresh_action, qt.QAction)
assert_type(channel_editor.show().widget.mode_combo, qt.QComboBox)
assert_type(channel_editor.show().widget.filter_combo, qt.QComboBox)
assert_type(channel_editor.show().widget.mode_label, qt.QLabel)
assert_type(channel_editor.show().widget.filter_label, qt.QLabel)
assert_type(channel_editor.show().widget.state_sweep, RadioButtonSweep)
assert_type(channel_editor.show().widget.lock_sweep, CheckBoxSweep)
assert_type(
    channel_editor.show().widget.controller.state_edit_session,
    MayaEditSession,
)
assert_type(channel_editor.show().widget.controller.begin_state_edit(), None)
assert_type(
    channel_editor.show().widget.controller.attribute_filter,
    ChannelAttributeFilter,
)
assert_type(
    channel_editor.show().widget.controller.set_attribute_filter("hidden"),
    None,
)
assert_type(
    channel_editor.show().widget.controller.mode, Literal["values", "states"]
)
assert_type(channel_editor.show().widget.controller.set_mode("states"), None)
assert_type(channel_editor.show().widget.row_widgets[0].context_menu, qt.QMenu)
