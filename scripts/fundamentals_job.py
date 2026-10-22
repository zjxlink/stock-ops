"""全市场基本面更新：对快照里的全部股票抓取最新季度财务指标，写入缓存。

每只约 4 次接口调用，全市场约 20 分钟；--budget 控制本次运行的秒数上限，超时自动停止，下次从未更新的股票继续。
用法: python scripts/fundamentals_job.py [--budget 3000] [--max-age 7]
"""

from __future__ import annotations

import argparse
import logging
import sys

from stock_ops.config import Config
from stock_ops.data import Cache, Fetcher
from stock_ops.data.fetch import update_fundamentals
from stock_ops.portfolio import TradeBook

log = logging.getLogger("fundamentals")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--budget", type=float, default=3000, help="本次运行秒数上限")
    ap.add_argument("--max-age", type=int, default=7)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = Config.load(args.config)
    cache = Cache(cfg.db_path)
    snap = cache.snapshot()
    if snap.empty:
        log.info("快照为空，先拉取全市场快照")
        n, src = Fetcher(cache).update_snapshot()
        log.info("快照 %d 只，来源 %s", n, src)
        snap = cache.snapshot()
    universe = sorted(
        set(snap["code"].astype(str)) | set(cfg.watchlist) | set(TradeBook(cfg.trades_path).codes())
    )
    stale = cache.fundamentals_stale(universe, args.max_age)
    log.info("全市场 %d 只，需更新 %d 只", len(universe), len(stale))
    n = update_fundamentals(cache, universe, max_age_days=args.max_age, time_budget_s=args.budget)
    remaining = len(cache.fundamentals_stale(universe, args.max_age))
    log.info("本次写入 %d 只，仍待更新 %d 只", n, remaining)
    return 0


if __name__ == "__main__":
    sys.exit(main())
