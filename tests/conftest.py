import numpy as np
import pandas as pd
import pytest

from stock_ops.data.base import DAILY_COLUMNS


def make_daily(code="600000", n=200, seed=0, trend=0.001) -> pd.DataFrame:
    """合成一段带趋势的随机日K，用于离线测试。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d")
    ret = rng.normal(trend, 0.02, n)
    close = 10 * np.cumprod(1 + ret)
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    df = pd.DataFrame(
        {
            "code": code,
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "amount": vol * close,
            "turnover": rng.uniform(0.5, 3, n),
            "pct_chg": ret * 100,
        }
    )
    return df[DAILY_COLUMNS]


@pytest.fixture
def daily():
    return make_daily()


@pytest.fixture
def snapshot():
    return pd.DataFrame(
        {
            "code": ["600001", "600002", "600003", "600004", "600005"],
            "name": ["好公司", "ST烂厂", "贵公司", "小公司", "冷门股"],
            "price": [10, 2, 100, 5, 8],
            "pct_chg": [1, -3, 2, 0, 0.5],
            "pe_ttm": [15, 8, 80, 12, 10],
            "pb": [1.5, 0.8, 10, 2, 1.2],
            "total_mv": [1e10, 2e9, 5e11, 1e9, 2e10],
            "float_mv": [8e9, 1e9, 4e11, 8e8, 1e10],
            "turnover": [1.2, 5, 0.8, 3, 0.1],
            "volume": [1e6] * 5,
            "amount": [1e7] * 5,
        }
    )
