"""持仓账本：由交易流水推导持仓、成本与盈亏。成本采用移动加权平均，卖出按比例释放成本。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Position:
    code: str
    shares: int = 0
    cost: float = 0.0  # 持仓总成本（含手续费）
    realized_pnl: float = 0.0  # 已实现盈亏
    trades: int = 0
    first_date: str | None = None
    last_date: str | None = None
    history: list[dict] = field(default_factory=list)

    @property
    def avg_cost(self) -> float:
        return self.cost / self.shares if self.shares else 0.0

    def market_value(self, price: float) -> float:
        return self.shares * price

    def unrealized_pnl(self, price: float) -> float:
        return self.market_value(price) - self.cost if self.shares else 0.0


def positions_from_trades(trades: pd.DataFrame) -> dict[str, Position]:
    """trades 列：code,date,side(buy/sell),price,shares,fee。按日期顺序回放。"""
    book: dict[str, Position] = {}
    if trades is None or trades.empty:
        return book
    for t in trades.sort_values(["date", "id"] if "id" in trades else ["date"]).itertuples(
        index=False
    ):
        pos = book.setdefault(t.code, Position(code=t.code))
        fee = float(getattr(t, "fee", 0) or 0)
        side = str(t.side).lower()
        if side == "buy":
            pos.cost += t.price * t.shares + fee
            pos.shares += int(t.shares)
        elif side == "sell":
            if t.shares > pos.shares:
                raise ValueError(f"{t.code} 于 {t.date} 卖出 {t.shares} 股超过持仓 {pos.shares} 股")
            released = pos.avg_cost * t.shares
            pos.realized_pnl += t.price * t.shares - fee - released
            pos.cost -= released
            pos.shares -= int(t.shares)
            if pos.shares == 0:
                pos.cost = 0.0
        else:
            raise ValueError(f"未知方向: {t.side}")
        pos.trades += 1
        pos.first_date = pos.first_date or t.date
        pos.last_date = t.date
        pos.history.append(
            {"date": t.date, "side": side, "price": t.price, "shares": t.shares, "fee": fee}
        )
    return book


def portfolio_summary(book: dict[str, Position], prices: pd.Series | dict) -> pd.DataFrame:
    """合并最新价，输出每只股票的市值、浮盈、已实现盈亏与仓位占比。"""
    rows = []
    for code, pos in book.items():
        price = float(prices.get(code, float("nan")))
        mv = pos.market_value(price) if not math.isnan(price) else float("nan")
        rows.append(
            {
                "code": code,
                "shares": pos.shares,
                "avg_cost": round(pos.avg_cost, 3),
                "price": price,
                "market_value": mv,
                "unrealized_pnl": pos.unrealized_pnl(price)
                if not math.isnan(price)
                else float("nan"),
                "realized_pnl": round(pos.realized_pnl, 2),
                "pnl_pct": (price / pos.avg_cost - 1) * 100
                if pos.shares and not math.isnan(price)
                else float("nan"),
                "first_date": pos.first_date,
                "last_date": pos.last_date,
                "trades": pos.trades,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    total_mv = df["market_value"].sum(skipna=True)
    df["weight_pct"] = df["market_value"] / total_mv * 100 if total_mv else float("nan")
    return df.sort_values("market_value", ascending=False).reset_index(drop=True)
