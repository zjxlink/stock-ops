from stock_ops.analysis.technical import rank_signals, technical_signals
from tests.conftest import make_daily


def test_insufficient_data():
    s = technical_signals(make_daily(n=30))
    assert s["ok"] is False


def test_uptrend_is_bullish():
    s = technical_signals(make_daily(n=200, trend=0.01, seed=1))
    assert s["ok"] and s["ma_bull"] and s["macd_above_zero"]
    assert s["score"] >= 3


def test_downtrend_is_bearish():
    s = technical_signals(make_daily(n=200, trend=-0.01, seed=2))
    assert s["ok"] and not s["ma_bull"] and not s["above_ma_mid"]


def test_rank_orders_by_score():
    up = technical_signals(make_daily("A", trend=0.01, seed=1))
    down = technical_signals(make_daily("B", trend=-0.01, seed=2))
    df = rank_signals([down, up])
    assert df.iloc[0]["code"] == "A"
