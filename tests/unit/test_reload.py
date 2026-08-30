# coding: utf-8
from __future__ import annotations

import os
import subprocess
import sys


def test_reload_rebuilds_package_and_runs_disposer() -> None:
    """独立processでpackageの再構築と終了処理を確認する。"""
    # 現在のpytest processへ影響させずreloadを検証するscriptを組み立てる
    script = """
import sys
import bd_tools

old_package = bd_tools
events = []
bd_tools.register_reload_disposer(lambda: events.append("disposed"))
new_package = bd_tools.reload_package()

assert events == ["disposed"]
assert new_package is sys.modules["bd_tools"]
assert new_package is not old_package
assert old_package.__version__ == new_package.__version__
"""

    # 独立processでscriptを実行し、reload後のmodule状態を検証する
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert completed.returncode == 0, completed.stderr
