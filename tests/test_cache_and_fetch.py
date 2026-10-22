import pandas as pd

from stock_ops.data import Cache, Fetcher
from tests.conftest import make_daily


class FailingProvider:
    name = "fail"

    def daily(self, code, start, end):
        raise ConnectionError("boom")

    def snapshot(self):
        raise ConnectionError("boom")


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def daily(self, code, start, end):
        self.calls.append((code, start, end))
        df = make_daily(code)
        return df[(df["date"] >= start) & (df["date"] <= end)]

    def snapshot(self):
        raise NotImplementedError


def test_cache_roundtrip(tmp_path):
    c = Cache(tmp_path / "t.db")
    df = make_daily("600000", n=10)
    assert c.upsert_daily(df) == 10
    assert c.upsert_daily(df) == 10  # 幂等
    back = c.daily("600000")
    assert len(back) == 10 and back["close"].iloc[-1] == df["close"].iloc[-1]
    assert c.last_date("600000") == df["date"].iloc[-1]
    assert c.latest_closes(["600000"])["600000"] == df["close"].iloc[-1]


def test_fetch_fallback_and_incremental(tmp_path):
    c = Cache(tmp_path / "t.db")
    fake = FakeProvider()
    f = Fetcher(c, providers=[FailingProvider(), fake], request_interval=0, max_retries=1)
    n1 = f.update_daily("600000", start="2025-01-01", end="2025-03-31")
    assert n1 > 0 and fake.calls[0][1] == "2025-01-01"
    n2 = f.update_daily("600000", start="2025-01-01", end="2025-06-30")
    assert n2 > 0 and fake.calls[1][1] > "2025-03-31"  # 从缓存末日之后增量
    assert len(c.daily("600000")) == n1 + n2


def test_snapshot_fallback_order(tmp_path):
    class Snap:
        def __init__(self, name, df):
            self.name, self.df = name, df

        def snapshot(self, codes=None):
            if self.df is None:
                raise ConnectionError("boom")
            return self.df

    good = pd.DataFrame(
        [
            {
                "code": "600519",
                "name": "茅台",
                "price": 1500.0,
                "pct_chg": 1.0,
                "pe_ttm": 20.0,
                "pb": 8.0,
                "total_mv": 1.9e12,
                "float_mv": 1.9e12,
                "turnover": 0.3,
                "volume": 1e6,
                "amount": 1e9,
            }
        ]
    )
    c = Cache(tmp_path / "t.db")
    f = Fetcher(
        c,
        providers=[FakeProvider()],
        snapshot_providers=[Snap("a", None), Snap("b", good)],
        request_interval=0,
        max_retries=1,
    )
    n, src = f.update_snapshot()
    assert (n, src) == (1, "b")
    assert c.snapshot().iloc[0]["name"] == "茅台"
