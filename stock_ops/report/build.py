"""把缓存里的数据组装成日报所需的三张表，CLI、每日任务和 Web 页面共用。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import fundamental_screen, technical_signals
from ..analysis.technical import rank_signals
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


def build_report(
    cfg: Config,
    cache: Cache,
    as_of: str,
    prices: pd.Series | None = None,
    names: pd.Series | None = None,
    price_note: str = "收盘价",
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
    return ReportData(as_of, summary, sigs, screened, closed, updated, price_note)
