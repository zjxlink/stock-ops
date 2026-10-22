from pathlib import Path

from stock_ops.analysis import fundamental_screen
from stock_ops.config import Config

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_numbers_are_numeric_and_screen_runs(snapshot):
    cfg = Config.load(ROOT / "config.example.yaml", root=ROOT)
    assert isinstance(cfg.fundamental["total_mv_min"], float)
    assert isinstance(cfg.technical["ma_fast"], int)
    out = fundamental_screen(snapshot, cfg.fundamental)
    assert list(out["code"]) == ["600001"]


def test_yaml_string_exponent_is_coerced(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("screen:\n  fundamental:\n    total_mv_min: 5.0e9\n", encoding="utf-8")
    cfg = Config.load(p, root=tmp_path)
    assert cfg.fundamental["total_mv_min"] == 5.0e9
    assert cfg.watchlist == []


def test_stock_rule_lookup(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        'plan:\n  rules:\n    "300458":\n      mode: hold\n      trailing_stop: 0.2\n',
        encoding="utf-8",
    )
    cfg = Config.load(p, root=tmp_path)
    assert cfg.stock_rule("300458") == {"mode": "hold", "trailing_stop": 0.2}
    assert cfg.stock_rule("600519") == {}
    bc = cfg.backtest_config()
    assert (
        bc.atr_stop == 3.0
        and bc.trailing_stop is None
        and bc.min_hold_days == 5
        and cfg.market["index"] == "sh.000300"
    )
