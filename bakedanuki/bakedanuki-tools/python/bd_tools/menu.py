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
_CHILD_SET_ID = "bdChildCompensatedSet"
_ROTATION_SET_ID = "bdRotationPreservingPose"
_installed = False


def _show_channel_box() -> None:
    """メニュー操作時にbdChannelBoxを読み込んで表示する。"""
    from .bd_channel_box import show

    show()


def _show_child_compensated_set() -> None:
    """メニュー操作時に子維持ツールを読み込んで表示する。"""
    from .bd_child_compensated_set import show

    show()


def _show_rotation_preserving_pose() -> None:
    """メニュー操作時に姿勢維持ツールを読み込んで表示する。"""
    from .bd_rotation_preserving_pose import show

    show()


def install_menu() -> bool:
    """Maya上部の``bakedanuki > tools``へ3ツールを登録する。

    MayaのUIがまだ利用できない場合は``False``を返す。
    """
    from bd_util.maya.ui import register_menu_item

    global _installed
    entries = (
        (_CHANNEL_BOX_ID, "bdChannelBox", _show_channel_box),
        (
            _CHILD_SET_ID,
            "移動・回転をセット（子を維持）",
            _show_child_compensated_set,
        ),
        (
            _ROTATION_SET_ID,
            "回転をセット（姿勢を維持）",
            _show_rotation_preserving_pose,
        ),
    )
    registered = False
    try:
        # 3項目を順番に登録し、途中失敗ではtools所有項目を片付ける
        for item_id, label, command in entries:
            if not register_menu_item(
                owner=_OWNER,
                category=_CATEGORY,
                item_id=item_id,
                label=label,
                command=command,
            ):
                if registered:
                    uninstall_menu()
                return False
            registered = True
    except Exception:
        if registered:
            uninstall_menu()
        raise
    _installed = True
    register_reload_disposer(uninstall_menu)
    return True


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
