"""盘后每日任务：判交易日 -> 更新自选股与持仓股日K -> 全市场快照 -> 写日报。

在 GitHub Actions 上由 .github/workflows/daily.yml 调用，也可本地手动运行。
退出码 0 表示完成（含非交易日跳过）；非 0 表示核心步骤失败。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ops.config import Config
from stock_ops.data import Cache, Fetcher
from stock_ops.data.baostock_provider import BaostockProvider
from stock_ops.data.fetch import build_providers
from stock_ops.portfolio import TradeBook
from stock_ops.report import build_report, daily_report
from stock_ops.report.html import write_site

log = logging.getLogger("daily")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--site", default="site", help="静态看板输出目录")
    ap.add_argument("--force", action="store_true", help="非交易日也运行")
    ap.add_argument("--no-snapshot", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    cfg = Config.load(args.config)

    bs = BaostockProvider()
    try:
        if not args.force and not bs.is_trading_day(today):
            log.info("%s 非交易日，跳过", today)
            return 0
    finally:
        bs.close()

    cache = Cache(cfg.db_path)
    f = Fetcher(
        cache,
        providers=build_providers(cfg.data["provider_order"]),
        request_interval=cfg.data["request_interval"],
        max_retries=cfg.data["max_retries"],
    )
    codes = sorted(set(cfg.watchlist) | set(TradeBook(cfg.trades_path).codes()))
    log.info("更新 %d 只: %s", len(codes), " ".join(codes))
    res = f.update_many(codes)
    failed = [c for c, n in res.items() if n < 0]
    if failed:
        log.error("更新失败: %s", failed)
    if len(failed) == len(codes) and codes:
        return 1

    if not args.no_snapshot:
        try:
            n, src = f.update_snapshot()
            log.info("快照 %d 只，来源 %s", n, src)
        except Exception as e:
            log.error("快照失败，沿用上次缓存: %s", e)

    rd = build_report(cfg, cache, today)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = daily_report(rd.date, rd.portfolio, rd.signals, rd.screened)
    (out / f"{today}.md").write_text(text, encoding="utf-8")
    (out / "latest.md").write_text(text, encoding="utf-8")
    log.info("日报已写入 %s", out / f"{today}.md")
    log.info("看板已写入 %s", write_site(rd, cache, cfg, args.site))
    return 0


if __name__ == "__main__":
    sys.exit(main())
