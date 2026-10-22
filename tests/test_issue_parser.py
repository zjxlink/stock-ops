from stock_ops.portfolio.issue_parser import parse_issue

FORM = """### 方向

buy 买入

### 代码

600519

### 价格

1500

### 股数

100

### 手续费

_No response_

### 日期

2026-10-20

### 备注

首仓
"""


def test_parse_form():
    (c,) = parse_issue(FORM)
    assert (c.side, c.code, c.price, c.shares, c.fee, c.date, c.note) == (
        "buy",
        "600519",
        1500.0,
        100,
        0.0,
        "2026-10-20",
        "首仓",
    )


def test_parse_free_text_lines():
    cmds = parse_issue(
        "buy 600519 1500 100\n卖出 000001 10.5 200 5 2026-10-21 止盈\n随便一行", today="2026-10-22"
    )
    assert len(cmds) == 2
    assert cmds[0].date == "2026-10-22" and cmds[0].fee == 0
    assert (cmds[1].side, cmds[1].fee, cmds[1].date, cmds[1].note) == (
        "sell",
        5.0,
        "2026-10-21",
        "止盈",
    )


def test_parse_title_only():
    (c,) = parse_issue("", title="b sh600519 1500 100")
    assert c.code == "600519" and c.side == "buy"


def test_parse_nothing():
    assert parse_issue("hello world") == []
