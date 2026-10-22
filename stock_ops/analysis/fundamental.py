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
    "roe_prev",
    "yoy_ni_prev",
    "report_date_prev",
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


def quality_score(df: pd.DataFrame, growth_cap: float = 50.0) -> pd.Series:
    """稳健成长分（0 到 1）：各项按横截面百分位排名后加权平均，缺失项记 0.5。

    - ROE（封顶 40）越高越好，权重 2
    - 净利润同比落在 [10%, growth_cap] 区间得分最高，越偏离越低（爆发式反转不加分），权重 2；上一期也为正再加分
    - ROE 两期波动越小越好（稳定性），权重 1
    - 毛利率越高越好（护城河代理），权重 1
    - 经营现金流 / 净利润（封顶 3）越高越好，权重 1
    - 资产负债率越低越好，权重 1；PE 越低越好，权重 1
    """
    comps: list[tuple[pd.Series, float]] = []

    def add(series: pd.Series, higher_better: bool, w: float):
        if series.notna().any():
            r = series.rank(pct=True)
            comps.append(((r if higher_better else 1 - r).fillna(0.5), w))

    if "roe" in df:
        add(df["roe"].clip(upper=40), True, 2)
    if "yoy_ni" in df:
        # 区间偏好：增速落在 [10%, growth_cap] 得满分，低于 10% 或高于 growth_cap 都递减；
        # 两期都超过 growth_cap 的爆发式增长（低基数 / 周期顶部）不再是优势
        g = df["yoy_ni"]
        band = pd.Series(
            np.where(g < 10, g - 10, np.where(g > growth_cap, growth_cap - g, 0.0)), index=df.index
        )
        band[g.isna()] = np.nan
        add(band, True, 2)
        if "yoy_ni_prev" in df:
            both = ((df["yoy_ni"] > 0) & (df["yoy_ni_prev"] > 0)).astype(float)
            both[df["yoy_ni_prev"].isna()] = np.nan
            add(both, True, 1)
    if "roe" in df and "roe_prev" in df:
        add((df["roe"] - df["roe_prev"]).abs(), False, 1)
    if "gp_margin" in df:
        add(df["gp_margin"], True, 1)
    if "cfo_to_np" in df:
        add(df["cfo_to_np"].clip(upper=3), True, 1)
    if "liability_to_asset" in df:
        add(df["liability_to_asset"], False, 1)
    if "pe_ttm" in df:
        add(df["pe_ttm"], False, 1)
    if not comps:
        return pd.Series(np.nan, index=df.index)
    total = sum(w for _, w in comps)
    return (sum(s * w for s, w in comps) / total).round(3)


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
        "roe_min": 10,
        "yoy_ni_min": 10,
        "yoy_ni_max": 100,
        "yoy_ni_prev_min": 0,
        "liability_to_asset_max": 60,
        "growth_cap": 50,
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
    if p.get("yoy_ni_max") is not None:
        apply("yoy_ni_max", df["yoy_ni"].isna() | (df["yoy_ni"] <= p["yoy_ni_max"]), "yoy_ni")
    if p.get("yoy_ni_prev_min") is not None:
        apply(
            "yoy_ni_prev_min",
            df["yoy_ni_prev"].isna() | (df["yoy_ni_prev"] >= p["yoy_ni_prev_min"]),
            "yoy_ni_prev",
        )
    if p.get("liability_to_asset_max") is not None:
        apply(
            "liability_max",
            df["liability_to_asset"].isna()
            | (df["liability_to_asset"] <= p["liability_to_asset_max"]),
            "liability_to_asset",
        )

    df = df.copy()
    df["quality"] = quality_score(df, growth_cap=float(p.get("growth_cap") or 50))
    out = df.sort_values(
        ["quality", "pe_ttm"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    out.attrs["rejects"] = rejects
    out.attrs["input_count"] = len(snap)
    out.attrs["skipped"] = skipped
    out.attrs["fund_coverage"] = int(df["roe"].notna().sum())
    return out
