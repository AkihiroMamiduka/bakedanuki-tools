# coding: utf-8
"""正規化パス経由の再読込でも実ファイル名の大小文字を保つことを検証する。"""

from __future__ import annotations

import json
from pathlib import Path

from bd_util.ui import qt

from bd_tools.bd_channel_box.custom_filter_registry import CustomFilterRegistry
from bd_tools.bd_channel_box.custom_filters import (
    filter_display_name,
    load_custom_filter,
    normalize_filter_path,
)


def test_registry_reload_preserves_file_case_after_external_rewrite(
    qt_application: qt.QApplication, tmp_path: Path
) -> None:
    """共有定義を外部更新して構成保存した後も、ディレクトリ上の名前を使う。"""
    assert qt_application is not None
    path = tmp_path / "B.json"

    def rewrite(name: str) -> None:
        """旧形式の表示名だけが変わる外部更新を再現する。"""
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": name,
                    "node_types": {"transform": ["visibility"]},
                }
            ),
            encoding="utf-8",
        )

    def state() -> dict[str, object]:
        """実ファイル名と正規化後の名前取得を障害切分け用に記録する。"""
        normalized = normalize_filter_path(path)
        return {
            "directory_names": [item.name for item in tmp_path.iterdir()],
            "resolved": str(Path(normalized).resolve()),
            "helper_name": filter_display_name(normalized),
            "loaded_name": load_custom_filter(normalized).name,
        }

    rewrite("Original")
    registry = CustomFilterRegistry()
    registry.add_paths((path,))
    before = state()
    assert before["loaded_name"] == "B", before
    rewrite("Updated B")
    after_rewrite = state()
    assert after_rewrite["loaded_name"] == "B", after_rewrite
    registry.save()
    after_save = state()
    assert after_save["loaded_name"] == "B", after_save
    registry.reload_all()
    after_reload = state()
    assert after_reload["loaded_name"] == "B", after_reload
    definition = registry.entries[0].definition
    assert definition is not None
    assert definition.name == "B", after_reload
