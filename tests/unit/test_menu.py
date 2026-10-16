# coding: utf-8
from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

import bd_tools
from bd_tools import _startup, menu


@pytest.fixture
def menu_icon_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, Path]:
    """ツール本体とutilを読み込まず、各ツールの画像定数を差し替える。"""
    paths: dict[str, Path] = {}
    for name in (
        "bd_channel_box",
        "bd_child_compensated_set",
        "bd_rotation_preserving_pose",
    ):
        package = ModuleType(f"bd_tools.{name}")
        icon = ModuleType(f"{package.__name__}.icon")
        path = tmp_path / f"{name}-menu.png"
        monkeypatch.setattr(icon, "MENU", path, raising=False)
        monkeypatch.setattr(package, "icon", icon, raising=False)
        monkeypatch.setitem(sys.modules, package.__name__, package)
        monkeypatch.setattr(bd_tools, name, package, raising=False)
        paths[name] = path
    return paths


def test_menu_registration_is_owned_by_tools_and_lazily_opens_each_tool(
    monkeypatch: pytest.MonkeyPatch,
    menu_icon_paths: dict[str, Path],
) -> None:
    """3項目の再登録・解除とクリック時の遅延importを確認する。"""
    registrations: list[tuple[str, str, str, str, Callable[[], object]]] = []
    removed_owners: list[str] = []
    shown: list[str] = []
    icon_paths: list[Path] = []
    fake_ui = ModuleType("bd_util.maya.ui")
    fake_channel_box = sys.modules["bd_tools.bd_channel_box"]
    fake_child_set = sys.modules["bd_tools.bd_child_compensated_set"]
    fake_rotation_set = sys.modules["bd_tools.bd_rotation_preserving_pose"]

    def register_menu_item(
        *,
        owner: str,
        category: str,
        item_id: str,
        label: str,
        command: Callable[[], object],
        icon_path: Path,
    ) -> bool:
        """登録引数を保持する偽の共通メニューAPI。"""
        registrations.append((owner, category, item_id, label, command))
        icon_paths.append(icon_path)
        return True

    def unregister_menu_owner(owner: str) -> None:
        """解除対象の所有者を記録する。"""
        removed_owners.append(owner)

    def show_channel_box() -> None:
        """クリックでだけ呼び出される偽のbdChannelBox。"""
        shown.append("bdChannelBox")

    def show_child_set() -> None:
        """クリックでだけ呼び出される偽の子維持ツール。"""
        shown.append("bdChildCompensatedSet")

    def show_rotation_set() -> None:
        """クリックでだけ呼び出される偽の姿勢維持ツール。"""
        shown.append("bdRotationPreservingPose")

    monkeypatch.setitem(sys.modules, "bd_util.maya.ui", fake_ui)
    monkeypatch.setattr(
        fake_ui, "register_menu_item", register_menu_item, raising=False
    )
    monkeypatch.setattr(
        fake_ui, "unregister_menu_owner", unregister_menu_owner, raising=False
    )
    monkeypatch.setattr(
        fake_channel_box, "show", show_channel_box, raising=False
    )
    monkeypatch.setattr(fake_child_set, "show", show_child_set, raising=False)
    monkeypatch.setattr(
        fake_rotation_set, "show", show_rotation_set, raising=False
    )

    try:
        assert bd_tools.install_menu()
        assert bd_tools.install_menu()
        assert menu.was_menu_installed()
        assert len(registrations) == 6
        assert [registration[:4] for registration in registrations[:3]] == [
            ("bd_tools", "tools", "bdChannelBox", "bdChannelBox"),
            (
                "bd_tools",
                "tools",
                "bdChildCompensatedSet",
                "移動・回転をセット（子を維持）",
            ),
            (
                "bd_tools",
                "tools",
                "bdRotationPreservingPose",
                "回転をセット（姿勢を維持）",
            ),
        ]
        assert [registration[:4] for registration in registrations[3:]] == [
            registration[:4] for registration in registrations[:3]
        ]
        assert not shown
        expected_icons = list(menu_icon_paths.values())
        assert icon_paths == expected_icons * 2
        for registration in registrations[3:]:
            registration[4]()
        assert shown == [
            "bdChannelBox",
            "bdChildCompensatedSet",
            "bdRotationPreservingPose",
        ]
    finally:
        bd_tools.uninstall_menu()

    assert removed_owners == ["bd_tools"]
    assert not menu.was_menu_installed()


def test_menu_registration_cleans_up_after_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    menu_icon_paths: dict[str, Path],
) -> None:
    """途中の登録失敗ではtools所有項目を残さない。"""
    registered_ids: list[str] = []
    removed_owners: list[str] = []
    fake_ui = ModuleType("bd_util.maya.ui")

    def register_menu_item(
        *,
        owner: str,
        category: str,
        item_id: str,
        label: str,
        command: Callable[[], object],
        icon_path: Path,
    ) -> bool:
        """2項目目だけUI未生成として失敗させる。"""
        registered_ids.append(item_id)
        return len(registered_ids) != 2

    def unregister_menu_owner(owner: str) -> None:
        """失敗時に解除した所有者を記録する。"""
        removed_owners.append(owner)

    monkeypatch.setitem(sys.modules, "bd_util.maya.ui", fake_ui)
    monkeypatch.setattr(
        fake_ui, "register_menu_item", register_menu_item, raising=False
    )
    monkeypatch.setattr(
        fake_ui, "unregister_menu_owner", unregister_menu_owner, raising=False
    )

    assert not bd_tools.install_menu()
    assert registered_ids == ["bdChannelBox", "bdChildCompensatedSet"]
    assert removed_owners == ["bd_tools"]
    assert not menu.was_menu_installed()


def test_user_setup_does_not_leave_package_names_in_main_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mayaが共有する__main__辞書へパッケージ名を残さない。"""
    scheduled: list[bool] = []

    def schedule() -> None:
        """起動hookの呼出しを記録する。"""
        scheduled.append(True)

    monkeypatch.setattr(_startup, "schedule_menu_install", schedule)
    path = (
        Path(__file__).resolve().parents[2]
        / "bakedanuki"
        / "bakedanuki-tools"
        / "scripts"
        / "userSetup.py"
    )
    namespace: dict[str, object] = {"__name__": "__main__"}

    exec(
        compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace
    )

    assert scheduled == [True]
    assert set(namespace) == {"__name__", "__builtins__"}

    # 起動hookの失敗も後続のuserSetup.pyへ伝播させない
    errors: list[bool] = []

    def fail_to_schedule() -> None:
        """起動hookの例外を再現する。"""
        raise RuntimeError("startup failed")

    def record_error() -> None:
        """記録されたtracebackの回数を数える。"""
        errors.append(True)

    monkeypatch.setattr(_startup, "schedule_menu_install", fail_to_schedule)
    monkeypatch.setattr(traceback, "print_exc", record_error)
    exec(
        compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace
    )

    assert errors == [True]
    assert set(namespace) == {"__name__", "__builtins__"}


def test_startup_skips_batch_and_defers_interactive_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """batchを除外し、interactive時はMayaのdeferred queueを使う。"""
    callbacks: list[Callable[[], None]] = []
    installed: list[bool] = []
    fake_maya = ModuleType("maya")
    fake_cmds = ModuleType("maya.cmds")
    fake_utils = ModuleType("maya.utils")
    fake_util_ui = ModuleType("bd_util.maya.ui")
    auto_install_enabled = [True]
    ensured: list[bool] = []

    def ensure_config_file() -> Path:
        """起動設定の初回作成を記録する。"""
        ensured.append(True)
        return Path("config.toml")

    def is_menu_auto_install_enabled() -> bool:
        """共有設定で起動時表示が有効か返す。"""
        return auto_install_enabled[0]

    def about_batch(*, batch: bool) -> bool:
        """batch起動を返す。"""
        return True

    def about_interactive(*, batch: bool) -> bool:
        """interactive起動を返す。"""
        return False

    def execute_deferred(callback: Callable[[], None]) -> None:
        """Mayaのdeferred queueへの登録を記録する。"""
        callbacks.append(callback)

    def install_menu() -> bool:
        """遅延実行された登録を記録する。"""
        installed.append(True)
        return True

    monkeypatch.setitem(sys.modules, "maya", fake_maya)
    monkeypatch.setitem(sys.modules, "bd_util.maya.ui", fake_util_ui)
    monkeypatch.setattr(fake_maya, "cmds", fake_cmds, raising=False)
    monkeypatch.setattr(fake_maya, "utils", fake_utils, raising=False)
    monkeypatch.setattr(
        fake_utils, "executeDeferred", execute_deferred, raising=False
    )
    monkeypatch.setattr(fake_cmds, "about", about_batch, raising=False)
    monkeypatch.setattr(
        fake_util_ui,
        "is_menu_auto_install_enabled",
        is_menu_auto_install_enabled,
        raising=False,
    )
    monkeypatch.setattr(
        fake_util_ui,
        "ensure_config_file",
        ensure_config_file,
        raising=False,
    )
    monkeypatch.setattr(menu, "install_menu", install_menu)

    _startup.schedule_menu_install()
    assert not callbacks

    monkeypatch.setattr(fake_cmds, "about", about_interactive)
    _startup.schedule_menu_install()
    assert len(callbacks) == 1
    assert not installed
    callbacks[0]()
    assert installed == [True]
    assert ensured == [True]

    auto_install_enabled[0] = False
    _startup.schedule_menu_install()
    callbacks[1]()
    assert installed == [True]
    assert ensured == [True, True]
