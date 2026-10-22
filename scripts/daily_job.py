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

import pandas as pd

from stock_ops.config import Config
from stock_ops.data import Cache, Fetcher
from stock_ops.data.baostock_provider import BaostockProvider
from stock_ops.data.fetch import build_providers, update_fundamentals
from stock_ops.portfolio import TradeBook
from stock_ops.predict import PredictionLog, predict_latest, walk_forward
from stock_ops.report import build_report, render_report
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
    if cfg.market.get("index"):
        codes.append(str(cfg.market["index"]))  # 大盘过滤用的指数
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

    # 基本面：持仓股与自选股，缓存超过 N 天重新抓取
    try:
        nf = update_fundamentals(
            cache,
            [c for c in codes if "." not in c],
            max_age_days=int(cfg.data.get("fundamentals_max_age_days") or 7),
        )
        log.info("基本面更新 %d 只", nf)
    except Exception as e:
        log.error("基本面更新失败，沿用缓存: %s", e)

    # 预测：先验证昨日，再对每只股票做明日预测；首次见到的股票回填历史
    try:
        stock_codes = [c for c in codes if "." not in c]
        plog = PredictionLog(cfg.predictions_path)
        _, nv = plog.verify({c: cache.daily(c) for c in stock_codes})
        existing = plog.load()
        new_rows = []
        for c in stock_codes:
            d = cache.daily(c)
            if d is None or len(d) < 130:
                continue
            if existing.empty or not (existing["code"] == c).any():
                new_rows.append(walk_forward(d, last_n=int(cfg.predict["backfill_days"]), code=c))
            last_date = str(d["date"].iloc[-1])
            if (
                existing.empty
                or not ((existing["code"] == c) & (existing["date"] == last_date)).any()
            ):
                new_rows.append(predict_latest(d, code=c))
        if new_rows:
            plog.append(pd.concat(new_rows, ignore_index=True))
        log.info("预测：验证 %d 条，新增 %d 条", nv, sum(len(x) for x in new_rows))
    except Exception as e:
        log.error("预测步骤失败，跳过: %s", e)

    rd = build_report(cfg, cache, today)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = render_report(rd)
    (out / f"{today}.md").write_text(text, encoding="utf-8")
    (out / "latest.md").write_text(text, encoding="utf-8")
    log.info("日报已写入 %s", out / f"{today}.md")
    log.info("看板已写入 %s", write_site(rd, cache, cfg, args.site))
    return 0


if __name__ == "__main__":
    sys.exit(main())
