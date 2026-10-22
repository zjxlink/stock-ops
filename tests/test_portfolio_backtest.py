import pandas as pd

from stock_ops.backtest import BacktestConfig, Strategy, get_strategy, run_portfolio
from tests.conftest import make_daily


def _sig(idx):
    return lambda x: pd.Series(x.index.isin(idx), index=x.index)


def test_portfolio_respects_max_positions_and_shares_cash():
    data = {
        c: make_daily(c, n=300, seed=i, trend=0.002) for i, c in enumerate(["A", "B", "C", "D"])
    }
    strat = Strategy("t", "", _sig([100]), _sig([150]))  # 四只同一天发信号
    cfg = BacktestConfig(atr_stop=None, min_hold_days=0, slippage=0, min_commission=0)
    r = run_portfolio(data, strat, cfg, max_positions=2)
    assert len(r.trades) == 2  # 只开了两只
    entry_cost = sum(t.shares * t.entry_price for t in r.trades)
    assert 0.8 * cfg.initial_cash < entry_cost <= cfg.initial_cash  # 两个仓位各约一半资金
    assert set(r.metrics) >= {"total_return", "max_drawdown", "exposure", "buy_hold", "calmar"}
    assert 0 < r.metrics["exposure"] < 100


def test_portfolio_regime_blocks_and_cooldown():
    data = {"A": make_daily("A", n=300, seed=1, trend=0.0)}
    dates = data["A"]["date"].astype(str)
    regime = pd.Series(False, index=dates.to_numpy())
    strat = Strategy("t", "", _sig([100, 120]), _sig([110]))
    r = run_portfolio(data, strat, BacktestConfig(atr_stop=None), regime=regime)
    assert r.trades == []


def test_portfolio_builtin_strategies_run():
    data = {
        c: make_daily(c, n=400, seed=i, trend=t)
        for i, (c, t) in enumerate([("A", 0.003), ("B", -0.001), ("C", 0.001)])
    }
    for name in ["donchian", "breakout20", "ma_bull"]:
        r = run_portfolio(data, get_strategy(name), BacktestConfig(), max_positions=2)
        assert len(r.equity) == 400 and r.metrics["max_drawdown"] <= 0
