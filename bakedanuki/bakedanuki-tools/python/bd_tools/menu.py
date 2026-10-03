# coding: utf-8
"""bakedanuki共通メニューへのtools項目の登録。"""

from __future__ import annotations

from ._dev.lifecycle import (
    register_reload_disposer,
    unregister_reload_disposer,
)

_OWNER = "bd_tools"
_CATEGORY = "tools"
_CHANNEL_BOX_ID = "bdChannelBox"
_installed = False


def _show_channel_box() -> None:
    """メニュー操作時にbdChannelBoxを読み込んで表示する。"""
    from .bd_channel_box import show

    show()


def install_menu() -> bool:
    """Maya上部の``bakedanuki > tools``へbdChannelBoxを登録する。

    MayaのUIがまだ利用できない場合は``False``を返す。
    """
    from bd_util.maya.ui import register_menu_item

    global _installed
    installed = register_menu_item(
        owner=_OWNER,
        category=_CATEGORY,
        item_id=_CHANNEL_BOX_ID,
        label=_CHANNEL_BOX_ID,
        command=_show_channel_box,
    )
    if installed:
        _installed = True
        register_reload_disposer(uninstall_menu)
    return installed


def uninstall_menu() -> None:
    """toolsの項目だけを共通メニューから解除する。"""
    from bd_util.maya.ui import unregister_menu_owner

    global _installed
    unregister_menu_owner(_OWNER)
    _installed = False
    unregister_reload_disposer(uninstall_menu)


def was_menu_installed() -> bool:
    """このpackageが登録し、reload後に復元すべき状態か返す。"""
    return _installed


__all__ = ["install_menu", "uninstall_menu"]
