# coding: utf-8
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from bd_util.ui import qt

_qt_application: qt.QApplication | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Widget用applicationを先に確保してMaya standaloneを初期化する。"""
    import maya.standalone

    from bd_util.ui import qt

    global _qt_application

    # MayaがQGuiApplicationを生成する前にQWidget用のapplicationを保持する
    application = qt.QApplication.instance()
    if application is None:
        application = qt.QApplication([])
    if not isinstance(application, qt.QApplication):
        raise RuntimeError("Maya UI testにはQApplicationが必要です")
    _qt_application = application

    # テストsessionで利用するMaya standaloneを一度だけ初期化する
    maya.standalone.initialize(name="python")


@pytest.fixture(scope="session")
def qt_application() -> qt.QApplication:
    """standaloneより先に生成されたQApplicationの寿命を維持する。"""
    if _qt_application is None:
        raise RuntimeError("Maya UI testのQApplicationが初期化されていません")
    return _qt_application
