"""技术面信号。每个信号是对最后一根K线的布尔判断，汇总成一行打分。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .indicators import add_indicators

MIN_BARS = 70  # ma60 需要 60 根，留出余量


def technical_signals(df: pd.DataFrame, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回最后一根K线的信号字典。数据不足时 ok=False。"""
    p = {
        "ma_fast": 5,
        "ma_mid": 20,
        "ma_slow": 60,
        "rsi_period": 14,
        "rsi_max": 75,
        "volume_ratio_min": 1.2,
    }
    p.update(params or {})
    if df is None or len(df) < MIN_BARS:
        return {"ok": False, "reason": f"数据不足 {MIN_BARS} 根"}

    x = add_indicators(df, p["ma_fast"], p["ma_mid"], p["ma_slow"], p["rsi_period"])
    last, prev = x.iloc[-1], x.iloc[-2]
    f, m, s = f"ma{p['ma_fast']}", f"ma{p['ma_mid']}", f"ma{p['ma_slow']}"

    sig = {
        "ok": True,
        "code": str(last["code"]),
        "date": str(last["date"]),
        "close": float(last["close"]),
        # 趋势
        "ma_bull": bool(last[f] > last[m] > last[s]),  # 均线多头排列
        "above_ma_mid": bool(last["close"] > last[m]),  # 站上中期均线
        "golden_cross": bool(prev[f] <= prev[m] and last[f] > last[m]),  # 快线上穿中线
        "macd_cross_up": bool(prev["dif"] <= prev["dea"] and last["dif"] > last["dea"]),
        "macd_above_zero": bool(last["dif"] > 0),
        # 动量 / 超买
        "rsi": round(float(last["rsi"]), 2),
        "rsi_ok": bool(last["rsi"] < p["rsi_max"]),
        "ret20": round(float(last["ret20"]), 2),
        # 量能
        "vol_ratio": round(float(last["vol_ratio"]), 2),
        "volume_up": bool(last["vol_ratio"] >= p["volume_ratio_min"]),
        # 突破
        "breakout20": bool(last["close"] >= prev["high20"]),  # 收盘创 20 日新高
        "boll_squeeze": bool((last["boll_up"] - last["boll_low"]) / last["boll_mid"] < 0.1),
    }
    score = sum(
        [
            2 * sig["ma_bull"],
            sig["above_ma_mid"],
            2 * sig["golden_cross"],
            2 * sig["macd_cross_up"],
            sig["macd_above_zero"],
            sig["volume_up"],
            2 * sig["breakout20"],
        ]
    )
    if not sig["rsi_ok"]:
        score -= 2
    sig["score"] = int(score)
    return sig


def rank_signals(signals: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [s for s in signals if s.get("ok")]
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["score", "ret20"], ascending=[False, False])
        .reset_index(drop=True)
    )
