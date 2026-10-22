"""腾讯批量行情：qt.gtimg.cn/q=sh600519,sz000001,... 一次最多数十只，含 PE、PB、总市值、换手率。

在数据中心 IP（GitHub Actions 等）下可用，是东方财富不可用时的全市场快照来源。
股票池来自新浪 ak.stock_zh_a_spot()（约 5500 只），同样对数据中心 IP 友好。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

import pandas as pd

from .base import SNAPSHOT_COLUMNS, empty_snapshot, exchange_prefix, normalize_code

log = logging.getLogger(__name__)

_URL = "https://qt.gtimg.cn/q="
_BATCH = 60
# 腾讯行情字段索引（以 ~ 分隔）
_F = {
    "name": 1,
    "code": 2,
    "price": 3,
    "volume": 6,
    "pct_chg": 32,
    "amount": 37,
    "turnover": 38,
    "pe_ttm": 39,
    "total_mv": 44,
    "float_mv": 45,
    "pb": 46,
}


def parse_quote_line(line: str) -> dict | None:
    """解析形如 v_sh600519="1~贵州茅台~600519~..." 的一行。字段不足时返回 None。"""
    if '="' not in line:
        return None
    body = line.split('="', 1)[1].rstrip('";\n ')
    f = body.split("~")
    if len(f) <= max(_F.values()):
        return None

    def num(i: int) -> float:
        return pd.to_numeric(f[i], errors="coerce")

    return {
        "code": normalize_code(f[_F["code"]]),
        "name": f[_F["name"]],
        "price": num(_F["price"]),
        "pct_chg": num(_F["pct_chg"]),
        "pe_ttm": num(_F["pe_ttm"]),
        "pb": num(_F["pb"]),
        "total_mv": num(_F["total_mv"]) * 1e8,
        "float_mv": num(_F["float_mv"]) * 1e8,  # 亿 -> 元
        "turnover": num(_F["turnover"]),
        "volume": num(_F["volume"]) * 100,  # 手 -> 股
        "amount": num(_F["amount"]) * 1e4,  # 万 -> 元
    }


def sina_universe() -> list[str]:
    """从新浪全市场行情取 A 股代码池（6 位）。偶发超时。"""
    import akshare as ak

    df = ak.stock_zh_a_spot()
    codes = df["代码"].map(normalize_code)
    return sorted(c for c in codes if c[:2] in ("60", "68", "00", "30"))


def baostock_universe() -> list[str]:
    from .baostock_provider import BaostockProvider

    bs = BaostockProvider()
    try:
        return sorted(bs.stock_list()["code"].tolist())
    finally:
        bs.close()


def default_universe() -> list[str]:
    """股票池：新浪（快）失败时退化为 Baostock 股票列表（稳）。"""
    try:
        codes = sina_universe()
        if codes:
            return codes
        log.warning("新浪股票池为空，改用 baostock")
    except Exception as e:
        log.warning("新浪股票池失败，改用 baostock: %s", e)
    return baostock_universe()


class TencentQuoteProvider:
    name = "tencent"

    def __init__(self, request_interval: float = 0.2, universe_fn=default_universe) -> None:
        self.request_interval = request_interval
        self.universe_fn = universe_fn

    def quotes(self, codes: Iterable[str]) -> pd.DataFrame:
        import requests

        rows = []
        codes = [normalize_code(c) for c in codes]
        for i in range(0, len(codes), _BATCH):
            batch = codes[i : i + _BATCH]
            q = ",".join(f"{exchange_prefix(c)}{c}" for c in batch)
            r = requests.get(_URL + q, timeout=15)
            r.raise_for_status()
            r.encoding = "gbk"
            for line in r.text.splitlines():
                d = parse_quote_line(line)
                if d:
                    rows.append(d)
            time.sleep(self.request_interval)
        if not rows:
            return empty_snapshot()
        return pd.DataFrame(rows).reindex(columns=SNAPSHOT_COLUMNS)

    def snapshot(self, codes: list[str] | None = None) -> pd.DataFrame:
        universe = [normalize_code(c) for c in codes] if codes else self.universe_fn()
        log.info("腾讯快照：%d 只，分 %d 批", len(universe), -(-len(universe) // _BATCH))
        return self.quotes(universe)

    def daily(self, code: str, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError
