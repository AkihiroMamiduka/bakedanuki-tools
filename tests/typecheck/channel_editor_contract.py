# coding: utf-8
"""Channel Editorの公開入口とWindow内容の型契約。"""

from typing import assert_type

from bd_util.ui import BoolComboBox, FloatSliderSpinBox, FloatSpinBox

from bd_tools import channel_editor
from bd_tools.channel_editor.widget import ChannelEditorWidget

assert_type(channel_editor.show(), channel_editor.ChannelEditorWindow)
assert_type(channel_editor.show().widget, ChannelEditorWidget)
assert_type(
    channel_editor.show().widget.row_widgets[0].editor,
    BoolComboBox | FloatSliderSpinBox | FloatSpinBox,
)
assert_type(channel_editor.dispose(), None)
