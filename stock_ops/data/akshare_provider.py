"""AKShare：全市场快照主源；日K线的腾讯 / 东方财富两条备用线路。"""

from __future__ import annotations

import pandas as pd

from .base import DAILY_COLUMNS, SNAPSHOT_COLUMNS, empty_daily, exchange_prefix, normalize_code


def _compact(d: str) -> str:
    return d.replace("-", "")


class AkshareTxProvider:
    """腾讯行情历史K线，不易被封，但缺北交所。"""

    name = "akshare_tx"

    def daily(self, code: str, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        c = normalize_code(code)
        df = ak.stock_zh_a_hist_tx(
            symbol=f"{exchange_prefix(c)}{c}",
            start_date=_compact(start),
            end_date=_compact(end),
            adjust="qfq",
        )
        if df is None or df.empty:
            return empty_daily()
        df = df.rename(columns={"amount": "volume"})  # 腾讯接口 amount 列实为成交量（手）
        df["code"] = c
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
        df["amount"] = float("nan")
        df["turnover"] = float("nan")
        df["pct_chg"] = pd.to_numeric(df["close"], errors="coerce").pct_change() * 100
        return df.reindex(columns=DAILY_COLUMNS)

    def snapshot(self) -> pd.DataFrame:
        raise NotImplementedError


class AkshareEmProvider:
    """东方财富接口，数据最全但最常失效，放在最后兜底；同时承担全市场快照。"""

    name = "akshare_em"

    def daily(self, code: str, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        c = normalize_code(code)
        df = ak.stock_zh_a_hist(
            symbol=c,
            period="daily",
            start_date=_compact(start),
            end_date=_compact(end),
            adjust="qfq",
        )
        if df is None or df.empty:
            return empty_daily()
        df = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover",
                "涨跌幅": "pct_chg",
            }
        )
        df["code"] = c
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
        return df.reindex(columns=DAILY_COLUMNS)

    def snapshot(self) -> pd.DataFrame:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        df = df.rename(
            columns={
                "代码": "code",
                "名称": "name",
                "最新价": "price",
                "涨跌幅": "pct_chg",
                "市盈率-动态": "pe_ttm",
                "市净率": "pb",
                "总市值": "total_mv",
                "流通市值": "float_mv",
                "换手率": "turnover",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        df["code"] = df["code"].map(normalize_code)
        for col in SNAPSHOT_COLUMNS[2:]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.reindex(columns=SNAPSHOT_COLUMNS)


PROVIDERS = {
    "akshare_tx": AkshareTxProvider,
    "akshare_em": AkshareEmProvider,
}
