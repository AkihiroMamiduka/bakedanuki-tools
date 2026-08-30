# coding: utf-8
from __future__ import annotations

import pytest

pytestmark = pytest.mark.maya


def test_maya_runtime_and_package_dependencies_import() -> None:
    """Maya runtimeからtools、util、Qt facadeをimportできることを確認する。"""
    import maya.api.OpenMaya as om

    import bd_tools
    import bd_util
    from bd_util.ui import qt

    assert om.MGlobal.apiVersion() > 0
    assert bd_tools.__version__
    assert bd_util.__version__
    assert qt.QT_BINDING.startswith("PySide")


def test_reload_can_rebuild_util_before_tools() -> None:
    """utilとtoolsを依存順にreloadできることを確認する。"""
    import sys

    import bd_tools

    # utilとtoolsを依存順に再構築し、toolsの参照が更新されることを確認する
    original_tools = bd_tools
    reloaded_tools = bd_tools.reload_package(reload_util=True)

    assert reloaded_tools is sys.modules["bd_tools"]
    assert reloaded_tools is not original_tools
    assert original_tools.__version__ == reloaded_tools.__version__
