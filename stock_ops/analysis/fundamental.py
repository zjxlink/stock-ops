"""基本面硬过滤与质量排序。输入为 SNAPSHOT_COLUMNS 的全市场快照，可选合并季度财务指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FUND_FIELDS = [
    "roe",
    "np_margin",
    "gp_margin",
    "yoy_ni",
    "liability_to_asset",
    "cfo_to_np",
    "eps_ttm",
    "report_date",
]


def merge_fundamentals(snap: pd.DataFrame, fund: pd.DataFrame | None) -> pd.DataFrame:
    """把财务指标按 code 合并进快照；缺失的列补 NaN。"""
    out = snap.copy()
    if fund is not None and not fund.empty:
        cols = [c for c in FUND_FIELDS if c in fund.columns]
        out = out.merge(fund[["code", *cols]], on="code", how="left")
    for c in FUND_FIELDS:
        if c not in out.columns:
            out[c] = np.nan
    return out


def quality_score(df: pd.DataFrame) -> pd.Series:
    """质量综合分：ROE、净利润增速、经营现金流/净利润 越高越好，PE、负债率 越低越好。

    各项按横截面百分位排名后等权平均；某项缺失记 0.5（中性），因此没有财报的个股不会仅凭低 PE 排到前面。
    """
    parts = []
    for col, higher_better in (
        ("roe", True),
        ("yoy_ni", True),
        ("cfo_to_np", True),
        ("pe_ttm", False),
        ("liability_to_asset", False),
    ):
        if col in df.columns and df[col].notna().any():
            r = df[col].rank(pct=True)
            parts.append((r if higher_better else 1 - r).fillna(0.5))
    if not parts:
        return pd.Series(np.nan, index=df.index)
    return pd.concat(parts, axis=1).mean(axis=1).round(3)


def fundamental_screen(
    snap: pd.DataFrame, params: dict[str, Any] | None = None, fund: pd.DataFrame | None = None
) -> pd.DataFrame:
    """按估值、市值、换手、ST 以及财务规则过滤，按质量分降序；attrs 里记录剔除统计与因数据缺失而跳过的规则。"""
    p = {
        "pe_ttm_max": 40,
        "pe_ttm_min": 0,
        "pb_max": 8,
        "total_mv_min": 5.0e9,
        "turnover_min": 0.5,
        "exclude_st": True,
        "roe_min": 8,
        "yoy_ni_min": 0,
        "liability_to_asset_max": 70,
    }
    p.update(params or {})
    if snap is None or snap.empty:
        return pd.DataFrame(columns=snap.columns if snap is not None else [])

    df = merge_fundamentals(snap, fund)
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
    # 财务规则：字段为 NaN 的个股不剔除（财报缺失不等于不合格），只剔除明确不达标的
    if p.get("roe_min") is not None:
        apply("roe_min", df["roe"].isna() | (df["roe"] >= p["roe_min"]), "roe")
    if p.get("yoy_ni_min") is not None:
        apply("yoy_ni_min", df["yoy_ni"].isna() | (df["yoy_ni"] >= p["yoy_ni_min"]), "yoy_ni")
    if p.get("liability_to_asset_max") is not None:
        apply(
            "liability_max",
            df["liability_to_asset"].isna()
            | (df["liability_to_asset"] <= p["liability_to_asset_max"]),
            "liability_to_asset",
        )

    df = df.copy()
    df["quality"] = quality_score(df)
    out = df.sort_values(
        ["quality", "pe_ttm"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    out.attrs["rejects"] = rejects
    out.attrs["input_count"] = len(snap)
    out.attrs["skipped"] = skipped
    out.attrs["fund_coverage"] = int(df["roe"].notna().sum())
    return out
