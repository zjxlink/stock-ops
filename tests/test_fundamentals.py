import pandas as pd

from stock_ops.analysis.fundamental import fundamental_screen, merge_fundamentals, quality_score
from stock_ops.data import Cache
from stock_ops.data.fundamentals import FUND_COLUMNS, BaostockFundamentals, latest_quarters


class _RS:
    def __init__(self, rows, fields):
        self.error_code, self.error_msg, self.fields = "0", "", fields
        self._rows, self._i = rows, -1

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self):
        return self._rows[self._i]


class _FakeBs:
    def query_profit_data(self, code, year, quarter):
        if (year, quarter) != (2026, 2):
            return _RS([], ["code"])
        return _RS(
            [[code, "2026-08-20", "2026-06-30", "0.1523", "0.52", "0.91", "12.5", "55.2"]],
            [
                "code",
                "pubDate",
                "statDate",
                "roeAvg",
                "npMargin",
                "gpMargin",
                "epsTTM",
                "MBRevenue",
            ],
        )

    def query_growth_data(self, code, year, quarter):
        return _RS(
            [[code, "2026-08-20", "2026-06-30", "0.12", "0.10", "0.0885", "0.09", "0.0885"]],
            [
                "code",
                "pubDate",
                "statDate",
                "YOYEquity",
                "YOYAsset",
                "YOYNI",
                "YOYEPSBasic",
                "YOYPNI",
            ],
        )

    def query_balance_data(self, code, year, quarter):
        return _RS(
            [[code, "2026-08-20", "2026-06-30", "4.1", "3.9", "2.0", "0.05", "0.1621", "1.19"]],
            [
                "code",
                "pubDate",
                "statDate",
                "currentRatio",
                "quickRatio",
                "cashRatio",
                "YOYLiability",
                "liabilityToAsset",
                "assetToEquity",
            ],
        )

    def query_cash_flow_data(self, code, year, quarter):
        return _RS(
            [[code, "2026-08-20", "2026-06-30", "0.3", "0.7", "0.2", "", "0.55", "1.21", "0.5"]],
            [
                "code",
                "pubDate",
                "statDate",
                "CAToAsset",
                "NCAToAsset",
                "tangibleAssetToAsset",
                "ebitToInterest",
                "CFOToOR",
                "CFOToNP",
                "CFOToGr",
            ],
        )


class _FakeProvider:
    def _ensure_login(self):
        return _FakeBs()

    def close(self):
        pass


def test_latest_quarters():
    from datetime import date

    assert latest_quarters(date(2026, 10, 22), 3) == [(2026, 4), (2026, 3), (2026, 2)]


def test_fetch_parses_and_scales():
    bf = BaostockFundamentals(_FakeProvider(), request_interval=0)
    r = bf.fetch("600519")
    assert r["code"] == "600519" and r["report_date"] == "2026-06-30"
    assert r["roe"] == 15.23 and r["yoy_ni"] == 8.85 and r["liability_to_asset"] == 16.21
    assert r["cfo_to_np"] == 1.21 and r["eps_ttm"] == 12.5
    assert set(r) == set(FUND_COLUMNS)
    df = bf.fetch_many(["600519", "000001"], time_budget_s=None)
    assert len(df) == 2


def test_cache_fundamentals_roundtrip_and_stale(tmp_path):
    c = Cache(tmp_path / "t.db")
    df = BaostockFundamentals(_FakeProvider(), request_interval=0).fetch_many(["600519"])
    assert c.upsert_fundamentals(df) == 1
    assert c.fundamentals(["600519"]).iloc[0]["roe"] == 15.23
    assert c.fundamentals_stale(["600519", "000001"], max_age_days=7) == ["000001"]
    assert c.fundamentals_stale(["600519"], max_age_days=-1) == ["600519"]  # 立即过期


def test_screen_with_fundamentals(snapshot):
    fund = pd.DataFrame(
        [
            {
                "code": "600001",
                "roe": 15.0,
                "yoy_ni": 10.0,
                "liability_to_asset": 40.0,
                "cfo_to_np": 1.1,
                "report_date": "2026-06-30",
            },
            {
                "code": "600005",
                "roe": 3.0,
                "yoy_ni": -20.0,
                "liability_to_asset": 85.0,
                "cfo_to_np": 0.2,
                "report_date": "2026-06-30",
            },
        ]
    )
    out = fundamental_screen(
        snapshot, {"turnover_min": 0, "total_mv_min": 0, "pe_ttm_max": 100, "pb_max": 20}, fund
    )
    # 600005 因 ROE/增速/负债率不达标被剔除；600001 通过；600003/600004 无财报不因财务规则剔除
    assert "600005" not in set(out["code"]) and "600001" in set(out["code"])
    assert out.attrs["rejects"]["roe_min"] >= 1 and out.attrs["fund_coverage"] == 1
    assert "quality" in out.columns and out.iloc[0]["code"] == "600001"  # 质量分最高排第一


def test_screen_without_fundamentals_skips_rules(snapshot):
    out = fundamental_screen(snapshot, {"turnover_min": 0}, None)
    assert {"roe_min", "yoy_ni_min", "liability_max"} <= set(out.attrs["skipped"])
    assert out["quality"].notna().any()


def test_quality_score_direction():
    df = pd.DataFrame(
        {
            "roe": [20, 5, 10, 1, 8, 12],
            "yoy_ni": [30, -5, 10, -20, 0, 5],
            "cfo_to_np": [1.5, 0.2, 1, 0.1, 0.8, 1.2],
            "pe_ttm": [10, 50, 20, 80, 30, 15],
            "liability_to_asset": [30, 80, 50, 90, 60, 40],
        }
    )
    q = quality_score(df)
    assert q.iloc[0] == q.max() and q.iloc[3] == q.min()
    m = merge_fundamentals(pd.DataFrame({"code": ["A"]}), None)
    assert "roe" in m.columns and m["roe"].isna().all()
