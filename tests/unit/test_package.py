# coding: utf-8
from __future__ import annotations

from pathlib import Path

import bd_tools


def test_package_metadata() -> None:
    """Python packageが公開するmetadataを確認する。"""
    assert bd_tools.__version__ == "0.1.0"
    assert "reload_package" in bd_tools.__all__
    assert "register_reload_disposer" in bd_tools.__all__


def test_maya_module_version_matches_python_package() -> None:
    """Maya Module定義とPython packageのmetadataを照合する。"""
    # Maya Module定義のheaderからpackage情報を取り出す
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "bakedanuki" / "modules" / "bd_tools.mod"
    module_header = module_path.read_text(encoding="utf-8").splitlines()[0]
    marker, module_name, module_version, package_root = module_header.split()

    # 配布定義とPython packageの名前・version・相対pathを一致させる
    assert marker == "+"
    assert module_name == "bd_tools"
    assert module_version == bd_tools.__version__
    assert package_root == "../bakedanuki-tools"
