# coding: utf-8
"""子を維持する移動・回転設定を一つのdockable Windowで扱う。"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Literal, Protocol, cast

from maya import cmds

from bd_util.maya.ui import (
    MayaCallbackRegistry,
    MayaDockableWindow,
    MayaUiStateTracker,
    create_ui_state_manager,
    get_ui_settings_file,
    register_open_tool,
    unregister_open_tool,
)
from bd_util.maya.ui.dock import workspace_control
from bd_util.ui import SettingsPath, qt

from .._dev.reopen_targets import CHILD_SET_REOPEN
from .._shared.window_position import centered_position_within_screen
from .types import ChildSetTarget
from .window import ChildCompensatedSetWindow

__all__ = [
    "ChildSetDockWindow",
    "ChildSetTab",
    "TRANSLATE_INITIAL_WIDTH",
    "TRANSLATE_INITIAL_HEIGHT",
    "ROTATION_INITIAL_WIDTH",
    "ROTATION_INITIAL_HEIGHT",
]

ChildSetTab = Literal["translate", "rotation"]

# 初回表示時だけ使う浮動workspaceControl全体のサイズ（Qt論理px）
TRANSLATE_INITIAL_WIDTH = 328
TRANSLATE_INITIAL_HEIGHT = 190
ROTATION_INITIAL_WIDTH = 328
ROTATION_INITIAL_HEIGHT = 274

_SETTINGS_PATH = SettingsPath("bd_child_compensated_set/main")
_REOPEN_OWNER, _REOPEN_TOOL_ID, _REOPEN_MODULE, _REOPEN_FUNCTION = (
    CHILD_SET_REOPEN
)


class _QTimerType(Protocol):
    """Qt bindingのstub境界で使用する遅延呼出しの型。"""

    @staticmethod
    def singleShot(milliseconds: int, callback: Callable[[], None]) -> None:
        """指定時間後にcallbackを一度呼び出す。"""
        raise NotImplementedError


def _run_later(callback: Callable[[], None]) -> None:
    """MayaとQtのlayout更新後に処理を一度実行する。"""
    cast(_QTimerType, qt.QTimer).singleShot(0, callback)


class _FloatingTabSizes:
    """移動・回転タブの浮動時サイズをtoolのINIへ保存する。"""

    def __init__(self) -> None:
        """初回値を用意し、保存済みの正の幅と高さを読み込む。"""
        self._settings = qt.QtCore.QSettings(
            str(get_ui_settings_file(_SETTINGS_PATH)),
            qt.QtCore.QSettings.Format.IniFormat,
        )
        self._sizes: dict[ChildSetTab, qt.QSize] = {
            "translate": qt.QSize(
                TRANSLATE_INITIAL_WIDTH, TRANSLATE_INITIAL_HEIGHT
            ),
            "rotation": qt.QSize(
                ROTATION_INITIAL_WIDTH, ROTATION_INITIAL_HEIGHT
            ),
        }
        self._settings.beginGroup(_SETTINGS_PATH.group_path)
        self._settings.beginGroup("floating_sizes")
        try:
            for tab, default in tuple(self._sizes.items()):
                width = self._read_dimension(f"{tab}/width", default.width())
                height = self._read_dimension(
                    f"{tab}/height", default.height()
                )
                self._sizes[tab] = qt.QSize(width, height)
        finally:
            self._settings.endGroup()
            self._settings.endGroup()

    def _read_dimension(self, key: str, default: int) -> int:
        """保存値が正の整数であれば採用し、それ以外は初回値を返す。"""
        candidate: object = self._settings.value(key, default, int)
        if (
            isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and candidate > 0
        ):
            return candidate
        return default

    def size(self, tab: ChildSetTab) -> qt.QSize:
        """指定タブの保存サイズまたは初回サイズを返す。"""
        return qt.QSize(self._sizes[tab])

    def remember(self, tab: ChildSetTab, size: qt.QSize) -> None:
        """ユーザーが変更した浮動サイズをメモリへ退避する。"""
        if size.width() > 0 and size.height() > 0:
            self._sizes[tab] = qt.QSize(size)

    def save(self) -> None:
        """両タブのサイズをMaya user preferencesのINIへ同期する。"""
        self._settings.beginGroup(_SETTINGS_PATH.group_path)
        self._settings.beginGroup("floating_sizes")
        try:
            for tab, size in self._sizes.items():
                self._settings.setValue(f"{tab}/width", size.width())
                self._settings.setValue(f"{tab}/height", size.height())
        finally:
            self._settings.endGroup()
            self._settings.endGroup()
        self._settings.sync()
        if self._settings.status() != qt.QtCore.QSettings.Status.NoError:
            raise RuntimeError(
                "子を維持する設定Windowのサイズを保存できません"
            )


class ChildSetDockWindow(MayaDockableWindow):
    """移動・回転タブとMayaのworkspaceControlを結ぶWindow。"""

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """2つの入力画面、タブ状態、浮動時のサイズ保存を初期化する。"""
        super().__init__(parent)
        self.setWindowTitle("移動・回転をセット（子を維持）")
        self.resize(TRANSLATE_INITIAL_WIDTH, TRANSLATE_INITIAL_HEIGHT)
        self._disposed = False
        self._attached = False
        self._initial_request_active = False
        self._applying_size = False
        self._size_change_serial = 0
        self._floating_host: qt.QWidget | None = None
        self._active_tab: ChildSetTab = "translate"
        self._requested: tuple[ChildSetTab, ChildSetTarget] | None = None
        self._initial_anchor: qt.QPoint | None = None
        self._reopen_token = object()

        self.tabs = qt.QTabWidget(self)
        # 非表示の回転ページが移動ページの最小Window高を決めないようにする
        self.tabs.setMinimumSize(0, 0)
        self.tabs.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Ignored
        )
        self.translate_page = ChildCompensatedSetWindow(
            self.tabs, initial_target="translate", as_page=True
        )
        self.rotation_page = ChildCompensatedSetWindow(
            self.tabs, initial_target="rotate", as_page=True
        )
        # ドック幅が小さくても非表示ページの最小寸法でMayaのパネルを広げない
        self.translate_scroll = self._scrollable_page(self.translate_page)
        self.rotation_scroll = self._scrollable_page(self.rotation_page)
        self.tabs.addTab(self.translate_scroll, "移動")
        self.tabs.addTab(self.rotation_scroll, "回転")
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

        self.ui_state = create_ui_state_manager(_SETTINGS_PATH)
        self.ui_state.register_tab_widget("active_tab", self.tabs)
        self.ui_state.register_combo_box(
            "translate_space", self.translate_page.space_combo
        )
        self.ui_state.register_combo_box(
            "rotation_space", self.rotation_page.space_combo
        )
        assert self.rotation_page.preservation_combo is not None
        self.ui_state.register_combo_box(
            "rotation_preservation", self.rotation_page.preservation_combo
        )
        assert self.rotation_page.joint_child_combo is not None
        self.ui_state.register_combo_box(
            "rotation_joint_child_compensation",
            self.rotation_page.joint_child_combo,
        )
        self.ui_state_tracker = MayaUiStateTracker.for_dockable(
            self.ui_state, self
        )
        self._sizes = _FloatingTabSizes()
        self._maya_lifecycle = MayaCallbackRegistry(
            self, on_maya_exiting=self._save_sizes
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.dock_attached.connect(self._on_dock_attached)
        self.floating_changed.connect(self._on_floating_changed)
        self.dock_closed.connect(self._shutdown)
        self.dock_about_to_dispose.connect(self._shutdown)

    def _scrollable_page(
        self, page: ChildCompensatedSetWindow
    ) -> qt.QScrollArea:
        """狭いドックでは内容をスクロールし、ドック寸法は変更しない。"""
        scroll = qt.QScrollArea(self.tabs)
        scroll.setFrameShape(qt.QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(0, 0)
        scroll.setSizePolicy(
            qt.QSizePolicy.Policy.Ignored, qt.QSizePolicy.Policy.Ignored
        )
        scroll.setWidget(page)
        return scroll

    @property
    def is_disposed(self) -> bool:
        """両ページのMaya監視が終了しているか返す。"""
        return self._disposed

    def register_reopen(self) -> None:
        """reload後に表示を戻すdockable toolとして登録する。"""
        register_open_tool(
            _REOPEN_OWNER,
            _REOPEN_TOOL_ID,
            _REOPEN_MODULE,
            _REOPEN_FUNCTION,
            token=self._reopen_token,
        )

    def _unregister_reopen(self) -> None:
        """終了したWindowをreload後の再表示対象から外す。"""
        unregister_open_tool(
            _REOPEN_OWNER, _REOPEN_TOOL_ID, token=self._reopen_token
        )

    def request_tab(self, tab: ChildSetTab, target: ChildSetTarget) -> None:
        """指定されたタブと設定先を保存状態より優先する。"""
        if tab == "translate" and target != "translate":
            raise ValueError("移動タブにはtranslateを指定してください")
        if tab == "rotation" and target not in (
            "rotate",
            "rotateAxis",
            "jointOrient",
        ):
            raise ValueError("回転属性を指定してください")
        self._requested = (tab, target)
        if self._attached:
            self._apply_request()

    def set_initial_anchor(self, position: qt.QPoint) -> None:
        """初回作成時だけ指定位置へ浮動枠を寄せる。"""
        self._initial_anchor = qt.QPoint(position)
        if self._attached:
            _run_later(self._position_initial_window)

    def _apply_request(self) -> None:
        """復元済みの選択タブより明示指定を優先する。"""
        requested = self._requested
        self._requested = None
        if requested is None:
            return
        tab, target = requested
        if tab == "rotation":
            self.rotation_page.set_initial_target(target)
        else:
            self.translate_page.set_initial_target("translate")
        index = 0 if tab == "translate" else 1
        if self.tabs.currentIndex() == index:
            self._active_tab = tab
            self._apply_floating_size(tab)
        else:
            self.tabs.setCurrentIndex(index)

    def _on_dock_attached(self) -> None:
        """utilのタブ復元が終わった次のイベントで初期表示を確定する。"""
        _run_later(self._finish_attachment)

    def _finish_attachment(self) -> None:
        """保存タブまたは明示指定タブのサイズと内容を反映する。"""
        if self._disposed:
            return
        self._attached = True
        self._active_tab = self._tab_for_index(self.tabs.currentIndex())
        if self._requested is not None:
            # 初回は未表示の旧タブへレイアウト変更後の寸法を記録しない
            self._initial_request_active = True
            try:
                self._apply_request()
            finally:
                self._initial_request_active = False
        else:
            self._page(self._active_tab).refresh()
            self._apply_floating_size(self._active_tab)
        if self._initial_anchor is not None:
            _run_later(self._position_initial_window)

    def _tab_for_index(self, index: int) -> ChildSetTab:
        """タブindexを設定用の安定した識別子へ変換する。"""
        return "rotation" if index == 1 else "translate"

    def _page(self, tab: ChildSetTab) -> ChildCompensatedSetWindow:
        """指定タブの入力画面を返す。"""
        return (
            self.translate_page if tab == "translate" else self.rotation_page
        )

    def _on_tab_changed(self, index: int) -> None:
        """旧タブのサイズを退避し、新タブの実値とサイズを反映する。"""
        tab = self._tab_for_index(index)
        if not self._attached:
            self._active_tab = tab
            return
        if tab != self._active_tab and not self._initial_request_active:
            self._capture_floating_size(self._active_tab)
        self._active_tab = tab
        self._page(tab).refresh()
        self._apply_floating_size(tab)

    def _on_floating_changed(self, floating: bool) -> None:
        """ドックから浮動枠へ戻ったとき選択タブのサイズを反映する。"""
        if floating and self._attached and not self._disposed:
            _run_later(partial(self._apply_floating_size, self._active_tab))
        elif not floating:
            self._unwatch_floating_host()

    def _workspace_name(self) -> str:
        """controllerが固定したMaya workspaceControl名を返す。"""
        return f"{self.objectName()}WorkspaceControl"

    def _is_floating(self) -> bool:
        """Mayaが管理する現在のcontrolが浮動状態か返す。"""
        name = self._workspace_name()
        try:
            return workspace_control.exists(
                name
            ) and workspace_control.is_floating(name)
        except (ValueError, TypeError, RuntimeError):
            return False

    def _read_floating_size(self) -> qt.QSize:
        """内側controlと区別して浮動枠そのものの寸法を返す。"""
        host = self._watch_floating_host()
        if host is None:
            raise RuntimeError("浮動workspaceControlの外枠を取得できません")
        return qt.QSize(host.size())

    def _watch_floating_host(self) -> qt.QWidget | None:
        """現在の浮動枠だけに手動リサイズ監視を接続する。"""
        host = workspace_control.find_floating_host(
            self._workspace_name(), self
        )
        if host is self._floating_host:
            return host
        self._unwatch_floating_host()
        self._floating_host = host
        if host is not None:
            host.installEventFilter(self)
        return host

    def _unwatch_floating_host(self) -> None:
        """ドック移動や終了時に古い浮動枠の監視を解除する。"""
        host = self._floating_host
        self._floating_host = None
        if host is not None and qt.isValid(host):
            host.removeEventFilter(self)

    def _resize_floating_control(self, size: qt.QSize) -> None:
        """Mayaの浮動workspaceControlへ選択タブの寸法を指定する。"""
        cmds.workspaceControl(
            self._workspace_name(),
            edit=True,
            resizeWidth=size.width(),
            resizeHeight=size.height(),
        )

    def _capture_floating_size(self, tab: ChildSetTab) -> None:
        """浮動中だけ現在の外枠寸法を該当タブへ保存する。"""
        if not self._attached or not self._is_floating():
            return
        try:
            self._sizes.remember(tab, self._read_floating_size())
        except (ValueError, TypeError, RuntimeError):
            return

    def _apply_floating_size(self, tab: ChildSetTab) -> None:
        """ドック中のMayaレイアウトを触らず浮動時だけサイズを切り替える。"""
        if not self._attached or not self._is_floating():
            return
        size = self._sizes.size(tab)
        screen = cast(qt.QtGui.QScreen | None, self.screen())
        if screen is not None:
            available = screen.availableGeometry()
            size.setWidth(min(size.width(), available.width()))
            size.setHeight(min(size.height(), available.height()))
        self._size_change_serial += 1
        serial = self._size_change_serial
        self._applying_size = True
        try:
            self._watch_floating_host()
            self._resize_floating_control(size)
        finally:
            _run_later(partial(self._finish_size_change, serial))

    def _finish_size_change(self, serial: int) -> None:
        """最新のタブ切替によるサイズ変更が終わったら手動変更を監視する。"""
        if serial == self._size_change_serial:
            self._watch_floating_host()
            self._applying_size = False

    def eventFilter(
        self, watched: qt.QtCore.QObject, event: qt.QtCore.QEvent
    ) -> bool:
        """浮動枠の手動変更だけを現在のタブへ退避する。"""
        if (
            watched is self._floating_host
            and event.type() == qt.QtCore.QEvent.Type.Resize
            and self._attached
            and not self._initial_request_active
            and not self._applying_size
            and self._is_floating()
        ):
            resize_event = cast(qt.QtGui.QResizeEvent, event)
            self._sizes.remember(self._active_tab, resize_event.size())
        return super().eventFilter(watched, event)

    def _position_initial_window(self) -> None:
        """初回の浮動枠だけ指定位置を中心として画面内へ置く。"""
        anchor = self._initial_anchor
        self._initial_anchor = None
        if anchor is None or not self._is_floating():
            return
        host = workspace_control.find_floating_host(
            self._workspace_name(), self
        )
        if host is None:
            return
        screen = cast(
            qt.QtGui.QScreen | None, qt.QtGui.QGuiApplication.screenAt(anchor)
        )
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, host.screen())
        if screen is None:
            return
        host.move(
            centered_position_within_screen(
                anchor, host.frameGeometry().size(), screen.availableGeometry()
            )
        )

    def _save_sizes(self) -> None:
        """終了前に表示中タブの寸法を加えて両タブのサイズを同期する。"""
        if not self._disposed:
            self._capture_floating_size(self._active_tab)
        self._sizes.save()

    def _shutdown(self) -> None:
        """Maya側のcloseまたは完全破棄で状態と監視を終了する。"""
        if self._disposed:
            return
        try:
            self._save_sizes()
        finally:
            self._disposed = True
            self._unwatch_floating_host()
            self._unregister_reopen()
            self.translate_page.dispose()
            self.rotation_page.dispose()
            self._maya_lifecycle.dispose()

    def closeEvent(self, event: qt.QCloseEvent) -> None:
        """Qt側から閉じた場合もサイズとMaya callbackを残さない。"""
        self._shutdown()
        super().closeEvent(event)
