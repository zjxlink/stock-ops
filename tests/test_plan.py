import pandas as pd

from stock_ops.analysis.plan import build_plan, plan_for_code
from stock_ops.backtest import get_strategy
from stock_ops.portfolio.book import Position
from tests.conftest import make_daily


def test_holding_stop_loss_triggers_sell():
    df = make_daily("A", n=200, seed=1, trend=-0.01)
    pos = Position(code="A", shares=1000, cost=1000 * df["close"].iloc[-1] * 1.5)  # 成本远高于现价
    row = plan_for_code("A", df, get_strategy("ma_bull"), pos, stop_loss=0.08)
    assert row["action"] == "卖出" and "止损" in row["reason"] and row["status"] == "持仓"


def test_holding_in_uptrend_is_hold():
    df = make_daily("A", n=200, seed=1, trend=0.01)
    pos = Position(code="A", shares=1000, cost=1000 * df["close"].iloc[-1] * 0.9)
    row = plan_for_code("A", df, get_strategy("ma_bull"), pos, stop_loss=0.08)
    assert row["action"] == "持有" and row["stop_price"] < df["close"].iloc[-1]
    assert row["exit_level"] > 0


def test_watch_entry_signal_suggests_shares():
    df = make_daily("A", n=200, seed=1, trend=0.01)  # 强趋势：ma_bull 进场条件成立
    row = plan_for_code(
        "A", df, get_strategy("ma_bull"), None, capital=100000, position_pct=0.2, stop_loss=0.08
    )
    assert (
        row["action"] == "买入"
        and row["shares"] % 100 == 0
        and row["shares"] > 0
        and row["stop_price"] > 0
    )
    assert row["shares"] * df["close"].iloc[-1] <= 20000


def test_watch_no_signal():
    df = make_daily("A", n=200, seed=2, trend=-0.01)
    row = plan_for_code("A", df, get_strategy("ma_bull"), None)
    assert row["action"] == "观望" and "20日线" in row["reason"]


def test_build_plan_orders_sell_first_and_handles_missing():
    up, down = (
        make_daily("UP", n=200, seed=1, trend=0.01),
        make_daily("DN", n=200, seed=2, trend=-0.01),
    )
    book = {"DN": Position(code="DN", shares=100, cost=100 * down["close"].iloc[-1] * 2)}
    df = build_plan(
        ["UP", "DN", "NA"],
        {"UP": up, "DN": down, "NA": pd.DataFrame()},
        get_strategy("ma_bull"),
        book,
        names={"UP": "涨股"},
    )
    assert list(df["action"]) == ["卖出", "买入", "观望"]
    assert df.iloc[1]["name"] == "涨股" and df.iloc[2]["reason"] == "历史数据不足"


def test_hold_mode_never_sells_but_warns():
    df = make_daily("A", n=200, seed=1, trend=-0.01)
    pos = Position(
        code="A",
        shares=1000,
        cost=1000 * df["close"].iloc[-1] * 1.5,
        first_date=str(df["date"].iloc[0]),
    )
    row = plan_for_code(
        "A",
        df,
        get_strategy("ma_bull"),
        pos,
        stop_loss=0.08,
        trailing_stop=0.15,
        rule={"mode": "hold", "note": "长期持有"},
    )
    assert row["action"] == "持有" and "长期持有" in row["reason"] and "注意" in row["reason"]
    assert row["trail_price"] > 0 and "60日线" in row["reason"]


def test_trailing_stop_in_plan_uses_peak_since_entry():
    df = make_daily("A", n=200, seed=1, trend=0.0)
    df.loc[150:159, "close"] = df["close"].iloc[149] * 1.5  # 持仓期内冲高
    pos = Position(
        code="A", shares=100, cost=100 * df["close"].iloc[140], first_date=str(df["date"].iloc[140])
    )
    row = plan_for_code(
        "A", df, get_strategy("ma_bull"), pos, stop_loss=None, trailing_stop=0.15, atr_stop=None
    )
    peak = df["close"].iloc[140:].max()
    assert abs(row["trail_price"] - round(peak * 0.85, 2)) < 1e-6
    assert row["action"] == "卖出" and "移动止损" in row["reason"]


def test_per_stock_rule_overrides_trailing():
    df = make_daily("A", n=200, seed=1, trend=0.01)
    pos = Position(
        code="A",
        shares=100,
        cost=100 * df["close"].iloc[-1] * 0.9,
        first_date=str(df["date"].iloc[-5]),
    )
    row = plan_for_code(
        "A", df, get_strategy("ma_bull"), pos, trailing_stop=0.15, rule={"trailing_stop": 0.05}
    )
    assert abs(row["trail_price"] - round(df["close"].iloc[-5:].max() * 0.95, 2)) < 1e-6


def test_trailing_from_anchors_peak_for_legacy_positions():
    df = make_daily("A", n=200, seed=1, trend=0.0)
    df.loc[150:159, "close"] = df["close"].iloc[149] * 1.5  # 老仓位期间的历史高点
    pos = Position(
        code="A", shares=100, cost=100 * df["close"].iloc[140], first_date=str(df["date"].iloc[140])
    )
    anchor = str(df["date"].iloc[170])
    row = plan_for_code(
        "A",
        df,
        get_strategy("ma_bull"),
        pos,
        stop_loss=None,
        trailing_stop=0.15,
        trailing_from=anchor,
        atr_stop=None,
    )
    assert abs(row["trail_price"] - round(df["close"].iloc[170:].max() * 0.85, 2)) < 1e-6
    assert row["action"] in ("持有", "卖出")
