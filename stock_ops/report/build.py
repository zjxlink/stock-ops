"""把缓存里的数据组装成日报所需的三张表，CLI、每日任务和 Web 页面共用。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import fundamental_screen, technical_signals
from ..analysis.plan import build_plan
from ..analysis.technical import rank_signals
from ..backtest import get_strategy, run_many
from ..config import Config
from ..data import Cache
from ..portfolio import TradeBook, portfolio_summary, positions_from_trades


@dataclass
class ReportData:
    date: str
    portfolio: pd.DataFrame
    signals: pd.DataFrame
    screened: pd.DataFrame
    closed_pnl: dict[str, float]
    snapshot_updated_at: str | None
    price_note: str = "收盘价"
    backtest: pd.DataFrame | None = None
    backtest_note: str = ""
    equity_curves: dict[str, list[float]] | None = None
    plan: pd.DataFrame | None = None
    plan_note: str = ""


def build_report(
    cfg: Config,
    cache: Cache,
    as_of: str,
    prices: pd.Series | None = None,
    names: pd.Series | None = None,
    price_note: str = "收盘价",
    with_backtest: bool = True,
) -> ReportData:
    """prices / names 给定时用实时行情替代缓存收盘价（盘中刷新），否则用缓存最新收盘。"""
    trades = TradeBook(cfg.trades_path).load()
    book = positions_from_trades(trades)
    held = {c: p for c, p in book.items() if p.shares > 0}
    closed = {c: round(p.realized_pnl, 2) for c, p in book.items() if p.shares == 0}
    live = prices if prices is not None else cache.latest_closes(list(held))
    summary = portfolio_summary(held, live)
    codes = sorted(set(cfg.watchlist) | set(held))
    sigs = rank_signals([technical_signals(cache.daily(c), cfg.technical) for c in codes])
    snap = cache.snapshot()
    snap_names = snap.set_index("code")["name"] if not snap.empty else pd.Series(dtype=str)
    names = (
        snap_names
        if names is None
        else pd.concat([names, snap_names[~snap_names.index.isin(names.index)]])
    )
    if not summary.empty:
        summary.insert(1, "name", summary["code"].map(names).fillna(""))
    if not sigs.empty:
        sigs.insert(1, "name", sigs["code"].map(names).fillna(""))
    screened = fundamental_screen(snap, cfg.fundamental) if not snap.empty else snap
    updated = str(snap["updated_at"].iloc[0]) if not snap.empty and "updated_at" in snap else None
    rd = ReportData(as_of, summary, sigs, screened, closed, updated, price_note)
    if codes:
        strat = get_strategy(cfg.backtest["strategy"])
        daily_by_code = {c: cache.daily(c) for c in codes}
        last_dates = [
            str(d["date"].iloc[-1]) for d in daily_by_code.values() if d is not None and not d.empty
        ]
        rd.plan = build_plan(
            codes,
            daily_by_code,
            strat,
            book,
            names,
            stop_loss=cfg.backtest.get("stop_loss") or None,
            take_profit=cfg.backtest.get("take_profit") or None,
            capital=float(cfg.plan["capital"]),
            position_pct=float(cfg.plan["position_pct"]),
        )
        rd.plan_note = f"基于 {max(last_dates) if last_dates else as_of} 收盘，策略 {strat.name}（{strat.description}）。价格为挂单参考，开盘成交；仅供个人研究，不构成投资建议。"
    if with_backtest and codes:
        strat = get_strategy(cfg.backtest["strategy"])
        table, results = run_many(
            {c: cache.daily(c, start=str(cfg.backtest["start"])) for c in codes},
            strat,
            cfg.backtest_config(),
        )
        if not table.empty:
            table.insert(1, "name", table["code"].map(names).fillna(""))
        rd.backtest = table
        sl = cfg.backtest.get("stop_loss")
        rd.backtest_note = (
            f"策略 {strat.name}（{strat.description}），{cfg.backtest['start']} 起，初始资金 {cfg.backtest['initial_cash']:,}"
            + (f"，止损 {sl * 100:.0f}%" if sl else "")
        )
        rd.equity_curves = {c: r.equity.tolist() for c, r in results.items()}
    return rd
