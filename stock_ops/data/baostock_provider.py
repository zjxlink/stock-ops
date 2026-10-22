"""Baostock：历史日K主源。免费、无 Token、官方服务器，稳定性最好。"""

from __future__ import annotations

import pandas as pd

from .base import DAILY_COLUMNS, empty_daily, exchange_prefix, normalize_code

_FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg"


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
        c = normalize_code(code)
        rs = bs.query_history_k_data_plus(
            f"{exchange_prefix(c)}.{c}",
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

    def snapshot(self) -> pd.DataFrame:
        raise NotImplementedError("baostock 不提供全市场快照")
