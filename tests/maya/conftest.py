# coding: utf-8
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

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

    # Windowsのoffscreen backendは標準フォントを列挙しない場合がある
    if (
        application.platformName() == "offscreen"
        and not qt.QtGui.QFontDatabase.families()
    ):
        font_path = Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"
        font_id = qt.QtGui.QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            raise RuntimeError(f"配置検証用フォントを読めません: {font_path}")
        set_font = cast(
            Callable[[qt.QFont], None], getattr(application, "setFont")
        )
        set_font(qt.QtGui.QFont("Segoe UI", 9))

    # テストsessionで利用するMaya standaloneを一度だけ初期化する
    maya.standalone.initialize(name="python")


@pytest.fixture(scope="session")
def qt_application() -> qt.QApplication:
    """standaloneより先に生成されたQApplicationの寿命を維持する。"""
    if _qt_application is None:
        raise RuntimeError("Maya UI testのQApplicationが初期化されていません")
    return _qt_application


@pytest.fixture(autouse=True)
def isolated_ui_preferences(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """設定をテストごとに分離し、フィルター選択の保存がほかの検証へ漏れるのを防ぐ。"""
    from bd_util.maya.ui import settings as maya_settings

    def settings_root() -> Path:
        """現在のテストだけが使用する設定フォルダーを返す。"""
        return tmp_path / "tool-preferences"

    monkeypatch.setattr(maya_settings, "get_ui_settings_root", settings_root)
