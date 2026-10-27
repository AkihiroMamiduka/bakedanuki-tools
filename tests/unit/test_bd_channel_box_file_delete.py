# coding: utf-8
"""実削除と個人設定確定の失敗から、所有する変更だけを戻すことを検証する。"""

import hashlib
from pathlib import Path

import pytest

from bd_tools.bd_channel_box.custom_filter_presets import (
    FileDeletion,
    FileUpdate,
    commit_file_updates,
)
from bd_tools.bd_channel_box.custom_filters import CustomFilterError


def _deletion(path: Path) -> FileDeletion:
    """現在の内容を基準にした削除予定を作る。"""
    return FileDeletion(
        str(path), hashlib.sha256(path.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("external", (False, True))
def test_finalize_failure_restores_deletions_and_protects_external_recreation(
    tmp_path: Path, external: bool
) -> None:
    """個人設定の確定失敗で削除を戻し、他者が作り直した内容は保護して通知する。"""
    first, second = tmp_path / "First.json", tmp_path / "Second.json"
    first.write_bytes(b"first original")
    second.write_bytes(b"second original")
    deletions = (_deletion(first), _deletion(second))

    def fail() -> None:
        """削除後に個人設定の失敗と任意の外部再作成を再現する。"""
        assert not first.exists() and not second.exists()
        if external:
            first.write_bytes(b"external replacement")
        raise OSError("個人設定保存に失敗")

    with pytest.raises(CustomFilterError) as captured:
        commit_file_updates((), deletions, finalize=fail)
    assert second.read_bytes() == b"second original"
    assert first.read_bytes() == (
        b"external replacement" if external else b"first original"
    )
    assert ("復元できない" in str(captured.value)) == external
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_rollback_reports_external_destination_and_restores_move_source(
    tmp_path: Path,
) -> None:
    """移動先の外部更新を消さず、元ファイルを復元して残る移動先を報告する。"""
    source, target = tmp_path / "Original.json", tmp_path / "Moved.json"
    source.write_bytes(b"original")
    update = FileUpdate(
        str(source),
        str(target),
        b"moved",
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    def fail() -> None:
        """移動先を外部更新し、その後に個人設定確定を失敗させる。"""
        target.write_bytes(b"external replacement")
        raise OSError("個人設定保存に失敗")

    with pytest.raises(CustomFilterError, match="復元できない") as captured:
        commit_file_updates((update,), finalize=fail)
    assert str(target) in str(captured.value)
    assert source.read_bytes() == b"original"
    assert target.read_bytes() == b"external replacement"


def test_stale_deletion_aborts_reference_updates(tmp_path: Path) -> None:
    """確認後に対象が変わった場合は、参照元の書込みも開始しない。"""
    source, parent = tmp_path / "Filter.json", tmp_path / "Preset.json"
    source.write_bytes(b"original")
    parent.write_bytes(b"original references")
    deletion = _deletion(source)
    update = FileUpdate(
        str(parent),
        str(parent),
        b"new references",
        hashlib.sha256(parent.read_bytes()).hexdigest(),
    )
    source.write_bytes(b"external replacement")
    with pytest.raises(CustomFilterError, match="外部"):
        commit_file_updates((update,), (deletion,))
    assert parent.read_bytes() == b"original references"
    assert source.read_bytes() == b"external replacement"
