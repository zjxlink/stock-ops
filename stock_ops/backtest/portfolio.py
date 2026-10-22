"""组合级回测：一份总资金在多只股票间调度，最多同时持有 max_positions 只，按信号强度排序进场。

与单票引擎共用策略定义、费用模型、ATR / 百分比止损、最少持仓、冷却与大盘过滤。
每个仓位目标金额 = 当前权益 / max_positions，受现金约束。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..analysis.indicators import add_indicators
from .engine import TRADING_DAYS, BacktestConfig, Trade, _fee_buy, _fee_sell
from .strategies import Strategy


@dataclass
class _Pos:
    shares: int
    cost: float
    entry_date: str
    peak: float = 0.0
    stop_level: float = 0.0
    days: int = 0


@dataclass
class PortfolioResult:
    strategy: str
    start: str
    end: str
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    exposure_series: pd.Series | None = None


def run_portfolio(
    daily_by_code: dict[str, pd.DataFrame],
    strategy: Strategy,
    cfg: BacktestConfig | None = None,
    regime: pd.Series | None = None,
    max_positions: int = 3,
    rank_key: str = "ret20",
) -> PortfolioResult:
    cfg = cfg or BacktestConfig()
    frames: dict[str, pd.DataFrame] = {}
    for code, df in daily_by_code.items():
        if df is None or len(df) < cfg.warmup + 5:
            continue
        x = add_indicators(df)
        x["entry"] = strategy.entry(x).fillna(False).astype(bool)
        x["exit"] = strategy.exit(x).fillna(False).astype(bool)
        x["date"] = x["date"].astype(str)
        x["bar_i"] = np.arange(len(x))
        frames[code] = x.set_index("date")
    if not frames:
        raise ValueError("没有足够数据的股票")
    dates = sorted(set().union(*[set(f.index) for f in frames.values()]))
    reg_map = regime.to_dict() if regime is not None else {}

    cash = cfg.initial_cash
    positions: dict[str, _Pos] = {}
    pending_buys: list[str] = []
    pending_sells: dict[str, str] = {}
    last_exit: dict[str, tuple[int, str]] = {}  # code -> (date_idx, reason)
    last_close: dict[str, float] = {}
    trades: list[Trade] = []
    equity = np.empty(len(dates))
    invested = np.empty(len(dates))
    prev_equity = cfg.initial_cash

    for di, d in enumerate(dates):
        # ---- 开盘成交：先卖后买 ----
        for code, reason in list(pending_sells.items()):
            f = frames[code]
            if d not in f.index:
                continue
            o = float(f.at[d, "open"])
            pos = positions.pop(code)
            px = o * (1 - cfg.slippage)
            amt = pos.shares * px
            cash += amt - _fee_sell(amt, cfg)
            pnl = amt - _fee_sell(amt, cfg) - pos.cost
            trades.append(
                Trade(
                    pos.entry_date,
                    d,
                    round(pos.cost / pos.shares, 3),
                    round(px, 3),
                    pos.shares,
                    round(pnl, 2),
                    round(pnl / pos.cost, 4),
                    pos.days,
                    reason,
                )
            )
            last_exit[code] = (di, reason)
            del pending_sells[code]
        slots = max_positions - len(positions)
        for code in pending_buys:
            if slots <= 0:
                break
            f = frames[code]
            if d not in f.index or code in positions:
                continue
            o = float(f.at[d, "open"])
            if math.isnan(o) or o <= 0:
                continue
            px = o * (1 + cfg.slippage)
            budget = min(cash, prev_equity / max_positions)
            qty = int(budget / (px * (1 + cfg.commission)) // cfg.lot * cfg.lot)
            if qty <= 0:
                continue
            amt = qty * px
            fee = _fee_buy(amt, cfg)
            cash -= amt + fee
            positions[code] = _Pos(qty, amt + fee, d)
            slots -= 1
        pending_buys = []

        # ---- 收盘权益 ----
        mv = 0.0
        for code, pos in positions.items():
            f = frames[code]
            if d in f.index:
                last_close[code] = float(f.at[d, "close"])
            mv += pos.shares * last_close.get(code, pos.cost / pos.shares)
        equity[di] = cash + mv
        invested[di] = mv / equity[di] if equity[di] > 0 else 0.0
        prev_equity = equity[di]
        if di == len(dates) - 1:
            break

        # ---- 收盘确认次日指令：持仓股止损 / 出场 ----
        for code, pos in positions.items():
            f = frames[code]
            if d not in f.index or code in pending_sells:
                continue
            row = f.loc[d]
            c, atr = float(row["close"]), float(row["atr"])
            pos.days += 1
            pos.peak = max(pos.peak, c)
            if cfg.atr_stop and not math.isnan(atr) and atr > 0:
                pos.stop_level = max(pos.stop_level, pos.peak - cfg.atr_stop * atr)
            cost_px = pos.cost / pos.shares
            if cfg.stop_loss and c <= cost_px * (1 - cfg.stop_loss):
                pending_sells[code] = "stop_loss"
            elif cfg.trailing_stop and c <= pos.peak * (1 - cfg.trailing_stop):
                pending_sells[code] = "trailing_stop"
            elif cfg.atr_stop and pos.stop_level > 0 and c <= pos.stop_level:
                pending_sells[code] = "atr_stop"
            elif cfg.take_profit and c >= cost_px * (1 + cfg.take_profit):
                pending_sells[code] = "take_profit"
            elif bool(row["exit"]) and pos.days >= cfg.min_hold_days:
                pending_sells[code] = "signal"

        # ---- 候选进场：按 rank_key 排序，受仓位数与大盘过滤约束 ----
        if not reg_map.get(d, True):
            continue
        free = max_positions - len(positions) + len(pending_sells)
        if free <= 0:
            continue
        cands = []
        for code, f in frames.items():
            if code in positions or d not in f.index:
                continue
            row = f.loc[d]
            if int(row["bar_i"]) < cfg.warmup or not bool(row["entry"]):
                continue
            le = last_exit.get(code)
            if le and "stop" in le[1] and (di - le[0]) < cfg.cooldown_days:
                continue
            score = float(row.get(rank_key, 0.0))
            cands.append((0.0 if math.isnan(score) else score, code))
        cands.sort(reverse=True)
        pending_buys = [c for _, c in cands[:free]]

    eq = pd.Series(equity, index=pd.Index(dates, name="date"))
    res = PortfolioResult(
        strategy.name,
        dates[0],
        dates[-1],
        eq,
        trades,
        exposure_series=pd.Series(invested, index=eq.index),
    )
    res.metrics = _metrics(res, frames, cfg)
    return res


def _metrics(res: PortfolioResult, frames: dict[str, pd.DataFrame], cfg: BacktestConfig) -> dict:
    eq = res.equity
    total = float(eq.iloc[-1] / cfg.initial_cash - 1)
    years = len(eq) / TRADING_DAYS
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan")
    dd = float((eq / eq.cummax() - 1).min())
    daily = eq.pct_change().dropna()
    sharpe = (
        float(daily.mean() / daily.std() * math.sqrt(TRADING_DAYS))
        if daily.std() > 0
        else float("nan")
    )
    wins = [t for t in res.trades if t.pnl > 0]
    losses = [t for t in res.trades if t.pnl <= 0]
    gw, gl = sum(t.pnl for t in wins), -sum(t.pnl for t in losses)
    # 等权买入持有：各股从预热期后首个交易日开盘持有到结束
    rets = []
    for f in frames.values():
        after = f[f["bar_i"] >= cfg.warmup + 1]
        if len(after) > 1 and float(after["open"].iloc[0]) > 0:
            rets.append(float(after["close"].iloc[-1] / after["open"].iloc[0] - 1))
    bh = float(np.mean(rets)) if rets else float("nan")
    return {
        "total_return": round(total * 100, 2),
        "cagr": round(cagr * 100, 2) if not math.isnan(cagr) else float("nan"),
        "max_drawdown": round(dd * 100, 2),
        "sharpe": round(sharpe, 2) if not math.isnan(sharpe) else float("nan"),
        "trades": len(res.trades),
        "win_rate": round(len(wins) / len(res.trades) * 100, 1) if res.trades else float("nan"),
        "profit_factor": round(gw / gl, 2) if gl > 0 else float("inf") if gw > 0 else float("nan"),
        "avg_days": round(sum(t.days for t in res.trades) / len(res.trades), 1)
        if res.trades
        else float("nan"),
        "exposure": round(float(res.exposure_series.mean()) * 100, 1)
        if res.exposure_series is not None
        else float("nan"),
        "buy_hold": round(bh * 100, 2) if not math.isnan(bh) else float("nan"),
        "excess": round((total - bh) * 100, 2) if not math.isnan(bh) else float("nan"),
        "calmar": round((cagr / abs(dd)), 2) if dd and not math.isnan(cagr) else float("nan"),
    }
