"""全市场基本面更新（可分片并行）。

模式：
  抓取：python scripts/fundamentals_job.py --shard 0 --shards 4 --out fund/shard0.csv [--budget 2700]
        不给 --out 时直接写入缓存。
  合并：python scripts/fundamentals_job.py --merge fund/   把目录里所有 CSV 写入缓存。

股票池默认为"通过价格类筛选的股票 + 持仓股 + 自选股"（约 1000 只），--universe all 则为快照全部股票。
只抓缓存里缺最新季度财报的股票（见 Cache.fundamentals_stale）。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from stock_ops.analysis.fundamental import fundamental_screen
from stock_ops.config import Config
from stock_ops.data import Cache, Fetcher
from stock_ops.data.fundamentals import FUND_COLUMNS, BaostockFundamentals
from stock_ops.portfolio import TradeBook

log = logging.getLogger("fundamentals")


def universe_codes(cfg: Config, cache: Cache, mode: str) -> list[str]:
    snap = cache.snapshot()
    if snap.empty:
        log.info("快照为空，先拉取全市场快照")
        n, src = Fetcher(cache).update_snapshot()
        log.info("快照 %d 只，来源 %s", n, src)
        snap = cache.snapshot()
    if mode == "all":
        pool = set(snap["code"].astype(str))
    else:
        price_only = {
            k: v
            for k, v in cfg.fundamental.items()
            if k not in ("roe_min", "yoy_ni_min", "liability_to_asset_max")
        }
        price_only.update({"roe_min": None, "yoy_ni_min": None, "liability_to_asset_max": None})
        pool = set(fundamental_screen(snap, price_only, None)["code"].astype(str))
    return sorted(pool | set(cfg.watchlist) | set(TradeBook(cfg.trades_path).codes()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--universe", choices=["screened", "all"], default="screened")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--budget", type=float, default=2700, help="本次运行秒数上限")
    ap.add_argument("--max-age", type=int, default=7)
    ap.add_argument("--out", default=None, help="结果写到 CSV 而不是缓存（分片模式）")
    ap.add_argument("--merge", default=None, help="把目录下所有 CSV 合并写入缓存")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = Config.load(args.config)
    cache = Cache(cfg.db_path)

    if args.merge:
        files = sorted(Path(args.merge).glob("**/*.csv"))
        frames = [
            pd.read_csv(
                f, dtype={"code": str, "report_date": str, "pub_date": str, "updated_at": str}
            )
            for f in files
        ]
        frames = [f for f in frames if not f.empty]
        if not frames:
            log.info("没有可合并的分片结果")
            return 0
        df = pd.concat(frames, ignore_index=True).drop_duplicates("code", keep="last")
        df["code"] = df["code"].str.zfill(6)
        n = cache.upsert_fundamentals(df)
        total = len(cache.fundamentals())
        log.info("合并 %d 个分片，写入 %d 只，缓存共 %d 只有财报数据", len(files), n, total)
        return 0

    codes = universe_codes(cfg, cache, args.universe)
    stale = cache.fundamentals_stale(codes, args.max_age)
    mine = stale[args.shard :: args.shards]
    log.info(
        "股票池 %d 只，需更新 %d 只，本分片 %d/%d 负责 %d 只",
        len(codes),
        len(stale),
        args.shard,
        args.shards,
        len(mine),
    )
    bf = BaostockFundamentals()
    try:
        df = bf.fetch_many(
            mine, time_budget_s=args.budget, progress=lambda i, n: log.info("进度 %d/%d", i, n)
        )
    finally:
        bf.close()
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.reindex(columns=FUND_COLUMNS).to_csv(args.out, index=False, encoding="utf-8")
        log.info("本分片完成 %d 只，写入 %s", len(df), args.out)
    else:
        n = cache.upsert_fundamentals(df)
        log.info(
            "本次写入 %d 只，仍待更新 %d 只", n, len(cache.fundamentals_stale(codes, args.max_age))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
