"""参数扫描：在同一批股票上比较 策略 × ATR 倍数 × 大盘过滤 的组合，按最大回撤与收益排序。

用法: python scripts/sweep.py [--config config.yaml] [--out sweep.md]
在 GitHub Actions 上由 sweep.yml 调用，结果写成 commit 评论。需要缓存里已有日K与指数数据（Daily report 跑过即可）。
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import pandas as pd

from stock_ops.backtest import STRATEGIES, BacktestConfig, market_regime, run_many
from stock_ops.config import Config
from stock_ops.data import Cache
from stock_ops.portfolio import TradeBook


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default="sweep.md")
    ap.add_argument("--strategies", default="breakout20,donchian,trend60,ma_bull,macd")
    ap.add_argument("--atr", default="0,2,3,4")
    ap.add_argument("--regime-ma", default="0,60,120")
    ap.add_argument("--min-hold", default="5")
    ap.add_argument("--start", default=None)
    args = ap.parse_args()

    cfg = Config.load(args.config)
    cache = Cache(cfg.db_path)
    codes = sorted(set(cfg.watchlist) | set(TradeBook(cfg.trades_path).codes()))
    start = args.start or str(cfg.backtest["start"])
    data = {c: cache.daily(c, start=start) for c in codes}
    data = {c: d for c, d in data.items() if d is not None and len(d) > 120}
    index_df = cache.daily(str(cfg.market.get("index") or "sh.000300"))
    base = cfg.backtest_config()

    rows = []
    for name, atr, rma, mh in itertools.product(
        args.strategies.split(","),
        [float(x) for x in args.atr.split(",")],
        [int(x) for x in args.regime_ma.split(",")],
        [int(x) for x in args.min_hold.split(",")],
    ):
        c = BacktestConfig(**{**base.__dict__, "atr_stop": atr or None, "min_hold_days": mh})
        regime = market_regime(index_df, rma) if rma else None
        table, _ = run_many(data, STRATEGIES[name], c, regime)
        if table.empty:
            continue
        avg = table[table["code"] == "平均"].iloc[0]
        worst = table[table["code"] != "平均"]["max_drawdown"].min()
        rows.append(
            {
                "strategy": name,
                "atr": atr,
                "regime_ma": rma,
                "min_hold": mh,
                "ret": avg["total_return"],
                "cagr": avg["cagr"],
                "mdd_avg": avg["max_drawdown"],
                "mdd_worst": worst,
                "sharpe": avg["sharpe"],
                "trades": avg["trades"],
                "win": avg["win_rate"],
                "pf": avg["profit_factor"],
                "calmar": round(avg["cagr"] / abs(avg["max_drawdown"]), 2)
                if avg["max_drawdown"]
                else float("nan"),
            }
        )
    df = (
        pd.DataFrame(rows)
        .sort_values(["mdd_avg", "ret"], ascending=[False, False])
        .reset_index(drop=True)
    )
    bh = run_many(data, STRATEGIES["ma_bull"], base)[0]
    bh_avg = bh[bh["code"] == "平均"].iloc[0]["buy_hold"] if not bh.empty else float("nan")

    lines = [
        f"### 参数扫描（{len(data)} 只，{start} 起，买入持有平均 {bh_avg:.1f}%）",
        "",
        "按平均最大回撤从小到大排序；mdd_worst 为单只最差回撤；calmar = 年化 / |回撤|",
        "",
        "| " + " | ".join(df.columns) + " |",
        "|" + "---|" * len(df.columns),
    ]
    for r in df.itertuples(index=False):
        lines.append(
            "| " + " | ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in r) + " |"
        )
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
