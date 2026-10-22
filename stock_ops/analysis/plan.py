"""下一交易日操作计划：基于最新收盘与配置的策略，给每只持仓股 / 自选股一个明确动作和关键价位。

动作只有四种：卖出、买入、持有、观望。价位用于挂条件单：
- stop_price   成本止损价（成本 × (1 - stop_loss)），未启用则为空
- trail_price  移动止损价（持仓期间最高收盘 × (1 - trailing_stop)），未启用则为空
- exit_level   策略出场参考位（20 日均线），收盘跌破则次日卖出
- entry_level  触发买入的参考位（20 日均线 / 20 日高点）

单只股票可用 rules 覆盖：mode=hold 时永不发卖出指令，只提示关键位。
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
    "trail_price",
    "exit_level",
    "entry_level",
    "reason",
]

ACTION_ORDER = {"卖出": 0, "买入": 1, "持有": 2, "观望": 3}


def _lot(shares: float, lot: int = 100) -> int:
    return int(shares // lot * lot)


def _f(v: float) -> str:
    return f"{v:.2f}"


def plan_for_code(
    code: str,
    daily: pd.DataFrame,
    strategy: Strategy,
    position: Position | None,
    *,
    name: str = "",
    stop_loss: float | None = None,
    trailing_stop: float | None = 0.15,
    take_profit: float | None = None,
    capital: float = 100_000.0,
    position_pct: float = 0.2,
    rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rule = rule or {}
    if "stop_loss" in rule:
        stop_loss = rule["stop_loss"] or None
    if "trailing_stop" in rule:
        trailing_stop = rule["trailing_stop"] or None
    hold_mode = str(rule.get("mode", "rule")).lower() == "hold"

    row: dict[str, Any] = {k: float("nan") for k in PLAN_COLUMNS}
    held = bool(position and position.shares > 0)
    row.update({"code": code, "name": name, "status": "持仓" if held else "观望"})
    if daily is None or len(daily) < 70:
        row.update({"action": "持有" if held else "观望", "reason": "历史数据不足"})
        return row
    x = add_indicators(daily)
    last = x.iloc[-1]
    close, ma20, ma60 = float(last["close"]), float(last["ma20"]), float(last["ma60"])
    high20 = float(x["high20"].iloc[-2]) if len(x) > 1 else float("nan")
    low60 = float(x["low"].tail(60).min())
    entry_sig = bool(strategy.entry(x).fillna(False).iloc[-1])
    exit_sig = bool(strategy.exit(x).fillna(False).iloc[-1])
    row["exit_level"] = round(ma20, 2)
    row["entry_level"] = round(max(ma20, high20) if not math.isnan(high20) else ma20, 2)

    if held:
        cost = position.avg_cost
        row["shares"] = position.shares
        since = x[x["date"].astype(str) >= str(position.first_date)] if position.first_date else x
        peak = float(since["close"].max()) if not since.empty else close
        stop_px = cost * (1 - stop_loss) if stop_loss else None
        trail_px = peak * (1 - trailing_stop) if trailing_stop else None
        tp = cost * (1 + take_profit) if take_profit else None
        row["stop_price"] = round(stop_px, 2) if stop_px else float("nan")
        row["trail_price"] = round(trail_px, 2) if trail_px else float("nan")

        if hold_mode:
            note = rule.get("note") or "长期持有"
            levels = f"参考位：20日线 {_f(ma20)}、60日线 {_f(ma60)}、近60日低点 {_f(low60)}"
            if trail_px:
                levels += f"；移动止损参考 {_f(trail_px)}（自高点 {_f(peak)} 回撤 {trailing_stop * 100:.0f}%）"
            flags = []
            if stop_px and close <= stop_px:
                flags.append("已低于成本止损")
            if trail_px and close <= trail_px:
                flags.append("已低于移动止损")
            if exit_sig:
                flags.append(f"触发 {strategy.name} 出场信号")
            warn = f"。注意：{'、'.join(flags)}，规则已被 hold 模式覆盖" if flags else ""
            row.update({"action": "持有", "reason": f"{note}（规则关闭）。{levels}{warn}"})
            return row

        if stop_px and close <= stop_px:
            row.update(
                {
                    "action": "卖出",
                    "order_price": round(close, 2),
                    "reason": f"收盘 {_f(close)} 已低于成本止损 {_f(stop_px)}，明日开盘卖出",
                }
            )
        elif trail_px and close <= trail_px:
            row.update(
                {
                    "action": "卖出",
                    "order_price": round(close, 2),
                    "reason": f"收盘 {_f(close)} 自高点 {_f(peak)} 回撤超过 {trailing_stop * 100:.0f}%（移动止损 {_f(trail_px)}），明日开盘卖出",
                }
            )
        elif tp and close >= tp:
            row.update(
                {
                    "action": "卖出",
                    "order_price": round(close, 2),
                    "reason": f"收盘已达止盈价 {_f(tp)}，明日开盘卖出",
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
            hints = [f"挂移动止损 {_f(trail_px)}"] if trail_px else []
            if stop_px:
                hints.append(f"成本止损 {_f(stop_px)}")
            row.update(
                {
                    "action": "持有",
                    "reason": "持有。"
                    + ("；".join(hints) + "；" if hints else "")
                    + f"收盘跌破 {_f(ma20)}（20日线）则次日卖出",
                }
            )
        return row

    if entry_sig:
        qty = _lot(capital * position_pct / close)
        first_stop = (
            close * (1 - (stop_loss or trailing_stop or 0))
            if (stop_loss or trailing_stop)
            else None
        )
        row.update(
            {
                "action": "买入",
                "order_price": round(close, 2),
                "shares": qty,
                "stop_price": round(first_stop, 2) if first_stop else float("nan"),
                "reason": f"触发 {strategy.name} 进场信号，明日开盘买入约 {qty} 股"
                + (f"，成交后初始止损 {_f(first_stop)}" if first_stop else ""),
            }
        )
    else:
        need = "站上" if close < ma20 else "继续站稳"
        row.update(
            {
                "action": "观望",
                "reason": f"未触发进场。关注收盘{need} {_f(ma20)}（20日线）与突破 {_f(high20)}（20日高点）",
            }
        )
    return row


def build_plan(
    codes: list[str],
    daily_by_code: dict[str, pd.DataFrame],
    strategy: Strategy,
    book: dict[str, Position],
    names: pd.Series | dict | None = None,
    rules: dict[str, dict] | None = None,
    **kw,
) -> pd.DataFrame:
    names = names if names is not None else {}
    rules = rules or {}
    rows = [
        plan_for_code(
            c,
            daily_by_code.get(c),
            strategy,
            book.get(c),
            name=str(names.get(c, "") or ""),
            rule=rules.get(c),
            **kw,
        )
        for c in codes
    ]
    df = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    if df.empty:
        return df
    df["_o"] = df["action"].map(ACTION_ORDER)
    return df.sort_values(["_o", "status", "code"]).drop(columns="_o").reset_index(drop=True)
