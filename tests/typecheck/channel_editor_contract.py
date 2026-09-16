# coding: utf-8
"""Channel Editorの公開入口とWindow内容の型契約。"""

from typing import assert_type

from bd_util.ui import (
    BoolCheckBox,
    FloatSliderSpinBox,
    FloatValueStepSpinBox,
    qt,
)

from bd_tools import channel_editor
from bd_tools.channel_editor.widget import ChannelEditorWidget

assert_type(channel_editor.show(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.show().widget, ChannelEditorWidget)
assert_type(
    channel_editor.show().widget.row_widgets[0].editor,
    BoolCheckBox | FloatSliderSpinBox | FloatValueStepSpinBox,
)
assert_type(channel_editor.dispose(), None)
assert_type(channel_editor.close(), None)
assert_type(channel_editor.restore(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.reset_layout(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.WORKSPACE_CONTROL_NAME, str)
assert_type(channel_editor.show().widget.refresh_action, qt.QAction)
assert_type(
    channel_editor.show().widget.row_widgets[0].align_action, qt.QAction
)
assert_type(channel_editor.show().widget.row_widgets[0].context_menu, qt.QMenu)
