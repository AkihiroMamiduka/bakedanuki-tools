# coding: utf-8
"""共有フィルターの依存関係を閉じた一式出力と、失敗時の保護を検証する。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast

import pytest

from bd_tools.bd_channel_box import custom_filter_export as exporting
from bd_tools.bd_channel_box.custom_filter_export import (
    ExportKind,
    export_custom_filter_files,
)
from bd_tools.bd_channel_box.custom_filter_presets import (
    DocumentKind,
    FilterReference,
    PresetDocument,
    create_preset_document,
    read_preset_document,
)
from bd_tools.bd_channel_box.custom_filters import (
    CustomFilterDefinition,
    CustomFilterError,
    load_custom_filter,
    normalize_filter_path,
    serialize_custom_filter,
)


def _filter(path: Path, attribute: str) -> Path:
    """識別用の正式属性を一つ含むフィルターJSONを作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        serialize_custom_filter(
            CustomFilterDefinition(path.stem, {"transform": (attribute,)})
        )
    )
    return path


def _document(
    path: Path,
    kind: DocumentKind,
    references: tuple[FilterReference, ...] = (),
) -> Path:
    """実参照を持つ共有文書を既存の保存APIで作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = create_preset_document(path, kind, references)
    assert document.error is None
    return path


def _reference(path: Path, enabled: bool = True) -> FilterReference:
    """参照先を既存のパス正規化規則に合わせる。"""
    return FilterReference(normalize_filter_path(path), enabled)


def _tree_snapshot(directory: Path) -> dict[str, bytes | None]:
    """空フォルダーも含め、出力前後の内容を比較できる形で返す。"""
    return {
        path.relative_to(directory).as_posix(): (
            path.read_bytes() if path.is_file() else None
        )
        for path in directory.rglob("*")
    }


def _read_internal_document(
    path: Path, kind: DocumentKind, root: Path
) -> PresetDocument:
    """保存された参照が相対表記かつ出力一式の内部にあることを確認する。"""
    document = read_preset_document(path, kind)
    assert document.error is None
    assert not document.is_dirty
    for reference in document.references:
        target = Path(reference.path)
        assert target.is_file()
        assert target.is_relative_to(root.resolve())

    # 読込時の絶対化だけでなく、保存JSONそのものの相対表記も確認する
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    payload = cast(dict[str, object], raw)
    key = "presets" if kind == "preset_group" else "filters"
    records = payload[key]
    assert isinstance(records, list)
    for record in cast(list[object], records):
        if kind == "preset_group":
            raw_path = record
        else:
            assert isinstance(record, dict)
            raw_path = cast(dict[str, object], record)["path"]
        assert isinstance(raw_path, str)
        assert not Path(raw_path).is_absolute()
    return document


def _attributes(document: PresetDocument) -> tuple[tuple[str, ...], ...]:
    """プリセットの参照順に、実フィルターの属性定義を返す。"""
    return tuple(
        load_custom_filter(reference.path).node_types["transform"]
        for reference in document.references
    )


def test_group_export_is_portable_and_preserves_order_off_and_shared_filter(
    tmp_path: Path,
) -> None:
    """移設した一式でも、全参照の順序・OFF状態・共有先を維持する。"""
    source = tmp_path / "Source"
    shared = _filter(source / "common" / "Shared.json", "translateX")
    other = _filter(source / "external" / "Other.json", "rotateZ")
    first = _document(
        source / "presets" / "First.json",
        "preset",
        (_reference(other, False), _reference(shared)),
    )
    second = _document(
        source / "presets" / "Second.json",
        "preset",
        (_reference(shared, False),),
    )
    group = _document(
        source / "groups" / "Main.json",
        "preset_group",
        (_reference(second), _reference(first)),
    )
    baseline = _tree_snapshot(source)
    destination = tmp_path / "Destination"
    destination.mkdir()

    exported = export_custom_filter_files(
        "preset_group", (group,), destination
    )
    assert exported == destination / "export_custom_filter"
    assert set(path.name for path in exported.iterdir()) == {
        "preset_group",
        "preset",
        "filter",
    }
    assert len(tuple((exported / "filter").iterdir())) == 2
    assert set(path.name for path in (exported / "preset").iterdir()) == {
        "First.json",
        "Second.json",
    }
    assert _tree_snapshot(source) == baseline

    # 別の親へ移して読み直し、元ライブラリを参照しないことを確認する
    moved = tmp_path / "SharedCopy"
    shutil.move(str(exported), str(moved))
    exported_group = _read_internal_document(
        moved / "preset_group" / "Main.json", "preset_group", moved
    )
    assert tuple(
        Path(ref.path).name.casefold() for ref in exported_group.references
    ) == (
        "second.json",
        "first.json",
    )
    exported_second, exported_first = tuple(
        _read_internal_document(Path(ref.path), "preset", moved)
        for ref in exported_group.references
    )
    assert _attributes(exported_second) == (("translateX",),)
    assert _attributes(exported_first) == (("rotateZ",), ("translateX",))
    assert tuple(ref.enabled for ref in exported_second.references) == (False,)
    assert tuple(ref.enabled for ref in exported_first.references) == (
        False,
        True,
    )
    assert (
        exported_second.references[0].path == exported_first.references[1].path
    )
    assert _tree_snapshot(source) == baseline


def test_preset_export_contains_only_preset_and_filter_directories(
    tmp_path: Path,
) -> None:
    """プリセット単体を出力すると、必要な二階層だけを相対参照で作る。"""
    first = _filter(tmp_path / "Source" / "First.json", "translateY")
    second = _filter(tmp_path / "Source" / "Second.json", "rotateX")
    preset = _document(
        tmp_path / "Source" / "Preset.json",
        "preset",
        (_reference(second, False), _reference(first)),
    )
    destination = tmp_path / "Destination"
    destination.mkdir()

    exported = export_custom_filter_files("preset", (preset,), destination)

    assert set(path.name for path in exported.iterdir()) == {
        "preset",
        "filter",
    }
    document = _read_internal_document(
        exported / "preset" / preset.name, "preset", exported
    )
    assert _attributes(document) == (("rotateX",), ("translateY",))
    assert tuple(ref.enabled for ref in document.references) == (False, True)


def test_filter_export_copies_multiple_sources_once_without_empty_directories(
    tmp_path: Path,
) -> None:
    """複数フィルターを重複なくコピーし、元JSONの内容を維持する。"""
    first = _filter(tmp_path / "Source" / "First.json", "translateZ")
    second = _filter(tmp_path / "Source" / "Second.json", "scaleX")
    baseline = _tree_snapshot(tmp_path / "Source")
    destination = tmp_path / "Destination"
    destination.mkdir()

    exported = export_custom_filter_files(
        "filter",
        (first, str(second), first.parent / "." / first.name),
        destination,
    )

    assert set(path.name for path in exported.iterdir()) == {"filter"}
    assert len(tuple((exported / "filter").iterdir())) == 2
    assert (
        exported / "filter" / first.name
    ).read_bytes() == first.read_bytes()
    assert (
        exported / "filter" / second.name
    ).read_bytes() == second.read_bytes()
    assert _tree_snapshot(tmp_path / "Source") == baseline


def test_export_distinguishes_case_and_secondary_filename_collisions(
    tmp_path: Path,
) -> None:
    """大小文字の同名と連番候補の元名が混在しても、参照先を取り違えない。"""
    source = tmp_path / "Source"
    filters = tuple(
        _filter(source / str(index) / name, attribute)
        for index, (name, attribute) in enumerate(
            (
                ("Pose.json", "translateX"),
                ("pose.JSON", "translateY"),
                ("Pose_001.json", "translateZ"),
                ("Pose.json", "rotateX"),
            )
        )
    )
    presets = tuple(
        _document(
            source / str(index) / name,
            "preset",
            tuple(_reference(filters[item]) for item in indices),
        )
        for index, (name, indices) in enumerate(
            (
                ("Preset.json", (0, 1)),
                ("preset.JSON", (2,)),
                ("Preset_001.json", (3,)),
            )
        )
    )
    group = _document(
        source / "Main.json",
        "preset_group",
        tuple(_reference(path) for path in presets),
    )
    destination = tmp_path / "Destination"
    destination.mkdir()

    exported = export_custom_filter_files(
        "preset_group", (group,), destination
    )

    for kind, count in (("preset", 3), ("filter", 4)):
        names = tuple(path.name for path in (exported / kind).iterdir())
        assert len(names) == count
        assert len({name.casefold() for name in names}) == count
    exported_group = _read_internal_document(
        exported / "preset_group" / group.name, "preset_group", exported
    )
    assert tuple(
        _attributes(
            _read_internal_document(Path(ref.path), "preset", exported)
        )
        for ref in exported_group.references
    ) == (
        (("translateX",), ("translateY",)),
        (("translateZ",),),
        (("rotateX",),),
    )


@pytest.mark.parametrize("kind", ("preset_group", "preset"))
def test_empty_document_export_does_not_create_unused_directories(
    tmp_path: Path, kind: DocumentKind
) -> None:
    """空グループと空プリセットは、選んだ文書とそのフォルダーだけ出力する。"""
    source = _document(tmp_path / "Source" / "Empty.json", kind)
    destination = tmp_path / "Destination"
    destination.mkdir()

    exported = export_custom_filter_files(kind, (source,), destination)

    assert set(path.name for path in exported.iterdir()) == {kind}
    assert (
        _read_internal_document(
            exported / kind / source.name, kind, exported
        ).references
        == ()
    )


def test_existing_export_directories_and_files_are_preserved(
    tmp_path: Path,
) -> None:
    """既存のフォルダーとファイルを上書きせず、次の連番へ一式を作る。"""
    source = _filter(tmp_path / "Source" / "Filter.json", "scaleY")
    destination = tmp_path / "Destination"
    (destination / "export_custom_filter").mkdir(parents=True)
    marker = destination / "export_custom_filter" / "Keep.txt"
    marker.write_bytes(b"existing export")
    occupied_file = destination / "export_custom_filter_001"
    occupied_file.write_bytes(b"occupied filename")
    (destination / "export_custom_filter_002").mkdir()

    exported = export_custom_filter_files("filter", (source,), destination)

    assert exported == destination / "export_custom_filter_003"
    assert marker.read_bytes() == b"existing export"
    assert occupied_file.read_bytes() == b"occupied filename"
    assert not tuple((destination / "export_custom_filter_002").iterdir())
    assert (
        exported / "filter" / source.name
    ).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("kind", ("preset_group", "preset"))
def test_missing_reference_aborts_whole_export(
    tmp_path: Path, kind: DocumentKind
) -> None:
    """OFFを含む参照先の欠落があれば、他の正常な参照も出力しない。"""
    existing = (
        _document(tmp_path / "Source" / "Valid.json", "preset")
        if kind == "preset_group"
        else _filter(tmp_path / "Source" / "Valid.json", "translateX")
    )
    source = _document(
        tmp_path / "Source" / "Root.json",
        kind,
        (
            _reference(existing),
            _reference(tmp_path / "Source" / "Missing.json", False),
        ),
    )
    destination = tmp_path / "Destination"
    destination.mkdir()
    baseline = _tree_snapshot(tmp_path / "Source")

    with pytest.raises(CustomFilterError):
        export_custom_filter_files(kind, (source,), destination)

    assert not tuple(destination.iterdir())
    assert _tree_snapshot(tmp_path / "Source") == baseline


@pytest.mark.parametrize("kind", ("preset_group", "preset", "filter"))
def test_invalid_root_json_aborts_without_output(
    tmp_path: Path, kind: ExportKind
) -> None:
    """どの文書種別でも不正JSONを出力せず、元内容を維持する。"""
    source = tmp_path / "Invalid.json"
    source.write_bytes(b"{ invalid json")
    destination = tmp_path / "Destination"
    destination.mkdir()

    with pytest.raises(CustomFilterError):
        export_custom_filter_files(kind, (source,), destination)

    assert not tuple(destination.iterdir())
    assert source.read_bytes() == b"{ invalid json"


@pytest.mark.parametrize("kind", ("preset_group", "preset"))
def test_invalid_referenced_json_aborts_without_output(
    tmp_path: Path, kind: DocumentKind
) -> None:
    """参照元が正常でも、下位JSONが壊れていれば一式の出力を中止する。"""
    invalid = tmp_path / "Source" / "Invalid.json"
    invalid.parent.mkdir()
    invalid.write_bytes(b"{}")
    source = _document(
        tmp_path / "Source" / "Root.json",
        kind,
        (_reference(invalid, False),),
    )
    destination = tmp_path / "Destination"
    destination.mkdir()

    with pytest.raises(CustomFilterError):
        export_custom_filter_files(kind, (source,), destination)

    assert not tuple(destination.iterdir())
    assert invalid.read_bytes() == b"{}"


def test_export_rejects_invalid_copied_bytes_after_transient_source_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """検証時だけ正常になる元JSONでも、不正なコピー内容の公開を拒否する。"""
    source = tmp_path / "Filter.json"
    source.write_bytes(b"{}")
    destination = tmp_path / "Destination"
    destination.mkdir()
    valid_content = serialize_custom_filter(
        CustomFilterDefinition("Filter", {"transform": ("translateX",)})
    )
    source_validated = False
    copied_bytes_validated = False

    def load_with_transient_source_update(
        path: str | Path,
    ) -> CustomFilterDefinition:
        """元ファイルの検証中だけ正常化し、コピー内容はそのまま検証する。"""
        nonlocal source_validated, copied_bytes_validated
        if normalize_filter_path(path) == normalize_filter_path(source):
            source_validated = True
            source.write_bytes(valid_content)
            try:
                return load_custom_filter(path)
            finally:
                source.write_bytes(b"{}")
        copied_bytes_validated = True
        return load_custom_filter(path)

    monkeypatch.setattr(
        exporting, "load_custom_filter", load_with_transient_source_update
    )

    with pytest.raises(CustomFilterError):
        export_custom_filter_files("filter", (source,), destination)

    assert source_validated
    assert copied_bytes_validated
    assert source.read_bytes() == b"{}"
    assert not tuple(destination.iterdir())


@pytest.mark.parametrize(
    ("kind", "count"),
    (
        ("preset_group", 0),
        ("preset", 0),
        ("filter", 0),
        ("preset_group", 2),
        ("preset", 2),
    ),
)
def test_invalid_selection_count_creates_no_output(
    tmp_path: Path, kind: ExportKind, count: int
) -> None:
    """未選択と上位文書の複数指定を、副作用が起きる前に拒否する。"""
    sources = tuple(
        _filter(tmp_path / "Source" / f"Filter{index}.json", "translateX")
        for index in range(count)
    )
    destination = tmp_path / "Destination"
    destination.mkdir()

    with pytest.raises(CustomFilterError):
        export_custom_filter_files(kind, sources, destination)

    assert not tuple(destination.iterdir())


def test_write_failure_cleans_owned_staging_and_preserves_other_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """途中の部分書込を含めて片付け、既存出力と他者の一時一式を保護する。"""
    first = _filter(tmp_path / "Source" / "First.json", "translateX")
    second = _filter(tmp_path / "Source" / "Second.json", "translateY")
    destination = tmp_path / "Destination"
    for name in ("export_custom_filter", ".export_custom_filter-foreign"):
        directory = destination / name
        directory.mkdir(parents=True)
        (directory / "Keep.txt").write_bytes(name.encode("utf-8"))
    baseline = _tree_snapshot(destination)
    source_baseline = _tree_snapshot(tmp_path / "Source")
    write_bytes = Path.write_bytes
    calls = 0

    def fail_second(path: Path, content: bytes) -> int:
        """二件目だけ部分書込の後に失敗させ、最初の成功も片付けさせる。"""
        nonlocal calls
        if path.is_relative_to(destination) and path.suffix == ".json":
            calls += 1
            if calls == 2:
                write_bytes(path, b"partial contents")
                raise OSError("injected write failure")
        return write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_second)

    with pytest.raises(CustomFilterError, match="injected write failure"):
        export_custom_filter_files("filter", (first, second), destination)

    assert calls == 2
    assert _tree_snapshot(destination) == baseline
    assert _tree_snapshot(tmp_path / "Source") == source_baseline


def test_publish_failure_cleans_staging_without_removing_other_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """完成後の公開に失敗しても、一式を残さず既存の出力は保護する。"""
    source = _filter(tmp_path / "Source" / "Filter.json", "scaleZ")
    destination = tmp_path / "Destination"
    for name in ("export_custom_filter", ".export_custom_filter-foreign"):
        directory = destination / name
        directory.mkdir(parents=True)
        (directory / "Keep.txt").write_bytes(b"preserve")
    baseline = _tree_snapshot(destination)
    source_content = source.read_bytes()
    attempted = False

    def fail_publish(path: Path, target: str | Path) -> Path:
        """所有する完成一式のrenameだけを失敗させる。"""
        nonlocal attempted
        assert path.name.startswith(".export_custom_filter-")
        assert Path(target).parent == destination
        attempted = True
        raise OSError("injected publish failure")

    monkeypatch.setattr(Path, "rename", fail_publish)

    with pytest.raises(CustomFilterError, match="injected publish failure"):
        export_custom_filter_files("filter", (source,), destination)

    assert attempted
    assert _tree_snapshot(destination) == baseline
    assert source.read_bytes() == source_content


def test_publish_race_preserves_new_external_export_and_uses_next_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """公開直前に他者が作った同名出力を保護し、次の連番で公開する。"""
    source = _filter(tmp_path / "Source" / "Filter.json", "translateX")
    destination = tmp_path / "Destination"
    destination.mkdir()
    rename = Path.rename
    injected = False

    def create_external_before_publish(path: Path, target: str | Path) -> Path:
        """初回の公開先だけを先に確保して、実際の競合エラーを返す。"""
        nonlocal injected
        target_path = Path(target)
        if not injected:
            injected = True
            target_path.mkdir()
            (target_path / "Keep.txt").write_bytes(b"external export")
            raise FileExistsError("injected concurrent export")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", create_external_before_publish)

    exported = export_custom_filter_files("filter", (source,), destination)

    assert injected
    assert exported == destination / "export_custom_filter_001"
    assert (
        destination / "export_custom_filter" / "Keep.txt"
    ).read_bytes() == b"external export"
    assert (
        exported / "filter" / source.name
    ).read_bytes() == source.read_bytes()
    assert set(path.name for path in destination.iterdir()) == {
        "export_custom_filter",
        "export_custom_filter_001",
    }
