"""解析 GitHub Issue 里的交易指令。

支持两种格式：
1. Issue 表单（.github/ISSUE_TEMPLATE/trade.yml）生成的 "### 字段\\n\\n值" 段落；
2. 自由文本，每行一笔：buy 600519 1500 100 [fee] [note] 或 买入 600519 1500 100。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..data.base import normalize_code

_SIDE = {
    "buy": "buy",
    "b": "buy",
    "买": "buy",
    "买入": "buy",
    "sell": "sell",
    "s": "sell",
    "卖": "sell",
    "卖出": "sell",
}
_FIELD_MAP = {
    "方向": "side",
    "代码": "code",
    "价格": "price",
    "股数": "shares",
    "手续费": "fee",
    "日期": "date",
    "备注": "note",
}


@dataclass
class TradeCmd:
    code: str
    side: str
    price: float
    shares: int
    fee: float = 0.0
    date: str = ""
    note: str = ""


def _parse_form(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"^###\s*(.+?)\s*\n+(.*?)(?=^###|\Z)", body, flags=re.S | re.M):
        key = _FIELD_MAP.get(m.group(1).strip())
        if key:
            val = m.group(2).strip()
            out[key] = "" if val in ("_No response_", "") else val
    return out


def parse_issue(body: str, title: str = "", today: str | None = None) -> list[TradeCmd]:
    today = today or date.today().isoformat()
    body = body or ""
    cmds: list[TradeCmd] = []

    form = _parse_form(body)
    if {"side", "code", "price", "shares"} <= set(k for k, v in form.items() if v):
        side = _SIDE.get(form["side"].strip().lower().split()[0])
        if side:
            cmds.append(
                TradeCmd(
                    code=normalize_code(form["code"]),
                    side=side,
                    price=float(form["price"]),
                    shares=int(float(form["shares"])),
                    fee=float(form.get("fee") or 0),
                    date=form.get("date") or today,
                    note=form.get("note", ""),
                )
            )
            return cmds

    for line in (title + "\n" + body).splitlines():
        parts = line.strip().replace("，", " ").split()
        if len(parts) < 4 or parts[0].lower() not in _SIDE:
            continue
        try:
            cmd = TradeCmd(
                code=normalize_code(parts[1]),
                side=_SIDE[parts[0].lower()],
                price=float(parts[2]),
                shares=int(float(parts[3])),
                date=today,
            )
        except ValueError:
            continue
        rest = parts[4:]
        if rest and re.fullmatch(r"\d+(\.\d+)?", rest[0]):
            cmd.fee = float(rest.pop(0))
        if rest and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rest[0]):
            cmd.date = rest.pop(0)
        cmd.note = " ".join(rest)
        cmds.append(cmd)
    return cmds
