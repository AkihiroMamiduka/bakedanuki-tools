"""ヘルプ対応表と公開APIの戻り値型を固定する。"""

from collections.abc import Mapping
from typing import assert_type

from bd_tools import help as tool_help
from bd_tools.help import PAGES, HelpPage, get_url, open_page

assert_type(PAGES, Mapping[str, HelpPage])
assert_type(tool_help.PAGES["bd_channel_box"], HelpPage)
assert_type(PAGES["bd_channel_box"].page_id, str)
assert_type(PAGES["bd_channel_box"].path, str)
assert_type(PAGES["bd_channel_box"].source, str)
assert_type(PAGES["bd_channel_box"].categories, tuple[str, ...])
assert_type(get_url(page_id="bd_channel_box"), str)
assert_type(tool_help.get_url("bd_channel_box"), str)
assert_type(open_page(page_id="bd_channel_box"), bool)
assert_type(tool_help.open_page("bd_channel_box"), bool)
