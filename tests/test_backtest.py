import numpy as np
import pandas as pd
import pytest

from stock_ops.backtest import BacktestConfig, Strategy, get_strategy, run_backtest, run_many
from stock_ops.data.base import DAILY_COLUMNS
from tests.conftest import make_daily


def _flat(n=200, price=10.0):
    dates = pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d")
    df = pd.DataFrame(
        {
            "code": "T",
            "date": dates,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1e6,
            "amount": 1e7,
            "turnover": 1.0,
            "pct_chg": 0.0,
        }
    )
    return df[DAILY_COLUMNS]


def test_fills_next_open_and_fees_are_charged():
    """第 100 日收盘发信号，第 101 日开盘买入；第 110 日信号出场，第 111 日开盘卖出。价格恒为 10，净亏损 = 费用。"""
    df = _flat()
    entry = lambda x: pd.Series(x.index == 100, index=x.index)  # noqa: E731
    exit_ = lambda x: pd.Series(x.index == 110, index=x.index)  # noqa: E731
    cfg = BacktestConfig(
        initial_cash=100_000, commission=0.001, min_commission=0, stamp_duty=0.001, slippage=0
    )
    r = run_backtest(df, Strategy("t", "", entry, exit_), cfg)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.entry_date == df["date"][101] and t.exit_date == df["date"][111]
    assert t.shares == 9900  # 100000/(10*1.001) 向下取整到 100 股
    expected_fee = 99_000 * 0.001 + 99_000 * (0.001 + 0.001)
    assert t.pnl == pytest.approx(-expected_fee, abs=0.01)
    assert r.equity.iloc[-1] == pytest.approx(100_000 - expected_fee, abs=0.01)


def test_no_lookahead_signal_on_last_bar_not_traded():
    df = _flat()
    entry = lambda x: pd.Series(x.index == len(x) - 1, index=x.index)  # noqa: E731
    r = run_backtest(df, Strategy("t", "", entry, lambda x: pd.Series(False, index=x.index)))
    assert r.trades == [] and r.metrics["trades"] == 0


def test_stop_loss_triggers():
    df = _flat(n=200, price=10.0)
    df.loc[120:, ["open", "high", "low", "close"]] = 9.0  # 第 120 日起跌 10%
    entry = lambda x: pd.Series(x.index == 100, index=x.index)  # noqa: E731
    cfg = BacktestConfig(stop_loss=0.08, slippage=0, min_commission=0)
    r = run_backtest(df, Strategy("t", "", entry, lambda x: pd.Series(False, index=x.index)), cfg)
    assert len(r.trades) == 1 and r.trades[0].reason == "stop_loss"
    assert r.trades[0].exit_date == df["date"][121]
    assert r.metrics["max_drawdown"] < -9


def test_builtin_strategies_run_on_synthetic():
    df = make_daily("600000", n=400, seed=3, trend=0.002)
    for name in ["ma_bull", "golden_cross", "macd", "breakout20", "score"]:
        r = run_backtest(df, get_strategy(name))
        assert set(r.metrics) >= {"total_return", "max_drawdown", "sharpe", "win_rate", "buy_hold"}
        assert r.metrics["max_drawdown"] <= 0
        assert len(r.equity) == len(df)


def test_run_many_skips_short_and_adds_mean():
    data = {"A": make_daily("A", n=400, seed=1), "B": make_daily("B", n=30, seed=2)}
    table, results = run_many(data, get_strategy("ma_bull"))
    assert list(table["code"]) == ["A", "平均"] and set(results) == {"A"}
    assert np.isfinite(table.iloc[-1]["total_return"])


def test_cli_backtest(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from stock_ops.cli import app
    from stock_ops.data import Cache

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "220")
    (tmp_path / "config.yaml").write_text(
        "data:\n  db_path: db.sqlite\nwatchlist: ['600000']\nbacktest:\n  start: '2024-01-01'\n",
        encoding="utf-8",
    )
    Cache(tmp_path / "db.sqlite").upsert_daily(make_daily("600000", n=400))
    r = CliRunner().invoke(app, ["backtest", "-s", "golden_cross", "--trades"])
    assert r.exit_code == 0, r.output
    assert "600000" in r.output
    r = CliRunner().invoke(app, ["backtest", "-s", "all"])
    assert r.exit_code == 0 and "ma_bull" in r.output


def test_trailing_stop_triggers_from_peak():
    df = _flat(n=200, price=10.0)
    df.loc[110:119, ["open", "high", "low", "close"]] = 12.0  # 冲高到 12
    df.loc[120:, ["open", "high", "low", "close"]] = 10.0  # 回到 10：自高点回撤 16.7%
    entry = lambda x: pd.Series(x.index == 100, index=x.index)  # noqa: E731
    cfg = BacktestConfig(stop_loss=None, trailing_stop=0.15, slippage=0, min_commission=0)
    r = run_backtest(df, Strategy("t", "", entry, lambda x: pd.Series(False, index=x.index)), cfg)
    assert len(r.trades) == 1 and r.trades[0].reason == "trailing_stop"
    assert r.trades[0].exit_date == df["date"][121]
