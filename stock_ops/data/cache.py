"""SQLite 本地缓存。分析和回测只读这里，不在分析时发网络请求。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .base import DAILY_COLUMNS, SNAPSHOT_COLUMNS, empty_daily, empty_snapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
    code TEXT NOT NULL, date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL, turnover REAL, pct_chg REAL,
    PRIMARY KEY (code, date)
);
CREATE TABLE IF NOT EXISTS snapshot (
    code TEXT PRIMARY KEY, name TEXT, price REAL, pct_chg REAL,
    pe_ttm REAL, pb REAL, total_mv REAL, float_mv REAL,
    turnover REAL, volume REAL, amount REAL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fundamentals (
    code TEXT PRIMARY KEY, report_date TEXT, pub_date TEXT,
    roe REAL, np_margin REAL, gp_margin REAL, eps_ttm REAL, yoy_ni REAL, yoy_revenue REAL, yoy_equity REAL,
    liability_to_asset REAL, current_ratio REAL, cfo_to_np REAL, cfo_to_revenue REAL,
    report_date_prev TEXT, roe_prev REAL, yoy_ni_prev REAL, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_daily_code ON daily(code);
"""


class Cache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """老库补列：fundamentals 新增的上一期字段。"""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(fundamentals)")}
        for col, typ in (
            ("report_date_prev", "TEXT"),
            ("roe_prev", "REAL"),
            ("yoy_ni_prev", "REAL"),
        ):
            if col not in have:
                self.conn.execute(f"ALTER TABLE fundamentals ADD COLUMN {col} {typ}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- daily ----
    def upsert_daily(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        rows = (
            df.reindex(columns=DAILY_COLUMNS)
            .astype(object)
            .where(pd.notna(df), None)
            .values.tolist()
        )
        self.conn.executemany(
            f"INSERT OR REPLACE INTO daily ({','.join(DAILY_COLUMNS)}) VALUES ({','.join('?' * len(DAILY_COLUMNS))})",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def daily(self, code: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        sql, params = "SELECT * FROM daily WHERE code=?", [code]
        if start:
            sql += " AND date>=?"
            params.append(start)
        if end:
            sql += " AND date<=?"
            params.append(end)
        df = pd.read_sql(sql + " ORDER BY date", self.conn, params=params)
        return df if not df.empty else empty_daily()

    def last_date(self, code: str) -> str | None:
        row = self.conn.execute("SELECT MAX(date) FROM daily WHERE code=?", (code,)).fetchone()
        return row[0] if row and row[0] else None

    def latest_closes(self, codes: list[str]) -> pd.Series:
        if not codes:
            return pd.Series(dtype=float)
        q = ",".join("?" * len(codes))
        df = pd.read_sql(
            f"SELECT code, close FROM daily d WHERE code IN ({q}) AND date=(SELECT MAX(date) FROM daily WHERE code=d.code)",
            self.conn,
            params=codes,
        )
        return df.set_index("code")["close"]

    # ---- snapshot ----
    def replace_snapshot(self, df: pd.DataFrame, updated_at: str) -> int:
        if df is None or df.empty:
            return 0
        df = df.reindex(columns=SNAPSHOT_COLUMNS).copy()
        df["updated_at"] = updated_at
        self.conn.execute("DELETE FROM snapshot")
        df.to_sql("snapshot", self.conn, if_exists="append", index=False)
        self.conn.commit()
        return len(df)

    def snapshot(self) -> pd.DataFrame:
        df = pd.read_sql("SELECT * FROM snapshot", self.conn)
        return df if not df.empty else empty_snapshot()

    # ---- fundamentals ----
    def upsert_fundamentals(self, df: pd.DataFrame) -> int:
        from .fundamentals import FUND_COLUMNS

        if df is None or df.empty:
            return 0
        d = df.reindex(columns=FUND_COLUMNS)
        rows = d.astype(object).where(pd.notna(d), None).values.tolist()
        self.conn.executemany(
            f"INSERT OR REPLACE INTO fundamentals ({','.join(FUND_COLUMNS)}) VALUES ({','.join('?' * len(FUND_COLUMNS))})",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def fundamentals(self, codes: list[str] | None = None) -> pd.DataFrame:
        if codes is not None:
            if not codes:
                return pd.DataFrame()
            q = ",".join("?" * len(codes))
            return pd.read_sql(
                f"SELECT * FROM fundamentals WHERE code IN ({q})", self.conn, params=list(codes)
            )
        return pd.read_sql("SELECT * FROM fundamentals", self.conn)

    def fundamentals_stale(self, codes: list[str], max_age_days: int, today=None) -> list[str]:
        """需要重抓的代码：缓存缺失；或还没拿到最近一个已结束季度的财报、且距上次检查已超过 max_age_days。

        已经拿到最新季报的股票在下个季度结束前不会再抓。
        """
        from .fundamentals import last_completed_quarter, quarter_end

        if not codes:
            return []
        df = self.fundamentals(codes)
        if df.empty:
            return list(codes)
        qe = quarter_end(*last_completed_quarter(today))
        now = pd.Timestamp(today) if today else pd.Timestamp.today().normalize()
        cutoff = (now - pd.Timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        has_latest = df["report_date"].astype(str) >= qe
        checked_recently = (
            df["updated_at"].astype(str) > cutoff
            if max_age_days > 0
            else pd.Series(False, index=df.index)
        )
        has_prev = (
            df["report_date_prev"].notna() & (df["report_date_prev"].astype(str) != "")
            if "report_date_prev" in df
            else pd.Series(False, index=df.index)
        )
        fresh = set(df[(has_latest & has_prev) | checked_recently]["code"])
        return [c for c in codes if c not in fresh]
