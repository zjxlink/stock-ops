"""基本面硬过滤。输入为 SNAPSHOT_COLUMNS 的全市场快照。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fundamental_screen(snap: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """按估值、市值、换手、ST 规则过滤，返回通过的子集并附带 reject 原因统计在 attrs 中。"""
    p = {
        "pe_ttm_max": 40,
        "pe_ttm_min": 0,
        "pb_max": 8,
        "total_mv_min": 5.0e9,
        "turnover_min": 0.5,
        "exclude_st": True,
    }
    p.update(params or {})
    if snap is None or snap.empty:
        return pd.DataFrame(columns=snap.columns if snap is not None else [])

    df = snap.copy()
    rejects: dict[str, int] = {}

    skipped: list[str] = []

    def apply(name: str, mask: pd.Series, col: str | None = None):
        nonlocal df
        if col is not None and df[col].isna().all():
            skipped.append(name)  # 数据源不提供该字段时跳过，而不是全部剔除
            return
        mask = mask.fillna(False).astype(bool)
        rejects[name] = int((~mask).sum())
        df = df[mask]

    if p["exclude_st"] and "name" in df:
        apply("st", ~df["name"].astype(str).str.contains("ST|退", regex=True))
    apply(
        "pe_range", (df["pe_ttm"] > p["pe_ttm_min"]) & (df["pe_ttm"] <= p["pe_ttm_max"]), "pe_ttm"
    )
    apply("pb_max", (df["pb"] > 0) & (df["pb"] <= p["pb_max"]), "pb")
    apply("total_mv_min", df["total_mv"] >= p["total_mv_min"], "total_mv")
    apply("turnover_min", df["turnover"] >= p["turnover_min"], "turnover")

    out = df.sort_values("pe_ttm").reset_index(drop=True)
    out.attrs["rejects"] = rejects
    out.attrs["input_count"] = len(snap)
    out.attrs["skipped"] = skipped
    return out
