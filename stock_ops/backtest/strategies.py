"""内置策略：每个策略给出进场 / 出场布尔序列，基于 add_indicators 之后的日K。

信号在第 t 日收盘确认，引擎在第 t+1 日开盘成交。策略函数不得使用未来数据。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from ..analysis.technical import technical_signals  # noqa: F401  (保持与信号定义一致的引用)

Rule = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class Strategy:
    name: str
    description: str
    entry: Rule
    exit: Rule


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.shift(1) <= b.shift(1)) & (a > b)


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.shift(1) >= b.shift(1)) & (a < b)


def _score(x: pd.DataFrame) -> pd.Series:
    """与 technical_signals 相同口径的逐日综合评分。"""
    ma_bull = (x["ma5"] > x["ma20"]) & (x["ma20"] > x["ma60"])
    above = x["close"] > x["ma20"]
    gc = _cross_up(x["ma5"], x["ma20"])
    mc = _cross_up(x["dif"], x["dea"])
    macd_pos = x["dif"] > 0
    vol_up = x["vol_ratio"] >= 1.2
    brk = x["close"] >= x["high20"].shift(1)
    rsi_bad = x["rsi"] >= 75
    return (
        2 * ma_bull + above + 2 * gc + 2 * mc + macd_pos + vol_up + 2 * brk - 2 * rsi_bad
    ).astype(float)


STRATEGIES: dict[str, Strategy] = {
    "ma_bull": Strategy(
        "ma_bull",
        "均线多头：5>20>60 进场，收盘跌破 20 日线出场",
        entry=lambda x: (x["ma5"] > x["ma20"]) & (x["ma20"] > x["ma60"]),
        exit=lambda x: x["close"] < x["ma20"],
    ),
    "golden_cross": Strategy(
        "golden_cross",
        "金叉：5 日线上穿 20 日线进场，下穿出场",
        entry=lambda x: _cross_up(x["ma5"], x["ma20"]),
        exit=lambda x: _cross_down(x["ma5"], x["ma20"]),
    ),
    "macd": Strategy(
        "macd",
        "MACD：DIF 上穿 DEA 进场，下穿出场",
        entry=lambda x: _cross_up(x["dif"], x["dea"]),
        exit=lambda x: _cross_down(x["dif"], x["dea"]),
    ),
    "breakout20": Strategy(
        "breakout20",
        "20 日突破：收盘创 20 日新高且放量进场，收盘跌破 20 日线出场",
        entry=lambda x: (x["close"] >= x["high20"].shift(1)) & (x["vol_ratio"] >= 1.2),
        exit=lambda x: x["close"] < x["ma20"],
    ),
    "score": Strategy(
        "score",
        "综合评分：评分 ≥ 4 进场，评分 ≤ 0 或跌破 20 日线出场",
        entry=lambda x: _score(x) >= 4,
        exit=lambda x: (_score(x) <= 0) | (x["close"] < x["ma20"]),
    ),
}


def get_strategy(name: str) -> Strategy:
    if name not in STRATEGIES:
        raise KeyError(f"未知策略 {name}，可选: {', '.join(STRATEGIES)}")
    return STRATEGIES[name]
