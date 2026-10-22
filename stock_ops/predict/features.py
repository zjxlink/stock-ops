"""预测用特征。全部由 add_indicators 之后的日K派生，只用当日及之前的数据。"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["r1", "r5", "r20", "rsi_c", "vol_ratio_c", "pos20", "ma5_gap", "ma20_gap", "atr_pct"]


def make_features(x: pd.DataFrame) -> pd.DataFrame:
    """输入 add_indicators 的输出，返回带特征列与 target（次日是否上涨）的副本。最后一行 target 为 NaN。"""
    f = x.copy()
    close = f["close"].astype(float)
    f["r1"] = close.pct_change(1)
    f["r5"] = close.pct_change(5)
    f["r20"] = close.pct_change(20)
    f["rsi_c"] = (f["rsi"] - 50) / 50
    f["vol_ratio_c"] = (f["vol_ratio"].clip(upper=5) - 1).fillna(0)
    rng = (f["high20"] - f["low20"]).replace(0, np.nan)
    f["pos20"] = ((close - f["low20"]) / rng - 0.5).fillna(0)
    f["ma5_gap"] = close / f["ma5"] - 1
    f["ma20_gap"] = close / f["ma20"] - 1
    f["atr_pct"] = f["atr"] / close
    f["target"] = (close.shift(-1) > close).astype(float)
    f.loc[f.index[-1], "target"] = np.nan
    return f
