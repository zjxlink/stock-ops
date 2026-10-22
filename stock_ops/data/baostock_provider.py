"""Baostock：历史日K主源。免费、无 Token、官方服务器，稳定性最好。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .base import (
    DAILY_COLUMNS,
    SNAPSHOT_COLUMNS,
    empty_daily,
    empty_snapshot,
    exchange_prefix,
    normalize_code,
)

_FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg"


def bs_code_of(code: str) -> tuple[str, str]:
    """返回 (缓存用代码, baostock 代码)。带交易所前缀的指数如 sh.000300 原样直通，否则按 6 位股票代码推断。"""
    s = str(code).strip().lower()
    if "." in s and s.split(".")[0] in ("sh", "sz") and s.split(".")[1].isdigit():
        return s, s
    c = normalize_code(s)
    return c, f"{exchange_prefix(c)}.{c}"


class BaostockProvider:
    name = "baostock"

    def __init__(self) -> None:
        self._logged_in = False

    def _ensure_login(self):
        import baostock as bs

        if not self._logged_in:
            lg = bs.login()
            if lg.error_code != "0":
                raise ConnectionError(f"baostock login failed: {lg.error_msg}")
            self._logged_in = True
        return bs

    def close(self) -> None:
        if self._logged_in:
            import baostock as bs

            bs.logout()
            self._logged_in = False

    def daily(self, code: str, start: str, end: str) -> pd.DataFrame:
        bs = self._ensure_login()
        c, bs_code = bs_code_of(code)
        rs = bs.query_history_k_data_plus(
            bs_code,
            _FIELDS,
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="2",
        )
        if rs.error_code != "0":
            raise ConnectionError(f"baostock query failed: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return empty_daily()
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={"turn": "turnover", "pctChg": "pct_chg"})
        df["code"] = c
        for col in ["open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[DAILY_COLUMNS]

    def is_trading_day(self, day: str) -> bool:
        bs = self._ensure_login()
        rs = bs.query_trade_dates(start_date=day, end_date=day)
        if rs.error_code != "0":
            raise ConnectionError(f"baostock query_trade_dates failed: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return bool(rows) and rows[0][1] == "1"

    def stock_list(self, day: str | None = None, lookback_days: int = 10) -> pd.DataFrame:
        """全部 A 股代码与名称。当天数据盘后才生成，因此从 day 起向前回退到最近有数据的交易日。"""
        bs = self._ensure_login()
        d0 = date.fromisoformat(day) if day else date.today()
        for back in range(lookback_days):
            d = (d0 - timedelta(days=back)).isoformat()
            rs = bs.query_all_stock(day=d)
            if rs.error_code != "0":
                raise ConnectionError(f"baostock query_all_stock failed: {rs.error_msg}")
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if rows:
                break
        else:
            return pd.DataFrame(columns=["code", "name", "trade_status"])
        df = pd.DataFrame(rows, columns=rs.fields).rename(
            columns={"code_name": "name", "tradeStatus": "trade_status"}
        )
        raw = df["code"].astype(str)
        # 只保留沪深 A 股：上海 60/68 开头，深圳 00/30 开头；排除 sh.000xxx / sz.399xxx 指数与基金债券
        mask = raw.str.match(r"^sh\.(60|68)\d{4}$") | raw.str.match(r"^sz\.(00|30)\d{4}$")
        df = df[mask].copy()
        df["code"] = df["code"].map(normalize_code)
        return df.drop_duplicates("code")[["code", "name", "trade_status"]].reset_index(drop=True)

    def latest_valuation(self, code: str, lookback_days: int = 10) -> dict | None:
        """最近一个交易日的收盘、涨跌幅、换手、PE(TTM)、PB(MRQ)。"""
        bs = self._ensure_login()
        c = normalize_code(code)
        end = date.today()
        start = end - timedelta(days=lookback_days)
        rs = bs.query_history_k_data_plus(
            f"{exchange_prefix(c)}.{c}",
            "date,close,pctChg,turn,peTTM,pbMRQ,volume,amount",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        if rs.error_code != "0":
            raise ConnectionError(f"baostock query failed: {rs.error_msg}")
        last = None
        while rs.next():
            last = rs.get_row_data()
        if not last:
            return None
        d = dict(zip(rs.fields, last, strict=True))
        num = lambda k: pd.to_numeric(d.get(k), errors="coerce")  # noqa: E731
        return {
            "code": c,
            "price": num("close"),
            "pct_chg": num("pctChg"),
            "pe_ttm": num("peTTM"),
            "pb": num("pbMRQ"),
            "total_mv": float("nan"),
            "float_mv": float("nan"),
            "turnover": num("turn"),
            "volume": num("volume"),
            "amount": num("amount"),
            "date": d.get("date"),
        }

    def snapshot(self, codes: list[str] | None = None, progress=None) -> pd.DataFrame:
        """逐只拼接的全市场快照。无市值字段；约 5000 只需数分钟，可用 codes 限定范围。"""
        universe = self.stock_list()
        if codes:
            wanted = {normalize_code(c) for c in codes}
            universe = universe[universe["code"].isin(wanted)]
        rows = []
        for i, (code, name) in enumerate(zip(universe["code"], universe["name"], strict=True)):
            v = self.latest_valuation(code)
            if v:
                v["name"] = name
                rows.append(v)
            if progress and i % 200 == 0:
                progress(i, len(universe))
        if not rows:
            return empty_snapshot()
        return pd.DataFrame(rows).reindex(columns=SNAPSHOT_COLUMNS)
