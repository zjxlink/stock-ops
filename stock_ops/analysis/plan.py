"""下一交易日操作计划：基于最新收盘与配置的策略，给每只持仓股 / 自选股一个明确动作和关键价位。

动作只有四种：卖出、买入、持有、观望。价位用于挂条件单：
- stop_price   持仓止损价（成本 × (1 - stop_loss)）
- exit_level   策略出场参考位（如 20 日均线），收盘跌破则次日卖出
- entry_level  触发买入的参考位（如 20 日均线 / 20 日高点）
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..analysis.indicators import add_indicators
from ..backtest.strategies import Strategy
from ..portfolio.book import Position

PLAN_COLUMNS = [
    "code",
    "name",
    "status",
    "action",
    "order_price",
    "shares",
    "stop_price",
    "exit_level",
    "entry_level",
    "reason",
]

ACTION_ORDER = {"卖出": 0, "买入": 1, "持有": 2, "观望": 3}


def _lot(shares: float, lot: int = 100) -> int:
    return int(shares // lot * lot)


def plan_for_code(
    code: str,
    daily: pd.DataFrame,
    strategy: Strategy,
    position: Position | None,
    *,
    name: str = "",
    stop_loss: float | None = 0.08,
    take_profit: float | None = None,
    capital: float = 100_000.0,
    position_pct: float = 0.2,
) -> dict[str, Any]:
    row: dict[str, Any] = {k: float("nan") for k in PLAN_COLUMNS}
    row.update(
        {
            "code": code,
            "name": name,
            "status": "持仓" if position and position.shares > 0 else "观望",
            "shares": float("nan"),
        }
    )
    if daily is None or len(daily) < 70:
        row.update({"action": "观望", "reason": "历史数据不足"})
        return row
    x = add_indicators(daily)
    last = x.iloc[-1]
    close = float(last["close"])
    ma20 = float(last["ma20"])
    high20 = float(x["high20"].iloc[-2]) if len(x) > 1 else float("nan")
    entry_sig = bool(strategy.entry(x).fillna(False).iloc[-1])
    exit_sig = bool(strategy.exit(x).fillna(False).iloc[-1])
    row["exit_level"] = round(ma20, 2)
    row["entry_level"] = round(max(ma20, high20) if not math.isnan(high20) else ma20, 2)

    if position and position.shares > 0:
        cost = position.avg_cost
        row["stop_price"] = round(cost * (1 - stop_loss), 2) if stop_loss else float("nan")
        tp = cost * (1 + take_profit) if take_profit else None
        row["shares"] = position.shares
        if stop_loss and close <= cost * (1 - stop_loss):
            row.update(
                {
                    "action": "卖出",
                    "order_price": round(close, 2),
                    "reason": f"收盘 {close:.2f} 已低于止损价 {row['stop_price']:.2f}，明日开盘卖出",
                }
            )
        elif tp and close >= tp:
            row.update(
                {
                    "action": "卖出",
                    "order_price": round(close, 2),
                    "reason": f"收盘已达止盈价 {tp:.2f}，明日开盘卖出",
                }
            )
        elif exit_sig:
            row.update(
                {
                    "action": "卖出",
                    "order_price": round(close, 2),
                    "reason": f"触发 {strategy.name} 出场信号，明日开盘卖出",
                }
            )
        else:
            hint = f"持有。挂止损单 {row['stop_price']:.2f}" if stop_loss else "持有"
            row.update(
                {"action": "持有", "reason": f"{hint}；收盘跌破 {ma20:.2f}（20日线）则次日卖出"}
            )
        return row

    if entry_sig:
        qty = _lot(capital * position_pct / close)
        row.update(
            {
                "action": "买入",
                "order_price": round(close, 2),
                "shares": qty,
                "stop_price": round(close * (1 - stop_loss), 2) if stop_loss else float("nan"),
                "reason": f"触发 {strategy.name} 进场信号，明日开盘买入约 {qty} 股"
                + (f"，成交后止损 {close * (1 - stop_loss):.2f}" if stop_loss else ""),
            }
        )
    else:
        need = "站上" if close < ma20 else "继续站稳"
        row.update(
            {
                "action": "观望",
                "reason": f"未触发进场。关注收盘{need} {ma20:.2f}（20日线）与突破 {high20:.2f}（20日高点）",
            }
        )
    return row


def build_plan(
    codes: list[str],
    daily_by_code: dict[str, pd.DataFrame],
    strategy: Strategy,
    book: dict[str, Position],
    names: pd.Series | dict | None = None,
    **kw,
) -> pd.DataFrame:
    names = names if names is not None else {}
    rows = [
        plan_for_code(
            c, daily_by_code.get(c), strategy, book.get(c), name=str(names.get(c, "") or ""), **kw
        )
        for c in codes
    ]
    df = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    if df.empty:
        return df
    df["_o"] = df["action"].map(ACTION_ORDER)
    return df.sort_values(["_o", "status", "code"]).drop(columns="_o").reset_index(drop=True)
