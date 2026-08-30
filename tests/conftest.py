# coding: utf-8
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_PYTHON_DIR = ROOT_DIR / "bakedanuki" / "bakedanuki-tools" / "python"


def _resolve_util_root() -> Path | None:
    """利用可能なbakedanuki-utilのrepository rootを返す。"""
    # 明示されたutil rootをsibling探索より優先する
    configured_root = os.environ.get("BAKEDANUKI_UTIL_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    sibling_root = ROOT_DIR.parent / "bakedanuki-util"
    if sibling_root.is_dir():
        return sibling_root.resolve()
    return None


def _prepend_python_path(path: Path) -> None:
    """指定pathをimport探索pathの先頭へ重複なく追加する。"""
    # 同じpathを重複させず、開発中packageをimport探索の先頭へ置く
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


# 最初にテスト対象のtools packageを解決できるようにする
_prepend_python_path(TOOLS_PYTHON_DIR)

# 利用可能な場合は、依存するutil packageも同じ方法で解決する
UTIL_ROOT = _resolve_util_root()
if UTIL_ROOT is not None:
    util_python_dir = UTIL_ROOT / "bakedanuki" / "bakedanuki-util" / "python"
    if util_python_dir.is_dir():
        _prepend_python_path(util_python_dir)
