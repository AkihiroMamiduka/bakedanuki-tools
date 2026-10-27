# coding: utf-8
"""登録の表示状態と行選択を独立して操作する一覧を提供する。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from bd_util.ui import add_path_actions, qt

__all__ = ["CustomFilterRegistrationTree", "create_manager_tool_button"]

_ICON_SIZE = 16
_TOGGLE_SIZE = 20


def _ignore_maya_space(event: qt.QEvent) -> bool:
    """Spaceの予約・押下・解放をQtの操作に使わずMayaへ受け流す。"""
    if (
        isinstance(event, qt.QtGui.QKeyEvent)
        and event.key() == qt.Qt.Key.Key_Space
        and event.type()
        in (
            qt.QEvent.Type.ShortcutOverride,
            qt.QEvent.Type.KeyPress,
            qt.QEvent.Type.KeyRelease,
        )
    ):
        event.ignore()
        return True
    return False


class _ManagerToolButton(qt.QToolButton):
    """SpaceだけをMayaへ渡し、それ以外の標準ボタン操作を保持する。"""

    def event(self, e: qt.QEvent) -> bool:
        """管理画面のSpaceでボタンを押さず、Mayaのショートカットへ渡す。"""
        if _ignore_maya_space(e):
            return False
        return super().event(e)


def create_manager_tool_button(parent: qt.QWidget) -> qt.QToolButton:
    """SpaceをMayaへ渡す管理画面専用ボタンを標準の公開型で返す。"""
    return _ManagerToolButton(parent)


class _VisibilityStyleOption(Protocol):
    """同梱stubにないQtの公開描画属性を使用範囲だけで型付けする。"""

    features: qt.QtWidgets.QStyleOptionViewItem.ViewItemFeature
    decorationSize: qt.QSize
    icon: qt.QIcon
    checkState: qt.Qt.CheckState


class _PathStyleOption(Protocol):
    """同梱stubにないパス描画の省略位置だけを型付けする。"""

    textElideMode: qt.Qt.TextElideMode


class _StatusStyleOption(Protocol):
    """選択中も状態列の文字色を維持する公開palette属性を型付けする。"""

    palette: qt.QPalette


class _LoadStatusDelegate(qt.QStyledItemDelegate):
    """読込エラーの文字色を、行選択のハイライト上でも維持する。"""

    def initStyleOption(
        self,
        option: qt.QtWidgets.QStyleOptionViewItem,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> None:
        """明示した前景色がある状態だけ、選択時の文字色にも適用する。"""
        super().initStyleOption(option, index)
        brush: object = index.data(qt.Qt.ItemDataRole.ForegroundRole)
        if (
            isinstance(brush, qt.QtGui.QBrush)
            and brush.style() != qt.Qt.BrushStyle.NoBrush
        ):
            cast(_StatusStyleOption, option).palette.setBrush(
                qt.QPalette.ColorRole.HighlightedText, brush
            )


class _FilePathDelegate(qt.QStyledItemDelegate):
    """実パスを保持したまま、末尾のファイル名を優先して描画する。"""

    def initStyleOption(
        self,
        option: qt.QtWidgets.QStyleOptionViewItem,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> None:
        """パス列だけを左側省略にし、他の列の省略規則を変えない。"""
        super().initStyleOption(option, index)
        cast(_PathStyleOption, option).textElideMode = (
            qt.Qt.TextElideMode.ElideLeft
        )


class _VisibilityDelegate(qt.QStyledItemDelegate):
    """標準チェックの状態を維持し、目のアイコンで描画する。"""

    def __init__(self, parent: qt.QWidget) -> None:
        """表示と非表示を示すMaya同梱アイコンを保持する。"""
        super().__init__(parent)
        self._visible_icon = qt.QIcon(":/ghostingVisible.png")
        self._hidden_icon = qt.QIcon(":/ghostingHidden.png")

    def initStyleOption(
        self,
        option: qt.QtWidgets.QStyleOptionViewItem,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> None:
        """アクセシビリティ用のチェック状態を残し、絵だけを置き換える。"""
        super().initStyleOption(option, index)
        styled = cast(_VisibilityStyleOption, option)
        feature = qt.QtWidgets.QStyleOptionViewItem.ViewItemFeature
        styled.features &= ~feature.HasCheckIndicator
        styled.features |= feature.HasDecoration
        # アイコンは16四方で描き、横幅20の操作領域と本文を分離する
        styled.decorationSize = qt.QSize(_TOGGLE_SIZE, _ICON_SIZE)
        styled.icon = (
            self._visible_icon
            if styled.checkState == qt.Qt.CheckState.Checked
            else self._hidden_icon
        )

    def sizeHint(
        self,
        option: qt.QtWidgets.QStyleOptionViewItem,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> qt.QSize:
        """目の操作領域が隣の行へはみ出さない高さと余白を確保する。"""
        size = super().sizeHint(option, index)
        return qt.QSize(size.width() + 4, max(size.height(), _TOGGLE_SIZE + 2))

    def editorEvent(
        self,
        event: qt.QEvent,
        model: qt.QAbstractItemModel,
        option: qt.QtWidgets.QStyleOptionViewItem,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> bool:
        """標準チェック領域や行全体からの二重切替を防ぐ。"""
        del event, model, option, index
        return False


class CustomFilterRegistrationTree(qt.QTreeWidget):
    """目の操作で複数選択を崩さず、表示状態だけを切り替える。"""

    visibility_clicked = qt.Signal(object)

    def __init__(
        self, parent: qt.QWidget, *, show_visibility: bool = True
    ) -> None:
        """必要な一覧だけに目を描き、Mayaへ届くキー操作を共用する。"""
        super().__init__(parent)
        self._show_visibility = show_visibility
        self._visibility_delegate = _VisibilityDelegate(self)
        if show_visibility:
            self.setItemDelegateForColumn(0, self._visibility_delegate)
        self._path_delegate = _FilePathDelegate(self)
        self.setItemDelegateForColumn(1, self._path_delegate)
        self._status_delegate = _LoadStatusDelegate(self)
        self.setItemDelegateForColumn(2, self._status_delegate)
        self._eye_gesture = False
        self._eye_press: qt.QtCore.QPersistentModelIndex | None = None
        self._eye_press_position = qt.QPoint()

    def _visibility_rect(self, index: qt.QModelIndex) -> qt.QRect:
        """目を持つ一覧だけ、名前セル左端の操作領域を返す。"""
        if (
            not self._show_visibility
            or not index.isValid()
            or index.column() != 0
        ):
            return qt.QRect()
        cell = self.visualRect(index)
        rect = qt.QRect(
            cell.left() + 2,
            cell.top() + max((cell.height() - _TOGGLE_SIZE) // 2, 0),
            _TOGGLE_SIZE,
            _TOGGLE_SIZE,
        )
        return rect.intersected(cell)

    def _visibility_index_at(self, position: qt.QPoint) -> qt.QModelIndex:
        """目の範囲内だけを切替対象とし、名前や余白は対象外にする。"""
        index = self.indexAt(position)
        if self._visibility_rect(index).contains(position):
            return index
        return qt.QModelIndex()

    def _toggle_visibility(self, index: qt.QModelIndex) -> None:
        """選択対象と切替後の状態の決定を、管理画面へ依頼する。"""
        if not index.isValid():
            return
        item = cast(qt.QTreeWidgetItem | None, self.itemFromIndex(index))
        if item is None or item.isDisabled():
            return
        if not item.flags() & qt.Qt.ItemFlag.ItemIsUserCheckable:
            return
        self.visibility_clicked.emit(item)

    def mousePressEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        """右クリックで選択を変えず、目の左押下を切替候補として記憶する。"""
        self._eye_gesture = False
        self._eye_press = None
        if event.button() == qt.Qt.MouseButton.RightButton:
            event.accept()
            return
        position = event.position().toPoint()
        index = self._visibility_index_at(position)
        if index.isValid():
            self._eye_gesture = True
            if event.button() == qt.Qt.MouseButton.LeftButton:
                self._eye_press = qt.QtCore.QPersistentModelIndex(index)
                self._eye_press_position = position
                self.setFocus(qt.Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        """目からのドラッグを行選択へ渡さず、距離超過時は切替を中止する。"""
        if self._eye_gesture:
            distance = (
                event.position().toPoint() - self._eye_press_position
            ).manhattanLength()
            if distance >= qt.QApplication.startDragDistance():
                self._eye_press = None
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        """同じ目を左で押して離したときだけ一度切り替える。"""
        if event.button() == qt.Qt.MouseButton.RightButton:
            event.accept()
            return
        if self._eye_gesture:
            pressed = self._eye_press
            self._eye_gesture = False
            self._eye_press = None
            index = self._visibility_index_at(event.position().toPoint())
            if (
                event.button() == qt.Qt.MouseButton.LeftButton
                and pressed is not None
                and pressed.isValid()
                and qt.QtCore.QPersistentModelIndex(index) == pressed
            ):
                self._toggle_visibility(index)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: qt.QtGui.QMouseEvent) -> None:
        """目のダブルクリックを消費し、一回目の切替を打ち消さない。"""
        if event.button() == qt.Qt.MouseButton.RightButton:
            event.accept()
            return
        if self._visibility_index_at(event.position().toPoint()).isValid():
            self._eye_gesture = True
            self._eye_press = None
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, arg__1: qt.QtGui.QContextMenuEvent) -> None:
        """選択と現在行を変えず、右クリックした行の表示パスだけを操作する。"""
        event = arg__1
        item = cast(
            qt.QTreeWidgetItem | None,
            (
                self.currentItem()
                if event.reason() == qt.QtGui.QContextMenuEvent.Reason.Keyboard
                else self.itemAt(event.pos())
            ),
        )
        if item is not None and item.text(1):
            menu = qt.QMenu(self)
            try:
                add_path_actions(menu, item.text(1), event.globalPos())
                execute = cast(
                    Callable[[qt.QPoint], qt.QAction | None],
                    getattr(menu, "exec"),
                )
                execute(event.globalPos())
            finally:
                menu.deleteLater()
        event.accept()

    def event(self, e: qt.QEvent) -> bool:
        """SpaceをMayaへ受け流し、非活性化では未完了の入力状態を解除する。"""
        if _ignore_maya_space(e):
            return False
        if e.type() in (
            qt.QEvent.Type.Hide,
            qt.QEvent.Type.WindowDeactivate,
            qt.QEvent.Type.FocusOut,
            qt.QEvent.Type.UngrabMouse,
        ):
            self._eye_gesture = False
            self._eye_press = None
        return super().event(e)

    def viewportEvent(self, event: qt.QEvent) -> bool:
        """目の範囲だけに現在の表示設定と操作方法を案内する。"""
        if event.type() in (
            qt.QEvent.Type.Hide,
            qt.QEvent.Type.WindowDeactivate,
            qt.QEvent.Type.UngrabMouse,
        ):
            self._eye_gesture = False
            self._eye_press = None
        if isinstance(event, qt.QtGui.QHelpEvent):
            index = self._visibility_index_at(event.pos())
            if index.isValid():
                item = cast(
                    qt.QTreeWidgetItem | None, self.itemFromIndex(index)
                )
                if item is not None:
                    state = (
                        "ON"
                        if item.checkState(0) == qt.Qt.CheckState.Checked
                        else "OFF"
                    )
                    count = (
                        len(self.selectedItems()) if item.isSelected() else 1
                    )
                    target = "OFF" if state == "ON" else "ON"
                    action = (
                        f"選択中の{count}件を{target}にする"
                        if count > 1
                        else f"この1件を{target}にする"
                    )
                    qt.QtWidgets.QToolTip.showText(
                        event.globalPos(),
                        f"Attribute Filter への表示設定: {state}\n"
                        f"クリックで{action}",
                        self.viewport(),
                        self._visibility_rect(index),
                    )
                    event.accept()
                    return True
        return super().viewportEvent(event)
