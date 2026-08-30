# coding: utf-8
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Maya runtime test用にstandalone環境を初期化する。"""
    # Maya runtimeを利用できないinterpreterでは初期化を行わない
    try:
        import maya.standalone
    except Exception:
        return

    # テストsessionで利用するMaya standaloneを一度だけ初期化する
    try:
        maya.standalone.initialize(name="python")
    except Exception:
        pass
