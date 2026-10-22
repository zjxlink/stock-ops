from typer.testing import CliRunner

from stock_ops.cli import app
from stock_ops.data import Cache
from tests.conftest import make_daily

runner = CliRunner()


def test_cli_trade_portfolio_signals_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    (tmp_path / "config.yaml").write_text(
        "data:\n  db_path: db.sqlite\nwatchlist: ['600000']\n", encoding="utf-8"
    )
    Cache(tmp_path / "db.sqlite").upsert_daily(make_daily("600000"))

    r = runner.invoke(app, ["trade", "add", "600000", "buy", "10", "100", "--date", "2025-06-01"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["portfolio"])
    assert r.exit_code == 0 and "600000" in r.output
    r = runner.invoke(app, ["signals"])
    assert r.exit_code == 0 and "600000" in r.output
    r = runner.invoke(app, ["report", "--out", "rep"])
    assert r.exit_code == 0 and (tmp_path / "rep").glob("*.md")
