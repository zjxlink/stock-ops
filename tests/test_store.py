from stock_ops.portfolio import TradeBook


def test_tradebook_roundtrip(tmp_path):
    tb = TradeBook(tmp_path / "t.csv")
    assert tb.load().empty and tb.codes() == []
    a = tb.add("600519", "2026-01-01", "buy", 100.0, 100, 5, "首仓")
    b = tb.add("000001", "2026-01-02", "sell", 10.5, 200)
    assert (a, b) == (1, 2)
    df = tb.load()
    assert list(df["code"]) == ["600519", "000001"] and df.iloc[0]["note"] == "首仓"
    assert tb.codes() == ["000001", "600519"]
    assert tb.delete(1) and not tb.delete(99)
    assert list(tb.load()["id"]) == [2]
    assert tb.add("000002", "2026-01-03", "buy", 1, 1) == 3  # id 不复用
