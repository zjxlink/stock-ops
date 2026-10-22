"""命令行入口：stock-ops <命令>。"""

from __future__ import annotations

import logging
import math
from datetime import date
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from .analysis import fundamental_screen, technical_signals
from .analysis.technical import rank_signals
from .config import Config
from .data import Cache, Fetcher, normalize_code
from .data.fetch import build_providers
from .portfolio import portfolio_summary, positions_from_trades
from .report import daily_report

app = typer.Typer(help="个人 A 股分析操作系统", no_args_is_help=True)
trade_app = typer.Typer(help="交易流水与持仓")
app.add_typer(trade_app, name="trade")
console = Console()


def _ctx(config: str | None = None) -> tuple[Config, Cache]:
    cfg = Config.load(config)
    return cfg, Cache(cfg.db_path)


def _fetcher(cfg: Config, cache: Cache) -> Fetcher:
    return Fetcher(
        cache,
        providers=build_providers(cfg.data["provider_order"]),
        request_interval=cfg.data["request_interval"],
        max_retries=cfg.data["max_retries"],
    )


def _print_df(df, title: str, cols: list[str] | None = None, max_rows: int = 40):
    if df is None or df.empty:
        rprint(f"[yellow]{title}: 无数据[/]")
        return
    cols = [c for c in (cols or list(df.columns)) if c in df.columns]
    t = Table(title=title)
    for c in cols:
        t.add_column(c)
    for row in df[cols].head(max_rows).itertuples(index=False):
        t.add_row(
            *[
                ""
                if (isinstance(v, float) and math.isnan(v))
                else (f"{v:,.2f}" if isinstance(v, float) else str(v))
                for v in row
            ]
        )
    console.print(t)


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )


@app.command()
def update(
    codes: list[str] = typer.Argument(None, help="股票代码，留空则更新自选股和持仓股"),
    start: str = typer.Option("2018-01-01", help="首次抓取起始日期"),
    snapshot: bool = typer.Option(False, "--snapshot", help="同时更新全市场快照"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """增量更新日K线缓存。"""
    cfg, cache = _ctx(config)
    f = _fetcher(cfg, cache)
    targets = (
        [normalize_code(c) for c in codes]
        if codes
        else sorted(set(cfg.watchlist) | set(cache.trades()["code"].astype(str)))
    )
    if not targets and not snapshot:
        rprint(
            "[yellow]没有要更新的代码。请在 config.yaml 的 watchlist 中添加，或传入代码参数。[/]"
        )
        raise typer.Exit(1)
    res = f.update_many(targets, start=start)
    for c, n in res.items():
        rprint(f"{c}: " + ("[red]失败[/]" if n < 0 else f"+{n} 行"))
    if snapshot:
        n = f.update_snapshot()
        rprint(f"快照: {n} 只")


@app.command()
def signals(
    codes: list[str] = typer.Argument(None, help="股票代码，留空则用自选股"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """基于本地缓存计算技术面信号并排序。"""
    cfg, cache = _ctx(config)
    targets = [normalize_code(c) for c in codes] if codes else cfg.watchlist
    out = [technical_signals(cache.daily(c), cfg.technical) for c in targets]
    for c, s in zip(targets, out, strict=True):
        if not s.get("ok"):
            rprint(f"[yellow]{c}: {s.get('reason')}[/]")
    _print_df(
        rank_signals(out),
        "技术信号",
        [
            "code",
            "date",
            "close",
            "score",
            "ma_bull",
            "golden_cross",
            "macd_cross_up",
            "breakout20",
            "volume_up",
            "rsi",
            "ret20",
        ],
    )


@app.command()
def screen(config: str | None = typer.Option(None, "--config", "-c"), top: int = 30):
    """基本面筛选（需先 update --snapshot）。"""
    cfg, cache = _ctx(config)
    snap = cache.snapshot()
    if snap.empty:
        rprint("[yellow]快照为空，请先运行: stock-ops update --snapshot[/]")
        raise typer.Exit(1)
    res = fundamental_screen(snap, cfg.fundamental)
    rprint(f"输入 {res.attrs['input_count']} 只，通过 {len(res)} 只，剔除 {res.attrs['rejects']}")
    _print_df(
        res,
        "基本面筛选",
        ["code", "name", "price", "pe_ttm", "pb", "total_mv", "turnover"],
        max_rows=top,
    )


@trade_app.command("add")
def trade_add(
    code: str,
    side: str = typer.Argument(..., help="buy 或 sell"),
    price: float = typer.Argument(...),
    shares: int = typer.Argument(...),
    on: str = typer.Option(date.today().isoformat(), "--date"),
    fee: float = 0.0,
    note: str = "",
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """记录一笔交易。"""
    if side not in ("buy", "sell"):
        raise typer.BadParameter("side 必须是 buy 或 sell")
    _, cache = _ctx(config)
    tid = cache.add_trade(normalize_code(code), on, side, price, shares, fee, note)
    rprint(f"已记录 #{tid}: {on} {side} {code} {shares}股 @ {price}")


@trade_app.command("list")
def trade_list(code: str | None = None, config: str | None = typer.Option(None, "--config", "-c")):
    """列出交易流水。"""
    _, cache = _ctx(config)
    _print_df(cache.trades(normalize_code(code) if code else None), "交易流水", max_rows=200)


@trade_app.command("rm")
def trade_rm(trade_id: int, config: str | None = typer.Option(None, "--config", "-c")):
    """删除一笔交易。"""
    _, cache = _ctx(config)
    rprint("已删除" if cache.delete_trade(trade_id) else "[red]未找到[/]")


@app.command()
def portfolio(config: str | None = typer.Option(None, "--config", "-c")):
    """当前持仓与盈亏（价格取本地缓存最新收盘）。"""
    _, cache = _ctx(config)
    book = positions_from_trades(cache.trades())
    held = {c: p for c, p in book.items() if p.shares > 0}
    prices = cache.latest_closes(list(held))
    summary = portfolio_summary(held, prices)
    _print_df(
        summary,
        "持仓",
        [
            "code",
            "shares",
            "avg_cost",
            "price",
            "pnl_pct",
            "unrealized_pnl",
            "realized_pnl",
            "weight_pct",
        ],
    )
    closed = {c: p for c, p in book.items() if p.shares == 0}
    if closed:
        rprint(
            "已清仓已实现盈亏: "
            + "，".join(f"{c} {p.realized_pnl:,.0f}" for c, p in closed.items())
        )


@app.command()
def report(
    out: Path = typer.Option(Path("reports"), help="输出目录"),
    config: str | None = typer.Option(None, "--config", "-c"),
):
    """生成 Markdown 日报到 reports/YYYY-MM-DD.md。"""
    cfg, cache = _ctx(config)
    book = {c: p for c, p in positions_from_trades(cache.trades()).items() if p.shares > 0}
    summary = portfolio_summary(book, cache.latest_closes(list(book)))
    sigs = rank_signals(
        [
            technical_signals(cache.daily(c), cfg.technical)
            for c in sorted(set(cfg.watchlist) | set(book))
        ]
    )
    snap = cache.snapshot()
    screened = fundamental_screen(snap, cfg.fundamental) if not snap.empty else snap
    today = date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{today}.md"
    path.write_text(daily_report(today, summary, sigs, screened), encoding="utf-8")
    rprint(f"已写入 {path}")


if __name__ == "__main__":
    app()
