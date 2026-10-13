# coding: utf-8
"""即時反映する変換値Windowの選択監視とXYZ入力部品。"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import cast

from maya.api import OpenMaya as om

from bd_util.maya.node import selected_node_names
from bd_util.maya.ui import MayaCallbackRegistry
from bd_util.ui import FloatValueStepSpinBox, FloatViewModel, qt

from .window_position import centered_position_within_screen

__all__ = ["LiveSetWindowBase", "LiveXyzEditor"]

_Values = tuple[float, float, float]


class LiveXyzEditor(qt.QWidget):
    """表示値のXYZと独立したStepを並べ、入力要求を外側へ渡す。"""

    def __init__(
        self,
        parent: qt.QWidget | None = None,
        *,
        angle: bool,
    ) -> None:
        """距離または角度の既定Stepで、3軸の入力欄を作る。"""
        super().__init__(parent)
        self._value_handler: Callable[[int, float], None] | None = None
        self._step_handler: Callable[[int, int, float], None] | None = None
        self._models = tuple(FloatViewModel(0.0, self) for _ in range(3))
        # 値欄の長いsizeHintでStep欄がWindow外へ押し出されないよう幅を固定
        self.value_editors = tuple(
            FloatValueStepSpinBox(
                model,
                self,
                decimals=15,
                single_step=15.0 if angle else 1.0,
                step_mode="additive" if angle else "multiplicative",
                step_increment=15.0 if angle else 1.0,
                value_wheel_requires_focus=True,
                step_wheel_requires_focus=True,
                value_select_all_on_mouse_focus=True,
                step_select_all_on_mouse_focus=True,
                value_width=150,
                step_width=60,
            )
            for model in self._models
        )
        self.value_spins = tuple(
            editor.spin_box for editor in self.value_editors
        )
        self.step_spins = tuple(
            editor.step_spin_box for editor in self.value_editors
        )

        layout = qt.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setVerticalSpacing(2)
        self.setSizePolicy(
            qt.QSizePolicy.Policy.Preferred, qt.QSizePolicy.Policy.Fixed
        )
        for axis, editor in enumerate(self.value_editors):
            label = qt.QLabel("XYZ"[axis], self)
            layout.addWidget(label, axis, 0)
            layout.addWidget(editor, axis, 1)
            editor.spin_box.setAccessibleName(f"{'XYZ'[axis]} 値")
            editor.step_spin_box.setAccessibleName(f"{'XYZ'[axis]} Step")
            editor.step_spin_box.setToolTip(
                "値欄のホイール・上下操作の刻み幅。Stepの変更ではsceneを変更しません"
            )
            editor.spin_box.setValueRequestHandler(
                partial(self._request_value, axis)
            )
            editor.spin_box.setStepRequestHandler(
                partial(self._request_step, axis)
            )
        layout.setColumnStretch(1, 1)

    def set_value_handler(
        self, handler: Callable[[int, float], None] | None
    ) -> None:
        """確定した表示値を受ける処理を設定する。"""
        self._value_handler = handler

    def set_step_handler(
        self, handler: Callable[[int, int, float], None] | None
    ) -> None:
        """ホイール・上下操作のstep数を受ける処理を設定する。"""
        self._step_handler = handler

    def _request_value(self, axis: int, value: float) -> bool:
        """外側へ絶対値入力を渡し、メモリ正本への二重入力を止める。"""
        handler = self._value_handler
        if handler is not None:
            handler(axis, value)
        return True

    def _request_step(self, axis: int, steps: int) -> bool:
        """現在の表示Stepを添えて相対入力を外側へ渡す。"""
        handler = self._step_handler
        if handler is not None:
            handler(axis, steps, self.value_editors[axis].singleStep())
        return True

    def set_values(self, values: _Values) -> None:
        """同じ値の編集中文字を残し、変化したXYZだけ表示更新する。"""
        for model, value in zip(self._models, values):
            model.set_value_command.execute(value)

    def discard_pending_input(self) -> None:
        """旧ノードに対する未確定文字を破棄して確定値へ戻す。"""
        for model, spin in zip(self._models, self.value_spins):
            blocker = qt.QtCore.QSignalBlocker(spin)
            try:
                spin.setValue(model.value.value)
                line_edit = spin.lineEdit()
                line_edit.setText(spin.textFromValue(model.value.value))
                line_edit.setModified(False)
            finally:
                del blocker

    def set_input_enabled(self, enabled: bool) -> None:
        """Stepの設定を許したまま、値欄の入力だけ切り替える。"""
        for spin in self.value_spins:
            spin.setInputEnabled(enabled)

    def dispose(self) -> None:
        """値入力ViewModelを終了し、遅れて届く要求を止める。"""
        for model in self._models:
            model.dispose()


class LiveSetWindowBase(qt.QWidget):
    """Mayaの選択・Undo・scene変更に追従する入力画面の基底。"""

    selection_invalidated = qt.Signal()
    units_invalidated = qt.Signal()
    refresh_requested = qt.Signal()

    def __init__(
        self, parent: qt.QWidget | None = None, *, as_page: bool = False
    ) -> None:
        """選択監視と通常Window時の指定位置基準配置を初期化する。"""
        super().__init__(parent)
        if not as_page:
            self.setWindowFlag(qt.Qt.WindowType.Window, True)
        self._anchor_position: qt.QPoint | None = None
        self._disposed = False
        self._refresh_timer = qt.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_requested.emit)
        self._events = MayaCallbackRegistry(self)
        self._watched_node_name: str | None = None
        self._watched_node = MayaCallbackRegistry(self)
        try:
            self._events.register(
                om.MEventMessage.addEventCallback(
                    "SelectionChanged", self._on_selection_changed
                )
            )
            for event in ("Undo", "Redo", "timeChanged"):
                self._events.register(
                    om.MEventMessage.addEventCallback(
                        event, self.queue_refresh
                    )
                )
            for event in ("linearUnitChanged", "angularUnitChanged"):
                self._events.register(
                    om.MEventMessage.addEventCallback(
                        event, self._on_units_changed
                    )
                )
            for message in (
                om.MSceneMessage.kBeforeNew,
                om.MSceneMessage.kBeforeOpen,
            ):
                self._events.register(
                    om.MSceneMessage.addCallback(message, self._before_scene)
                )
            for message in (
                om.MSceneMessage.kAfterNew,
                om.MSceneMessage.kAfterOpen,
            ):
                self._events.register(
                    om.MSceneMessage.addCallback(message, self.queue_refresh)
                )
        except Exception:
            LiveSetWindowBase.dispose(self)
            raise

    @property
    def is_disposed(self) -> bool:
        """Maya監視と入力が終了済みか返す。"""
        return self._disposed

    def selected_node_name(self) -> str | None:
        """現在選択の末尾にある基準ノードを返す。"""
        names = selected_node_names()
        return names[-1] if names else None

    def watch_node(self, node_name: str | None) -> None:
        """表示対象の属性変更を監視し、外部の値編集も再取得する。"""
        if self._disposed or node_name == self._watched_node_name:
            return
        self._watched_node.dispose()
        self._watched_node.deleteLater()
        self._watched_node = MayaCallbackRegistry(self)
        self._watched_node_name = None
        if node_name is None:
            return
        selection = om.MSelectionList()
        selection.add(node_name)
        node = selection.getDependNode(0)
        self._watched_node.register(
            om.MNodeMessage.addAttributeChangedCallback(
                node, self._on_attribute_changed
            )
        )
        self._watched_node_name = node_name

    def _on_attribute_changed(
        self,
        message: int,
        _plug: om.MPlug,
        _other: om.MPlug,
        *_args: object,
    ) -> None:
        """監視中ノードの値変更を次のQtイベントでまとめて反映する。"""
        if message & om.MNodeMessage.kAttributeSet:
            self.queue_refresh()

    def queue_refresh(self, *_args: object) -> None:
        """複数のMaya通知を次のQtイベントで一度の再取得にまとめる。"""
        if not self._disposed:
            self._refresh_timer.start(0)

    def _on_selection_changed(self, *_args: object) -> None:
        """古い文字入力を先に無効化し、現在選択の再取得を予約する。"""
        if self._disposed:
            return
        self.selection_invalidated.emit()
        self.queue_refresh()

    def _on_units_changed(self, *_args: object) -> None:
        """表示単位が変わったとき旧単位の入力文字を捨てて再取得する。"""
        if self._disposed:
            return
        self.units_invalidated.emit()
        self.queue_refresh()

    def _before_scene(self, *_args: object) -> None:
        """scene切替前に古い対象の入力と再取得を停止する。"""
        if self._disposed:
            return
        self._refresh_timer.stop()
        self.selection_invalidated.emit()
        self.watch_node(None)

    def set_anchor_position(self, position: qt.QPoint) -> None:
        """指定位置を記録し、画面内へWindowを配置する。"""
        self._anchor_position = qt.QPoint(position.x(), position.y())
        self._position_near_anchor()

    def showEvent(self, event: qt.QtGui.QShowEvent) -> None:
        """表示後のウィンドウ枠寸法で配置を補正する。"""
        super().showEvent(event)
        self._position_near_anchor()

    def changeEvent(self, event: qt.QEvent) -> None:
        """MayaからWindowへ戻った際に外部変更を読み直す。"""
        super().changeEvent(event)
        if event.type() == qt.QEvent.Type.WindowActivate:
            self.queue_refresh()

    def _position_near_anchor(self) -> None:
        """指定位置を中心にし、モニター端からはみ出さないよう移動する。"""
        anchor = self._anchor_position
        if anchor is None:
            return
        application = qt.QtGui.QGuiApplication.instance()
        if not isinstance(application, qt.QtGui.QGuiApplication):
            return
        screen = cast(
            qt.QtGui.QScreen | None,
            qt.QtGui.QGuiApplication.screenAt(anchor),
        )
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, self.screen())
        if screen is None:
            screen = cast(qt.QtGui.QScreen | None, application.primaryScreen())
        if screen is None or screen.availableGeometry().isEmpty():
            return
        self.move(
            centered_position_within_screen(
                anchor, self.frameGeometry().size(), screen.availableGeometry()
            )
        )

    def dispose(self) -> None:
        """Windowが所有するMaya callbackと再取得を終了する。"""
        if self._disposed:
            return
        self._disposed = True
        self._refresh_timer.stop()
        self._watched_node.dispose()
        self._events.dispose()

    def closeEvent(self, event: qt.QCloseEvent) -> None:
        """通常の終了でもMaya callbackを即座に解除する。"""
        self.dispose()
        super().closeEvent(event)
