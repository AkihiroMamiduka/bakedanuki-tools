"""同梱JSONを検証し、読み取り専用のヘルプ対応表へ保持する。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn, cast

_PAGE_ID = re.compile(r"[a-z][a-z0-9_]*")
_PAGE_PATH = re.compile(r"(?:[a-z0-9]+(?:-[a-z0-9]+)*/)+")
_CATEGORY = re.compile(r"[a-z][a-z0-9-]*")


@dataclass(frozen=True)
class HelpPage:
    """ページID、公開パス、原稿パス、分類を保持する変更不能な値。"""

    page_id: str
    path: str
    source: str
    categories: tuple[str, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSONオブジェクト内の重複キーを拒否する。"""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSONのキーが重複しています: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    """JSONで定義されていない数値定数を拒否する。"""
    raise ValueError(f"JSONで使用できない定数です: {value}")


def _as_object(value: object, field: str) -> dict[str, object]:
    """指定フィールドをJSONオブジェクトとして検証する。"""
    if not isinstance(value, dict):
        raise ValueError(f"{field}にはJSONオブジェクトが必要です")
    return cast(dict[str, object], value)


def _load_page(page_id: str, value: object) -> HelpPage:
    """ページごとのフィールドを検証し、変更不能な値を返す。"""
    if _PAGE_ID.fullmatch(page_id) is None:
        raise ValueError(f"ページIDの形式が不正です: {page_id}")
    field = f"pages.{page_id}"
    data = _as_object(value, field)
    if set(data) != {"path", "source", "categories"}:
        raise ValueError(
            f"{field}のフィールドはpath・source・categoriesのみです"
        )

    # 公開パスをtools配下に限定し、ホストや共通パスの置換を防ぐ
    path = data["path"]
    if (
        not isinstance(path, str)
        or not path.startswith("tools/")
        or _PAGE_PATH.fullmatch(path) is None
    ):
        raise ValueError(f"{field}.pathの形式が不正です")

    # 原稿の存在は要求せず、配布root内の相対パスとして検証する
    source = data["source"]
    if (
        not isinstance(source, str)
        or not source.startswith("docs/help/")
        or not source.endswith(".md")
        or "\\" in source
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in source
        )
        or any(part in ("", ".", "..") for part in source.split("/"))
    ):
        raise ValueError(f"{field}.sourceの形式が不正です")

    # 分類は順序を持つ固定tupleへ変換し、同一ページ内の重複を拒否する
    categories_value = data["categories"]
    if not isinstance(categories_value, list):
        raise ValueError(f"{field}.categoriesには配列が必要です")
    categories: list[str] = []
    for category in cast(list[object], categories_value):
        if (
            not isinstance(category, str)
            or _CATEGORY.fullmatch(category) is None
        ):
            raise ValueError(f"{field}.categoriesの分類IDが不正です")
        if category in categories:
            raise ValueError(f"{field}.categoriesに重複があります: {category}")
        categories.append(category)

    return HelpPage(page_id, path, source, tuple(categories))


def _load_pages() -> Mapping[str, HelpPage]:
    """同梱JSONの形式と一意性を検証し、読み取り専用の対応表を返す。"""
    data_path = Path(__file__).with_name("pages.json")

    # 作業directoryへ依存せず、同梱ファイルを一度だけ読み込む
    try:
        text = data_path.read_text(encoding="utf-8")
    except OSError as error:
        raise OSError(
            f"ヘルプ対応表を読み込めません: {data_path}: {error}"
        ) from error
    except UnicodeError as error:
        raise ValueError(
            f"{data_path}: UTF-8のヘルプ対応表を読み込めません: {error}"
        ) from error

    # キーと型を固定し、不正な設定を補正や代替ページで隠さない
    try:
        payload = cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            ),
        )
        data = _as_object(payload, "ルート")
        if set(data) != {"schema_version", "package", "pages"}:
            raise ValueError(
                "ルートのフィールドはschema_version・package・pagesのみです"
            )
        schema_version = data["schema_version"]
        if type(schema_version) is not int or schema_version != 1:
            raise ValueError("schema_versionは整数の1で指定してください")
        if data["package"] != "bd_tools":
            raise ValueError("packageはbd_toolsで指定してください")
        pages_data = _as_object(data["pages"], "pages")
        if not pages_data:
            raise ValueError("pagesには1件以上のページが必要です")

        # 公開パスと原稿の割当てをページ間でも一意にする
        pages: dict[str, HelpPage] = {}
        paths: set[str] = set()
        sources: set[str] = set()
        for page_id, value in pages_data.items():
            page = _load_page(page_id, value)
            if page.path in paths:
                raise ValueError(f"pathが重複しています: {page.path}")
            if page.source in sources:
                raise ValueError(f"sourceが重複しています: {page.source}")
            paths.add(page.path)
            sources.add(page.source)
            pages[page_id] = page
        return MappingProxyType(pages)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"{data_path}: {error}") from error


# 読込後の参照はJSONへアクセスせず、正規reload時にのみ作り直す
PAGES: Final[Mapping[str, HelpPage]] = _load_pages()
