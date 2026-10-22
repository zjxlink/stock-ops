"""盘中刷新：用腾讯实时行情更新持仓股与自选股现价，重新生成看板。不写缓存、不跑全市场筛选。

交易时段由 .github/workflows/intraday.yml 的 cron 控制；本脚本只负责判交易日并生成页面。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_ops.config import Config
from stock_ops.data import Cache
from stock_ops.data.baostock_provider import BaostockProvider
from stock_ops.data.tencent_provider import TencentQuoteProvider
from stock_ops.portfolio import TradeBook
from stock_ops.report import build_report
from stock_ops.report.html import write_site

log = logging.getLogger("intraday")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--site", default="site")
    ap.add_argument("--force", action="store_true", help="非交易日也运行")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date().isoformat()
    cfg = Config.load(args.config)

    if not args.force:
        bs = BaostockProvider()
        try:
            if not bs.is_trading_day(today):
                log.info("%s 非交易日，跳过", today)
                return 0
        finally:
            bs.close()

    codes = sorted(set(cfg.watchlist) | set(TradeBook(cfg.trades_path).codes()))
    quotes = TencentQuoteProvider().quotes(codes)
    if quotes.empty:
        log.error("未取到实时行情")
        return 1
    prices = quotes.set_index("code")["price"]
    names = quotes.set_index("code")["name"]
    log.info("实时行情 %d 只: %s", len(quotes), ", ".join(f"{c} {p}" for c, p in prices.items()))

    cache = Cache(cfg.db_path)  # 由 Actions cache 恢复；缺失时信号与筛选为空，持仓仍可计算
    rd = build_report(
        cfg, cache, today, prices=prices, names=names, price_note=f"盘中实时 {now:%H:%M}"
    )
    log.info("看板已写入 %s", write_site(rd, cache, cfg, args.site))
    return 0


if __name__ == "__main__":
    sys.exit(main())
