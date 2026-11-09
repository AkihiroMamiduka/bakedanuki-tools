"""ヘルプ対応表の厳密検証と遅延依存、公開APIの委譲を確認する。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast
from uuid import uuid4

import pytest

import bd_tools
from bd_tools import help as tool_help
from bd_tools.help import HelpPage


class _HelpAPI(Protocol):
    """一時配布配置で読み込むヘルプAPIの型境界。"""

    PAGES: Mapping[str, HelpPage]

    def get_url(self, page_id: str) -> str:
        """登録されたページIDの完成URLを返す。"""
        ...

    def open_page(self, page_id: str) -> bool:
        """登録されたヘルプをブラウザーへ渡す。"""
        ...


def _entry() -> dict[str, object]:
    """初回のページ対応表に相当する独立した値を返す。"""
    return {
        "path": "tools/tool/bd-channel-box/",
        "source": "docs/help/tool/bd-channel-box/index.md",
        "categories": ["util"],
    }


def _payload() -> dict[str, object]:
    """検証用の独立したページ対応表を返す。"""
    return {
        "schema_version": 1,
        "package": "bd_tools",
        "pages": {"bd_channel_box": _entry()},
    }


def _content(payload: object) -> bytes:
    """検証用の値をUTF-8 JSONへ変換する。"""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _load_help(tmp_path: Path, content: bytes | None) -> _HelpAPI:
    """原稿のない一時配布配置へAPIとJSONを置いて読み込む。"""
    source = Path(tool_help.__file__).parent
    package_path = tmp_path / "help"
    package_path.mkdir()
    for path in source.glob("*.py"):
        (package_path / path.name).write_bytes(path.read_bytes())
    if content is not None:
        (package_path / "pages.json").write_bytes(content)

    # 別名で読み込んで正規moduleと区別し、dataclassにもmoduleを解決させる
    name = f"bd_tools._help_probe_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        name,
        package_path / "__init__.py",
        submodule_search_locations=[str(package_path)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        # 一時moduleだけを取り除き、後続testの読込結果へ影響させない
        for module_name in tuple(sys.modules):
            if module_name == name or module_name.startswith(name + "."):
                sys.modules.pop(module_name, None)
    return cast(_HelpAPI, module)


def _fake_util(
    monkeypatch: pytest.MonkeyPatch,
    build_url: Callable[[str], str],
    open_url: Callable[[str], bool],
) -> None:
    """Mayaへ依存せず、利用するutilの公開APIだけを差し替える。"""
    util = ModuleType("bd_util")
    site = ModuleType("bd_util.site")
    py = ModuleType("bd_util.py")
    web = ModuleType("bd_util.py.web")
    setattr(util, "__path__", [])
    setattr(py, "__path__", [])
    setattr(site, "build_url", build_url)
    setattr(web, "open_url", open_url)
    setattr(util, "site", site)
    setattr(util, "py", py)
    setattr(py, "web", web)
    for module in (util, site, py, web):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def test_shipped_pages_are_available_and_immutable() -> None:
    """初回の登録内容を取得でき、対応表と値を変更できない。"""
    page = tool_help.PAGES["bd_channel_box"]
    assert page == HelpPage(
        "bd_channel_box",
        "tools/tool/bd-channel-box/",
        "docs/help/tool/bd-channel-box/index.md",
        ("util",),
    )
    with pytest.raises(TypeError):
        cast(MutableMapping[str, HelpPage], tool_help.PAGES)["other"] = page
    with pytest.raises(FrozenInstanceError):
        setattr(page, "path", "tools/other/")


def test_help_uses_its_own_json_and_caches_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """作業場所に依存せず同梱JSONを読み、保持後の変更を再参照しない。"""
    monkeypatch.chdir(tmp_path)
    loaded = _load_help(tmp_path, _content(_payload()))
    (tmp_path / "help/pages.json").write_text("{}", encoding="utf-8")
    assert loaded.PAGES["bd_channel_box"].path == "tools/tool/bd-channel-box/"


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"{",
        b"[]",
        b"{}",
        b"\xff",
        b'\xef\xbb\xbf{"schema_version":1,"package":"bd_tools","pages":{}}',
        b'{"schema_version":1,"package":"bd_tools","pages":NaN}',
        b'{"schema_version":1,"package":"bd_tools","package":"bd_rig",'
        b'"pages":{}}',
    ],
)
def test_help_rejects_invalid_json(tmp_path: Path, content: bytes) -> None:
    """形式不正、文字コード不正、重複キーを対象ファイル付きで拒否する。"""
    with pytest.raises(ValueError, match=r"pages\.json"):
        _load_help(tmp_path, content)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("schema_version", "1"),
        ("package", "bd_rig"),
        ("package", "BD_TOOLS"),
        ("package", None),
        ("pages", []),
        ("pages", {}),
        ("pages", None),
        ("extra", 1),
    ],
)
def test_help_rejects_invalid_root_contract(
    tmp_path: Path, field: str, value: object
) -> None:
    """rootのschema、所有package、対応表と未知フィールドを検証する。"""
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValueError, match=r"pages\.json"):
        _load_help(tmp_path, _content(payload))


@pytest.mark.parametrize("field", ["schema_version", "package", "pages"])
def test_help_requires_all_root_fields(tmp_path: Path, field: str) -> None:
    """必須フィールドの欠落を代替値で隠さない。"""
    payload = _payload()
    payload.pop(field)
    with pytest.raises(ValueError, match=r"pages\.json"):
        _load_help(tmp_path, _content(payload))


@pytest.mark.parametrize("page_id", ["", "1tool", "Tool", "tool-name", "../"])
def test_help_rejects_invalid_page_ids(tmp_path: Path, page_id: str) -> None:
    """ページIDを小文字の識別子へ固定する。"""
    payload = _payload()
    payload["pages"] = {page_id: _entry()}
    with pytest.raises(ValueError, match=r"pages\.json"):
        _load_help(tmp_path, _content(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", ""),
        ("path", None),
        ("path", "tools"),
        ("path", "rig/tool/"),
        ("path", "/tools/tool/"),
        ("path", "https://example.test/tools/"),
        ("path", "tools//tool/"),
        ("path", "tools/../"),
        ("path", "tools/./"),
        ("path", "tools/Tool/"),
        ("path", "tools/tool_name/"),
        ("path", "tools/tool/?query=1"),
        ("path", "tools/tool/#part"),
        ("path", "tools/%2e%2e/"),
        ("path", "tools\\tool/"),
        ("path", "tools/tool/\n"),
        ("source", ""),
        ("source", None),
        ("source", "/docs/help/help.md"),
        ("source", "docs/help.md"),
        ("source", "docs/user/bd-channel-box/index.md"),
        ("source", "docs/help-other/help.md"),
        ("source", "docs/help/help.mdx"),
        ("source", "docs/help/../help.md"),
        ("source", "docs/help/./help.md"),
        ("source", "docs/help//help.md"),
        ("source", "docs/help\\help.md"),
        ("source", "docs/help/\x00help.md"),
        ("categories", "util"),
        ("categories", None),
        ("categories", [1]),
        ("categories", [""]),
        ("categories", ["Util"]),
        ("categories", ["tool_group"]),
        ("categories", ["1util"]),
        ("categories", ["util", "util"]),
        ("extra", 1),
    ],
)
def test_help_rejects_invalid_page_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    """公開先の逸脱、原稿rootの逸脱、不正分類と未知フィールドを拒否する。"""
    entry = _entry()
    entry[field] = value
    payload = _payload()
    payload["pages"] = {"bd_channel_box": entry}
    with pytest.raises(ValueError, match=r"pages\.json"):
        _load_help(tmp_path, _content(payload))


@pytest.mark.parametrize("field", ["path", "source", "categories"])
def test_help_requires_all_page_fields(tmp_path: Path, field: str) -> None:
    """ページの必須フィールドをすべて要求する。"""
    entry = _entry()
    entry.pop(field)
    payload = _payload()
    payload["pages"] = {"bd_channel_box": entry}
    with pytest.raises(ValueError, match=r"pages\.json"):
        _load_help(tmp_path, _content(payload))


@pytest.mark.parametrize("field", ["path", "source"])
def test_help_rejects_duplicate_destinations(
    tmp_path: Path, field: str
) -> None:
    """公開パスと原稿を複数のページへ割り当てない。"""
    entry = _entry()
    other = _entry()
    other["path"] = "tools/tool/other/"
    other["source"] = "docs/help/tool/other/index.md"
    other[field] = entry[field]
    payload = _payload()
    payload["pages"] = {"bd_channel_box": entry, "other": other}
    with pytest.raises(ValueError, match=field):
        _load_help(tmp_path, _content(payload))


@pytest.mark.parametrize("categories", [[], ["util", "model"]])
def test_help_accepts_empty_and_multiple_categories(
    tmp_path: Path, categories: list[str]
) -> None:
    """分類なしと複数分類を固定tupleとして保持する。"""
    entry = _entry()
    entry["categories"] = categories
    payload = _payload()
    payload["pages"] = {"bd_channel_box": entry}
    loaded = _load_help(tmp_path, _content(payload))
    assert loaded.PAGES["bd_channel_box"].categories == tuple(categories)


def test_missing_pages_json_reports_the_path(tmp_path: Path) -> None:
    """同梱JSONの欠落をファイル名付きの読込失敗として通知する。"""
    with pytest.raises(OSError, match=r"pages\.json"):
        _load_help(tmp_path, None)


@pytest.mark.parametrize(
    "base_url", ["https://example.test/", "https://example.test/docs/v1/"]
)
@pytest.mark.parametrize(
    "source",
    [
        "docs/help/index.md",
        "docs/help/faq.md",
        "docs/help/tool/bd-channel-box/index.md",
    ],
)
def test_get_url_is_independent_of_help_document_placement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    source: str,
) -> None:
    """原稿root直下とtool配下で公開URLを保ち、原稿を省いた配布も許容する。"""
    entry = _entry()
    entry["source"] = source
    payload = _payload()
    payload["pages"] = {"bd_channel_box": entry}
    loaded = _load_help(tmp_path, _content(payload))
    assert loaded.PAGES["bd_channel_box"].source == source
    calls: list[str] = []

    def build_url(path: str) -> str:
        """URL生成に渡された相対パスを記録する。"""
        calls.append(path)
        return base_url + path

    def fail_open(url: str) -> bool:
        """URL生成だけでブラウザーを起動した場合に失敗させる。"""
        pytest.fail(f"URL生成中にブラウザーを起動しました: {url}")

    _fake_util(monkeypatch, build_url, fail_open)
    assert loaded.get_url("bd_channel_box") == (
        base_url + "tools/tool/bd-channel-box/"
    )
    assert calls == ["tools/tool/bd-channel-box/"]


@pytest.mark.parametrize("result", [False, True])
def test_open_page_preserves_the_browser_result(
    monkeypatch: pytest.MonkeyPatch, result: bool
) -> None:
    """完成URLをブラウザーAPIへ渡し、起動依頼の成否をそのまま返す。"""
    calls: list[str] = []

    def build_url(path: str) -> str:
        """共通パスを含むサイトURLを返す。"""
        return "https://example.test/docs/" + path

    def open_url(url: str) -> bool:
        """受け取った完成URLと起動結果を記録する。"""
        calls.append(url)
        return result

    _fake_util(monkeypatch, build_url, open_url)
    assert tool_help.open_page("bd_channel_box") is result
    assert calls == ["https://example.test/docs/tools/tool/bd-channel-box/"]


@pytest.mark.parametrize("error", [webbrowser.Error("browser"), OSError("os")])
def test_open_page_propagates_browser_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """ブラウザー起動の例外を呼び出し側の通知へ渡す。"""

    def build_url(path: str) -> str:
        """検証用の完成URLを返す。"""
        return "https://example.test/" + path

    def fail_open(url: str) -> bool:
        """OSまたはブラウザーの起動失敗を再現する。"""
        raise error

    _fake_util(monkeypatch, build_url, fail_open)
    with pytest.raises(type(error)) as caught:
        tool_help.open_page("bd_channel_box")
    assert caught.value is error


def test_help_import_and_regular_reload_keep_dependencies_lazy(
    tmp_path: Path,
) -> None:
    """独立processで初回読込、未知ID、保持値、正規reloadの契約を確認する。"""
    source = '''
import importlib
import json
import sys
from pathlib import Path

baseline = set(sys.modules)
import bd_tools
assert "bd_tools.help" not in sys.modules
target = Path(bd_tools.__file__).parent / "help" / "pages.json"
original_read = Path.read_text
path = ["tools/tool/first/"]
reads = [0]

def read_pages(
    file: Path, encoding: str | None = None, errors: str | None = None
) -> str:
    """ヘルプJSONだけを仮想化し、配布ファイルを変更せず更新する。"""
    if file.resolve() == target.resolve():
        reads[0] += 1
        return json.dumps({
            "schema_version": 1,
            "package": "bd_tools",
            "pages": {"bd_channel_box": {
                "path": path[0],
                "source": "docs/help/example/index.md",
                "categories": ["util"],
            }},
        })
    return original_read(file, encoding=encoding, errors=errors)

Path.read_text = read_pages
try:
    old_help = importlib.import_module("bd_tools.help")
    old_pages = old_help.PAGES
    assert old_pages["bd_channel_box"].path == "tools/tool/first/"
    for operation in (old_help.get_url, old_help.open_page):
        try:
            operation("unknown")
        except KeyError as error:
            assert error.args == ("unknown",)
        else:
            raise AssertionError("unknown page ID did not fail")
    path[0] = "tools/tool/second/"
    assert old_help.PAGES["bd_channel_box"].path == "tools/tool/first/"
    assert reads[0] == 1
    bd_tools.reload_package()
    assert "bd_tools.help" not in sys.modules
    new_help = importlib.import_module("bd_tools.help")
    assert new_help is not old_help
    assert new_help.PAGES is not old_pages
    assert new_help.PAGES["bd_channel_box"].path == "tools/tool/second/"
    assert reads[0] == 2
    assert not any(
        name.startswith(("bd_util", "maya", "PySide", "PyQt", "webbrowser"))
        or name.startswith("bd_tools.bd_")
        for name in set(sys.modules) - baseline
    )
finally:
    Path.read_text = original_read
'''
    script_path = tmp_path / "reload_help.py"
    script_path.write_text(source, encoding="utf-8")
    environment = os.environ.copy()
    python_root = str(Path(bd_tools.__file__).resolve().parent.parent)
    environment["PYTHONPATH"] = os.pathsep.join(
        (python_root, environment.get("PYTHONPATH", ""))
    )
    completed = subprocess.run(
        [sys.executable, "-B", str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
