import pandas as pd
import pytest

from stock_ops.portfolio import portfolio_summary, positions_from_trades


def _trades(rows):
    return pd.DataFrame(rows, columns=["id", "code", "date", "side", "price", "shares", "fee"])


def test_weighted_average_cost_and_realized():
    book = positions_from_trades(
        _trades(
            [
                (1, "600519", "2026-01-05", "buy", 100.0, 100, 5),
                (2, "600519", "2026-01-10", "buy", 120.0, 100, 5),
                (3, "600519", "2026-02-01", "sell", 130.0, 100, 5),
            ]
        )
    )
    p = book["600519"]
    assert p.shares == 100
    assert p.avg_cost == pytest.approx(110.05)
    assert p.realized_pnl == pytest.approx(130 * 100 - 5 - 110.05 * 100)


def test_oversell_raises():
    with pytest.raises(ValueError):
        positions_from_trades(_trades([(1, "000001", "2026-01-01", "sell", 10, 100, 0)]))


def test_summary_weights():
    book = positions_from_trades(
        _trades(
            [
                (1, "A", "2026-01-01", "buy", 10, 100, 0),
                (2, "B", "2026-01-01", "buy", 20, 100, 0),
            ]
        )
    )
    s = portfolio_summary(book, {"A": 12.0, "B": 20.0}).set_index("code")
    assert s.loc["A", "pnl_pct"] == pytest.approx(20)
    assert s.loc["A", "weight_pct"] + s.loc["B", "weight_pct"] == pytest.approx(100)
