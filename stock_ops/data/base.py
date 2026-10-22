"""数据源抽象。所有 Provider 返回统一列名的 DataFrame，分析层不关心数据来自哪里。"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

# 日K线统一列
DAILY_COLUMNS = [
    "code",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
    "pct_chg",
]
# 全市场快照统一列
SNAPSHOT_COLUMNS = [
    "code",
    "name",
    "price",
    "pct_chg",
    "pe_ttm",
    "pb",
    "total_mv",
    "float_mv",
    "turnover",
    "volume",
    "amount",
]


def normalize_code(code: str) -> str:
    """把 sh.600519 / 600519.SH / sh600519 统一成 6 位数字代码。"""
    s = str(code).strip().lower()
    for prefix in ("sh.", "sz.", "bj.", "sh", "sz", "bj"):
        if s.startswith(prefix) and s[len(prefix) :].isdigit():
            s = s[len(prefix) :]
            break
    s = s.split(".")[0]
    return s.zfill(6)


def exchange_prefix(code: str) -> str:
    """根据代码判断交易所前缀：sh / sz / bj。"""
    c = normalize_code(code)
    if c.startswith(("6", "9", "5")):
        return "sh"
    if c.startswith(("4", "8")):
        return "bj"
    return "sz"


def empty_daily() -> pd.DataFrame:
    return pd.DataFrame(columns=DAILY_COLUMNS)


def empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


class DataProvider(Protocol):
    name: str

    def daily(self, code: str, start: str, end: str) -> pd.DataFrame:
        """前复权日K线，日期格式 YYYY-MM-DD，返回 DAILY_COLUMNS。"""
        ...

    def snapshot(self) -> pd.DataFrame:
        """全市场最新快照，返回 SNAPSHOT_COLUMNS。不支持时抛 NotImplementedError。"""
        ...
