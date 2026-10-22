import numpy as np
import pandas as pd

from stock_ops.predict import (
    METHODS,
    PredictionLog,
    accuracy_table,
    best_methods,
    predict_latest,
    walk_forward,
)
from stock_ops.predict.models import Logit
from tests.conftest import make_daily


def test_logit_learns_separable():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 3))
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(float)
    m = Logit().fit(X, y)
    acc = np.mean([(m.proba(x) >= 0.5) == bool(t) for x, t in zip(X, y, strict=True)])
    assert acc > 0.9


def test_walk_forward_no_lookahead_and_shapes():
    df = make_daily("600000", n=400, seed=3)
    wf = walk_forward(df, last_n=100)
    assert set(wf["method"]) == set(METHODS)
    assert wf["actual"].notna().all() and (wf["backfilled"] == 1).all()
    # 每条记录的 target_date 必须是 date 的下一根K线
    dates = df["date"].tolist()
    for r in wf.itertuples():
        assert dates[dates.index(r.date) + 1] == r.target_date
    # 回填的正确性字段与真实涨跌一致
    close = df.set_index("date")["close"]
    r = wf.iloc[0]
    assert r.actual == int(close[r.target_date] > close[r.date])


def test_predict_latest_and_log_roundtrip(tmp_path):
    df = make_daily("600000", n=400, seed=3)
    latest = predict_latest(df)
    assert latest["date"].iloc[0] == df["date"].iloc[-1] and latest["actual"].isna().all()
    log = PredictionLog(tmp_path / "p.csv")
    log.append(walk_forward(df.iloc[:-1], last_n=80))  # 回填到倒数第二天
    # 倒数第二天的前瞻预测，用完整数据验证
    live = predict_latest(df.iloc[:-1])
    merged = log.append(live)
    assert (merged["backfilled"] == 0).sum() == len(live)
    verified, n = log.verify({"600000": df})
    assert n == len(live) and verified["actual"].notna().all()
    acc = accuracy_table(verified, window=60, min_n=10)
    assert {"acc", "ci_low", "baseline", "significant", "live_n"} <= set(acc.columns)
    assert (acc["n"] <= 60).all()
    assert isinstance(best_methods(acc), dict)


def test_append_keeps_live_over_backfill(tmp_path):
    log = PredictionLog(tmp_path / "p.csv")
    live = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "code": "600000",
                "method": "ma5",
                "pred": 1,
                "prob": 0.55,
                "target_date": None,
                "actual": None,
                "correct": None,
                "backfilled": 0,
            }
        ]
    )
    back = live.assign(pred=0, backfilled=1)
    log.append(live)
    merged = log.append(back)
    assert (
        len(merged) == 1
        and int(merged.iloc[0]["pred"]) == 1
        and int(merged.iloc[0]["backfilled"]) == 0
    )


def test_significance_requires_sample_and_margin():
    rows = [
        {
            "date": f"2026-01-{i % 28 + 1:02d}",
            "code": "A",
            "method": "m",
            "pred": 1,
            "prob": 0.6,
            "target_date": "x",
            "actual": 1 if i % 10 < 7 else 0,
            "correct": 1 if i % 10 < 7 else 0,
            "backfilled": 1,
        }
        for i in range(100)
    ]
    acc = accuracy_table(pd.DataFrame(rows), window=100, min_n=40)
    r = acc.iloc[0]
    assert r["acc"] == 70.0 and r["ci_low"] > 60
    # 基线（永远看涨）也是 70%，所以不算显著
    assert not r["significant"]
    small = accuracy_table(pd.DataFrame(rows[:20]), window=100, min_n=40)
    assert not small.iloc[0]["significant"]
