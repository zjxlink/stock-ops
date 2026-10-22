"""预测日志：data/predictions.csv。每天追加前瞻预测，次日用真实收盘验证，并统计滚动准确率与显著性。"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

COLUMNS = [
    "date",
    "code",
    "method",
    "pred",
    "prob",
    "target_date",
    "actual",
    "correct",
    "backfilled",
]


class PredictionLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=COLUMNS)
        df = pd.read_csv(
            self.path, dtype={"code": str, "date": str, "target_date": str, "method": str}
        )
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df["code"] = df["code"].str.zfill(6)
        for c in ("pred", "actual", "correct", "backfilled"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.reindex(columns=COLUMNS)

    def save(self, df: pd.DataFrame) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        df.reindex(columns=COLUMNS).sort_values(["code", "date", "method"]).to_csv(
            self.path, index=False, encoding="utf-8"
        )

    def append(self, new: pd.DataFrame) -> pd.DataFrame:
        """追加并按 (date, code, method) 去重，保留已有记录（前瞻记录不可被回填覆盖）。"""
        df = self.load()
        if new is None or new.empty:
            return df
        merged = pd.concat([df, new.reindex(columns=COLUMNS)], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date", "code", "method"], keep="first")
        self.save(merged)
        return merged

    def verify(self, closes_by_code: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, int]:
        """用缓存里的日K填 actual / correct。closes_by_code[code] 为 DAILY_COLUMNS 表。返回 (表, 本次验证条数)。"""
        df = self.load()
        if df.empty:
            return df, 0
        n = 0
        pending = df["actual"].isna()
        for code in df.loc[pending, "code"].unique():
            d = closes_by_code.get(code)
            if d is None or d.empty:
                continue
            d = d.sort_values("date").reset_index(drop=True)
            dates = d["date"].astype(str).tolist()
            close = d["close"].astype(float).tolist()
            pos = {dt: k for k, dt in enumerate(dates)}
            mask = pending & (df["code"] == code)
            for idx in df.index[mask]:
                k = pos.get(str(df.at[idx, "date"]))
                if k is None or k + 1 >= len(dates):
                    continue
                actual = int(close[k + 1] > close[k])
                df.at[idx, "target_date"] = dates[k + 1]
                df.at[idx, "actual"] = actual
                df.at[idx, "correct"] = int(int(df.at[idx, "pred"]) == actual)
                n += 1
        if n:
            self.save(df)
        return df, n


def _ci_low(acc: float, n: int) -> float:
    return acc - 1.96 * math.sqrt(acc * (1 - acc) / n) if n > 0 else float("nan")


def accuracy_table(df: pd.DataFrame, window: int = 60, min_n: int = 40) -> pd.DataFrame:
    """按 (code, method) 统计最近 window 条已验证预测的准确率、95% 置信下限、基线（上涨占比）与是否显著。"""
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "code",
                "method",
                "n",
                "acc",
                "ci_low",
                "baseline",
                "significant",
                "live_n",
                "live_acc",
            ]
        )
    v = df[df["correct"].notna()].sort_values("date")
    rows = []
    for (code, method), g in v.groupby(["code", "method"]):
        g = g.tail(window)
        n = len(g)
        acc = float(g["correct"].mean()) if n else float("nan")
        base = float(g["actual"].mean()) if n else float("nan")  # 永远看涨的命中率
        base = max(base, 1 - base) if n else float("nan")  # 永远看多/看空中更好的那个
        live = g[g["backfilled"] == 0]
        rows.append(
            {
                "code": code,
                "method": method,
                "n": n,
                "acc": round(acc * 100, 1),
                "ci_low": round(_ci_low(acc, n) * 100, 1),
                "baseline": round(base * 100, 1),
                "significant": bool(n >= min_n and _ci_low(acc, n) > 0.5 and acc > base),
                "live_n": len(live),
                "live_acc": round(float(live["correct"].mean()) * 100, 1)
                if len(live)
                else float("nan"),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["code", "acc"], ascending=[True, False])
        .reset_index(drop=True)
    )


def best_methods(acc: pd.DataFrame) -> dict[str, dict]:
    """每只股票准确率最高且显著的方法；没有显著的返回空。"""
    out: dict[str, dict] = {}
    if acc is None or acc.empty:
        return out
    for code, g in acc[acc["significant"]].groupby("code"):
        out[code] = g.sort_values("acc", ascending=False).iloc[0].to_dict()
    return out
