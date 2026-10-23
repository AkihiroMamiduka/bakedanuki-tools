# coding: utf-8
"""複数登録の移動・解除が一度の保存と通知で確定することを検証する。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bd_tools.bd_channel_box.custom_filter_editor import create_custom_filter
from bd_tools.bd_channel_box.custom_filter_registry import CustomFilterRegistry


class _CountingRegistry(CustomFilterRegistry):
    """個人設定への書込回数を記録し、通常の保存経路も実行する。"""

    def __init__(self) -> None:
        """既存設定を読み込み、書込回数を初期化する。"""
        super().__init__()
        self.save_count = 0

    def _save(self) -> None:
        """書込回数を数えて実設定を更新する。"""
        self.save_count += 1
        super()._save()


def _registry(
    tmp_path: Path,
) -> tuple[_CountingRegistry, tuple[Path, ...], tuple[str, ...]]:
    """5件のJSONを登録し、1件をOFFにした独立設定を用意する。"""
    files = tuple(tmp_path / f"{name}.json" for name in "ABCDE")
    for path in files:
        create_custom_filter(path, path.stem)
    registry = _CountingRegistry()
    paths = registry.add_paths(files)
    registry.set_enabled(paths[1], False)
    registry.save_count = 0
    return registry, files, paths


@pytest.mark.parametrize(
    ("selected", "offset", "expected", "changed"),
    (
        ((1, 2), -1, (1, 2, 0, 3, 4), True),
        ((1, 3), -1, (1, 0, 3, 2, 4), True),
        ((1, 2), 1, (0, 3, 1, 2, 4), True),
        ((1, 3), 1, (0, 2, 1, 4, 3), True),
        ((0, 2), -1, (0, 1, 2, 3, 4), False),
        ((1, 4), 1, (0, 1, 2, 3, 4), False),
        ((0, 1, 2, 3, 4), -1, (0, 1, 2, 3, 4), False),
        ((0, 1, 2, 3, 4), 1, (0, 1, 2, 3, 4), False),
    ),
)
def test_registry_moves_selection_once_and_restores_saved_state(
    tmp_path: Path,
    selected: tuple[int, ...],
    offset: int,
    expected: tuple[int, ...],
    changed: bool,
) -> None:
    """連続・非連続選択の移動と境界を検証し、中間状態を通知しない。"""
    registry, files, paths = _registry(tmp_path)
    observed: list[tuple[str, ...]] = []

    def record_change() -> None:
        """通知を受けた時点の登録順を記録する。"""
        observed.append(tuple(entry.path for entry in registry.entries))

    registry.changed.connect(record_change)
    # 入力の順序・重複・不明パスは登録順に基づく移動結果を変えない
    selection = tuple(paths[index] for index in reversed(selected))
    assert (
        registry.move_many(iter(selection + selection + ("unknown",)), offset)
        is changed
    )
    order = tuple(paths[index] for index in expected)
    assert tuple(entry.path for entry in registry.entries) == order
    assert registry.save_count == int(changed)
    assert observed == ([order] if changed else [])
    restored = CustomFilterRegistry()
    assert tuple(entry.path for entry in restored.entries) == order
    assert tuple(
        entry.path for entry in restored.entries if not entry.enabled
    ) == (paths[1],)
    assert all(path.is_file() for path in files)


def test_registry_removes_selection_once_and_keeps_shared_files(
    tmp_path: Path,
) -> None:
    """複数登録の解除を一度で通知・保存し、共有JSONと残りの状態を維持する。"""
    registry, files, paths = _registry(tmp_path)
    before = tuple(path.read_bytes() for path in files)
    observed: list[tuple[str, ...]] = []

    def record_change() -> None:
        """解除完了後の登録だけを記録する。"""
        observed.append(tuple(entry.path for entry in registry.entries))

    registry.changed.connect(record_change)
    assert registry.remove_many(
        iter((paths[4], paths[2], paths[2], "unknown"))
    )
    expected = (paths[0], paths[1], paths[3])
    assert observed == [expected]
    assert registry.save_count == 1
    assert (
        tuple(entry.path for entry in CustomFilterRegistry().entries)
        == expected
    )
    assert not registry.entries[1].enabled
    assert tuple(path.read_bytes() for path in files) == before


def test_registry_empty_unknown_and_single_operations(tmp_path: Path) -> None:
    """空・不明の選択は通知せず、既存の単体操作も同じ保存契約を守る。"""
    registry, _files, paths = _registry(tmp_path)
    observed: list[tuple[str, ...]] = []

    def record_change() -> None:
        """操作後の登録を記録する。"""
        observed.append(tuple(entry.path for entry in registry.entries))

    registry.changed.connect(record_change)
    for selection in ((), ("unknown",)):
        assert not registry.remove_many(selection)
        assert not registry.move_many(selection, -1)
        assert not registry.move_many(selection, 1)
    assert not observed and registry.save_count == 0
    assert registry.move(paths[1], -1)
    assert registry.remove(paths[1])
    assert registry.save_count == 2 and len(observed) == 2
    assert (
        tuple(entry.path for entry in registry.entries)
        == paths[:1] + paths[2:]
    )


@pytest.mark.parametrize("offset", (-2, 0, 2))
def test_registry_rejects_invalid_offset_without_saving(
    tmp_path: Path, offset: int
) -> None:
    """選択の有無にかかわらず無効な移動量を拒否し、設定を変更しない。"""
    registry, _files, paths = _registry(tmp_path)
    for selection in ((), (paths[1],)):
        with pytest.raises(ValueError):
            registry.move_many(selection, offset)
    with pytest.raises(ValueError):
        registry.move(paths[1], offset)
    assert registry.save_count == 0
    assert tuple(entry.path for entry in registry.entries) == paths
