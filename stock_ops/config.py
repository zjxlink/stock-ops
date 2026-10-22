"""配置加载。优先读取 config.yaml，缺省回退到 config.example.yaml 的默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "data": {
        "db_path": "data/stock_ops.db",
        "provider_order": ["baostock", "akshare_tx", "akshare_em"],
        "request_interval": 0.3,
        "max_retries": 3,
        "fundamentals_max_age_days": 7,
    },
    "screen": {
        "fundamental": {
            "pe_ttm_max": 30,
            "pe_ttm_min": 0,
            "pb_max": 8,
            "total_mv_min": 5.0e9,
            "turnover_min": 0.5,
            "exclude_st": True,
            "min_listed_days": 250,
            "roe_min": 10,
            "yoy_ni_min": 10,
            "yoy_ni_max": 100,
            "yoy_ni_prev_min": 0,
            "liability_to_asset_max": 60,
            "growth_cap": 50,
        },
        "technical": {
            "ma_fast": 5,
            "ma_mid": 20,
            "ma_slow": 60,
            "rsi_period": 14,
            "rsi_max": 75,
            "volume_ratio_min": 1.2,
            "lookback_days": 120,
        },
    },
    "portfolio": {"trades_path": "data/trades.csv"},
    "plan": {"capital": 100000, "position_pct": 0.2, "rules": {}, "trailing_from": None},
    "market": {"index": "sh.000300", "ma": 60},
    "predict": {"path": "data/predictions.csv", "window": 60, "min_n": 40, "backfill_days": 250},
    "backtest": {
        "strategy": "donchian",
        "start": "2019-01-01",
        "initial_cash": 100000,
        "commission": 0.0003,
        "min_commission": 5,
        "stamp_duty": 0.0005,
        "slippage": 0.001,
        "stop_loss": None,
        "trailing_stop": None,
        "atr_stop": 2.0,
        "min_hold_days": 5,
        "cooldown_days": 10,
        "take_profit": None,
        "max_positions": 3,
    },
    "watchlist": [],
}


def _coerce_numbers(obj):
    """YAML 1.1 把 5.0e9 这类写法解析为字符串，这里统一转回数字。"""
    if isinstance(obj, dict):
        return {k: _coerce_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_numbers(v) for v in obj]
    if isinstance(obj, str):
        try:
            return float(obj) if any(ch in obj for ch in ".eE") else int(obj)
        except ValueError:
            return obj
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=lambda: dict(DEFAULTS))
    root: Path = field(default_factory=Path.cwd)

    @classmethod
    def load(cls, path: str | Path | None = None, root: Path | None = None) -> Config:
        root = Path(root or Path.cwd())
        candidates = [Path(path)] if path else [root / "config.yaml", root / "config.example.yaml"]
        raw = dict(DEFAULTS)
        for p in candidates:
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    raw = _deep_merge(DEFAULTS, yaml.safe_load(f) or {})
                raw["screen"] = _coerce_numbers(raw["screen"])
                raw["data"] = _coerce_numbers(raw["data"])
                raw["backtest"] = _coerce_numbers(raw.get("backtest", {}))
                raw["plan"] = _coerce_numbers(raw.get("plan", {}))
                raw["market"] = _coerce_numbers(raw.get("market", {}))
                raw["predict"] = _coerce_numbers(raw.get("predict", {}))
                break
        return cls(raw=raw, root=root)

    @property
    def db_path(self) -> Path:
        p = Path(self.raw["data"]["db_path"])
        return p if p.is_absolute() else self.root / p

    @property
    def trades_path(self) -> Path:
        p = Path(self.raw["portfolio"]["trades_path"])
        return p if p.is_absolute() else self.root / p

    @property
    def data(self) -> dict[str, Any]:
        return self.raw["data"]

    @property
    def fundamental(self) -> dict[str, Any]:
        return self.raw["screen"]["fundamental"]

    @property
    def technical(self) -> dict[str, Any]:
        return self.raw["screen"]["technical"]

    @property
    def plan(self) -> dict[str, Any]:
        return self.raw["plan"]

    def stock_rule(self, code: str) -> dict[str, Any]:
        """单只股票的计划规则覆盖：mode(rule|hold)、stop_loss、trailing_stop、note。"""
        rules = self.plan.get("rules") or {}
        return dict(rules.get(str(code).zfill(6)) or rules.get(int(code)) or {}) if rules else {}

    @property
    def predict(self) -> dict[str, Any]:
        return self.raw["predict"]

    @property
    def predictions_path(self) -> Path:
        p = Path(self.predict["path"])
        return p if p.is_absolute() else self.root / p

    @property
    def market(self) -> dict[str, Any]:
        return self.raw["market"]

    @property
    def backtest(self) -> dict[str, Any]:
        return self.raw["backtest"]

    def backtest_config(self):
        from .backtest import BacktestConfig

        b = self.backtest
        return BacktestConfig(
            initial_cash=float(b["initial_cash"]),
            commission=float(b["commission"]),
            min_commission=float(b["min_commission"]),
            stamp_duty=float(b["stamp_duty"]),
            slippage=float(b["slippage"]),
            stop_loss=b.get("stop_loss") or None,
            trailing_stop=b.get("trailing_stop") or None,
            atr_stop=b.get("atr_stop") or None,
            min_hold_days=int(b.get("min_hold_days") or 0),
            cooldown_days=int(b.get("cooldown_days") or 0),
            take_profit=b.get("take_profit") or None,
        )

    @property
    def watchlist(self) -> list[str]:
        return [str(c).zfill(6) for c in self.raw.get("watchlist") or []]
