# coding: utf-8
"""Maya起動時にtoolsメニューを遅延登録する入口。"""

from __future__ import annotations

import traceback


def _install_menu_deferred() -> None:
    """起動時表示が有効ならUI初期化後にtoolsメニューを登録する。"""
    try:
        from bd_util.maya.ui import is_menu_auto_install_enabled

        if not is_menu_auto_install_enabled():
            return
        from .menu import install_menu

        install_menu()
    except Exception:
        traceback.print_exc()


def schedule_menu_install() -> None:
    """interactive Mayaでだけメニュー登録を遅延予約する。"""
    try:
        from maya import cmds, utils

        if cmds.about(batch=True):
            return
        utils.executeDeferred(_install_menu_deferred)
    except Exception:
        traceback.print_exc()


__all__ = ["schedule_menu_install"]
