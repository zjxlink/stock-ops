"""预测方法。每种方法给出 (方向, 概率)，方向 1 为涨、0 为跌。

规则类方法无参数；logit 为 numpy 实现的逻辑回归，滚动训练（只用训练窗口内目标已知的样本），每 refit_every 天重拟合一次。
always_up 是基线：A 股单日上涨概率接近 50%，任何方法必须显著高于它才有意义。
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ..analysis.indicators import add_indicators
from ..backtest.strategies import _score
from .features import FEATURES, make_features

TRAIN_WINDOW = 500
REFIT_EVERY = 20
MIN_TRAIN = 120

Rule = Callable[[pd.Series], tuple[int, float]]


def _rule_momentum(r: pd.Series) -> tuple[int, float]:
    return (1, 0.55) if r["r1"] > 0 else (0, 0.55)


def _rule_reversal(r: pd.Series) -> tuple[int, float]:
    return (0, 0.55) if r["r1"] > 0 else (1, 0.55)


def _rule_ma5(r: pd.Series) -> tuple[int, float]:
    return (1, 0.55) if r["ma5_gap"] > 0 else (0, 0.55)


def _rule_score(r: pd.Series) -> tuple[int, float]:
    return (1, 0.55) if r["score"] > 0 else (0, 0.55)


def _rule_always_up(r: pd.Series) -> tuple[int, float]:
    return (1, 0.5)


RULES: dict[str, Rule] = {
    "momentum": _rule_momentum,
    "reversal": _rule_reversal,
    "ma5": _rule_ma5,
    "score": _rule_score,
    "always_up": _rule_always_up,
}
METHODS = [*RULES.keys(), "logit", "vote"]
VOTERS = ["momentum", "ma5", "score", "logit"]


class Logit:
    """标准化 + L2 逻辑回归，梯度下降。"""

    def __init__(self, l2: float = 1.0, iters: int = 300, lr: float = 0.1) -> None:
        self.l2, self.iters, self.lr = l2, iters, lr
        self.mu = self.sd = self.w = None
        self.b = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> Logit:
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        n, k = Z.shape
        self.w, self.b = np.zeros(k), 0.0
        for _ in range(self.iters):
            p = 1 / (1 + np.exp(-(Z @ self.w + self.b)))
            g = p - y
            self.w -= self.lr * (Z.T @ g / n + self.l2 * self.w / n)
            self.b -= self.lr * g.mean()
        return self

    def proba(self, x: np.ndarray) -> float:
        z = (x - self.mu) / self.sd
        return float(1 / (1 + np.exp(-(z @ self.w + self.b))))


def _prepare(daily: pd.DataFrame) -> pd.DataFrame:
    x = add_indicators(daily)
    x["score"] = _score(x)
    f = make_features(x)
    return f


def _logit_at(f: pd.DataFrame, i: int, model_cache: dict) -> tuple[int, float] | None:
    """用第 i 行之前目标已知的样本训练，预测第 i 行。样本不足返回 None。"""
    train = f.iloc[max(0, i - TRAIN_WINDOW) : i].dropna(subset=[*FEATURES, "target"])
    if len(train) < MIN_TRAIN:
        return None
    key = i // REFIT_EVERY
    if key not in model_cache:
        model_cache.clear()
        model_cache[key] = Logit().fit(
            train[FEATURES].to_numpy(float), train["target"].to_numpy(float)
        )
    row = f.iloc[i][FEATURES].to_numpy(float)
    if np.isnan(row).any():
        return None
    p = model_cache[key].proba(row)
    return (1 if p >= 0.5 else 0, round(max(p, 1 - p), 4))


def predict_row(f: pd.DataFrame, i: int, model_cache: dict) -> dict[str, tuple[int, float]]:
    r = f.iloc[i]
    out: dict[str, tuple[int, float]] = {}
    if r[FEATURES].isna().any():
        return out
    for name, rule in RULES.items():
        out[name] = rule(r)
    lg = _logit_at(f, i, model_cache)
    if lg is not None:
        out["logit"] = lg
    votes = [out[m][0] for m in VOTERS if m in out]
    if votes:
        up = sum(votes) / len(votes)
        out["vote"] = (1 if up >= 0.5 else 0, round(max(up, 1 - up), 4))
    return out


def walk_forward(daily: pd.DataFrame, last_n: int = 250, code: str | None = None) -> pd.DataFrame:
    """对最近 last_n 根K线逐日前瞻预测（第 i 日预测 i+1），返回含 actual 的长表。用于回填。"""
    f = _prepare(daily)
    code = code or str(f["code"].iloc[0])
    rows = []
    cache: dict = {}
    start = max(60, len(f) - last_n - 1)
    for i in range(start, len(f) - 1):  # 最后一行没有次日，留给 predict_latest
        preds = predict_row(f, i, cache)
        actual = int(f["target"].iloc[i]) if not np.isnan(f["target"].iloc[i]) else None
        for m, (d, p) in preds.items():
            rows.append(
                {
                    "date": str(f["date"].iloc[i]),
                    "code": code,
                    "method": m,
                    "pred": d,
                    "prob": p,
                    "target_date": str(f["date"].iloc[i + 1]),
                    "actual": actual,
                    "correct": (int(d == actual) if actual is not None else None),
                    "backfilled": 1,
                }
            )
    return pd.DataFrame(rows)


def predict_latest(daily: pd.DataFrame, code: str | None = None) -> pd.DataFrame:
    """用最后一根K线预测下一交易日，返回未验证的长表（actual 为空）。"""
    f = _prepare(daily)
    code = code or str(f["code"].iloc[0])
    i = len(f) - 1
    preds = predict_row(f, i, {})
    return pd.DataFrame(
        [
            {
                "date": str(f["date"].iloc[i]),
                "code": code,
                "method": m,
                "pred": d,
                "prob": p,
                "target_date": None,
                "actual": None,
                "correct": None,
                "backfilled": 0,
            }
            for m, (d, p) in preds.items()
        ]
    )
