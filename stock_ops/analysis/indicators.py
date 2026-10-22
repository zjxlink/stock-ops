"""常用技术指标，纯 pandas 实现，不依赖 TA-Lib。输入为 DAILY_COLUMNS 的 DataFrame（按日期升序）。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return pd.DataFrame({"dif": dif, "dea": dea, "macd": (dif - dea) * 2})


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100).where(avg_loss != 0, 100).where(avg_gain.notna(), np.nan)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"boll_mid": mid, "boll_up": mid + k * std, "boll_low": mid - k * std})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def add_indicators(
    df: pd.DataFrame, ma_fast: int = 5, ma_mid: int = 20, ma_slow: int = 60, rsi_period: int = 14
) -> pd.DataFrame:
    """在原 DataFrame 基础上追加指标列，返回新 DataFrame。"""
    out = df.sort_values("date").reset_index(drop=True).copy()
    close = out["close"].astype(float)
    out[f"ma{ma_fast}"] = sma(close, ma_fast)
    out[f"ma{ma_mid}"] = sma(close, ma_mid)
    out[f"ma{ma_slow}"] = sma(close, ma_slow)
    out = pd.concat([out, macd(close), bollinger(close)], axis=1)
    out["rsi"] = rsi(close, rsi_period)
    out["atr"] = atr(out)
    out["vol_ma20"] = sma(out["volume"].astype(float), 20)
    out["vol_ratio"] = out["volume"] / out["vol_ma20"]
    out["high20"] = out["high"].rolling(20, min_periods=20).max()
    out["ret20"] = close.pct_change(20) * 100
    return out
