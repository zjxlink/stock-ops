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
        if (year, quarter) == (2026, 2):
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
        if (year, quarter) == (2026, 1):
            return _RS(
                [[code, "2026-04-20", "2026-03-31", "0.07", "0.50", "0.90", "12.0", "25.0"]],
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
        return _RS([], ["code"])

    def query_growth_data(self, code, year, quarter):
        yoy = "0.0885" if quarter == 2 else "0.05"
        return _RS(
            [[code, "2026-08-20", "2026-06-30", "0.12", "0.10", yoy, "0.09", yoy]],
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

    assert latest_quarters(date(2026, 10, 22), 3) == [(2026, 3), (2026, 2), (2026, 1)]
    assert latest_quarters(date(2026, 1, 5), 2) == [(2025, 4), (2025, 3)]
    from stock_ops.data.fundamentals import last_completed_quarter, quarter_end

    assert quarter_end(*last_completed_quarter(date(2026, 10, 22))) == "2026-09-30"


def test_fetch_parses_and_scales():
    bf = BaostockFundamentals(_FakeProvider(), request_interval=0)
    r = bf.fetch("600519")
    assert r["code"] == "600519" and r["report_date"] == "2026-06-30"
    assert r["roe"] == 15.23 and r["yoy_ni"] == 8.85 and r["liability_to_asset"] == 16.21
    assert r["cfo_to_np"] == 1.21 and r["eps_ttm"] == 12.5
    assert (
        r["report_date_prev"] == "2026-03-31" and r["roe_prev"] == 7.0 and r["yoy_ni_prev"] == 5.0
    )
    assert set(r) == set(FUND_COLUMNS)
    df = bf.fetch_many(["600519", "000001"], time_budget_s=None)
    assert len(df) == 2


def test_cache_fundamentals_roundtrip_and_stale(tmp_path):
    c = Cache(tmp_path / "t.db")
    df = BaostockFundamentals(_FakeProvider(), request_interval=0).fetch_many(["600519"])
    assert c.upsert_fundamentals(df) == 1
    assert c.fundamentals(["600519"]).iloc[0]["roe"] == 15.23
    # 假数据财报期 2026-06-30，最近已结束季度为 2026-09-30：缺最新季报，但 7 天内检查过 -> 不重抓；000001 缺失 -> 重抓
    from datetime import date as _d

    today = _d(2026, 10, 22)
    assert c.fundamentals_stale(["600519", "000001"], max_age_days=7, today=today) == ["000001"]
    assert c.fundamentals_stale(["600519"], max_age_days=0, today=today) == ["600519"]  # 每天重查
    # 已拿到最新季报的股票不再抓
    df2 = df.assign(report_date="2026-09-30")
    c.upsert_fundamentals(df2)
    assert c.fundamentals_stale(["600519"], max_age_days=0, today=today) == []


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
        snapshot,
        {"turnover_min": 0, "total_mv_min": 0, "pe_ttm_max": 100, "pb_max": 20, "yoy_ni_min": 0},
        fund,
    )
    # 600005 因 ROE/增速/负债率不达标被剔除；600001 通过；600003/600004 无财报不因财务规则剔除
    assert "600005" not in set(out["code"]) and "600001" in set(out["code"])
    assert out.attrs["rejects"]["roe_min"] >= 1 and out.attrs["fund_coverage"] == 1
    assert "quality" in out.columns and out.iloc[0]["code"] == "600001"  # 质量分最高排第一


def test_screen_without_fundamentals_skips_rules(snapshot):
    out = fundamental_screen(snapshot, {"turnover_min": 0}, None)
    assert {"roe_min", "yoy_ni_min", "yoy_ni_prev_min", "liability_max"} <= set(
        out.attrs["skipped"]
    )
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


def test_stable_growth_prefers_consistent_over_spike():
    df = pd.DataFrame(
        {
            "roe": [18, 35, 12, 9],
            "roe_prev": [17, 5, 11, 9],
            "yoy_ni": [20, 900, 15, 12],
            "yoy_ni_prev": [18, -60, 12, 11],
            "gp_margin": [45, 15, 40, 30],
            "cfo_to_np": [1.1, 0.3, 1.0, 0.9],
            "liability_to_asset": [35, 70, 40, 50],
            "pe_ttm": [22, 8, 25, 18],
        }
    )
    q = quality_score(df)
    assert q.iloc[0] > q.iloc[1]  # 稳定成长股胜过周期反转的爆发股
    snap = pd.DataFrame(
        {
            "code": ["A", "B"],
            "name": ["a", "b"],
            "price": [1, 1],
            "pct_chg": [0, 0],
            "pe_ttm": [20, 8],
            "pb": [3, 1],
            "total_mv": [1e10, 1e10],
            "float_mv": [1e10, 1e10],
            "turnover": [1, 1],
            "volume": [1, 1],
            "amount": [1, 1],
        }
    )
    fund = pd.DataFrame(
        {
            "code": ["A", "B"],
            "roe": [18, 35],
            "yoy_ni": [20, 900],
            "yoy_ni_prev": [18, -60],
            "liability_to_asset": [35, 50],
            "report_date": ["x", "x"],
        }
    )
    out = fundamental_screen(snap, None, fund)
    assert list(out["code"]) == ["A"]  # B 本期 900% 超上限被剔除
    assert out.attrs["rejects"]["yoy_ni_max"] == 1
    out = fundamental_screen(snap, {"yoy_ni_max": None}, fund)
    assert (
        list(out["code"]) == ["A"] and out.attrs["rejects"]["yoy_ni_prev_min"] == 1
    )  # 放开上限后仍因上一期负增长被剔除


def test_cache_migration_adds_prev_columns(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE fundamentals (code TEXT PRIMARY KEY, report_date TEXT, pub_date TEXT, roe REAL, np_margin REAL, gp_margin REAL, eps_ttm REAL, yoy_ni REAL, yoy_revenue REAL, yoy_equity REAL, liability_to_asset REAL, current_ratio REAL, cfo_to_np REAL, cfo_to_revenue REAL, updated_at TEXT)"
    )
    con.execute(
        "INSERT INTO fundamentals (code, report_date, updated_at) VALUES ('600519', '2026-09-30', '2026-10-22')"
    )
    con.commit()
    con.close()
    c = Cache(db)
    cols = {r[1] for r in c.conn.execute("PRAGMA table_info(fundamentals)")}
    assert {"report_date_prev", "roe_prev", "yoy_ni_prev"} <= cols
    from datetime import date as _d

    # 有最新季报但从未抓过上一期（NULL）-> 即使 7 天内更新过也必须重抓
    assert c.fundamentals_stale(["600519"], max_age_days=7, today=_d(2026, 10, 22)) == ["600519"]
    # 抓过、公司没有上一期（空字符串）、且 7 天内检查过 -> 不重抓
    c.conn.execute("UPDATE fundamentals SET report_date_prev='' WHERE code='600519'")
    c.conn.commit()
    assert c.fundamentals_stale(["600519"], max_age_days=7, today=_d(2026, 10, 22)) == []


def test_growth_band_prefers_moderate_growth():
    df = pd.DataFrame({"yoy_ni": [25.0, 300.0, 2.0], "roe": [15, 15, 15]})
    q = quality_score(df)
    assert q.iloc[0] > q.iloc[1] and q.iloc[0] > q.iloc[2]
