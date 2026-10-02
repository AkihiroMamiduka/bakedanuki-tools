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


def _menu_state() -> tuple[str, str]:
    """共有メニューと bdChannelBox 項目を確認する。"""
    from maya import cmds, mel

    main_window = mel.eval("$bdMenuSmokeMainWindow=$gMainWindow")
    menus = cmds.window(main_window, query=True, menuArray=True) or []
    roots = [
        menu
        for menu in menus
        if cmds.menu(menu, query=True, label=True) == "bd"
    ]
    if len(roots) != 1:
        raise AssertionError(f"bd メニュー数が {len(roots)} 件です")
    root = roots[0]
    category = _find_labeled_menu(root, "tools")
    item = _find_labeled_menu(category, "bdChannelBox")
    return root, item


def _run_in_maya() -> None:
    """起動 hook、メニューセット、reload、クリック起動を確認する。"""
    from maya import OpenMayaUI as omui
    from maya import cmds, mel

    from bd_util.ui import qt

    output = Path(os.environ[_OUTPUT_VARIABLE])

    def finish(success: bool, detail: str) -> None:
        """結果を保存し、検証専用 Maya を終了する。"""
        (output / "result.json").write_text(
            json.dumps(
                {"success": success, "detail": detail}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        qt.QTimer.singleShot(0, lambda: cmds.quit(force=True))

    def check_after_click() -> None:
        """項目のクリックで dockable UI が開いたことを確認する。"""
        try:
            from bd_tools.bd_channel_box import WORKSPACE_CONTROL_NAME

            if not cmds.workspaceControl(
                WORKSPACE_CONTROL_NAME, query=True, exists=True
            ):
                raise AssertionError(
                    "bdChannelBox の WorkspaceControl がありません"
                )
            finish(True, "startup, menu set, reload, click: passed")
        except Exception:
            finish(False, traceback.format_exc())

    def check_after_menu_set() -> None:
        """メニューセット切替後の表示を確認して項目を起動する。"""
        try:
            root, item = _menu_state()
            if not cmds.menu(root, query=True, visible=True):
                raise AssertionError("切替後に bd メニューが非表示です")

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

            bd_tools.reload_package(reload_util=True)
            root, item = _menu_state()
            _find_labeled_menu(root, "rig")
            from bd_util.maya.ui import unregister_menu_owner

            unregister_menu_owner("bd_rig")
            _menu_state()

            # 実際の QAction を起動して公開 show() への接続を確認する
            pointer = omui.MQtUtil.findMenuItem(item)
            if not pointer:
                raise AssertionError("bdChannelBox の QAction がありません")
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
            if not Path(os.environ[_USER_SETUP_MARKER]).is_file():
                raise AssertionError(
                    "ユーザーの userSetup.py が実行されていません"
                )
            _menu_state()
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

    # Maya の起動処理が完了してからメニューを検査する
    qt.QTimer.singleShot(1500, check_startup)


def _run_launcher(maya_version: str, util_root: Path, timeout: int) -> int:
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
    environment["MAYA_APP_DIR"] = str(output / "prefs")
    environment["MAYA_ENV_DIR"] = str(output / "env")
    environment["MAYA_PROJECT"] = str(output / "project")
    environment["MAYA_SCRIPT_PATH"] = str(output / "scripts")
    environment["MAYA_DISABLE_ADP"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment[_OUTPUT_VARIABLE] = str(output)
    environment[_USER_SETUP_MARKER] = str(output / "user-setup-ran.txt")
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

    with (output / "process.log").open("wb") as process_log:
        process = subprocess.Popen(
            [
                str(executable),
                "-noAutoloadPlugins",
                "-proj",
                str(output / "project"),
                "-log",
                str(output / "maya.log"),
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
                result_path = output / "result.json"
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
                                "maya_exit": process.poll(),
                                **result,
                            },
                            ensure_ascii=False,
                        )
                    )
                    return (
                        0
                        if result["success"] and process.returncode == 0
                        else 1
                    )
                if process.poll() is not None:
                    break
                time.sleep(1)
            print(
                "Maya GUI smoke did not complete: "
                f"{output} (exit={process.poll()})",
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


def main() -> int:
    """CLI 引数に従って検証用 Maya を起動する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--maya-version", choices=("2025", "2026", "2027"), required=True
    )
    parser.add_argument("--util-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    arguments = parser.parse_args()
    return _run_launcher(
        arguments.maya_version,
        arguments.util_root.resolve(),
        arguments.timeout,
    )


if __name__ == "__maya_menu_smoke__":
    _run_in_maya()
elif __name__ == "__main__":
    raise SystemExit(main())
