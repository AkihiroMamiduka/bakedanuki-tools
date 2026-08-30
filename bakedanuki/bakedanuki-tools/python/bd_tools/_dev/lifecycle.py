# coding: utf-8
""":mod:`bd_tools`のreload前に使用するlifecycle hook。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

ReloadDisposer = Callable[[], None]
ReloadDisposerT = TypeVar("ReloadDisposerT", bound=ReloadDisposer)

# reload前に実行する終了処理を登録順で保持する
_reload_disposers: list[ReloadDisposer] = []


class ReloadDisposalError(RuntimeError):
    """1件以上のreload終了処理が失敗した場合の例外。"""

    errors: tuple[Exception, ...]

    def __init__(self, errors: Sequence[Exception]) -> None:
        """失敗した終了処理を保持する例外を初期化する。"""
        self.errors = tuple(errors)
        super().__init__(f"{len(self.errors)} reload disposer(s) failed.")


def register_reload_disposer(
    disposer: ReloadDisposerT,
) -> ReloadDisposerT:
    """次回のreload前に1度だけ呼び出す終了処理を登録する。

    同じcallableを再登録しても重複させない。
    終了処理は登録と逆の順序で実行する。
    """
    # 同じ終了処理の二重登録を避ける
    if disposer not in _reload_disposers:
        _reload_disposers.append(disposer)
    return disposer


def unregister_reload_disposer(disposer: ReloadDisposer) -> bool:
    """登録済みの終了処理を解除する。

    戻り値:
        登録済みの終了処理を解除した場合は``True``。
    """
    # 未登録の場合は例外を外へ出さず、解除できなかったことを返す
    try:
        _reload_disposers.remove(disposer)
    except ValueError:
        return False
    return True


def dispose_for_reload() -> None:
    """登録されたすべての終了処理を実行して登録を空にする。

    途中で失敗しても残りのcallbackを実行する。
    破棄が不完全なMaya状態でreloadを続けないよう、最後に失敗をまとめて通知する。
    """
    # 実行前に登録を空にし、再入時の二重実行を防ぐ
    disposers = tuple(reversed(_reload_disposers))
    _reload_disposers.clear()

    # すべての終了処理を試し、個別の失敗を保持する
    errors: list[Exception] = []
    for disposer in disposers:
        try:
            disposer()
        except Exception as error:
            errors.append(error)

    # 失敗があれば、終了処理を一巡した後でまとめて通知する
    if errors:
        raise ReloadDisposalError(errors)
