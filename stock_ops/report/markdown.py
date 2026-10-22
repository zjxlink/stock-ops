"""生成 Markdown 日报：持仓概览 + 自选股技术信号 + 基本面筛选结果。"""

from __future__ import annotations

import math

import pandas as pd


def _table(df: pd.DataFrame, cols: list[str], max_rows: int = 30) -> str:
    if df is None or df.empty:
        return "_无数据_\n"
    d = df[[c for c in cols if c in df.columns]].head(max_rows)
    head = "| " + " | ".join(d.columns) + " |\n|" + "---|" * len(d.columns) + "\n"
    body = ""
    for row in d.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append("" if math.isnan(v) else f"{v:,.2f}")
            else:
                cells.append(str(v))
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def daily_report(
    date: str, portfolio: pd.DataFrame, signals: pd.DataFrame, screened: pd.DataFrame
) -> str:
    parts = [f"# 每日报告 {date}\n"]
    parts.append("## 持仓\n")
    if portfolio is not None and not portfolio.empty:
        total_mv = portfolio["market_value"].sum(skipna=True)
        total_unreal = portfolio["unrealized_pnl"].sum(skipna=True)
        total_real = portfolio["realized_pnl"].sum()
        parts.append(
            f"总市值 {total_mv:,.0f}，浮动盈亏 {total_unreal:,.0f}，已实现盈亏 {total_real:,.0f}\n"
        )
    parts.append(
        _table(
            portfolio,
            ["code", "shares", "avg_cost", "price", "pnl_pct", "unrealized_pnl", "weight_pct"],
        )
    )
    parts.append("\n## 自选股技术信号\n")
    parts.append(
        _table(
            signals,
            [
                "code",
                "close",
                "score",
                "ma_bull",
                "golden_cross",
                "macd_cross_up",
                "breakout20",
                "rsi",
                "vol_ratio",
                "ret20",
            ],
        )
    )
    parts.append("\n## 基本面筛选\n")
    if screened is not None and "rejects" in screened.attrs:
        r = screened.attrs["rejects"]
        parts.append(
            f"输入 {screened.attrs.get('input_count', 0)} 只，通过 {len(screened)} 只。剔除："
            + "，".join(f"{k} {v}" for k, v in r.items())
            + "\n"
        )
    parts.append(
        _table(screened, ["code", "name", "price", "pe_ttm", "pb", "total_mv", "turnover"])
    )
    return "\n".join(parts)
