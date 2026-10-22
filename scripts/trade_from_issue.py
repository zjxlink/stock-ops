"""GitHub Actions 调用：读取 Issue 正文，解析交易指令，写入 data/trades.csv，输出回复文本。

用法: python scripts/trade_from_issue.py --title "..." --body-file body.txt --reply-file reply.md
退出码 0 写入成功；2 没有可识别的指令；1 其他错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_ops.config import Config
from stock_ops.portfolio import TradeBook, positions_from_trades
from stock_ops.portfolio.issue_parser import parse_issue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="")
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--reply-file", required=True)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = Config.load(args.config)
    body = Path(args.body_file).read_text(encoding="utf-8")
    cmds = parse_issue(body, args.title)
    reply = Path(args.reply_file)
    if not cmds:
        reply.write_text(
            "没有识别到交易指令。请用表单，或每行一笔：`buy 600519 1500 100` / `卖出 600519 1600 50 5 2026-10-22 止盈`"
            "（顺序：方向 代码 价格 股数 [手续费] [日期] [备注]）。",
            encoding="utf-8",
        )
        return 2

    tb = TradeBook(cfg.trades_path)
    lines = ["已写入交易流水：", ""]
    for c in cmds:
        tid = tb.add(c.code, c.date, c.side, c.price, c.shares, c.fee, c.note)
        lines.append(
            f"- #{tid} {c.date} {'买入' if c.side == 'buy' else '卖出'} {c.code} {c.shares} 股 @ {c.price}"
            + (f"，手续费 {c.fee}" if c.fee else "")
            + (f"，{c.note}" if c.note else "")
        )
    try:
        book = positions_from_trades(tb.load())
    except ValueError as e:
        # 卖出超过持仓等逻辑错误：回滚本次写入
        for _ in cmds:
            df = tb.load()
            tb.delete(int(df["id"].max()))
        reply.write_text(f"未写入：{e}", encoding="utf-8")
        return 1
    lines += ["", "当前持仓："]
    held = [(c, p) for c, p in book.items() if p.shares > 0]
    lines += [f"- {c}: {p.shares} 股，成本 {p.avg_cost:.3f}" for c, p in held] or ["- 空仓"]
    lines += ["", "看板将在下一次每日更新后刷新；也可在 Actions 里手动运行 Daily report。"]
    reply.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
