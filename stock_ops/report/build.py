"""把缓存里的数据组装成日报所需的三张表，CLI、每日任务和 Web 页面共用。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis import fundamental_screen, technical_signals
from ..analysis.plan import build_plan
from ..analysis.technical import rank_signals
from ..backtest import STRATEGIES, get_strategy, market_regime, run_many, run_portfolio
from ..config import Config
from ..data import Cache
from ..portfolio import TradeBook, portfolio_summary, positions_from_trades
from ..predict import PredictionLog, accuracy_table, best_methods


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
    portfolio_bt: dict | None = None
    portfolio_equity: list[float] | None = None
    portfolio_note: str = ""
    predictions: pd.DataFrame | None = None
    accuracy: pd.DataFrame | None = None
    prediction_note: str = ""
    fundamentals: pd.DataFrame | None = None
    fund_note: str = ""


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
    fund_all = cache.fundamentals()
    screened = fundamental_screen(snap, cfg.fundamental, fund_all) if not snap.empty else snap
    updated = str(snap["updated_at"].iloc[0]) if not snap.empty and "updated_at" in snap else None
    rd = ReportData(as_of, summary, sigs, screened, closed, updated, price_note)
    fund_codes = fund_all[fund_all["code"].isin(codes)] if not fund_all.empty else fund_all
    if not fund_codes.empty:
        ft = fund_codes.copy()
        ft.insert(1, "name", ft["code"].map(names).fillna(""))
        if not snap.empty:
            ft = ft.merge(snap[["code", "pe_ttm", "pb", "total_mv"]], on="code", how="left")
        rd.fundamentals = ft.sort_values("code").reset_index(drop=True)
        rd.fund_note = "最新一期财报（Baostock 季度数据），比率单位 %。ROE 为报告期平均净资产收益率，净利润同比为归母净利润同比。"
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
        # 明日涨跌预测与准确率
        try:
            plog = PredictionLog(cfg.predictions_path).load()
            if not plog.empty:
                acc = accuracy_table(
                    plog, window=int(cfg.predict["window"]), min_n=int(cfg.predict["min_n"])
                )
                best = best_methods(acc)
                latest = plog.sort_values("date").groupby(["code", "method"]).tail(1)
                latest = latest[latest["code"].isin(codes)]
                rows = []
                for c in codes:
                    g = latest[latest["code"] == c]
                    if g.empty:
                        continue
                    b = best.get(c)
                    if b:
                        row = g[g["method"] == b["method"]]
                        pred = int(row["pred"].iloc[0]) if not row.empty else None
                        rows.append(
                            {
                                "code": c,
                                "name": names.get(c, ""),
                                "date": str(g["date"].max()),
                                "reliable": True,
                                "method": b["method"],
                                "pred": "涨" if pred == 1 else "跌" if pred == 0 else "",
                                "prob": float(row["prob"].iloc[0])
                                if not row.empty
                                else float("nan"),
                                "acc": b["acc"],
                                "ci_low": b["ci_low"],
                                "baseline": b["baseline"],
                                "n": int(b["n"]),
                                "live_n": int(b["live_n"]),
                            }
                        )
                    else:
                        a = acc[acc["code"] == c].sort_values("acc", ascending=False)
                        top = a.iloc[0] if not a.empty else None
                        vote = g[g["method"] == "vote"]
                        rows.append(
                            {
                                "code": c,
                                "name": names.get(c, ""),
                                "date": str(g["date"].max()),
                                "reliable": False,
                                "method": top["method"] if top is not None else "",
                                "pred": ("涨" if int(vote["pred"].iloc[0]) == 1 else "跌")
                                if not vote.empty
                                else "",
                                "prob": float("nan"),
                                "acc": top["acc"] if top is not None else float("nan"),
                                "ci_low": top["ci_low"] if top is not None else float("nan"),
                                "baseline": top["baseline"] if top is not None else float("nan"),
                                "n": int(top["n"]) if top is not None else 0,
                                "live_n": int(top["live_n"]) if top is not None else 0,
                            }
                        )
                rd.predictions = pd.DataFrame(rows)
                rd.accuracy = acc[acc["code"].isin(codes)].reset_index(drop=True)
                n_rel = sum(1 for r in rows if r["reliable"])
                rd.prediction_note = (
                    f"对次日涨跌的方向预测，共 {len(acc['method'].unique())} 种方法。准确率取最近 {cfg.predict['window']} 条已验证预测；"
                    f"只有样本 ≥ {cfg.predict['min_n']}、95% 置信下限高于 50% 且高于基线（永远看涨/看跌）的方法才标为可参考。"
                    f"当前 {len(rows)} 只中 {n_rel} 只有可参考方法。回填样本是用历史数据事后计算的，真实前瞻样本数见 live_n。"
                )
                if rd.plan is not None and not rd.plan.empty:
                    txt = {}
                    for r in rows:
                        txt[r["code"]] = (
                            f"{r['pred']}（{r['method']} {r['acc']:.0f}%，n={r['n']}）"
                            if r["reliable"]
                            else f"无可靠预测（最佳 {r['acc']:.0f}%）"
                            if r["n"]
                            else "无可靠预测"
                        )
                    rd.plan["prediction"] = rd.plan["code"].map(txt).fillna("")
        except Exception:  # 预测日志缺失或格式问题不影响日报
            rd.predictions = None
    if with_backtest and codes:
        strat = get_strategy(cfg.backtest["strategy"])
        table, results = run_many(
            {c: cache.daily(c, start=str(cfg.backtest["start"])) for c in codes},
            strat,
            cfg.backtest_config(),
            regime,
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
                    regime,
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
        # 组合级回测：一份资金在这批股票间调度
        try:
            maxp = int(cfg.backtest.get("max_positions") or 3)
            pr = run_portfolio(
                {c: cache.daily(c, start=str(cfg.backtest["start"])) for c in codes},
                strat,
                cfg.backtest_config(),
                regime,
                max_positions=maxp,
            )
            rd.portfolio_bt = pr.metrics
            rd.portfolio_equity = pr.equity.tolist()
            rd.portfolio_note = (
                f"同一策略与风控，一份资金 {cfg.backtest['initial_cash']:,} 在 {len(codes)} 只股票间调度，"
                f"最多同时持有 {maxp} 只，每仓约 1/{maxp} 权益；对比等权买入持有"
            )
        except ValueError:
            rd.portfolio_bt = None
    return rd
