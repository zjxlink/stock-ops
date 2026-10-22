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
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL, date TEXT NOT NULL, side TEXT NOT NULL,
    price REAL NOT NULL, shares INTEGER NOT NULL, fee REAL DEFAULT 0,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_daily_code ON daily(code);
"""


class Cache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(_SCHEMA)

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

    # ---- trades ----
    def add_trade(
        self,
        code: str,
        date: str,
        side: str,
        price: float,
        shares: int,
        fee: float = 0,
        note: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO trades (code,date,side,price,shares,fee,note) VALUES (?,?,?,?,?,?,?)",
            (code, date, side, price, shares, fee, note),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def trades(self, code: str | None = None) -> pd.DataFrame:
        if code:
            return pd.read_sql(
                "SELECT * FROM trades WHERE code=? ORDER BY date,id", self.conn, params=[code]
            )
        return pd.read_sql("SELECT * FROM trades ORDER BY date,id", self.conn)

    def delete_trade(self, trade_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
        self.conn.commit()
        return cur.rowcount > 0
