from stock_ops.analysis.fundamental import fundamental_screen


def test_screen_filters(snapshot):
    out = fundamental_screen(snapshot)
    assert list(out["code"]) == ["600001"]
    r = out.attrs["rejects"]
    assert r["st"] == 1 and r["pe_range"] == 1 and r["total_mv_min"] == 1 and r["turnover_min"] == 1
    assert out.attrs["input_count"] == 5


def test_screen_params_override(snapshot):
    out = fundamental_screen(
        snapshot, {"pe_ttm_max": 100, "pb_max": 20, "total_mv_min": 0, "turnover_min": 0}
    )
    assert len(out) == 4  # 只剔除 ST
