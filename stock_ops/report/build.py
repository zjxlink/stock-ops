"""把缓存里的数据组装成日报所需的三张表，CLI、每日任务和 Web 页面共用。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import fundamental_screen, technical_signals
from ..analysis.plan import build_plan
from ..analysis.technical import rank_signals
from ..backtest import STRATEGIES, get_strategy, market_regime, run_many
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
    strategy_compare: pd.DataFrame | None = None
    regime_ok: bool | None = None
    regime_note: str = ""


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
    index_code, index_ma = str(cfg.market.get("index") or ""), int(cfg.market.get("ma") or 0)
    index_df = cache.daily(index_code) if index_code else None
    regime = market_regime(index_df, index_ma) if index_ma else None
    if regime is not None and len(regime):
        rd.regime_ok = bool(regime.iloc[-1])
        last_close = float(index_df["close"].iloc[-1])
        ma_val = float(index_df["close"].astype(float).rolling(index_ma).mean().iloc[-1])
        rd.regime_note = (
            f"大盘过滤：{index_code} 收盘 {last_close:.0f}，{index_ma} 日线 {ma_val:.0f}，"
            + ("多头，允许开新仓" if rd.regime_ok else "弱势，不开新仓")
        )
    elif index_ma:
        rd.regime_note = f"大盘过滤：{index_code} 数据缺失，暂不过滤"
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
            rules={str(k).zfill(6): v for k, v in (cfg.plan.get("rules") or {}).items()},
            stop_loss=cfg.backtest.get("stop_loss") or None,
            trailing_stop=cfg.backtest.get("trailing_stop") or None,
            trailing_from=str(cfg.plan.get("trailing_from") or "") or None,
            atr_stop=cfg.backtest.get("atr_stop") or None,
            regime_ok=rd.regime_ok,
            take_profit=cfg.backtest.get("take_profit") or None,
            capital=float(cfg.plan["capital"]),
            position_pct=float(cfg.plan["position_pct"]),
        )
        rd.plan_note = f"基于 {max(last_dates) if last_dates else as_of} 收盘，策略 {strat.name}（{strat.description}）。{rd.regime_note + '。' if rd.regime_note else ''}价格为挂单参考，开盘成交；仅供个人研究，不构成投资建议。"
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
            + (f"，成本止损 {sl * 100:.0f}%" if sl else "")
            + (f"，移动止损 {ts * 100:.0f}%" if (ts := cfg.backtest.get("trailing_stop")) else "")
            + (f"，ATR 跟踪止损 {k:g} 倍" if (k := cfg.backtest.get("atr_stop")) else "")
            + (f"，最少持仓 {mh} 天" if (mh := cfg.backtest.get("min_hold_days")) else "")
            + (f"，止损后冷却 {cd} 天" if (cd := cfg.backtest.get("cooldown_days")) else "")
            + (f"，大盘过滤 {index_code} {index_ma} 日线" if regime is not None else "")
        )
        rd.equity_curves = {c: r.equity.tolist() for c, r in results.items()}
        rows = []
        for name, st in STRATEGIES.items():
            t = (
                table
                if name == strat.name
                else run_many(
                    {c: cache.daily(c, start=str(cfg.backtest["start"])) for c in codes},
                    st,
                    cfg.backtest_config(),
                )[0]
            )
            if not t.empty:
                avg = t[t["code"] == "平均"].iloc[0].to_dict()
                rows.append(
                    {
                        "strategy": name,
                        "description": st.description,
                        **{
                            k: v
                            for k, v in avg.items()
                            if k not in ("code", "name", "start", "end")
                        },
                    }
                )
        rd.strategy_compare = (
            pd.DataFrame(rows).sort_values("total_return", ascending=False).reset_index(drop=True)
            if rows
            else None
        )
    return rd
