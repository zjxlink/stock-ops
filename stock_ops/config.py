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
    },
    "screen": {
        "fundamental": {
            "pe_ttm_max": 40,
            "pe_ttm_min": 0,
            "pb_max": 8,
            "total_mv_min": 5.0e9,
            "turnover_min": 0.5,
            "exclude_st": True,
            "min_listed_days": 250,
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
    "watchlist": [],
}


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
                break
        return cls(raw=raw, root=root)

    @property
    def db_path(self) -> Path:
        p = Path(self.raw["data"]["db_path"])
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
    def watchlist(self) -> list[str]:
        return [str(c).zfill(6) for c in self.raw.get("watchlist") or []]
