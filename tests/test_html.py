from stock_ops.config import Config
from stock_ops.data import Cache
from stock_ops.portfolio import TradeBook
from stock_ops.report import build_report
from stock_ops.report.html import sparkline, write_site
from tests.conftest import make_daily


def test_sparkline_svg():
    svg = sparkline([1.0, 2.0, 1.5])
    assert svg.startswith("<svg") and "polyline" in svg and "var(--up)" in svg
    assert sparkline([1.0]) == ""


def test_write_site(tmp_path, snapshot):
    cache = Cache(tmp_path / "db.sqlite")
    cache.upsert_daily(make_daily("600001"))
    cache.replace_snapshot(snapshot, "2026-10-22T18:00:00")
    TradeBook(tmp_path / "trades.csv").add("600001", "2025-06-01", "buy", 10, 100)
    cfg = Config(
        raw={**Config().raw, "watchlist": ["600001"], "portfolio": {"trades_path": "trades.csv"}},
        root=tmp_path,
    )
    rd = build_report(cfg, cache, "2026-10-22")
    path = write_site(rd, cache, cfg, tmp_path / "site")
    html = path.read_text(encoding="utf-8")
    assert "600001" in html and "好公司" in html and "<svg" in html and "录入交易" in html
    assert (tmp_path / "site" / ".nojekyll").exists()


def test_build_report_live_prices(tmp_path, snapshot):
    import pandas as pd

    cache = Cache(tmp_path / "db.sqlite")
    cache.upsert_daily(make_daily("600001"))
    TradeBook(tmp_path / "trades.csv").add("600001", "2025-06-01", "buy", 10, 100)
    cfg = Config(raw={**Config().raw, "portfolio": {"trades_path": "trades.csv"}}, root=tmp_path)
    rd = build_report(
        cfg,
        cache,
        "2026-10-22",
        prices=pd.Series({"600001": 12.0}),
        names=pd.Series({"600001": "好公司"}),
        price_note="盘中实时 10:30",
    )
    row = rd.portfolio.iloc[0]
    assert row["price"] == 12.0 and row["name"] == "好公司" and abs(row["pnl_pct"] - 20) < 1e-9
    assert "盘中实时 10:30" in write_site(rd, cache, cfg, tmp_path / "site").read_text(
        encoding="utf-8"
    )
