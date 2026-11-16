# coding: utf-8
"""属性一覧の差分更新で、残存入力とQtの行識別子を維持することを検証する。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest

from bd_util.ui import qt
from bd_tools.bd_channel_box.table import ChannelTableView, TableRow


def _events() -> None:
    """配置と遅延削除を処理し、editorの最終的な寿命を確認する。"""
    for _ in range(3):
        qt.QApplication.processEvents()
        qt.QApplication.sendPostedEvents(None, qt.QEvent.Type.DeferredDelete)


@pytest.fixture
def table(qt_application: qt.QApplication) -> Iterator[ChannelTableView]:
    """値書込みを持たない一覧を表示し、test終了時に確実に解放する。"""
    assert qt_application is not None
    widget = ChannelTableView()
    widget.resize(360, 240)
    widget.show()
    yield widget
    widget.dispose()
    widget.close()
    widget.deleteLater()
    _events()


def _row(table: ChannelTableView, name: str) -> TableRow:
    """Maya Bindingを使わない数値入力行を作り、一覧の寿命だけを検証する。"""
    widget = qt.QWidget(table.viewport())
    label = qt.QLabel(name, widget)
    spin_box = qt.QDoubleSpinBox(widget)
    layout = qt.QHBoxLayout(widget)
    layout.addWidget(label)
    layout.addWidget(spin_box)
    return TableRow(
        (name, "number"),
        widget,
        label,
        value_field=spin_box,
        direct_numeric_input=True,
    )


def _model(table: ChannelTableView) -> qt.QtCore.QAbstractItemModel:
    """private modelの実装型へ依存せず、Qtの公開行操作を確認する。"""
    model = table.model()
    assert model is not None
    return model


def test_same_rows_keep_editor_focus_and_persistent_index(
    table: ChannelTableView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ行の更新ではeditorを開き直さず、focusとmodel indexを維持する。"""
    rows = (_row(table, "a"), _row(table, "b"))
    table.set_rows(rows)
    _events()
    model = _model(table)
    persistent = qt.QtCore.QPersistentModelIndex(model.index(1, 0))
    field = rows[1].value_field
    assert field is not None
    field.setFocus()
    _events()
    focused = qt.QApplication.focusWidget()
    assert focused is not None
    calls: list[int] = []

    def refuse_reopen(index: qt.QModelIndex) -> None:
        """同じeditorを作り直そうとする操作を記録する。"""
        calls.append(index.row())

    monkeypatch.setattr(table, "openPersistentEditor", refuse_reopen)
    table.set_rows(tuple(replace(row) for row in rows))
    _events()
    assert not calls
    assert persistent.isValid() and persistent.row() == 1
    assert table.indexWidget(model.index(1, 0)) is rows[1].widget
    assert qt.QApplication.focusWidget() is focused
    assert all(qt.isValid(row.widget) for row in rows)


def test_reordered_rows_keep_editors_and_restore_attribute_selection(
    table: ChannelTableView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """行移動でもeditorを保持し、選択と現在行を正式keyへ対応させる。"""
    a, b, c = (_row(table, name) for name in ("a", "b", "c"))
    table.set_rows((a, b, c))
    table.select_keys((a.key, c.key))
    _events()
    model = _model(table)
    a_index = qt.QtCore.QPersistentModelIndex(model.index(0, 0))
    c_index = qt.QtCore.QPersistentModelIndex(model.index(2, 0))
    reopened: list[int] = []

    def record_reopen(index: qt.QModelIndex) -> None:
        """移動だけで新しいeditorを要求した場合に記録する。"""
        reopened.append(index.row())

    monkeypatch.setattr(table, "openPersistentEditor", record_reopen)
    table.set_rows((c, b, a))
    _events()
    assert not reopened
    assert a_index.isValid() and a_index.row() == 2
    assert c_index.isValid() and c_index.row() == 0
    assert table.selected_keys() == (c.key, a.key)
    assert table.currentIndex().row() == 2
    for index, row in enumerate((c, b, a)):
        assert qt.isValid(row.widget)
        assert table.indexWidget(model.index(index, 0)) is row.widget


def test_insert_remove_and_replace_destroy_only_departed_editors(
    table: ChannelTableView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """追加・削除・同keyの別Widgetへの交換を、残存行を壊さず反映する。"""
    a, b, c = (_row(table, name) for name in ("a", "b", "c"))
    table.set_rows((a, b, c))
    _events()
    model = _model(table)
    retained = qt.QtCore.QPersistentModelIndex(model.index(2, 0))
    replacement = _row(table, "a")
    added = _row(table, "d")
    opened: list[int] = []
    open_editor = table.openPersistentEditor

    def record_open(index: qt.QModelIndex) -> None:
        """新規Widgetを持つ行だけがeditorを開くことを記録する。"""
        opened.append(index.row())
        open_editor(index)

    monkeypatch.setattr(table, "openPersistentEditor", record_open)
    table.set_rows((added, c, replacement))
    _events()
    assert not qt.isValid(a.widget)
    assert not qt.isValid(b.widget)
    assert qt.isValid(c.widget)
    assert opened == [0, 2]
    assert retained.isValid() and retained.row() == 1
    for index, row in enumerate((added, c, replacement)):
        assert table.indexWidget(model.index(index, 0)) is row.widget


def test_row_moves_reconnect_input_targets_and_can_clear_selection(
    table: ChannelTableView,
) -> None:
    """移動後のラベル入力は新しい行番号を使い、明示した選択解除も保つ。"""
    a, b = (_row(table, name) for name in ("a", "b"))
    table.set_rows((a, b))
    table.select_keys((a.key,))
    table.set_rows((b, a), preserve_selection=False)
    _events()
    assert not table.selected_keys()
    assert not table.currentIndex().isValid()
    point = a.name_label.rect().center()
    for kind, buttons in (
        (qt.QEvent.Type.MouseButtonPress, qt.Qt.MouseButton.LeftButton),
        (qt.QEvent.Type.MouseButtonRelease, qt.Qt.MouseButton.NoButton),
    ):
        qt.QApplication.sendEvent(
            a.name_label,
            qt.QtGui.QMouseEvent(
                kind,
                qt.QPointF(point),
                qt.QPointF(a.name_label.mapToGlobal(point)),
                qt.Qt.MouseButton.LeftButton,
                buttons,
                qt.Qt.KeyboardModifier.NoModifier,
            ),
        )
    assert table.selected_keys() == (a.key,)


def test_retained_row_uses_replaced_value_field_for_input(
    table: ChannelTableView,
) -> None:
    """外側Widgetを残しても、交換前の値欄へ一括入力監視を残さない。"""
    row = _row(table, "a")
    table.set_rows((row,))
    _events()
    old_field = row.value_field
    assert old_field is not None
    layout = row.widget.layout()
    assert layout is not None
    layout.removeWidget(old_field)
    old_field.hide()
    new_field = qt.QDoubleSpinBox(row.widget)
    layout.addWidget(new_field)
    table.set_rows((replace(row, value_field=new_field),))
    _events()
    for field, expected in ((old_field, False), (new_field, True)):
        qt.QApplication.sendEvent(
            field,
            qt.QtGui.QKeyEvent(
                qt.QEvent.Type.KeyPress,
                qt.Qt.Key.Key_7,
                qt.Qt.KeyboardModifier.NoModifier,
                "7",
            ),
        )
        overlay = table.findChild(qt.QLineEdit, "channel_batch_numeric_editor")
        assert isinstance(overlay, qt.QLineEdit) is expected


def test_removing_selected_row_does_not_select_its_neighbor(
    table: ChannelTableView,
) -> None:
    """現在行の削除でQtが選ぶ隣接行を、利用者の属性選択として残さない。"""
    a, b = (_row(table, name) for name in ("a", "b"))
    table.set_rows((a, b))
    table.select_keys((a.key,))
    table.set_rows((b,))
    _events()
    assert not table.selected_keys()
    assert not table.currentIndex().isValid()


def test_row_update_discards_pending_numeric_input_without_request(
    table: ChannelTableView,
) -> None:
    """行を再利用する場合も、旧選択の一括入力を後から確定しない。"""
    row = _row(table, "a")
    table.set_rows((row,))
    table.select_keys((row.key,))
    _events()
    requests: list[float] = []

    def record_request(_keys: object, value: float) -> None:
        """取消した文字列が入力要求へ流れた場合に記録する。"""
        requests.append(value)

    table.numeric_input_requested.connect(record_request)
    qt.QApplication.sendEvent(
        table,
        qt.QtGui.QKeyEvent(
            qt.QEvent.Type.KeyPress,
            qt.Qt.Key.Key_7,
            qt.Qt.KeyboardModifier.NoModifier,
            "7",
        ),
    )
    overlay = table.findChild(qt.QLineEdit, "channel_batch_numeric_editor")
    assert isinstance(overlay, qt.QLineEdit)
    overlay.setText("42")
    overlay.setModified(True)
    table.set_rows((row,), preserve_selection=False)
    _events()
    assert not qt.isValid(overlay)
    assert not requests
    assert table.indexWidget(_model(table).index(0, 0)) is row.widget


def test_row_update_restores_search_hidden_rows_and_changed_heights(
    table: ChannelTableView,
) -> None:
    """再設定では検索条件を再適用できるよう行を戻し、変化した高さを反映する。"""
    a, b = (_row(table, name) for name in ("a", "b"))
    table.set_rows((a, b))
    table.set_visible_keys((a.key,))
    assert table.isRowHidden(1)
    layout = a.widget.layout()
    assert layout is not None
    before = a.widget.sizeHint().height()
    layout.setContentsMargins(0, 36, 0, 36)
    expected = a.widget.sizeHint().height()
    assert expected > before
    table.set_rows((a, b))
    _events()
    assert not table.isRowHidden(1)
    assert table.rowHeight(0) == expected


def test_contiguous_changes_emit_one_notice_and_keep_neighbor_editors(
    table: ChannelTableView,
) -> None:
    """連続追加と削除は各一通知とし、前後の入力部品とindexを残す。"""
    a, b = (_row(table, name) for name in ("a", "b"))
    table.set_rows((a, b))
    model = _model(table)
    persistent = qt.QtCore.QPersistentModelIndex(model.index(1, 0))
    inserted: list[tuple[int, int]] = []
    removed: list[tuple[int, int]] = []

    def record_insert(_parent: qt.QModelIndex, first: int, last: int) -> None:
        """追加された連続範囲をQtの公開通知から記録する。"""
        inserted.append((first, last))

    def record_remove(_parent: qt.QModelIndex, first: int, last: int) -> None:
        """削除された連続範囲をQtの公開通知から記録する。"""
        removed.append((first, last))

    model.rowsInserted.connect(record_insert)
    model.rowsRemoved.connect(record_remove)
    added = tuple(_row(table, f"new{index}") for index in range(6))
    table.set_rows((a, *added, b))
    _events()
    assert inserted == [(1, 6)]
    assert not removed
    assert persistent.isValid() and persistent.row() == 7
    for index, row in enumerate((a, *added, b)):
        assert table.indexWidget(model.index(index, 0)) is row.widget
    table.set_rows((a, b))
    _events()
    assert removed == [(1, 6)]
    assert qt.isValid(a.widget) and qt.isValid(b.widget)
    assert all(not qt.isValid(row.widget) for row in added)
    assert persistent.isValid() and persistent.row() == 1
    assert table.indexWidget(model.index(0, 0)) is a.widget
    assert table.indexWidget(model.index(1, 0)) is b.widget


def test_separate_blocks_and_reordering_preserve_only_surviving_inputs(
    table: ChannelTableView,
) -> None:
    """離れた増減範囲と行移動が混在しても、通知範囲と残存editorを保つ。"""
    a, b, c = (_row(table, name) for name in ("a", "b", "c"))
    discarded = tuple(_row(table, f"old{index}") for index in range(4))
    table.set_rows((a, *discarded[:2], b, *discarded[2:], c))
    table.select_keys((a.key, c.key))
    model = _model(table)
    persistent = qt.QtCore.QPersistentModelIndex(model.index(0, 0))
    inserted: list[tuple[int, int]] = []
    removed: list[tuple[int, int]] = []

    def record_insert(_parent: qt.QModelIndex, first: int, last: int) -> None:
        """追加通知が新しい連続block単位で発生することを記録する。"""
        inserted.append((first, last))

    def record_remove(_parent: qt.QModelIndex, first: int, last: int) -> None:
        """既存行を巻き込まず、削除blockだけが通知されることを記録する。"""
        removed.append((first, last))

    model.rowsInserted.connect(record_insert)
    model.rowsRemoved.connect(record_remove)
    added = tuple(_row(table, f"new{index}") for index in range(4))
    desired = (*added[:2], c, b, a, *added[2:])
    table.set_rows(desired)
    _events()
    assert inserted == [(0, 1), (5, 6)]
    assert removed == [(4, 5), (1, 2)]
    assert table.selected_keys() == (c.key, a.key)
    assert persistent.isValid() and persistent.row() == 4
    assert all(not qt.isValid(row.widget) for row in discarded)
    for index, row in enumerate(desired):
        assert qt.isValid(row.widget)
        assert table.indexWidget(model.index(index, 0)) is row.widget
