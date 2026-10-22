"""真实数据冒烟测试：在有外网的环境（GitHub Actions / 本地）验证各数据源可用，并走通完整流程。

用法: python scripts/smoke_live.py [--db path] [--summary out.md]
退出码非 0 表示核心链路失败（日K 全部数据源不可用或流程未走通）。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from stock_ops.analysis import fundamental_screen, technical_signals
from stock_ops.data import Cache, Fetcher
from stock_ops.data.akshare_provider import AkshareEmProvider, AkshareTxProvider
from stock_ops.data.baostock_provider import BaostockProvider

CODE = "600519"
START = (date.today() - timedelta(days=200)).isoformat()
END = date.today().isoformat()

LINES: list[str] = []


def say(msg: str) -> None:
    LINES.append(msg)
    print(msg, flush=True)


def check(name: str, fn) -> bool:
    try:
        df = fn()
        n = len(df)
        latest = f"，最新 {df['date'].iloc[-1]}" if n and "date" in df else ""
        say(f"[OK]   {name}: {n} 行{latest}")
        return n > 0
    except Exception as e:
        say(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:200]}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--summary", default=None, help="把结果写成 Markdown 到该文件")
    args = ap.parse_args()

    results: dict[str, bool] = {}
    bs = BaostockProvider()
    results["baostock.daily"] = check("baostock.daily", lambda: bs.daily(CODE, START, END))
    bs.close()
    results["akshare_tx.daily"] = check(
        "akshare_tx.daily", lambda: AkshareTxProvider().daily(CODE, START, END)
    )
    em = AkshareEmProvider()
    results["akshare_em.daily"] = check("akshare_em.daily", lambda: em.daily(CODE, START, END))
    results["akshare_em.snapshot"] = check("akshare_em.snapshot", em.snapshot)

    # 完整流程：Fetcher 自动切换 -> 缓存 -> 信号 -> 筛选
    db = Path(args.db) if args.db else Path(tempfile.mkdtemp()) / "smoke.db"
    cache = Cache(db)
    f = Fetcher(cache, request_interval=0.5, max_retries=2)
    try:
        n = f.update_daily(CODE, start=START)
        sig = technical_signals(cache.daily(CODE))
        say(f"[OK]   pipeline: 缓存 {n} 行，信号 score={sig.get('score')} ok={sig.get('ok')}")
        results["pipeline"] = bool(sig.get("ok"))
    except Exception as e:
        say(f"[FAIL] pipeline: {e}")
        results["pipeline"] = False
    try:
        n = f.update_snapshot()
        screened = fundamental_screen(cache.snapshot())
        say(
            f"[OK]   screen: 快照 {n} 只，通过 {len(screened)} 只，剔除 {screened.attrs.get('rejects')}"
        )
        results["screen"] = n > 0
    except Exception as e:
        say(f"[FAIL] screen: {e}")
        results["screen"] = False

    failed = [k for k, v in results.items() if not v]
    say(f"\n失败项: {failed or '无'}")
    daily_ok = any(results[k] for k in ("baostock.daily", "akshare_tx.daily", "akshare_em.daily"))
    core_ok = results.get("pipeline", False) and daily_ok
    if args.summary:
        status = "PASS" if core_ok else "FAIL"
        body = (
            f"### Live data smoke {date.today().isoformat()} — {status}\n\n```\n"
            + "\n".join(LINES)
            + "\n```\n"
        )
        Path(args.summary).write_text(body, encoding="utf-8")
    return 0 if core_ok else 1


if __name__ == "__main__":
    sys.exit(main())
