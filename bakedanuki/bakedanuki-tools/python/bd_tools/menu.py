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


def install_menu() -> bool:
    """設定された配置先の``bakedanuki > tools``へ3ツールを登録する。

    MayaのUIがまだ利用できない場合は``False``を返す。
    """
    from bd_util.maya.ui import register_menu_item

    # utilを利用するメニュー登録の段階で各ツールの画像情報を読み込む
    from .bd_channel_box import icon as channel_box_icon
    from .bd_child_compensated_set import icon as child_set_icon
    from .bd_rotation_preserving_pose import icon as rotation_set_icon

    global _installed
    entries = (
        (
            _CHANNEL_BOX_ID,
            "bdChannelBox",
            'python("import bd_tools.bd_channel_box; '
            'bd_tools.bd_channel_box.show()");',
            channel_box_icon.MENU,
        ),
        (
            _CHILD_SET_ID,
            "移動・回転をセット（子を維持）",
            'python("import bd_tools.bd_child_compensated_set; '
            'bd_tools.bd_child_compensated_set.show()");',
            child_set_icon.MENU,
        ),
        (
            _ROTATION_SET_ID,
            "回転をセット（姿勢を維持）",
            'python("import bd_tools.bd_rotation_preserving_pose; '
            'bd_tools.bd_rotation_preserving_pose.show()");',
            rotation_set_icon.MENU,
        ),
    )
    registered = False
    try:
        # 3項目を順番に登録し、途中失敗ではtools所有項目を片付ける
        for item_id, label, command, icon_path in entries:
            if not register_menu_item(
                owner=_OWNER,
                category=_CATEGORY,
                item_id=item_id,
                label=label,
                command=command,
                source_type="mel",
                icon_path=icon_path,
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
