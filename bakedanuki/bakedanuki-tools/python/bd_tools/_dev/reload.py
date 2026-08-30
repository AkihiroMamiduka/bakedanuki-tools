# coding: utf-8
"""開発中のpackage reloadを支援する処理。"""

from __future__ import annotations

import importlib
import pathlib
import shutil
import sys
from collections.abc import Callable
from types import ModuleType
from typing import cast

from .lifecycle import dispose_for_reload

# このmoduleが属するtop-level package名をreload対象として固定する
PACKAGE_NAME = __name__.split(".")[0]

ReloadFunction = Callable[[bool], ModuleType]


def _is_package_module(name: str) -> bool:
    """module名がreload対象packageに属するか返す。"""
    return name == PACKAGE_NAME or name.startswith(f"{PACKAGE_NAME}.")


def _get_package_module_names() -> list[str]:
    """読み込み済みのreload対象module名を返す。"""
    return [name for name in sys.modules if _is_package_module(name)]


def _remove_pycache() -> None:
    """reload対象package配下のbytecode cacheを削除する。"""
    # 読み込み済みpackageからcache削除対象のdirectoryを特定する
    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        return

    package_file = cast(str | None, getattr(package, "__file__", None))
    if package_file is None:
        return

    # package配下のbytecode cacheだけを削除する
    package_path = pathlib.Path(package_file).parent
    for path in package_path.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)


def _remove_parent_module_attrs(module_names: list[str]) -> None:
    """親moduleが保持する古い子module参照を削除する。"""
    # 深いmoduleから順に、親moduleが保持する古い子module参照を外す
    for name in sorted(
        module_names, key=lambda item: item.count("."), reverse=True
    ):
        parent_name, _, child_name = name.rpartition(".")
        if not parent_name:
            continue

        parent_module = sys.modules.get(parent_name)
        child_module = sys.modules.get(name)
        if parent_module is None or child_module is None:
            continue

        if getattr(parent_module, child_name, None) is child_module:
            delattr(parent_module, child_name)


def _remove_package_modules(module_names: list[str]) -> None:
    """reload対象moduleをsys.modulesから削除する。"""
    # 深いmoduleから順にsys.modulesの登録を取り除く
    for name in sorted(
        module_names, key=lambda item: item.count("."), reverse=True
    ):
        sys.modules.pop(name, None)


def _reload_bd_util(clear_pycache: bool) -> ModuleType:
    """bd_utilをreloadして新しいpackage moduleを返す。"""
    # 任意指定された依存packageをruntimeで読み込む
    try:
        package = importlib.import_module("bd_util")
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "reload_util=True requires bakedanuki-util on PYTHONPATH."
        ) from error

    # bd_utilが公開するreload APIだけを型付きcallableとして取得する
    reload_function = cast(
        ReloadFunction | None,
        getattr(package, "reload_package", None),
    )
    if reload_function is None or not callable(reload_function):
        raise RuntimeError("bd_util.reload_package() is not available.")

    return reload_function(clear_pycache)


def reload_package(
    clear_pycache: bool = False,
    *,
    reload_util: bool = False,
) -> ModuleType:
    """:mod:`bd_tools`をreloadし、新しいpackage moduleを返す。

    引数:
        clear_pycache: 再import前に``__pycache__``を削除するかどうか。
        reload_util: ``bd_tools``の再構築前に``bd_util``もreloadするかどうか。
            toolsだけを変更した場合は無効のままにする。

    登録済みのlifecycle終了処理は、どちらのpackageよりも先に実行する。
    ``reload_util``が有効な場合は、``bd_util``、``bd_tools``の順でreloadする。
    """
    # Maya外部状態を破棄してからPython moduleへ触れる
    dispose_for_reload()

    # 明示指定された場合だけbytecode cacheを削除する
    if clear_pycache:
        _remove_pycache()

    # 外部参照を更新するため、古いpackageとmodule一覧を退避する
    old_package = sys.modules.get(PACKAGE_NAME)
    module_names = _get_package_module_names()

    # utilも変更された場合は、依存順に先にreloadする
    if reload_util:
        _reload_bd_util(clear_pycache)

    # 古いmodule参照をすべて外し、packageをimportし直す
    _remove_parent_module_attrs(module_names)
    _remove_package_modules(module_names)
    importlib.invalidate_caches()
    new_package = importlib.import_module(PACKAGE_NAME)

    # Mayaコンソール等が保持する古いpackage変数へ新しい内容を反映する
    if old_package is not None and old_package is not new_package:
        old_package.__dict__.clear()
        old_package.__dict__.update(new_package.__dict__)

    return new_package
