"""生成 Markdown 日报：持仓概览 + 自选股技术信号 + 基本面筛选结果。"""

from __future__ import annotations

import math

import pandas as pd

INT_COLS = {"shares", "trades", "score", "n", "live_n"}


def _table(df: pd.DataFrame, cols: list[str], max_rows: int = 30) -> str:
    if df is None or df.empty:
        return "_无数据_\n"
    d = df[[c for c in cols if c in df.columns]].head(max_rows)
    head = "| " + " | ".join(d.columns) + " |\n|" + "---|" * len(d.columns) + "\n"
    body = ""
    for row in d.itertuples(index=False):
        cells = []
        for col, v in zip(d.columns, row, strict=True):
            if isinstance(v, float):
                cells.append(
                    "" if math.isnan(v) else (f"{int(v):,}" if col in INT_COLS else f"{v:,.2f}")
                )
            else:
                cells.append(str(v))
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def render_report(rd) -> str:
    """由 ReportData 生成 Markdown 日报（推荐入口）。"""
    return daily_report(
        rd.date,
        rd.portfolio,
        rd.signals,
        rd.screened,
        rd.backtest,
        rd.backtest_note,
        rd.plan,
        rd.plan_note,
        getattr(rd, "strategy_compare", None),
        getattr(rd, "portfolio_bt", None),
        getattr(rd, "portfolio_note", ""),
        getattr(rd, "predictions", None),
        getattr(rd, "prediction_note", ""),
        getattr(rd, "accuracy", None),
        getattr(rd, "fundamentals", None),
        getattr(rd, "fund_note", ""),
    )


def daily_report(
    date: str,
    portfolio: pd.DataFrame,
    signals: pd.DataFrame,
    screened: pd.DataFrame,
    backtest: pd.DataFrame | None = None,
    backtest_note: str = "",
    plan: pd.DataFrame | None = None,
    plan_note: str = "",
    strategy_compare: pd.DataFrame | None = None,
    portfolio_bt: dict | None = None,
    portfolio_note: str = "",
    predictions: pd.DataFrame | None = None,
    prediction_note: str = "",
    accuracy: pd.DataFrame | None = None,
    fundamentals: pd.DataFrame | None = None,
    fund_note: str = "",
) -> str:
    parts = [f"# 每日报告 {date}\n"]
    if plan is not None and not plan.empty:
        parts.append("## 下一交易日操作计划\n")
        parts.append(plan_note + "\n")
        parts.append(
            _table(
                plan,
                [
                    "code",
                    "name",
                    "status",
                    "action",
                    "order_price",
                    "shares",
                    "stop_price",
                    "trail_price",
                    "exit_level",
                    "entry_level",
                    "reason",
                    "prediction",
                ],
            )
        )
        parts.append("")
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
            [
                "code",
                "name",
                "shares",
                "avg_cost",
                "price",
                "pnl_pct",
                "unrealized_pnl",
                "weight_pct",
            ],
        )
    )
    parts.append("\n## 自选股技术信号\n")
    parts.append(
        _table(
            signals,
            [
                "code",
                "name",
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
    if fundamentals is not None and not fundamentals.empty:
        parts.append("\n## 持仓与自选股基本面\n")
        parts.append(fund_note + "\n")
        parts.append(
            _table(
                fundamentals,
                [
                    "code",
                    "name",
                    "report_date",
                    "roe",
                    "roe_prev",
                    "np_margin",
                    "gp_margin",
                    "yoy_ni",
                    "yoy_ni_prev",
                    "liability_to_asset",
                    "cfo_to_np",
                    "eps_ttm",
                    "pe_ttm",
                    "pb",
                ],
            )
        )
    parts.append("\n## 基本面筛选\n")
    if screened is not None and "rejects" in screened.attrs:
        r = screened.attrs["rejects"]
        parts.append(
            f"输入 {screened.attrs.get('input_count', 0)} 只，通过 {len(screened)} 只，其中有财报数据 {screened.attrs.get('fund_coverage', 0)} 只。剔除："
            + "，".join(f"{k} {v}" for k, v in r.items())
            + (
                f"。跳过（数据缺失）：{'、'.join(screened.attrs['skipped'])}"
                if screened.attrs.get("skipped")
                else ""
            )
            + "\n"
        )
    parts.append(
        _table(
            screened,
            [
                "code",
                "name",
                "price",
                "pe_ttm",
                "pb",
                "total_mv",
                "turnover",
                "roe",
                "yoy_ni",
                "yoy_ni_prev",
                "liability_to_asset",
                "quality",
                "report_date",
            ],
        )
    )
    if backtest is not None and not backtest.empty:
        parts.append("\n## 策略回测\n")
        parts.append(backtest_note + "\n")
        parts.append(
            _table(
                backtest,
                [
                    "code",
                    "name",
                    "total_return",
                    "buy_hold",
                    "excess",
                    "cagr",
                    "max_drawdown",
                    "sharpe",
                    "trades",
                    "win_rate",
                    "profit_factor",
                    "avg_days",
                ],
            )
        )
    if predictions is not None and not predictions.empty:
        parts.append("\n## 明日涨跌预测与准确率\n")
        parts.append(prediction_note + "\n")
        pr = predictions.copy()
        pr["reliable"] = pr["reliable"].map({True: "可参考", False: "不足"})
        parts.append(
            _table(
                pr,
                [
                    "code",
                    "name",
                    "date",
                    "reliable",
                    "method",
                    "pred",
                    "prob",
                    "acc",
                    "ci_low",
                    "baseline",
                    "n",
                    "live_n",
                ],
            )
        )
        if accuracy is not None and not accuracy.empty:
            parts.append("\n各方法准确率（最近窗口）：\n")
            parts.append(
                _table(
                    accuracy,
                    [
                        "code",
                        "method",
                        "n",
                        "acc",
                        "ci_low",
                        "baseline",
                        "significant",
                        "live_n",
                        "live_acc",
                    ],
                    max_rows=80,
                )
            )
    if portfolio_bt:
        parts.append("\n### 组合回测\n")
        parts.append(portfolio_note + "\n")
        m = portfolio_bt
        parts.append(
            "| 总收益 | 等权买入持有 | 超额 | 年化 | 最大回撤 | 夏普 | Calmar | 交易次数 | 胜率 | 盈亏比 | 平均持有天 | 资金使用率 |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
            f"| {m['total_return']:.2f}% | {m['buy_hold']:.2f}% | {m['excess']:.2f}% | {m['cagr']:.2f}% | {m['max_drawdown']:.2f}% | {m['sharpe']:.2f} | {m['calmar']:.2f} | {m['trades']} | {m['win_rate']:.1f}% | {m['profit_factor']:.2f} | {m['avg_days']:.1f} | {m['exposure']:.1f}% |\n"
        )
    if strategy_compare is not None and not strategy_compare.empty:
        parts.append("\n### 各策略平均表现（同一批股票）\n")
        parts.append(
            _table(
                strategy_compare,
                [
                    "strategy",
                    "description",
                    "total_return",
                    "buy_hold",
                    "excess",
                    "max_drawdown",
                    "sharpe",
                    "trades",
                    "win_rate",
                    "profit_factor",
                ],
            )
        )
    return "\n".join(parts)
