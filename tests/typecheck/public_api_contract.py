# coding: utf-8
from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import assert_type

import bd_tools

# 公開APIの戻り値型を固定し、IDE補完の退行を検出する
assert_type(bd_tools.__version__, str)
assert_type(bd_tools.reload_package(), ModuleType)
# utilを含むreload指定でも戻り値型を維持することを確認する
assert_type(
    bd_tools.reload_package(clear_pycache=True, reload_util=True),
    ModuleType,
)


def disposer() -> None:
    """reload lifecycleの型contractで使用する終了処理。"""
    pass


# reload lifecycle APIが具体的なcallable型を維持することを確認する
assert_type(
    bd_tools.register_reload_disposer(disposer),
    Callable[[], None],
)
assert_type(bd_tools.unregister_reload_disposer(disposer), bool)
