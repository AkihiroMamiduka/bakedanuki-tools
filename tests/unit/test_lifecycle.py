# coding: utf-8
from __future__ import annotations

import pytest

from bd_tools._dev.lifecycle import (
    ReloadDisposalError,
    dispose_for_reload,
    register_reload_disposer,
    unregister_reload_disposer,
)


def test_disposers_run_once_in_reverse_registration_order() -> None:
    """終了処理が登録と逆順で1度だけ実行されることを確認する。"""
    events: list[str] = []

    def first() -> None:
        """1件目の終了処理を記録する。"""
        events.append("first")

    def second() -> None:
        """2件目の終了処理を記録する。"""
        events.append("second")

    # 重複を含む登録後、終了処理を2回実行して一度だけ呼ばれることを確認する
    assert register_reload_disposer(first) is first
    assert register_reload_disposer(second) is second
    assert register_reload_disposer(first) is first

    dispose_for_reload()
    dispose_for_reload()

    assert events == ["second", "first"]


def test_unregister_reports_whether_disposer_was_registered() -> None:
    """登録解除の成否を戻り値で区別できることを確認する。"""

    def disposer() -> None:
        """登録解除後に呼ばれた場合はテストを失敗させる。"""
        raise AssertionError("unregistered disposer must not run")

    # 登録解除後の終了処理が呼ばれず、解除結果も区別できることを確認する
    register_reload_disposer(disposer)

    assert unregister_reload_disposer(disposer) is True
    assert unregister_reload_disposer(disposer) is False


def test_every_disposer_runs_before_failures_are_reported() -> None:
    """一部の失敗後も全終了処理が実行されることを確認する。"""
    events: list[str] = []

    def successful() -> None:
        """成功する終了処理を記録する。"""
        events.append("successful")

    def failing() -> None:
        """失敗する終了処理を記録して例外を送出する。"""
        events.append("failing")
        raise ValueError("expected failure")

    # 1件が失敗しても残りを実行し、最後に失敗をまとめることを確認する
    register_reload_disposer(successful)
    register_reload_disposer(failing)

    with pytest.raises(ReloadDisposalError) as caught:
        dispose_for_reload()

    assert events == ["failing", "successful"]
    assert len(caught.value.errors) == 1
    assert isinstance(caught.value.errors[0], ValueError)

    dispose_for_reload()
