"""基本面：Baostock 季度财务数据（盈利、成长、偿债、现金流），取最新一期财报，统一列名。

每只股票 4 次接口调用，全市场约 20 分钟，因此全市场每周更新一次，持仓股与自选股每日更新。
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date

import pandas as pd

from .baostock_provider import BaostockProvider, bs_code_of

log = logging.getLogger(__name__)

FUND_COLUMNS = [
    "code",
    "report_date",
    "pub_date",
    "roe",
    "np_margin",
    "gp_margin",
    "eps_ttm",
    "yoy_ni",
    "yoy_revenue",
    "yoy_equity",
    "liability_to_asset",
    "current_ratio",
    "cfo_to_np",
    "cfo_to_revenue",
    "report_date_prev",
    "roe_prev",
    "yoy_ni_prev",
    "updated_at",
]

# baostock 字段 -> 统一列名
_PROFIT = {"roeAvg": "roe", "npMargin": "np_margin", "gpMargin": "gp_margin", "epsTTM": "eps_ttm"}
_GROWTH = {
    "YOYNI": "yoy_ni",
    "YOYEquity": "yoy_equity",
    "YOYPNI": "yoy_revenue",
}  # YOYPNI 为归母净利润同比，暂作营收同比的替代
_BALANCE = {"liabilityToAsset": "liability_to_asset", "currentRatio": "current_ratio"}
_CASH = {"CFOToNP": "cfo_to_np", "CFOToOR": "cfo_to_revenue"}


def last_completed_quarter(today: date | None = None) -> tuple[int, int]:
    """最近一个已经结束的季度。10 月 22 日 -> (year, 3)；1 月 -> (year-1, 4)。"""
    today = today or date.today()
    q = (today.month - 1) // 3
    return (today.year, q) if q else (today.year - 1, 4)


def quarter_end(year: int, quarter: int) -> str:
    return f"{year}-{('03-31', '06-30', '09-30', '12-31')[quarter - 1]}"


def latest_quarters(today: date | None = None, n: int = 4) -> list[tuple[int, int]]:
    """从最近一个已结束的季度往前列出 n 个财报期。季报披露有滞后，调用方逐期尝试直到有数据。"""
    y, q = last_completed_quarter(today)
    out = []
    for _ in range(n):
        out.append((y, q))
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


def _rows(rs) -> list[dict]:
    if rs.error_code != "0":
        raise ConnectionError(rs.error_msg)
    out = []
    while rs.next():
        out.append(dict(zip(rs.fields, rs.get_row_data(), strict=True)))
    return out


def _num(v) -> float:
    try:
        return float(v) if v not in ("", None) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


class BaostockFundamentals:
    def __init__(
        self, provider: BaostockProvider | None = None, request_interval: float = 0.05
    ) -> None:
        self.provider = provider or BaostockProvider()
        self.request_interval = request_interval

    def close(self) -> None:
        self.provider.close()

    def _period(self, bs, bs_code: str, year: int, quarter: int, full: bool) -> dict | None:
        """抓一个财报期。full=False 只取盈利与成长（用于上一期）。无数据返回 None。"""
        profit = _rows(bs.query_profit_data(code=bs_code, year=year, quarter=quarter))
        time.sleep(self.request_interval)
        if not profit:
            return None
        growth = _rows(bs.query_growth_data(code=bs_code, year=year, quarter=quarter))
        row: dict = {
            "report_date": profit[0].get("statDate", ""),
            "pub_date": profit[0].get("pubDate", ""),
        }
        sources = [(profit, _PROFIT), (growth, _GROWTH)]
        if full:
            balance = _rows(bs.query_balance_data(code=bs_code, year=year, quarter=quarter))
            cash = _rows(bs.query_cash_flow_data(code=bs_code, year=year, quarter=quarter))
            sources += [(balance, _BALANCE), (cash, _CASH)]
        time.sleep(self.request_interval)
        for src, mapping in sources:
            if src:
                for k, v in mapping.items():
                    row[v] = _num(src[0].get(k))
        for k in (
            "roe",
            "np_margin",
            "gp_margin",
            "yoy_ni",
            "yoy_revenue",
            "yoy_equity",
            "liability_to_asset",
        ):
            if k in row and not math.isnan(row[k]):
                row[k] = round(row[k] * 100, 2)
        return row

    def fetch(self, code: str, today: date | None = None) -> dict | None:
        """最新一期财报的统一字段，并附上一期的 ROE 与净利润同比；该股近几期都没有数据则返回 None。"""
        bs = self.provider._ensure_login()
        c, bs_code = bs_code_of(code)
        quarters = latest_quarters(today, n=5)
        for idx, (year, quarter) in enumerate(quarters[:4]):
            cur = self._period(bs, bs_code, year, quarter, full=True)
            if cur is None:
                continue
            row: dict = {k: float("nan") for k in FUND_COLUMNS}
            row.update(cur)
            row["code"] = c
            prev = (
                self._period(bs, bs_code, *quarters[idx + 1], full=False)
                if idx + 1 < len(quarters)
                else None
            )
            if prev:
                row["report_date_prev"] = prev.get("report_date", "")
                row["roe_prev"] = prev.get("roe", float("nan"))
                row["yoy_ni_prev"] = prev.get("yoy_ni", float("nan"))
            else:
                row["report_date_prev"] = ""
            row["updated_at"] = (today or date.today()).isoformat()
            return row
        return None

    def fetch_many(
        self,
        codes: list[str],
        today: date | None = None,
        time_budget_s: float | None = None,
        progress=None,
    ) -> pd.DataFrame:
        """批量抓取；超出 time_budget_s 提前返回已完成部分（配合周更任务断点续跑）。"""
        t0 = time.time()
        rows = []
        for i, c in enumerate(codes):
            if time_budget_s and time.time() - t0 > time_budget_s:
                log.warning("基本面抓取到时限，完成 %d/%d", i, len(codes))
                break
            try:
                r = self.fetch(c, today)
                if r:
                    rows.append(r)
            except Exception as e:
                log.warning("%s 基本面失败: %s", c, e)
            if progress and i % 100 == 0:
                progress(i, len(codes))
        return pd.DataFrame(rows, columns=FUND_COLUMNS)
