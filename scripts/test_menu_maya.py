# coding: utf-8
"""独立した Maya 本体で Module 起動メニューを確認する。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

_OUTPUT_VARIABLE = "BAKEDANUKI_TOOLS_MENU_QA_OUTPUT"
_USER_SETUP_MARKER = "BAKEDANUKI_TOOLS_MENU_QA_USER_SETUP_MARKER"
_PHASE_VARIABLE = "BAKEDANUKI_TOOLS_MENU_QA_PHASE"
_INSTALLER_VARIABLE = "BAKEDANUKI_TOOLS_MENU_QA_INSTALLER"
_CONFIG_VARIABLE = "BAKEDANUKI_CONFIG_FILE"
_OPTION_LABEL = "Maya 起動時に bakedanuki メニューを表示"
_TOOL_LABELS = (
    "bdChannelBox",
    "移動・回転をセット（子を維持）",
    "回転をセット（姿勢を維持）",
)
_TOOL_PACKAGES = (
    "bd_channel_box",
    "bd_child_compensated_set",
    "bd_rotation_preserving_pose",
)
_COMMAND_SHELF = "BakedanukiCommandQA"


def _find_labeled_menu(parent: str, label: str) -> str:
    """親メニューから指定した表示名の項目を一つ取得する。"""
    from maya import cmds

    names = cmds.menu(parent, query=True, itemArray=True) or []
    items = [name if "|" in name else f"{parent}|{name}" for name in names]
    matches = [
        item
        for item in items
        if cmds.menuItem(item, query=True, label=True) == label
    ]
    if len(matches) != 1:
        raise AssertionError(f"{label!r} の項目数が {len(matches)} 件です")
    return matches[0]


def _menu_state() -> tuple[str, tuple[str, ...]]:
    """共有メニューと3ツールの項目・順序を確認する。"""
    from maya import cmds, mel

    main_window = mel.eval("$bdMenuSmokeMainWindow=$gMainWindow")
    menus = cmds.window(main_window, query=True, menuArray=True) or []
    roots = [
        menu
        for menu in menus
        if cmds.menu(menu, query=True, label=True) == "bakedanuki"
    ]
    if len(roots) != 1:
        raise AssertionError(f"bakedanuki メニュー数が {len(roots)} 件です")
    root = roots[0]
    category = _find_labeled_menu(root, "tools")
    items = tuple(
        _find_labeled_menu(category, label) for label in _TOOL_LABELS
    )
    ordered_items = cmds.menu(category, query=True, itemArray=True) or []
    ordered_paths = [
        item if "|" in item else f"{category}|{item}" for item in ordered_items
    ]
    indices = [ordered_paths.index(item) for item in items]
    if indices != sorted(indices):
        raise AssertionError("tools の3項目が指定順で並んでいません")
    return root, items


def _run_in_maya() -> None:
    """起動・表示設定・再有効化を実際のMaya画面で確認する。"""
    import runpy

    from maya import OpenMayaUI as omui
    from maya import cmds, mel

    from bd_util.ui import qt

    output = Path(os.environ[_OUTPUT_VARIABLE])
    phase = os.environ[_PHASE_VARIABLE]

    def check_commands(items: tuple[str, ...], *, shelf: bool) -> None:
        """メニューとShelfが同じ自己完結MELとその言語を保持するか確認する。"""
        for item, package in zip(items, _TOOL_PACKAGES, strict=True):
            if shelf:
                command = cmds.shelfButton(item, query=True, command=True)
                language = cmds.shelfButton(
                    item, query=True, command=True, sourceType=True
                )
            else:
                command = cmds.menuItem(item, query=True, command=True)
                language = cmds.menuItem(
                    item, query=True, command=True, sourceType=True
                )
            expected = (
                f'python("import bd_tools.{package}; '
                f'bd_tools.{package}.show()");'
            )
            if command != expected or language != "mel":
                raise AssertionError(
                    f"{package} のコマンドが不正です: {language}, {command!r}"
                )

    def save_command_shelf(items: tuple[str, ...]) -> None:
        """標準のメニュー転送処理でShelfへ登録し、MELファイルへ保存する。"""
        from maya.app.general.menuItemToShelf import menuItemToShelf

        check_commands(items, shelf=False)
        top = mel.eval("$bdCommandShelfTop=$gShelfTopLevel")
        shelf = cmds.shelfLayout(_COMMAND_SHELF, parent=top)
        buttons = tuple(menuItemToShelf(shelf, item) for item in items)
        check_commands(buttons, shelf=True)
        destination = output / f"shelf_{_COMMAND_SHELF}"
        cmds.saveShelf(shelf, destination.as_posix())
        saved = destination.with_suffix(".mel")
        if not saved.is_file() or b"<function" in saved.read_bytes():
            raise AssertionError("Shelfへ実行可能な文字列を保存できません")

    def check_saved_shelf() -> None:
        """再起動とreload後もメニュー登録なしで保存したShelfから起動する。"""
        try:
            import importlib

            import bd_tools

            def check_no_menu() -> None:
                """起動設定OFFのまま共有メニューが作成されていないか確認する。"""
                main = mel.eval("$bdCommandMain=$gMainWindow")
                menus = cmds.window(main, query=True, menuArray=True) or []
                if any(
                    cmds.menu(menu, query=True, label=True) == "bakedanuki"
                    for menu in menus
                ):
                    raise AssertionError("Shelf起動にメニュー登録は不要です")

            def click_buttons(buttons: tuple[str, ...]) -> None:
                """保存済みボタンをクリックし、各ツールが表示されたか確認する。"""
                check_commands(buttons, shelf=True)
                for button in buttons:
                    pointer = omui.MQtUtil.findControl(button)
                    if not pointer:
                        raise AssertionError(
                            f"Shelfボタンがありません: {button}"
                        )
                    widget = qt.wrapInstance(int(pointer), qt.QWidget)
                    position = qt.QPointF(widget.rect().center())
                    screen_position = qt.QPointF(
                        widget.mapToGlobal(position.toPoint())
                    )
                    # Maya独自のShelf widgetへ実クリックと同じマウス入力を送る
                    for event_type, buttons_state in (
                        (
                            qt.QEvent.Type.MouseButtonPress,
                            qt.Qt.MouseButton.LeftButton,
                        ),
                        (
                            qt.QEvent.Type.MouseButtonRelease,
                            qt.Qt.MouseButton.NoButton,
                        ),
                    ):
                        qt.QApplication.sendEvent(
                            widget,
                            qt.QtGui.QMouseEvent(
                                event_type,
                                position,
                                screen_position,
                                qt.Qt.MouseButton.LeftButton,
                                buttons_state,
                                qt.Qt.KeyboardModifier.NoModifier,
                            ),
                        )
                qt.QApplication.processEvents()
                for name in _TOOL_PACKAGES:
                    package = importlib.import_module(f"bd_tools.{name}")
                    if not cmds.workspaceControl(
                        package.WORKSPACE_CONTROL_NAME,
                        query=True,
                        visible=True,
                    ):
                        raise AssertionError(f"{name} がShelfから開きません")

            check_no_menu()
            # Maya標準の読込みで、前のprocessが保存したShelfを再構築する
            if cmds.shelfLayout(_COMMAND_SHELF, exists=True):
                cmds.deleteUI(_COMMAND_SHELF)
            path = (output / f"shelf_{_COMMAND_SHELF}.mel").as_posix()
            mel.eval(f'loadNewShelf "{path}";')
            buttons = tuple(
                cmds.shelfLayout(_COMMAND_SHELF, query=True, childArray=True)
                or []
            )
            click_buttons(buttons)
            for name in _TOOL_PACKAGES:
                importlib.import_module(f"bd_tools.{name}").close()
            bd_tools.reload_package(reload_util=True)
            check_no_menu()
            click_buttons(buttons)
            check_no_menu()
            finish(True, "saved MEL shelf, restart, no menu, reload: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def check_icons(items: tuple[str, ...], stage: str) -> None:
        """3画像の設定と読込み、Maya表示設定ON/OFFの実画面を確認する。"""
        from bd_tools.bd_channel_box import icon as channel_box_icon
        from bd_tools.bd_child_compensated_set import icon as child_set_icon
        from bd_tools.bd_rotation_preserving_pose import (
            icon as rotation_set_icon,
        )

        icons = (
            channel_box_icon,
            child_set_icon,
            rotation_set_icon,
        )
        for item, icon in zip(items, icons):
            expected = icon.MENU
            actual = cmds.menuItem(item, query=True, image=True)
            if Path(actual).resolve() != expected:
                raise AssertionError(
                    f"{icon.__name__} の画像pathが不正です: {actual}"
                )
            image = qt.QImage(actual)
            if image.isNull() or image.size() != qt.QSize(64, 64):
                raise AssertionError(
                    f"{icon.__name__} の64px PNGを読み込めません"
                )

        parent = items[0].rpartition("|")[0]
        pointer = omui.MQtUtil.findControl(parent)
        if not pointer:
            raise AssertionError("tools submenu の QMenu がありません")
        widget = qt.wrapInstance(int(pointer), qt.QMenu)
        original = int(cmds.optionVar(query="showIconsInMenus"))
        snapshots: list[qt.QtGui.QImage] = []
        try:
            # 専用profileで標準の表示設定を切り替え、同じメニューを描画する
            for enabled in (False, True):
                cmds.optionVar(intValue=("showIconsInMenus", int(enabled)))
                widget.popup(qt.QPoint(70, 90))
                qt.QApplication.processEvents()
                snapshot = widget.grab().toImage()
                snapshots.append(snapshot)
                suffix = "on" if enabled else "off"
                if not snapshot.save(
                    str(output / f"icons-{stage}-{suffix}.png")
                ):
                    raise AssertionError("アイコン検証画像を保存できません")
                widget.hide()
            if snapshots[0] == snapshots[1]:
                raise AssertionError(
                    "アイコン表示設定ON/OFFで画面が変化しません"
                )
        finally:
            cmds.optionVar(intValue=("showIconsInMenus", original))

    def check_icon_replacement() -> None:
        """同名画像の差し替えと解除が実際のQActionへ反映されるか確認する。"""
        from bd_util.maya.ui import register_menu_item, unregister_menu_owner

        owner = "bd_icon_smoke"
        icon_path = output / "replacement.png"
        try:
            for color_name in ("red", "blue"):
                image = qt.QImage(64, 64, qt.QImage.Format.Format_RGB32)
                image.fill(qt.QColor(color_name))
                if not image.save(str(icon_path)):
                    raise AssertionError("差し替え用の画像を保存できません")
                register_menu_item(
                    owner=owner,
                    category="iconQA",
                    item_id="sample",
                    label="Icon QA",
                    command=lambda: None,
                    icon_path=icon_path,
                )
                root, _ = _menu_state()
                category = _find_labeled_menu(root, "iconQA")
                item = _find_labeled_menu(category, "Icon QA")
                menu_pointer = omui.MQtUtil.findControl(category)
                if not menu_pointer:
                    raise AssertionError("差し替え項目のQMenuがありません")
                popup = qt.wrapInstance(int(menu_pointer), qt.QMenu)
                popup.popup(qt.QPoint(70, 90))
                qt.QApplication.processEvents()
                popup.grab().save(
                    str(output / f"replacement-{color_name}.png")
                )
                pointer = omui.MQtUtil.findMenuItem(item)
                if not pointer:
                    raise AssertionError("差し替え項目のQActionがありません")
                action = qt.wrapInstance(int(pointer), qt.QAction)
                pixels = action.icon().pixmap(16, 16).toImage()
                popup.hide()
                if pixels.isNull() or pixels.pixelColor(8, 8) != qt.QColor(
                    color_name
                ):
                    raise AssertionError(
                        f"同名画像の{color_name}が反映されません: "
                        f"null={pixels.isNull()}, "
                        f"actual={pixels.pixelColor(8, 8).name()}"
                    )
            register_menu_item(
                owner=owner,
                category="iconQA",
                item_id="sample",
                label="Icon QA",
                command=lambda: None,
            )
            if cmds.menuItem(item, query=True, image=True):
                raise AssertionError("省略した画像が解除されません")
        finally:
            unregister_menu_owner(owner)

    def finish(success: bool, detail: str) -> None:
        """結果を保存し、検証専用 Maya を終了する。"""
        result_name = (
            "result.json" if phase == "initial" else f"result-{phase}.json"
        )
        (output / result_name).write_text(
            json.dumps(
                {"success": success, "detail": detail}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        qt.QTimer.singleShot(0, lambda: cmds.quit(force=True))

    def check_after_click() -> None:
        """3項目のクリックで各 dockable UI が開いたことを確認する。"""
        try:
            import importlib

            import bd_tools

            from bd_tools.bd_channel_box import (
                WORKSPACE_CONTROL_NAME as channel_box_control,
            )
            from bd_tools.bd_child_compensated_set import (
                WORKSPACE_CONTROL_NAME as child_set_control,
            )
            from bd_tools.bd_rotation_preserving_pose import (
                WORKSPACE_CONTROL_NAME as rotation_set_control,
            )

            # 開いたUIと遅延解決済みの公開APIもtoolsだけのreloadで置き換える
            tool_names = (
                "bd_channel_box",
                "bd_child_compensated_set",
                "bd_rotation_preserving_pose",
            )
            old_shows = [
                importlib.import_module(f"bd_tools.{name}").show
                for name in tool_names
            ]
            bd_tools.reload_package()
            for name, old_show in zip(tool_names, old_shows):
                package = importlib.import_module(f"bd_tools.{name}")
                ui = importlib.import_module(f"bd_tools.{name}.ui")
                if package.show is old_show or package.show is not ui.show:
                    raise AssertionError(f"{name} の公開showが更新されません")

            for label, control in zip(
                _TOOL_LABELS,
                (channel_box_control, child_set_control, rotation_set_control),
            ):
                if not cmds.workspaceControl(control, query=True, exists=True):
                    raise AssertionError(
                        f"{label} の WorkspaceControl がありません"
                    )
            root, _ = _menu_state()
            option = _find_labeled_menu(root, _OPTION_LABEL)
            pointer = omui.MQtUtil.findMenuItem(option)
            if not pointer:
                raise AssertionError("起動時表示の QAction がありません")
            action = qt.wrapInstance(int(pointer), qt.QtGui.QAction)
            action.trigger()
            from bd_util.maya.ui import is_menu_auto_install_enabled

            if is_menu_auto_install_enabled():
                raise AssertionError("チェックOFFが保存されていません")
            setting_path = (
                Path(cmds.internalVar(userPrefDir=True))
                / "bakedanuki"
                / "menu.json"
            )
            if json.loads(setting_path.read_text(encoding="utf-8")) != {
                "show_menu_on_startup": False
            }:
                raise AssertionError("専用設定ファイルのOFFが不正です")
            _menu_state()
            finish(True, "startup, three menu items, reload, click: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def check_after_menu_set() -> None:
        """メニューセット切替後の表示を確認して項目を起動する。"""
        try:
            root, items = _menu_state()
            if not cmds.menu(root, query=True, visible=True):
                raise AssertionError(
                    "切替後に bakedanuki メニューが非表示です"
                )

            # 再登録と reload を経ても同じメニューを一つだけ保持する
            from bd_tools.menu import install_menu

            install_menu()
            install_menu()
            _menu_state()
            from bd_util.maya.ui import register_menu_item

            register_menu_item(
                owner="bd_rig",
                category="rig",
                item_id="smoke",
                label="Rig smoke",
                command=lambda: None,
            )
            rig_category = _find_labeled_menu(root, "rig")
            _find_labeled_menu(rig_category, "Rig smoke")
            import bd_tools

            # 旧表示名の共有rootを保持したままreload時に表示名を更新する
            cmds.menu(root, edit=True, label="bd")
            bd_tools.reload_package(reload_util=True)
            root, items = _menu_state()
            check_icons(items, "reloaded")
            save_command_shelf(items)
            _find_labeled_menu(root, "rig")
            from bd_util.maya.ui import unregister_menu_owner

            unregister_menu_owner("bd_rig")
            _menu_state()

            # 実際の QAction を順に起動して各公開 show() への接続を確認する
            for label, item in zip(_TOOL_LABELS, items):
                pointer = omui.MQtUtil.findMenuItem(item)
                if not pointer:
                    raise AssertionError(f"{label} の QAction がありません")
                action = qt.wrapInstance(int(pointer), qt.QtGui.QAction)
                action.trigger()
            qt.QTimer.singleShot(1000, check_after_click)
        except Exception:
            finish(False, traceback.format_exc())

    def check_startup() -> None:
        """Module の userSetup.py が自動作成したメニューを確認する。"""
        try:
            if cmds.about(batch=True):
                raise AssertionError("対話用 Maya ではありません")
            loaded_ui = [
                name
                for name in (
                    "bd_tools.bd_channel_box.ui",
                    "bd_tools.bd_child_compensated_set.ui",
                    "bd_tools.bd_rotation_preserving_pose.ui",
                )
                if name in sys.modules
            ]
            if loaded_ui:
                raise AssertionError(
                    f"アイコン取得でUI本体を読み込んでいます: {loaded_ui}"
                )
            if not Path(os.environ[_USER_SETUP_MARKER]).is_file():
                raise AssertionError(
                    "ユーザーの userSetup.py が実行されていません"
                )
            config = (
                Path(cmds.internalVar(userPrefDir=True))
                / "bakedanuki"
                / "config.toml"
            )
            if (
                not config.is_file()
                or "[menu]\n# parent_menu"
                not in config.read_text(encoding="utf-8")
            ):
                raise AssertionError(
                    "個人用の起動設定TOMLが自動作成されていません"
                )
            _, items = _menu_state()
            check_icons(items, "startup")
            check_icon_replacement()
            current_set = cmds.menuSet(query=True, currentMenuSet=True)
            other_sets = [
                name
                for name in (cmds.menuSet(query=True, allMenuSets=True) or [])
                if name not in (current_set, "commonMenuSet")
            ]
            if not other_sets:
                raise AssertionError("切替可能なメニューセットがありません")
            mel.eval(f'setMenuMode "{other_sets[0]}"')
            qt.QTimer.singleShot(500, check_after_menu_set)
        except Exception:
            finish(False, traceback.format_exc())

    def check_disabled() -> None:
        """再起動後はbdメニューが出ず、再D&Dで表示設定が戻ることを確認する。"""
        try:
            from bd_util.maya.ui import is_menu_auto_install_enabled

            if is_menu_auto_install_enabled():
                raise AssertionError("再起動後にOFF設定が読み込まれていません")
            main_window = mel.eval("$bdMenuDisabledWindow=$gMainWindow")
            menus = cmds.window(main_window, query=True, menuArray=True) or []
            if any(
                cmds.menu(menu, query=True, label=True) == "bakedanuki"
                for menu in menus
            ):
                raise AssertionError("OFFでもbdメニューが自動登録されました")

            # D&Dと同じinstaller入口を呼び、確認ダイアログだけ自動応答する
            namespace = runpy.run_path(
                os.environ[_INSTALLER_VARIABLE],
                run_name="__menu_smoke_installer__",
            )

            def approve(*_args: object, **_kwargs: object) -> bool:
                """再有効化の確認へOKで応答する。"""
                return True

            def ignore_message(*_args: object, **_kwargs: object) -> None:
                """完了ダイアログを自動検証中に表示しない。"""
                return None

            install = namespace["install"]
            install.__globals__["_confirm"] = approve
            install.__globals__["_message"] = ignore_message
            install()
            if not is_menu_auto_install_enabled():
                raise AssertionError("installerがOFF設定を解除しませんでした")
            finish(True, "disabled startup and installer re-enable: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def check_reenabled() -> None:
        """再D&D後の起動で共有メニューとチェック状態を確認する。"""
        try:
            root, _ = _menu_state()
            option = _find_labeled_menu(root, _OPTION_LABEL)
            if not cmds.menuItem(option, query=True, checkBox=True):
                raise AssertionError("再有効化後のチェックがOFFです")
            setting_path = (
                Path(cmds.internalVar(userPrefDir=True))
                / "bakedanuki"
                / "menu.json"
            )
            if json.loads(setting_path.read_text(encoding="utf-8")) != {
                "show_menu_on_startup": True
            }:
                raise AssertionError("専用設定ファイルのONが不正です")
            finish(True, "re-enabled startup: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def check_nested() -> None:
        """既存メニューへの登録・reload・解除をMaya本体で確認する。"""
        try:
            import bd_tools

            main_window = mel.eval("$bdMenuNestedWindow=$gMainWindow")
            parent = cmds.menu(
                "customToolsMenu",
                parent=main_window,
                label="tools",
                tearOff=False,
            )
            parent = cmds.menuItem(
                "freeToolsMenu",
                parent=parent,
                label="free_tools",
                subMenu=True,
                tearOff=False,
            )
            existing_item = f"{parent}|existingCustomItem"
            build_count = 0

            def populate_parent(*_args: object) -> None:
                """標準メニュー同様、初めて開いた空メニューへ既存項目を作る。"""
                nonlocal build_count
                build_count += 1
                if cmds.menu(parent, query=True, numberOfItems=True):
                    return
                cmds.menuItem(
                    "existingCustomItem",
                    parent=parent,
                    label="Existing custom item",
                )

            cmds.menu(
                parent,
                edit=True,
                postMenuCommand=populate_parent,
                postMenuCommandOnce=True,
            )

            def check_parent_items(*, installed: bool) -> None:
                """追加した項目だけが変化し、遅延生成が一度だけ行われたか確認する。"""
                names = cmds.menu(parent, query=True, itemArray=True) or []
                items = [
                    name if "|" in name else f"{parent}|{name}"
                    for name in names
                ]
                expected = (
                    [existing_item, root] if installed else [existing_item]
                )
                if items != expected or build_count != 1:
                    raise AssertionError(
                        "Python callbackの既存項目・順序・実行回数が不正です: "
                        f"items={items}, build_count={build_count}"
                    )

            config = Path(os.environ[_CONFIG_VARIABLE])
            config.write_text(
                f'[menu]\nparent_menu = "{parent}"\n',
                encoding="utf-8",
            )
            root = f"{parent}|bdUtilMainMenu"
            if not bd_tools.install_menu():
                raise AssertionError("既存メニューへの登録に失敗しました")
            if not cmds.menuItem(root, exists=True):
                raise AssertionError("bakedanuki submenuがありません")
            check_parent_items(installed=True)
            pointer = omui.MQtUtil.findControl(parent)
            if not pointer:
                raise AssertionError("配置先 submenu の QMenu がありません")
            parent_menu = qt.wrapInstance(int(pointer), qt.QMenu)
            parent_menu.popup(qt.QPoint(50, 70))
            qt.QApplication.processEvents()
            if not parent_menu.grab().save(str(output / "nested-lazy.png")):
                raise AssertionError("配置先 submenu の画像保存に失敗しました")
            parent_menu.hide()
            check_parent_items(installed=True)
            category = _find_labeled_menu(root, "tools")
            for label in _TOOL_LABELS:
                _find_labeled_menu(category, label)
            torn_root = tear_off_menu(root, 80)
            torn_tools = tear_off_menu(category, 400)
            from bd_util.maya.ui import set_menu_auto_install_enabled

            set_menu_auto_install_enabled(True)
            option = _find_labeled_menu(root, _OPTION_LABEL)
            if not cmds.menuItem(option, query=True, checkBox=True):
                raise AssertionError(
                    "入れ子メニューの表示設定が更新されません"
                )

            bd_tools.uninstall_menu()
            check_tear_off_closed(torn_root, torn_tools)
            menu_exists = cmds.menu(root, exists=True)
            item_exists = cmds.menuItem(root, exists=True)
            if menu_exists or item_exists:
                roots = [
                    path
                    for path in cmds.lsUI(menus=True, long=True) or []
                    if path.endswith("bdUtilMainMenu")
                ]
                raise AssertionError(
                    "tools解除後にbakedanuki submenuが残りました: "
                    f"menu={menu_exists}, item={item_exists}, roots={roots}"
                )
            if not cmds.menu(parent, exists=True):
                raise AssertionError("既存の親メニューが削除されました")
            check_parent_items(installed=False)
            if not bd_tools.install_menu():
                raise AssertionError("同じ親への再登録に失敗しました")
            check_parent_items(installed=True)

            bd_tools.reload_package(reload_util=True)
            if not cmds.menuItem(root, exists=True):
                raise AssertionError("reloadでbakedanuki submenuが消えました")
            check_parent_items(installed=True)
            bd_tools.uninstall_menu()
            if cmds.menuItem(root, exists=True):
                raise AssertionError(
                    "tools解除後にbakedanuki submenuが残りました"
                )
            if not cmds.menu(parent, exists=True):
                raise AssertionError("既存の親メニューが削除されました")
            check_parent_items(installed=False)
            finish(True, "nested placement, reload, owner cleanup: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def tear_off_menu(path: str, x: int) -> qt.QtWidgets.QMenu:
        """Maya標準の切り離しを表示し、元と同じ項目を持つWindowを取得する。"""
        pointer = omui.MQtUtil.findControl(path)
        if not pointer:
            raise AssertionError(f"メニューのQt UIがありません: {path}")
        original = qt.wrapInstance(int(pointer), qt.QMenu)
        if not original.isTearOffEnabled():
            raise AssertionError(f"切り離しが有効ではありません: {path}")
        before = set(qt.QApplication.topLevelWidgets())
        original.showTearOffMenu(qt.QPoint(x, 110))
        qt.QApplication.processEvents()
        copies = [
            widget
            for widget in qt.QApplication.topLevelWidgets()
            if widget not in before
            and isinstance(widget, qt.QtWidgets.QMenu)
            and widget.isVisible()
        ]
        if len(copies) != 1 or copies[0].actions() != original.actions():
            raise AssertionError(f"切り離したメニューの項目が不正です: {path}")
        return copies[0]

    def check_tear_off_closed(*menus: qt.QtWidgets.QMenu) -> None:
        """元メニューの破棄で切り離しWindowも終了するか確認する。"""
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)
        for menu in menus:
            if qt.isValid(menu) and menu.isVisible():
                raise AssertionError("古い切り離しメニューが残っています")

    def check_tear_off() -> None:
        """切り離し側の起動・設定同期・owner別解除とreloadを確認する。"""
        try:
            import importlib

            import bd_tools

            from bd_util.maya.ui import (
                is_menu_auto_install_enabled,
                register_menu_item,
                set_menu_auto_install_enabled,
                unregister_menu_owner,
            )

            bd_tools.install_menu()
            root, items = _menu_state()
            category = items[0].rpartition("|")[0]
            torn_root = tear_off_menu(root, 80)
            torn_tools = tear_off_menu(category, 400)
            for name, menu in (("root", torn_root), ("tools", torn_tools)):
                if not menu.grab().save(str(output / f"tearoff-{name}.png")):
                    raise AssertionError("切り離しメニューを撮影できません")

            # 切り離し側のチェック操作と外部APIによる変更を双方向に同期する
            enabled = is_menu_auto_install_enabled()
            option = _find_labeled_menu(root, _OPTION_LABEL)
            check = next(
                action
                for action in torn_root.actions()
                if action.isCheckable()
            )
            check.trigger()
            if is_menu_auto_install_enabled() == enabled or (
                cmds.menuItem(option, query=True, checkBox=True) == enabled
            ):
                raise AssertionError("切り離し側のチェックが保存されません")
            set_menu_auto_install_enabled(enabled)
            if check.isChecked() != enabled:
                raise AssertionError(
                    "切り離し側のチェック表示が更新されません"
                )

            # 切り離したtoolsから3つの公開起動入口を実行する
            for action in torn_tools.actions():
                action.trigger()
            qt.QApplication.processEvents()
            for name in _TOOL_PACKAGES:
                package = importlib.import_module(f"bd_tools.{name}")
                if not cmds.workspaceControl(
                    package.WORKSPACE_CONTROL_NAME, query=True, visible=True
                ):
                    raise AssertionError(f"切り離し側から{name}が開きません")
                package.close()

            # 同じcategoryの別ownerだけを残し、最後のowner解除で両Windowを閉じる
            register_menu_item(
                owner="bd_tearoff_qa",
                category="tools",
                item_id="sample",
                label="Tear-off QA",
                command='print("Tear-off QA");',
                source_type="mel",
            )
            bd_tools.uninstall_menu()
            if not torn_tools.isVisible() or [
                action.text() for action in torn_tools.actions()
            ] != ["Tear-off QA"]:
                raise AssertionError("別ownerの切り離し項目が維持されません")
            unregister_menu_owner("bd_tearoff_qa")
            check_tear_off_closed(torn_root, torn_tools)

            # toolsだけのreloadとutilを含むreloadで古い切り離しを残さない
            for reload_util in (False, True):
                bd_tools.install_menu()
                root, items = _menu_state()
                torn_root = tear_off_menu(root, 80)
                torn_tools = tear_off_menu(items[0].rpartition("|")[0], 400)
                bd_tools.reload_package(reload_util=reload_util)
                check_tear_off_closed(torn_root, torn_tools)
                _menu_state()
            finish(True, "tear-off, launch, settings, owners, reload: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def check_native_menu() -> None:
        """遅延生成される標準メニューの末尾への追加と項目維持を確認する。"""
        try:
            import bd_tools

            from bd_util.maya.ui import is_menu_auto_install_enabled

            parent = "MayaWindow|mainWindowMenu"
            root = f"{parent}|bdUtilMainMenu"
            if not is_menu_auto_install_enabled():
                raise AssertionError("標準メニュー検証の自動登録がOFFです")
            pointer = omui.MQtUtil.findControl(parent)
            if not pointer:
                raise AssertionError("Windows メニューの QMenu がありません")
            native_menu = qt.wrapInstance(int(pointer), qt.QMenu)

            def snapshot(name: str, *, installed: bool) -> dict[str, object]:
                """標準メニューを実際に開き、項目と既存callbackを記録する。"""
                native_menu.popup(qt.QPoint(50, 70))
                qt.QApplication.processEvents()
                image_path = output / f"native-{name}.png"
                if not native_menu.grab().save(str(image_path)):
                    raise AssertionError(
                        "標準メニューの画像保存に失敗しました"
                    )
                native_menu.hide()
                names = cmds.menu(parent, query=True, itemArray=True) or []
                items = [
                    name if "|" in name else f"{parent}|{name}"
                    for name in names
                ]
                state = {
                    "items": items,
                    "labels": [
                        cmds.menuItem(item, query=True, label=True)
                        for item in items
                    ],
                    "post_menu_command": cmds.menu(
                        parent, query=True, postMenuCommand=True
                    ),
                    "post_menu_command_once": cmds.menu(
                        parent, query=True, postMenuCommandOnce=True
                    ),
                }
                (output / f"native-{name}.json").write_text(
                    json.dumps(state, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                existing_items = [item for item in items if item != root]
                if len(existing_items) < 10:
                    raise AssertionError(
                        "Windows の標準項目が生成されていません: "
                        f"{state['labels']}"
                    )
                if installed:
                    if items[-1] != root or items.count(root) != 1:
                        raise AssertionError(
                            "bakedanuki が末尾に一つだけ登録されていません"
                        )
                    category = _find_labeled_menu(root, "tools")
                    for label in _TOOL_LABELS:
                        _find_labeled_menu(category, label)
                elif root in items:
                    raise AssertionError("解除後も bakedanuki が残っています")
                state["items"] = existing_items
                state["labels"] = [
                    cmds.menuItem(item, query=True, label=True)
                    for item in existing_items
                ]
                return state

            # 起動前に設定した配置先で標準項目が生成されていることを確認する
            original = snapshot("startup", installed=True)
            callback = original["post_menu_command"]
            if (
                not isinstance(callback, str)
                or "buildViewMenu" not in callback
            ):
                raise AssertionError("Windows の標準callbackがありません")
            if not original["post_menu_command_once"]:
                raise AssertionError("Windows の遅延生成フラグが失われました")

            # 再登録・reload・解除を通じて項目順序とcallbackを維持する
            bd_tools.install_menu()
            bd_tools.install_menu()
            if snapshot("reinstalled", installed=True) != original:
                raise AssertionError(
                    "再登録で標準項目かcallbackが変化しました"
                )
            bd_tools.reload_package(reload_util=True)
            if snapshot("reloaded", installed=True) != original:
                raise AssertionError(
                    "reloadで標準項目かcallbackが変化しました"
                )
            bd_tools.uninstall_menu()
            if snapshot("removed", installed=False) != original:
                raise AssertionError("解除で標準項目かcallbackが変化しました")
            finish(
                True,
                "native Windows menu, append, reload, owner cleanup: passed",
            )
        except Exception:
            finish(False, traceback.format_exc())

    # Maya の起動処理が完了してからメニューを検査する
    checks = {
        "initial": check_startup,
        "shelf": check_saved_shelf,
        "disabled": check_disabled,
        "reenabled": check_reenabled,
        "tearoff": check_tear_off,
        "nested": check_nested,
        "native": check_native_menu,
    }
    qt.QTimer.singleShot(5000, checks[phase])


def _run_launcher(
    maya_version: str, util_root: Path, timeout: int, phases: tuple[str, ...]
) -> int:
    """専用 profile と Module path で Maya を起動する。"""
    repository = Path(__file__).resolve().parents[1]
    executable = Path(
        f"C:/Program Files/Autodesk/Maya{maya_version}/bin/maya.exe"
    )
    if not executable.is_file():
        raise FileNotFoundError(executable)
    if not (util_root / "bakedanuki" / "modules" / "bd_util.mod").is_file():
        raise FileNotFoundError(
            util_root / "bakedanuki" / "modules" / "bd_util.mod"
        )

    output = Path(tempfile.mkdtemp(prefix=f"bd-menu-maya{maya_version}-"))
    for name in ("prefs", "env", "project", "scripts"):
        (output / name).mkdir()
    user_scripts = output / "prefs" / maya_version / "scripts"
    user_scripts.mkdir(parents=True)
    (user_scripts / "userSetup.py").write_text(
        "__import__('pathlib').Path("
        "__import__('os').environ["
        f"{_USER_SETUP_MARKER!r}]"
        ").write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    environment.pop("MAYA_SKIP_USERSETUP_PY", None)
    environment.pop(_CONFIG_VARIABLE, None)
    environment["MAYA_APP_DIR"] = str(output / "prefs")
    environment["MAYA_ENV_DIR"] = str(output / "env")
    environment["MAYA_PROJECT"] = str(output / "project")
    environment["MAYA_SCRIPT_PATH"] = str(output / "scripts")
    environment["MAYA_DISABLE_ADP"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment[_OUTPUT_VARIABLE] = str(output)
    environment[_USER_SETUP_MARKER] = str(output / "user-setup-ran.txt")
    environment[_INSTALLER_VARIABLE] = str(
        util_root / "bakedanuki" / "installer.py"
    )
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(repository / "bakedanuki" / "bakedanuki-tools" / "python"),
            str(util_root / "bakedanuki" / "bakedanuki-util" / "python"),
        )
    )
    environment["MAYA_MODULE_PATH"] = os.pathsep.join(
        (
            str(repository / "bakedanuki" / "modules"),
            str(util_root / "bakedanuki" / "modules"),
        )
    )
    maya_env_path = output / "prefs" / maya_version / "Maya.env"
    development_module_paths = (
        "MAYA_MODULE_PATH="
        f"{(repository / 'bakedanuki' / 'modules').as_posix()};"
        f"{(util_root / 'bakedanuki' / 'modules').as_posix()};\n"
    )
    maya_env_path.write_text(development_module_paths, encoding="utf-8")

    python_command = (
        "import runpy; runpy.run_path("
        + repr(Path(__file__).resolve().as_posix())
        + ", run_name='__maya_menu_smoke__')"
    )
    mel_command = python_command.replace("\\", "\\\\").replace('"', '\\"')
    startup_script = output / "startup.mel"
    startup_script.write_text(f'python("{mel_command}");\n', encoding="utf-8")
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE

    for phase in phases:
        environment[_PHASE_VARIABLE] = phase
        environment["MAYA_APP_DIR"] = str(output / "prefs")
        environment.pop(_CONFIG_VARIABLE, None)
        if phase == "native":
            # 過去のphaseの表示設定や既存メニュー状態を引き継がない
            native_profile = output / "prefs-native" / maya_version
            native_scripts = native_profile / "scripts"
            native_scripts.mkdir(parents=True)
            (native_scripts / "userSetup.py").write_text(
                (user_scripts / "userSetup.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (native_profile / "Maya.env").write_text(
                development_module_paths, encoding="utf-8"
            )
            config = output / "native-windows.toml"
            config.write_text(
                '[menu]\nparent_menu = "MayaWindow|mainWindowMenu"\n',
                encoding="utf-8",
            )
            environment["MAYA_APP_DIR"] = str(output / "prefs-native")
            environment[_CONFIG_VARIABLE] = str(config)
        if phase == "nested":
            settings = list((output / "prefs").rglob("menu.json"))
            if not settings:
                setting = (
                    output
                    / "prefs"
                    / maya_version
                    / "prefs"
                    / "bakedanuki"
                    / "menu.json"
                )
                setting.parent.mkdir(parents=True, exist_ok=True)
            elif len(settings) == 1:
                setting = settings[0]
            else:
                raise AssertionError("起動時表示設定の保存先が不明です")
            setting.write_text(
                '{"show_menu_on_startup": false}\n', encoding="utf-8"
            )
            environment[_CONFIG_VARIABLE] = str(output / "project-a.toml")
        result_name = (
            "result.json" if phase == "initial" else f"result-{phase}.json"
        )
        with (output / f"process-{phase}.log").open("wb") as process_log:
            process = subprocess.Popen(
                [
                    str(executable),
                    "-noAutoloadPlugins",
                    "-proj",
                    str(output / "project"),
                    "-log",
                    str(output / f"maya-{phase}.log"),
                    "-script",
                    str(startup_script),
                ],
                cwd=str(output),
                env=environment,
                startupinfo=startup_info,
                stdin=subprocess.DEVNULL,
                stdout=process_log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    result_path = output / result_name
                    if result_path.is_file():
                        result = json.loads(
                            result_path.read_text(encoding="utf-8")
                        )
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            result = {
                                "success": False,
                                "detail": "検証後に Maya が終了しませんでした",
                            }
                        print(
                            json.dumps(
                                {
                                    "output": str(output),
                                    "phase": phase,
                                    "maya_exit": process.poll(),
                                    **result,
                                },
                                ensure_ascii=False,
                            )
                        )
                        if not result["success"] or process.returncode != 0:
                            return 1
                        if phase == "disabled":
                            # sibling開発配置だけに必要なModule pathを次回起動前に戻す
                            maya_env_path.write_text(
                                development_module_paths, encoding="utf-8"
                            )
                        break
                    if process.poll() is not None:
                        break
                    time.sleep(1)
                else:
                    print(
                        "Maya GUI smoke timed out: "
                        f"{output} ({phase}, exit={process.poll()})",
                        file=sys.stderr,
                    )
                    return 1
                if not (output / result_name).is_file():
                    print(
                        "Maya GUI smoke did not complete: "
                        f"{output} ({phase}, exit={process.poll()})",
                        file=sys.stderr,
                    )
                    return 1
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    return 0


def main() -> int:
    """CLI 引数に従って検証用 Maya を起動する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--maya-version", choices=("2025", "2026", "2027"), required=True
    )
    parser.add_argument("--util-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--phase",
        action="append",
        choices=(
            "initial",
            "shelf",
            "disabled",
            "reenabled",
            "tearoff",
            "nested",
            "native",
        ),
    )
    arguments = parser.parse_args()
    phases = tuple(
        arguments.phase
        or (
            "initial",
            "shelf",
            "disabled",
            "reenabled",
            "tearoff",
            "nested",
            "native",
        )
    )
    return _run_launcher(
        arguments.maya_version,
        arguments.util_root.resolve(),
        arguments.timeout,
        phases,
    )


if __name__ == "__maya_menu_smoke__":
    _run_in_maya()
elif __name__ == "__main__":
    raise SystemExit(main())
