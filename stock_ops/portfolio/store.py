"""交易流水存储：仓库内的 CSV 文件，人类可读、可 git 跟踪，本地与 GitHub Actions 共用。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUMNS = ["id", "code", "date", "side", "price", "shares", "fee", "note"]


class TradeBook:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=COLUMNS)
        df = pd.read_csv(self.path, dtype={"code": str, "note": str}, keep_default_na=False)
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df["code"] = df["code"].str.zfill(6)
        df["id"] = df["id"].astype(int)
        df["shares"] = df["shares"].astype(int)
        for c in ("price", "fee"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        return df.reindex(columns=COLUMNS)

    def _save(self, df: pd.DataFrame) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        df.reindex(columns=COLUMNS).to_csv(self.path, index=False, encoding="utf-8")

    def add(
        self,
        code: str,
        date: str,
        side: str,
        price: float,
        shares: int,
        fee: float = 0.0,
        note: str = "",
    ) -> int:
        df = self.load()
        tid = int(df["id"].max()) + 1 if not df.empty else 1
        row = pd.DataFrame([[tid, code, date, side, price, shares, fee, note]], columns=COLUMNS)
        self._save(pd.concat([df, row], ignore_index=True))
        return tid

    def delete(self, trade_id: int) -> bool:
        df = self.load()
        keep = df[df["id"] != trade_id]
        if len(keep) == len(df):
            return False
        self._save(keep)
        return True

    def codes(self) -> list[str]:
        df = self.load()
        return sorted(df["code"].unique().tolist()) if not df.empty else []
