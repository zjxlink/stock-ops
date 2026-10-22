import numpy as np

from stock_ops.analysis.indicators import add_indicators, rsi, sma


def test_sma_matches_manual(daily):
    s = sma(daily["close"], 5)
    assert np.isnan(s.iloc[3])
    assert abs(s.iloc[4] - daily["close"].iloc[:5].mean()) < 1e-9


def test_rsi_bounds(daily):
    r = rsi(daily["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_rsi_all_up_is_100():
    import pandas as pd

    r = rsi(pd.Series(np.arange(1, 40, dtype=float)))
    assert r.iloc[-1] == 100


def test_add_indicators_columns(daily):
    x = add_indicators(daily)
    for col in [
        "ma5",
        "ma20",
        "ma60",
        "dif",
        "dea",
        "macd",
        "rsi",
        "boll_up",
        "atr",
        "vol_ratio",
        "high20",
    ]:
        assert col in x.columns
    assert x["ma60"].notna().sum() == len(daily) - 59
