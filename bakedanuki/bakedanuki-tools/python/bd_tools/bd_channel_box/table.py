# coding: utf-8
"""既存の属性行を常時表示し、属性選択と一括数値入力を管理する。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, cast

from bd_util.ui import qt

__all__ = ["ChannelTableView", "TableRow"]

_RowKey = tuple[str, str]


class _FontEditor(Protocol):
    """PySide 6.8 stubの曖昧なsetFont overloadを使用範囲だけで閉じる。"""

    def setFont(self, font: qt.QFont, /) -> None:
        """QFontを入力欄へ設定する。"""
        ...


@dataclass(frozen=True)
class TableRow:
    """表示する属性の識別子と、選択を扱う既存部品をまとめる。"""

    key: _RowKey
    widget: qt.QWidget
    name_label: qt.QLabel
    value_field: qt.QDoubleSpinBox | None = None


class _RowDelegate(qt.QStyledItemDelegate):
    """属性行全体を常時開いたeditorとして配置する。"""

    def __init__(self, table: ChannelTableView) -> None:
        """一覧と同じ寿命で、既存の属性行を参照する。"""
        super().__init__(table)
        self._table = table

    def createEditor(
        self,
        parent: qt.QWidget,
        option: qt.QtWidgets.QStyleOptionViewItem,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> qt.QWidget:
        """既存Viewの入力機能を維持して、セルの子へ配置する。"""
        del option
        widget = self._table.rows[index.row()].widget
        widget.setParent(parent)
        # 属性名と補助部品の周囲を通常のUI背景で塗り、入力欄と区別する
        widget.setAutoFillBackground(True)
        return widget

    def setEditorData(
        self,
        editor: qt.QWidget,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> None:
        """既存Bindingが表示を同期するため値を書き込まない。"""
        del editor, index

    def setModelData(
        self,
        editor: qt.QWidget,
        model: qt.QAbstractItemModel,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
    ) -> None:
        """既存入力経路と一括入力だけに変更を委譲する。"""
        del editor, model, index

    def eventFilter(self, object: qt.QObject, event: qt.QEvent) -> bool:
        """Enterやフォーカス移動で常時表示の属性行を閉じない。"""
        del object, event
        return False


class ChannelTableView(qt.QTableView):
    """単一列の属性一覧に、独立した複数選択と数値入力を提供する。"""

    selection_changed = qt.Signal()
    numeric_input_requested = qt.Signal(object, float)
    numeric_input_rejected = qt.Signal(str)

    def __init__(self, parent: qt.QWidget | None = None) -> None:
        """行の描画と選択を準備し、まだ属性へ入力しない。"""
        super().__init__(parent)
        self.rows: tuple[TableRow, ...] = ()
        self._row_model = qt.QStandardItemModel(self)
        self._row_delegate = _RowDelegate(self)
        self._targets: dict[qt.QObject, tuple[int, bool]] = {}
        self._palettes: list[tuple[qt.QWidget, qt.QPalette, bool]] = []
        self._anchor = -1
        self._press_row = -1
        self._press_position = qt.QPoint()
        self._press_numeric = False
        self._dragging = False
        self._drag_base: tuple[_RowKey, ...] = ()
        self._numeric_editor: qt.QLineEdit | None = None
        self._numeric_keys: tuple[_RowKey, ...] = ()
        self._disposed = False

        # 行を一つのセルへ置き、一覧の余剰幅を既存layoutへ配分する
        self.setModel(self._row_model)
        self.setItemDelegate(self._row_delegate)
        self.horizontalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().hide()
        self.verticalHeader().setMinimumSectionSize(1)
        self.setShowGrid(False)
        self.setFrameShape(qt.QFrame.Shape.NoFrame)
        self.viewport().setBackgroundRole(qt.QPalette.ColorRole.Window)
        self.setSelectionMode(
            qt.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setSelectionBehavior(
            qt.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setEditTriggers(qt.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(
            qt.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.setHorizontalScrollBarPolicy(
            qt.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.selectionModel().selectionChanged.connect(self._paint_selection)
        self.verticalScrollBar().valueChanged.connect(self._scroll_changed)

    def setupViewport(self, viewport: qt.QWidget) -> None:
        """Mayaが表示領域を交換した後も、一覧の余白を通常のUI背景にする。"""
        super().setupViewport(viewport)
        viewport.setBackgroundRole(qt.QPalette.ColorRole.Window)

    def set_rows(
        self, rows: Sequence[TableRow], preserve_selection: bool = True
    ) -> None:
        """旧入力を破棄し、残存する属性だけ選択を引き継ぐ。"""
        selected = self.selected_keys() if preserve_selection else ()
        current = self.currentIndex().row()
        current_key = (
            self.rows[current].key if 0 <= current < len(self.rows) else None
        )
        self.finish_numeric_edit(commit=False)
        self._finish_drag()
        self._remove_targets()
        self._row_model.clear()
        self.rows = tuple(rows)
        self._anchor = -1
        self._row_model.setColumnCount(1)

        # Bindingを持つ既存行はdelegateが所有し、値はmodelへ複製しない
        for index, row in enumerate(self.rows):
            item = qt.QStandardItem()
            item.setSizeHint(row.widget.sizeHint())
            self._row_model.setItem(index, 0, item)
            self.openPersistentEditor(self._row_model.index(index, 0))
            self.setRowHeight(index, max(1, row.widget.sizeHint().height()))
            self._add_target(row.widget, index, numeric=False)
            self._add_target(row.name_label, index, numeric=False)
            self._remember_palette(row.name_label)
            if row.value_field is not None:
                self._add_target(row.value_field, index, numeric=True)
                find_children = cast(
                    Callable[[type[qt.QLineEdit]], list[qt.QLineEdit]],
                    getattr(row.value_field, "findChildren"),
                )
                children = find_children(qt.QLineEdit)
                for child in children:
                    self._add_target(child, index, numeric=True)
                self._remember_palette(row.value_field)
        self.select_keys(selected)
        if preserve_selection and current_key is not None:
            for index, row in enumerate(self.rows):
                if row.key == current_key:
                    self._set_current(index)
                    break
        self._paint_selection()

    def selected_keys(self) -> tuple[_RowKey, ...]:
        """表示中の選択属性を行順で返し、widgetの寿命から切り離す。"""
        selected = {
            index.row() for index in self.selectionModel().selectedRows()
        }
        return tuple(
            row.key
            for index, row in enumerate(self.rows)
            if index in selected and not self.isRowHidden(index)
        )

    def select_keys(self, keys: Sequence[_RowKey]) -> None:
        """指定した残存属性だけを選択し、属性値を変更しない。"""
        selected = set(keys)
        self.selectionModel().clearSelection()
        first = -1
        for index, row in enumerate(self.rows):
            if row.key in selected and not self.isRowHidden(index):
                self.selectionModel().select(
                    self._row_model.index(index, 0),
                    qt.QItemSelectionModel.SelectionFlag.Select
                    | qt.QItemSelectionModel.SelectionFlag.Rows,
                )
                if first < 0:
                    first = index
        if first >= 0:
            self._anchor = first
            self._set_current(first)

    def set_visible_keys(self, keys: Sequence[_RowKey] | None) -> int:
        """指定した行だけを表示し、隠れた行を属性選択から外す。"""
        selected = self.selected_keys()
        current = self.currentIndex().row()
        current_key = (
            self.rows[current].key if 0 <= current < len(self.rows) else None
        )
        visible = None if keys is None else set(keys)
        visible_count = 0

        # 行WidgetとBindingを維持したまま、Tableの表示だけを切り替える
        for index, row in enumerate(self.rows):
            shown = visible is None or row.key in visible
            self.setRowHidden(index, not shown)
            visible_count += int(shown)

        # 見えない属性を後続の一括操作へ残さない
        self.select_keys(selected)
        current_visible = next(
            (
                index
                for index, row in enumerate(self.rows)
                if row.key == current_key and not self.isRowHidden(index)
            ),
            -1,
        )
        first_visible = next(
            (
                index
                for index in range(len(self.rows))
                if not self.isRowHidden(index)
            ),
            -1,
        )
        if current_visible >= 0:
            self._set_current(current_visible)
        elif first_visible >= 0:
            self._set_current(first_visible)
        else:
            self.setCurrentIndex(qt.QModelIndex())
        if not 0 <= self._anchor < len(self.rows) or self.isRowHidden(
            self._anchor
        ):
            # Shift選択の起点を、検索で隠れた行へ残さない
            self._anchor = (
                current_visible if current_visible >= 0 else first_visible
            )
        self._paint_selection()
        return visible_count

    def select_key(self, key: _RowKey, *, extend: bool = False) -> None:
        """一つの属性を選択し、指定時は現在の選択へ追加する。"""
        keys = self.selected_keys() if extend else ()
        self.select_keys((*keys, key))
        for index, row in enumerate(self.rows):
            if row.key == key:
                self._set_current(index)
                return

    def ensureWidgetVisible(
        self, widget: qt.QWidget, xmargin: int = 50, ymargin: int = 50
    ) -> None:
        """既存の操作確認コードから、部品を含む属性行へスクロールする。"""
        del xmargin, ymargin
        for index, row in enumerate(self.rows):
            if widget is row.widget or row.widget.isAncestorOf(widget):
                self.scrollTo(self._row_model.index(index, 0))
                return

    def finish_numeric_edit(self, *, commit: bool) -> None:
        """明示入力だけを確定し、閉じた後で凍結した対象へ通知する。"""
        editor, self._numeric_editor = self._numeric_editor, None
        keys, self._numeric_keys = self._numeric_keys, ()
        if editor is None:
            return
        entered = editor.text().strip()
        modified = editor.isModified()
        selected = self.selected_keys()
        current = self.currentIndex().row()
        anchor = self._anchor
        editor.removeEventFilter(self)
        editor.hide()
        editor.deleteLater()
        # overlay終了でQtが隣の常時editorへ移すfocusは属性選択にしない
        self.select_keys(selected)
        self._anchor = anchor
        if 0 <= current < len(self.rows):
            self._set_current(current)
        if not commit or self._disposed or not modified:
            return
        try:
            value = float(entered)
            if not isfinite(value):
                raise ValueError("有限の数値を入力してください")
        except ValueError:
            self.numeric_input_rejected.emit(
                "有限の数値を入力してください: " + entered
            )
            return
        self.numeric_input_requested.emit(keys, value)

    def _add_target(
        self, widget: qt.QWidget, index: int, *, numeric: bool
    ) -> None:
        """名前欄と数値欄だけを監視し、補助入力やsweepに干渉しない。"""
        self._targets[widget] = (index, numeric)
        widget.installEventFilter(self)

    def _remember_palette(self, widget: qt.QWidget) -> None:
        """選択解除で元の表示へ戻すため、部品の配色を保持する。"""
        self._palettes.append(
            (
                widget,
                qt.QPalette(widget.palette()),
                widget.autoFillBackground(),
            )
        )

    def _remove_targets(self) -> None:
        """再構築前にイベント監視と選択の配色を解除する。"""
        for target in self._targets:
            if qt.isValid(target):
                target.removeEventFilter(self)
        self._targets.clear()
        for widget, palette, fill in self._palettes:
            if qt.isValid(widget):
                widget.setPalette(palette)
                widget.setAutoFillBackground(fill)
        self._palettes.clear()

    def _paint_selection(self, *_args: object) -> None:
        """常時表示の名前欄と数値欄にも選択状態を表示する。"""
        selected = set(self.selected_keys())
        for widget, original, fill in self._palettes:
            if not qt.isValid(widget):
                continue
            target = self._targets.get(widget)
            if target is None or target[0] >= len(self.rows):
                continue
            active = self.rows[target[0]].key in selected
            palette = qt.QPalette(original)
            if active:
                highlight = self.palette().color(
                    qt.QPalette.ColorRole.Highlight
                )
                text = self.palette().color(
                    qt.QPalette.ColorRole.HighlightedText
                )
                for role in (
                    qt.QPalette.ColorRole.Window,
                    qt.QPalette.ColorRole.Base,
                ):
                    palette.setColor(role, highlight)
                for role in (
                    qt.QPalette.ColorRole.WindowText,
                    qt.QPalette.ColorRole.Text,
                ):
                    palette.setColor(role, text)
            widget.setPalette(palette)
            widget.setAutoFillBackground(active or fill)
            widget.update()
        self.selection_changed.emit()

    def _set_current(self, index: int) -> None:
        """選択集合を維持して、操作中の属性だけを移動する。"""
        self.selectionModel().setCurrentIndex(
            self._row_model.index(index, 0),
            qt.QItemSelectionModel.SelectionFlag.NoUpdate,
        )

    def selectionCommand(
        self,
        index: qt.QModelIndex | qt.QtCore.QPersistentModelIndex,
        event: qt.QEvent | None = None,
    ) -> qt.QItemSelectionModel.SelectionFlag:
        """部品間の自動フォーカス移動だけでは属性選択を変更しない。"""
        if event is None or event.type() in (
            qt.QEvent.Type.FocusIn,
            qt.QEvent.Type.FocusOut,
        ):
            return qt.QItemSelectionModel.SelectionFlag.NoUpdate
        return super().selectionCommand(index, event)

    def _select_pressed(
        self, index: int, event: qt.QtGui.QMouseEvent, *, numeric: bool
    ) -> None:
        """修飾キーと入力領域に応じて属性の選択を更新する。"""
        self.finish_numeric_edit(commit=True)
        modifiers = event.modifiers()
        key = self.rows[index].key
        selected = self.selected_keys()
        if modifiers & qt.Qt.KeyboardModifier.ShiftModifier:
            anchor = self._anchor if self._anchor >= 0 else index
            start, end = sorted((anchor, index))
            keys = tuple(row.key for row in self.rows[start : end + 1])
            if modifiers & qt.Qt.KeyboardModifier.ControlModifier:
                keys = (*selected, *keys)
            self.select_keys(keys)
            self._anchor = anchor
        elif modifiers & qt.Qt.KeyboardModifier.ControlModifier:
            self.select_keys(
                tuple(item for item in selected if item != key)
                if key in selected
                else (*selected, key)
            )
            self._anchor = index
        elif key not in selected or (
            not numeric and event.button() == qt.Qt.MouseButton.LeftButton
        ):
            self.select_keys((key,))
            self._anchor = index
        self._set_current(index)

    def _begin_drag(
        self, index: int, event: qt.QtGui.QMouseEvent, *, numeric: bool
    ) -> None:
        """左押下の位置を保持し、文字選択と属性ドラッグを区別する。"""
        self._press_row = index
        self._press_position = event.globalPosition().toPoint()
        self._press_numeric = numeric
        self._dragging = False
        self._drag_base = (
            self.selected_keys()
            if event.modifiers() & qt.Qt.KeyboardModifier.ControlModifier
            else ()
        )

    def _finish_drag(self) -> None:
        """操作の中断時にも押下状態とアプリケーション監視を解放する。"""
        self._press_row = -1
        self._dragging = False
        application = qt.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

    def _drag_move(self, event: qt.QtGui.QMouseEvent) -> bool:
        """名前欄のドラッグと値欄の縦ドラッグで範囲を選択する。"""
        if self._press_row < 0:
            return False
        if not event.buttons() & qt.Qt.MouseButton.LeftButton:
            self._finish_drag()
            return False
        position = event.globalPosition().toPoint()
        delta = position - self._press_position
        if not self._dragging:
            if delta.manhattanLength() < qt.QApplication.startDragDistance():
                return False
            if self._press_numeric and abs(delta.y()) <= abs(delta.x()):
                return False
            self._dragging = True
            application = qt.QApplication.instance()
            if application is not None:
                application.installEventFilter(self)
        local = self.viewport().mapFromGlobal(position)
        row_index = self.rowAt(local.y())
        if row_index < 0 and self.rows:
            row_index = 0 if local.y() < 0 else len(self.rows) - 1
        if row_index >= 0:
            start, end = sorted((self._press_row, row_index))
            self.select_keys(
                (
                    *self._drag_base,
                    *(r.key for r in self.rows[start : end + 1]),
                )
            )
            self._anchor = self._press_row
            self._set_current(row_index)
            self.scrollTo(self._row_model.index(row_index, 0))
        return True

    def _is_numeric_input(self, event: qt.QtGui.QKeyEvent) -> bool:
        """直接の数値文字と貼付けだけを一括入力の開始として扱う。"""
        if event.matches(qt.QKeySequence.StandardKey.Paste):
            return True
        if event.modifiers() & (
            qt.Qt.KeyboardModifier.ControlModifier
            | qt.Qt.KeyboardModifier.AltModifier
            | qt.Qt.KeyboardModifier.MetaModifier
        ):
            return False
        return bool(event.text()) and all(
            character in "0123456789+-.eE" for character in event.text()
        )

    def _start_numeric_edit(
        self, index: int, event: qt.QtGui.QKeyEvent
    ) -> bool:
        """元SpinBoxの制限や書込みを通さず、一括入力用の文字欄を開く。"""
        if len(self.selected_keys()) < 2 or not self._is_numeric_input(event):
            return False
        row = self.rows[index]
        field = row.value_field
        if field is None or not field.isEnabled():
            return False
        self.finish_numeric_edit(commit=True)
        self._numeric_keys = self.selected_keys()
        editor = qt.QLineEdit(self.viewport())
        self._numeric_editor = editor
        editor.setObjectName("channel_batch_numeric_editor")
        editor.setAlignment(field.alignment())
        cast(_FontEditor, editor).setFont(field.font())
        editor.setText(field.cleanText())
        editor.setGeometry(
            qt.QRect(field.mapTo(self.viewport(), qt.QPoint()), field.size())
        )
        editor.installEventFilter(self)
        editor.show()
        editor.raise_()
        editor.setFocus()
        editor.selectAll()
        forwarded = qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            event.key(),
            event.modifiers(),
            event.text(),
            event.isAutoRepeat(),
            event.count(),
        )
        qt.QApplication.sendEvent(editor, forwarded)
        return True

    def eventFilter(self, object: qt.QObject, event: qt.QEvent) -> bool:
        """選択対象だけを仲介し、既存部品の通常操作を維持する。"""
        if self._disposed:
            return False
        watched = object
        kind = event.type()
        if watched is self._numeric_editor:
            if isinstance(event, qt.QtGui.QKeyEvent):
                if kind == qt.QEvent.Type.KeyPress:
                    if event.key() == qt.Qt.Key.Key_Escape:
                        self.finish_numeric_edit(commit=False)
                        return True
                    if event.key() in (
                        qt.Qt.Key.Key_Return,
                        qt.Qt.Key.Key_Enter,
                    ):
                        self.finish_numeric_edit(commit=True)
                        return True
            elif kind == qt.QEvent.Type.FocusOut:
                self.finish_numeric_edit(commit=True)
            return False

        # ドラッグ開始後だけ領域外の移動と中断も追跡する
        if isinstance(event, qt.QtGui.QMouseEvent):
            if kind == qt.QEvent.Type.MouseMove and self._press_row >= 0:
                if self._drag_move(event):
                    return True
            if kind == qt.QEvent.Type.MouseButtonRelease:
                dragging = self._dragging
                self._finish_drag()
                if dragging:
                    return True
        if self._dragging and kind in (
            qt.QEvent.Type.ApplicationDeactivate,
            qt.QEvent.Type.WindowDeactivate,
            qt.QEvent.Type.UngrabMouse,
        ):
            self._finish_drag()
        target = self._targets.get(watched)
        if target is None:
            return False
        index, numeric = target
        if not 0 <= index < len(self.rows):
            return False
        if isinstance(event, qt.QtGui.QMouseEvent):
            if kind == qt.QEvent.Type.MouseButtonPress and event.button() in (
                qt.Qt.MouseButton.LeftButton,
                qt.Qt.MouseButton.RightButton,
            ):
                self._select_pressed(index, event, numeric=numeric)
                if event.button() == qt.Qt.MouseButton.LeftButton:
                    self._begin_drag(index, event, numeric=numeric)
                    if not numeric or event.modifiers() & (
                        qt.Qt.KeyboardModifier.ControlModifier
                        | qt.Qt.KeyboardModifier.ShiftModifier
                    ):
                        self.setFocus()
                        return True
        elif isinstance(event, qt.QtGui.QKeyEvent) and numeric:
            if (
                kind == qt.QEvent.Type.ShortcutOverride
                and self._is_numeric_input(event)
            ):
                event.accept()
                return True
            if kind == qt.QEvent.Type.KeyPress:
                return self._start_numeric_edit(index, event)
        return False

    def keyPressEvent(self, event: qt.QtGui.QKeyEvent) -> None:
        """一覧にフォーカスがある場合も選択数値属性へ直接入力する。"""
        if event.key() == qt.Qt.Key.Key_Escape:
            self.finish_numeric_edit(commit=False)
            self._finish_drag()
            event.accept()
            return
        index = self.currentIndex().row()
        if 0 <= index < len(self.rows) and self._start_numeric_edit(
            index, event
        ):
            event.accept()
            return
        super().keyPressEvent(event)

    def _scroll_changed(self, _value: int) -> None:
        """入力欄の移動前に一括入力を確定する。"""
        self.finish_numeric_edit(commit=True)

    def hideEvent(self, event: qt.QtGui.QHideEvent) -> None:
        """Windowが隠れた場合は未確定入力とドラッグを破棄する。"""
        self.finish_numeric_edit(commit=False)
        self._finish_drag()
        super().hideEvent(event)

    def clear(self) -> None:
        """全属性と未確定入力を破棄する。"""
        self.set_rows((), preserve_selection=False)

    def dispose(self) -> None:
        """入力と監視を終了し、古い属性への遅延書込みを防ぐ。"""
        if self._disposed:
            return
        self._disposed = True
        self.finish_numeric_edit(commit=False)
        self._finish_drag()
        self._remove_targets()
