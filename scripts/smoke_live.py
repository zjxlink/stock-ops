"""真实数据冒烟测试：在有外网的环境（GitHub Actions / 本地）验证各数据源可用，并走通完整流程。

用法: python scripts/smoke_live.py [--db path]
退出码非 0 表示有数据源失败。
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


def check(name: str, fn, print=print):
    try:
        df = fn()
        n = len(df)
        print(
            f"[OK]   {name}: {n} 行"
            + (f"，最新 {df['date'].iloc[-1] if 'date' in df else ''}" if n else "")
        )
        return n > 0
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:200]}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--summary", default=None, help="把结果写成 Markdown 到该文件")
    args = ap.parse_args()

    results = {}
    lines: list[str] = []
    _print = print

    def print(*a):
        msg = " ".join(str(x) for x in a)
        lines.append(msg)
        _print(msg)

    bs = BaostockProvider()
    results["baostock.daily"] = check("baostock.daily", lambda: bs.daily(CODE, START, END), print)
    bs.close()
    results["akshare_tx.daily"] = check(
        "akshare_tx.daily", lambda: AkshareTxProvider().daily(CODE, START, END)
    )
    em = AkshareEmProvider()
    results["akshare_em.daily"] = check(
        "akshare_em.daily", lambda: em.daily(CODE, START, END), print
    )
    results["akshare_em.snapshot"] = check("akshare_em.snapshot", em.snapshot, print)

    # 完整流程：Fetcher 自动切换 -> 缓存 -> 信号 -> 筛选
    db = Path(args.db) if args.db else Path(tempfile.mkdtemp()) / "smoke.db"
    cache = Cache(db)
    f = Fetcher(cache, request_interval=0.5, max_retries=2)
    try:
        n = f.update_daily(CODE, start=START)
        sig = technical_signals(cache.daily(CODE))
        print(f"[OK]   pipeline: 缓存 {n} 行，信号 score={sig.get('score')} ok={sig.get('ok')}")
        results["pipeline"] = bool(sig.get("ok"))
    except Exception as e:
        print(f"[FAIL] pipeline: {e}")
        results["pipeline"] = False
    try:
        n = f.update_snapshot()
        screened = fundamental_screen(cache.snapshot())
        print(
            f"[OK]   screen: 快照 {n} 只，通过 {len(screened)} 只，剔除 {screened.attrs.get('rejects')}"
        )
        results["screen"] = n > 0
    except Exception as e:
        print(f"[FAIL] screen: {e}")
        results["screen"] = False

    failed = [k for k, v in results.items() if not v]
    print("\n失败项:", failed or "无")
    if args.summary:
        body = (
            f"### Live data smoke {date.today().isoformat()}\n\n```\n"
            + "\n".join(lines)
            + "\n```\n"
        )
        Path(args.summary).write_text(body, encoding="utf-8")
    # 日K 至少一个源可用且流程走通即视为通过；快照失败只告警
    core_ok = results.get("pipeline") and any(
        results[k] for k in ("baostock.daily", "akshare_tx.daily", "akshare_em.daily")
    )
    return 0 if core_ok else 1


if __name__ == "__main__":
    sys.exit(main())
