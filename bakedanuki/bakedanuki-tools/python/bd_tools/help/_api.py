"""登録されたヘルプのURL生成とブラウザー起動。"""

from __future__ import annotations

from ._registry import PAGES


def get_url(page_id: str) -> str:
    """登録されたページIDの完成URLを返す。

    Args:
        page_id: 同梱のページ対応表へ登録されたID。

    Returns:
        utilのサイト基点URLと、登録された公開パスから作る完成URL。

    Raises:
        KeyError: `page_id` が未登録の場合。
        OSError: utilのサイト情報を読み込めない場合。
        ValueError: utilのサイト情報または公開パスが不正な場合。
    """
    # 未登録IDを先に拒否し、URL生成時だけutilを読み込む
    page = PAGES[page_id]
    from bd_util import site

    return site.build_url(page.path)


def open_page(page_id: str) -> bool:
    """登録されたヘルプをブラウザーへ渡し、起動依頼の成否を返す。

    ページの存在やHTTP応答は確認しません。importやURL生成だけでは
    ブラウザーを起動しません。

    Args:
        page_id: 同梱のページ対応表へ登録されたID。

    Returns:
        ブラウザーへの起動依頼が成功した場合は `True`。

    Raises:
        KeyError: `page_id` が未登録の場合。
        OSError: サイト情報の読込またはブラウザー起動に失敗した場合。
        ValueError: サイト情報または公開パスが不正な場合。
        webbrowser.Error: ブラウザー制御に失敗した場合。
    """
    # URLを確定してから、明示操作でだけブラウザーAPIを利用する
    url = get_url(page_id)
    from bd_util.py import web

    return web.open_url(url)
