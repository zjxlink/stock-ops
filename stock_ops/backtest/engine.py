"""回测引擎：单票多头、全仓进出、次日开盘成交、A 股费用与整手约束。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..analysis.indicators import add_indicators
from .strategies import Strategy

TRADING_DAYS = 244  # A 股年均交易日


@dataclass
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission: float = 0.0003  # 双边佣金率
    min_commission: float = 5.0
    stamp_duty: float = 0.0005  # 卖出印花税
    slippage: float = 0.001  # 单边滑点
    stop_loss: float | None = None  # 0.08 = 收盘低于成本 8% 次日止损
    take_profit: float | None = None
    lot: int = 100  # 整手
    warmup: int = 60  # 指标预热期，之前不交易


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    ret: float
    days: int
    reason: str


@dataclass
class BacktestResult:
    code: str
    strategy: str
    start: str
    end: str
    equity: pd.Series  # 按日期索引的权益曲线
    trades: list[Trade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def _fee_buy(amount: float, cfg: BacktestConfig) -> float:
    return max(amount * cfg.commission, cfg.min_commission)


def _fee_sell(amount: float, cfg: BacktestConfig) -> float:
    return max(amount * cfg.commission, cfg.min_commission) + amount * cfg.stamp_duty


def run_backtest(
    df: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig | None = None
) -> BacktestResult:
    cfg = cfg or BacktestConfig()
    if df is None or len(df) < cfg.warmup + 5:
        raise ValueError(f"数据不足：需要至少 {cfg.warmup + 5} 根K线")
    x = add_indicators(df)
    entry = strategy.entry(x).fillna(False).astype(bool).to_numpy()
    exit_ = strategy.exit(x).fillna(False).astype(bool).to_numpy()
    opens, closes, dates = (
        x["open"].to_numpy(float),
        x["close"].to_numpy(float),
        x["date"].astype(str).to_numpy(),
    )
    code = str(x["code"].iloc[0])

    cash, shares, cost_price, entry_i = cfg.initial_cash, 0, 0.0, -1
    pending: str | None = None  # 次日开盘要执行的动作：buy / sell:<reason>
    equity = np.empty(len(x))
    trades: list[Trade] = []

    for i in range(len(x)):
        o, c = opens[i], closes[i]
        # 1) 执行前一日收盘确认的指令
        if pending == "buy" and shares == 0 and not math.isnan(o):
            px = o * (1 + cfg.slippage)
            qty = int(cash / (px * (1 + cfg.commission)) // cfg.lot * cfg.lot)
            if qty > 0:
                amt = qty * px
                cash -= amt + _fee_buy(amt, cfg)
                shares, cost_price, entry_i = qty, px, i
        elif pending and pending.startswith("sell") and shares > 0 and not math.isnan(o):
            px = o * (1 - cfg.slippage)
            amt = shares * px
            cash += amt - _fee_sell(amt, cfg)
            pnl = cash - (equity[entry_i - 1] if entry_i > 0 else cfg.initial_cash)
            trades.append(
                Trade(
                    dates[entry_i],
                    dates[i],
                    round(cost_price, 3),
                    round(px, 3),
                    shares,
                    round(pnl, 2),
                    round(pnl / (shares * cost_price), 4),
                    i - entry_i,
                    pending.split(":", 1)[1],
                )
            )
            shares, cost_price, entry_i = 0, 0.0, -1
        pending = None
        equity[i] = cash + shares * (c if not math.isnan(c) else 0.0)
        # 2) 收盘确认次日指令
        if i < cfg.warmup or i == len(x) - 1:
            continue
        if shares > 0:
            if cfg.stop_loss and c <= cost_price * (1 - cfg.stop_loss):
                pending = "sell:stop_loss"
            elif cfg.take_profit and c >= cost_price * (1 + cfg.take_profit):
                pending = "sell:take_profit"
            elif exit_[i]:
                pending = "sell:signal"
        elif entry[i]:
            pending = "buy"

    eq = pd.Series(equity, index=pd.Index(dates, name="date"))
    res = BacktestResult(code, strategy.name, dates[0], dates[-1], eq, trades)
    res.metrics = compute_metrics(res, opens, closes, cfg)
    return res


def compute_metrics(
    res: BacktestResult, opens: np.ndarray, closes: np.ndarray, cfg: BacktestConfig
) -> dict:
    eq = res.equity
    ret = eq / cfg.initial_cash - 1
    total = float(ret.iloc[-1])
    n = len(eq)
    years = n / TRADING_DAYS
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan")
    dd = (eq / eq.cummax() - 1).min()
    daily = eq.pct_change().dropna()
    sharpe = (
        float(daily.mean() / daily.std() * math.sqrt(TRADING_DAYS))
        if daily.std() > 0
        else float("nan")
    )
    wins = [t for t in res.trades if t.pnl > 0]
    losses = [t for t in res.trades if t.pnl <= 0]
    gross_win, gross_loss = sum(t.pnl for t in wins), -sum(t.pnl for t in losses)
    first = cfg.warmup + 1
    bh = float(closes[-1] / opens[first] - 1) if first < n and opens[first] > 0 else float("nan")
    in_mkt = sum(t.days for t in res.trades) / max(n - cfg.warmup, 1)
    return {
        "total_return": round(total * 100, 2),
        "cagr": round(cagr * 100, 2) if not math.isnan(cagr) else float("nan"),
        "max_drawdown": round(float(dd) * 100, 2),
        "sharpe": round(sharpe, 2) if not math.isnan(sharpe) else float("nan"),
        "trades": len(res.trades),
        "win_rate": round(len(wins) / len(res.trades) * 100, 1) if res.trades else float("nan"),
        "profit_factor": round(gross_win / gross_loss, 2)
        if gross_loss > 0
        else float("inf")
        if gross_win > 0
        else float("nan"),
        "avg_days": round(sum(t.days for t in res.trades) / len(res.trades), 1)
        if res.trades
        else float("nan"),
        "exposure": round(min(in_mkt, 1.0) * 100, 1),
        "buy_hold": round(bh * 100, 2) if not math.isnan(bh) else float("nan"),
        "excess": round((total - bh) * 100, 2) if not math.isnan(bh) else float("nan"),
    }


def run_many(
    daily_by_code: dict[str, pd.DataFrame], strategy: Strategy, cfg: BacktestConfig | None = None
) -> tuple[pd.DataFrame, dict[str, BacktestResult]]:
    """对多只股票跑同一策略，返回汇总表（含均值行）与逐只结果。数据不足的股票跳过。"""
    rows, results = [], {}
    for code, df in daily_by_code.items():
        try:
            r = run_backtest(df, strategy, cfg)
        except ValueError:
            continue
        results[code] = r
        rows.append({"code": code, "start": r.start, "end": r.end, **r.metrics})
    table = pd.DataFrame(rows)
    if not table.empty:
        mean = (
            table.drop(columns=["code", "start", "end"])
            .replace([np.inf, -np.inf], np.nan)
            .mean(numeric_only=True)
            .round(2)
        )
        table = pd.concat(
            [table, pd.DataFrame([{"code": "平均", **mean.to_dict()}])], ignore_index=True
        )
    return table, results
