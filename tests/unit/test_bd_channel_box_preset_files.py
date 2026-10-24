# coding: utf-8
"""共有文書の移設と、複数ファイルの保存失敗時の保護を検証する。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from bd_tools.bd_channel_box import custom_filter_presets as files
from bd_tools.bd_channel_box.custom_filter_presets import (
    FileUpdate,
    FilterReference,
    commit_file_updates,
    create_preset_document,
    read_preset_document,
)
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterError,
    normalize_filter_path,
)


def _update(source: Path, destination: Path, content: bytes) -> FileUpdate:
    """読込済み内容を基準にした一件の保存予定を作る。"""
    return FileUpdate(
        str(source),
        str(destination),
        content,
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )


def test_relative_group_and_preset_references_survive_directory_copy(
    tmp_path: Path,
) -> None:
    """3種類のフォルダーをまとめて共有すると、相対参照もコピー先を指す。"""
    source = tmp_path / "Library"
    for kind in ("preset_group", "preset", "filter"):
        (source / kind).mkdir(parents=True)
    filter_path = source / "filter" / "Transform.json"
    filter_path.write_text(
        '{"schema_version": 2, "node_types": {}}', encoding="utf-8"
    )
    preset_path = source / "preset" / "Modeling.json"
    create_preset_document(
        preset_path,
        "preset",
        (FilterReference(normalize_filter_path(filter_path), False),),
    )
    group_path = source / "preset_group" / "Main.json"
    create_preset_document(
        group_path,
        "preset_group",
        (FilterReference(normalize_filter_path(preset_path)),),
    )
    assert json.loads(group_path.read_text(encoding="utf-8"))["presets"] == [
        "../preset/Modeling.json"
    ]
    assert json.loads(preset_path.read_text(encoding="utf-8"))["filters"] == [
        {"path": "../filter/Transform.json", "enabled": False}
    ]
    copied = tmp_path / "Shared"
    shutil.copytree(source, copied)
    group = read_preset_document(
        copied / "preset_group" / "Main.json", "preset_group"
    )
    assert group.error is None
    assert group.references[0].path == normalize_filter_path(
        copied / "preset" / "Modeling.json"
    )
    preset = read_preset_document(group.references[0].path, "preset")
    assert preset.error is None
    assert preset.references == (
        FilterReference(
            normalize_filter_path(copied / "filter" / "Transform.json"), False
        ),
    )
    assert not group.is_dirty and not preset.is_dirty


@pytest.mark.parametrize(
    "content",
    (
        '{"schema_version": true, "filters": []}',
        '{"schema_version": 2, "filters": []}',
        '{"schema_version": 1, "filters": [], "name": "Other"}',
        '{"schema_version": 1, "filters": [], "filters": []}',
        '{"schema_version": 1, "filters": [{"path":"a.json", "enabled": 1}]}',
        '{"schema_version": 1, "filters": [{"path":"", "enabled": true}]}',
    ),
)
def test_preset_reader_keeps_invalid_document_with_error(
    tmp_path: Path, content: str
) -> None:
    """不正JSONを正常な空プリセットに置き換えず、行に残せるエラーを返す。"""
    path = tmp_path / "Invalid.json"
    path.write_text(content, encoding="utf-8")
    document = read_preset_document(path, "preset")
    assert document.error is not None
    assert document.path == normalize_filter_path(path)
    assert document.references == ()
    assert path.read_text(encoding="utf-8") == content


def test_preset_reader_deduplicates_resolved_paths_in_first_order(
    tmp_path: Path,
) -> None:
    """同じ参照先の別表記をまとめ、最初の表示状態と順序を維持する。"""
    path = tmp_path / "Preset.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "filters": [
                    {"path": "Filter.json", "enabled": False},
                    {"path": "./Filter.json", "enabled": True},
                    {"path": "Second.json", "enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    document = read_preset_document(path, "preset")
    assert document.error is None
    assert document.references == (
        FilterReference(
            normalize_filter_path(tmp_path / "Filter.json"), False
        ),
        FilterReference(normalize_filter_path(tmp_path / "Second.json")),
    )


def test_document_commit_does_not_accept_unexpected_external_contents(
    tmp_path: Path,
) -> None:
    """保存確定の直前に別内容になったファイルを、自分の保存基準にしない。"""
    path = tmp_path / "Preset.json"
    document = create_preset_document(path, "preset")
    baseline = document.source_digest
    document.references = (
        FilterReference(normalize_filter_path(tmp_path / "Filter.json")),
    )
    path.write_bytes(b"external-change")
    with pytest.raises(CustomFilterError, match="外部"):
        document.mark_saved()
    assert document.source_digest == baseline
    assert document.is_dirty
    assert path.read_bytes() == b"external-change"


def test_batch_save_preflight_preserves_all_files_after_external_change(
    tmp_path: Path,
) -> None:
    """一件の外部変更を検出した時点で、他の保存対象も書き換えない。"""
    first, second = tmp_path / "First.json", tmp_path / "Second.json"
    first.write_bytes(b"original-first")
    second.write_bytes(b"original-second")
    updates = (
        _update(first, first, b"new-first"),
        _update(second, second, b"new-second"),
    )
    second.write_bytes(b"external-change")
    with pytest.raises(CustomFilterError, match="外部"):
        commit_file_updates(updates)
    assert first.read_bytes() == b"original-first"
    assert second.read_bytes() == b"external-change"
    assert not tuple(tmp_path.glob("*.tmp"))


def test_batch_save_rolls_back_prior_write_when_later_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """後続の書込失敗で、先に保存した内容も元へ戻す。"""
    first, second = tmp_path / "First.json", tmp_path / "Second.json"
    first.write_bytes(b"original-first")
    second.write_bytes(b"original-second")
    updates = (
        _update(first, first, b"new-first"),
        _update(second, second, b"new-second"),
    )
    replace = os.replace
    failed = False

    def fail_second(source: str | Path, destination: str | Path) -> None:
        """二件目の書込だけを一度失敗させ、復旧書込は許可する。"""
        nonlocal failed
        if (
            normalize_filter_path(destination) == normalize_filter_path(second)
            and not failed
        ):
            failed = True
            raise OSError("injected failure")
        replace(source, destination)

    monkeypatch.setattr(files.os, "replace", fail_second)
    with pytest.raises(CustomFilterError, match="injected failure"):
        commit_file_updates(updates)
    assert failed
    assert first.read_bytes() == b"original-first"
    assert second.read_bytes() == b"original-second"
    assert not tuple(tmp_path.glob("*.tmp"))


def test_batch_create_rolls_back_new_files_when_later_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新規ファイルの一部だけが残る状態を、後続失敗時に取り消す。"""
    first, second = tmp_path / "First.json", tmp_path / "Second.json"
    rename = os.rename

    def fail_second(source: str | Path, destination: str | Path) -> None:
        """二件目の新規配置を拒否し、一件目は通常どおり配置する。"""
        if normalize_filter_path(destination) == normalize_filter_path(second):
            raise OSError("injected failure")
        rename(source, destination)

    monkeypatch.setattr(files.os, "rename", fail_second)
    with pytest.raises(CustomFilterError, match="injected failure"):
        commit_file_updates(
            (
                FileUpdate(None, str(first), b"first", None),
                FileUpdate(None, str(second), b"second", None),
            )
        )
    assert not first.exists() and not second.exists()
    assert not tuple(tmp_path.glob("*.tmp"))


def test_batch_save_preserves_external_change_between_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一件目の確定後に入った他者の変更を保護し、一件目だけ巻き戻す。"""
    first, second = tmp_path / "First.json", tmp_path / "Second.json"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    updates = (
        _update(first, first, b"new-first"),
        _update(second, second, b"new-second"),
    )
    replace = os.replace
    injected = False

    def replace_and_change_next(
        source: str | Path, destination: str | Path
    ) -> None:
        """一件目を配置した直後、次の保存元を外部更新する。"""
        nonlocal injected
        replace(source, destination)
        if (
            normalize_filter_path(destination) == normalize_filter_path(first)
            and not injected
        ):
            injected = True
            second.write_bytes(b"external-change")

    monkeypatch.setattr(files.os, "replace", replace_and_change_next)
    with pytest.raises(CustomFilterError, match="外部"):
        commit_file_updates(updates)
    assert injected
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"external-change"
    assert not tuple(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(
    os.name != "nt", reason="Windowsの大小文字だけの改名を検証する"
)
def test_case_only_rename_rollback_restores_original_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内容が変わらない改名でも、後続失敗時には元のファイル名表記へ戻す。"""
    source, second = tmp_path / "OriginalCase.json", tmp_path / "Second.json"
    destination = tmp_path / "originalcase.json"
    source.write_bytes(b"unchanged")
    second.write_bytes(b"second")
    replace = os.replace
    failed = False

    def fail_second(
        source_path: str | Path, destination_path: str | Path
    ) -> None:
        """後続の置換だけを一度失敗させ、元表記への復元は許可する。"""
        nonlocal failed
        if (
            normalize_filter_path(destination_path)
            == normalize_filter_path(second)
            and not failed
        ):
            failed = True
            raise OSError("injected failure")
        replace(source_path, destination_path)

    monkeypatch.setattr(files.os, "replace", fail_second)
    with pytest.raises(CustomFilterError, match="injected failure"):
        commit_file_updates(
            (
                _update(source, destination, b"unchanged"),
                _update(second, second, b"new-second"),
            )
        )
    actual = next(
        path
        for path in tmp_path.iterdir()
        if path.name.casefold() == source.name.casefold()
    )
    assert actual.name == "OriginalCase.json"
    assert actual.read_bytes() == b"unchanged"
    assert second.read_bytes() == b"second"
    assert not tuple(tmp_path.glob("*.tmp"))


def test_batch_rename_rejects_existing_destination_without_changing_source(
    tmp_path: Path,
) -> None:
    """改名先に別ファイルがあれば、どちらの内容も維持する。"""
    source, destination = tmp_path / "Source.json", tmp_path / "Existing.json"
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")
    with pytest.raises(CustomFilterError, match="同名"):
        commit_file_updates((_update(source, destination, b"changed"),))
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"existing"


def test_batch_save_rejects_read_only_source_before_other_writes(
    tmp_path: Path,
) -> None:
    """参照元が読取専用なら、一括保存のほかの文書も変更しない。"""
    first, second = tmp_path / "First.json", tmp_path / "Second.json"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    updates = (
        _update(first, first, b"new-first"),
        _update(second, second, b"new-second"),
    )
    second.chmod(0o444)
    try:
        with pytest.raises(CustomFilterError, match="読取専用|書込"):
            commit_file_updates(updates)
        assert (
            first.read_bytes() == b"first" and second.read_bytes() == b"second"
        )
    finally:
        second.chmod(0o666)
