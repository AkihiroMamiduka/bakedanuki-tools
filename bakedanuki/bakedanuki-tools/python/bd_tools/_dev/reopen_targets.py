# coding: utf-8
"""bd_toolsが開発reload時に再表示するdockable toolの識別情報。"""

from __future__ import annotations

CHANNEL_BOX_REOPEN: tuple[str, str, str, str] = (
    "bd_tools",
    "bd_channel_box",
    "bd_tools.bd_channel_box.ui",
    "show",
)
CHANNEL_BOX_CONTROL_ID = "bdChannelBoxWindow"

# MayaがuiScriptをまだ実行していないdockも、control名から調べられるようにする
KNOWN_DOCK_TOOLS: tuple[tuple[tuple[str, str, str, str], str], ...] = (
    (CHANNEL_BOX_REOPEN, f"{CHANNEL_BOX_CONTROL_ID}WorkspaceControl"),
)
