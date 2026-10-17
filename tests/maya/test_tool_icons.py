"""utilと連携する同梱アイコンの取得とreloadを確認する。"""

import os
import subprocess
import sys


def test_tool_icons_use_util_without_loading_tool_windows() -> None:
    """独立processで画像定数とutil同時reloadを確認する。"""
    script = r"""
import importlib
import sys
from pathlib import Path

import maya.standalone
from bd_util.ui import qt

application = qt.QApplication([])
maya.standalone.initialize(name="python")

import bd_tools
from bd_util.py.path import resolve_relative_path

package_root = Path(bd_tools.__file__).resolve().parent
old_icons = []
for name in (
    "bd_channel_box",
    "bd_child_compensated_set",
    "bd_rotation_preserving_pose",
):
    package = importlib.import_module(f"bd_tools.{name}")
    old_icons.append((package.__name__, package.icon))
    expected = package_root / name / "icon" / f"{name}.png"
    assert isinstance(package.icon.MENU, Path)
    assert package.icon.MENU == expected
    assert package.icon.MENU == resolve_relative_path(
        base_file=package.icon.__file__, relative_path=expected.name
    )
    assert set(package.__all__).issubset(dir(package))
    assert not hasattr(package, "undefined_api")
    data = package.icon.MENU.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(data[16:20], "big") == 64
    assert int.from_bytes(data[20:24], "big") == 64

old_resolver = resolve_relative_path
bd_tools.reload_package(reload_util=True)
from bd_util.py.path import resolve_relative_path
assert resolve_relative_path is not old_resolver
for name, old_icon in old_icons:
    package = importlib.import_module(name)
    assert package.icon is not old_icon
    assert package.icon.MENU == old_icon.MENU
    assert package.icon.resolve_relative_path is resolve_relative_path
    assert f"{package.__name__}.ui" not in sys.modules
    assert f"{package.__name__}.dock_window" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
