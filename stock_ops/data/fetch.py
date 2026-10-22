"""抓取编排：按 provider_order 逐个尝试，失败自动切换；请求间隔 + 指数退避；增量写入缓存。"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd

from .akshare_provider import PROVIDERS as AK_PROVIDERS
from .akshare_provider import AkshareEmProvider
from .baostock_provider import BaostockProvider
from .base import DataProvider, empty_daily
from .cache import Cache
from .tencent_provider import TencentQuoteProvider

log = logging.getLogger(__name__)


def build_providers(order: list[str]) -> list[DataProvider]:
    registry = {"baostock": BaostockProvider, **AK_PROVIDERS}
    out = []
    for name in order:
        if name not in registry:
            raise ValueError(f"未知数据源: {name}")
        out.append(registry[name]())
    return out


class Fetcher:
    def __init__(
        self,
        cache: Cache,
        providers: list[DataProvider] | None = None,
        snapshot_providers: list | None = None,
        request_interval: float = 0.3,
        max_retries: int = 3,
    ) -> None:
        self.cache = cache
        self.providers = (
            providers
            if providers is not None
            else build_providers(["baostock", "akshare_tx", "akshare_em"])
        )
        # 快照源顺序：东财（快，家庭网络可用）-> 腾讯批量（数据中心可用）-> baostock 逐只（最慢最稳）
        self.snapshot_providers = (
            snapshot_providers
            if snapshot_providers is not None
            else [AkshareEmProvider(), TencentQuoteProvider(), BaostockProvider()]
        )
        self.request_interval = request_interval
        self.max_retries = max_retries
        self.snapshot_codes: list[str] | None = None  # 限定 baostock 快照范围（None 为全市场）

    def _with_retry(self, fn, *args):
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                result = fn(*args)
                time.sleep(self.request_interval)
                return result
            except NotImplementedError:
                raise
            except Exception as e:
                last = e
                wait = self.request_interval * (2**attempt)
                log.warning(
                    "请求失败 (%d/%d): %s，%.1fs 后重试", attempt + 1, self.max_retries, e, wait
                )
                time.sleep(wait)
        assert last is not None
        raise last

    def fetch_daily(self, code: str, start: str, end: str) -> tuple[pd.DataFrame, str]:
        """依次尝试各数据源，返回 (数据, 来源名)。全部失败抛出最后一个异常。"""
        last: Exception | None = None
        for p in self.providers:
            try:
                df = self._with_retry(p.daily, code, start, end)
                return df, p.name
            except NotImplementedError:
                continue
            except Exception as e:
                last = e
                log.warning("数据源 %s 失败，切换下一个: %s", p.name, e)
        raise RuntimeError(f"所有数据源均失败: {last}")

    def update_daily(self, code: str, start: str = "2018-01-01", end: str | None = None) -> int:
        """增量更新：从缓存最后日期的下一天开始抓，写入缓存，返回新增行数。"""
        end = end or date.today().isoformat()
        last = self.cache.last_date(code)
        if last:
            start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        if start > end:
            return 0
        df, source = self.fetch_daily(code, start, end)
        n = self.cache.upsert_daily(df)
        log.info("%s 更新 %d 行 (来源 %s)", code, n, source)
        return n

    def update_many(self, codes: list[str], start: str = "2018-01-01") -> dict[str, int]:
        result: dict[str, int] = {}
        for c in codes:
            try:
                result[c] = self.update_daily(c, start=start)
            except Exception as e:
                log.error("%s 更新失败: %s", c, e)
                result[c] = -1
        return result

    def update_snapshot(self) -> tuple[int, str]:
        """按 snapshot_providers 顺序尝试，返回 (只数, 来源)。snapshot_codes 可限定范围（东财始终全市场）。"""
        last: Exception | None = None
        for p in self.snapshot_providers:
            try:
                if isinstance(p, AkshareEmProvider):
                    df = self._with_retry(p.snapshot)
                else:
                    df = self._with_retry(p.snapshot, self.snapshot_codes)
                if df is None or df.empty:
                    raise RuntimeError("返回空快照")
                n = self.cache.replace_snapshot(
                    df, updated_at=pd.Timestamp.now().isoformat(timespec="seconds")
                )
                return n, p.name
            except Exception as e:
                last = e
                log.warning("快照源 %s 失败，切换下一个: %s", p.name, e)
        raise RuntimeError(f"所有快照源均失败: {last}")


def update_fundamentals(
    cache: Cache,
    codes: list[str],
    max_age_days: int = 7,
    time_budget_s: float | None = None,
    today=None,
) -> int:
    """抓取缓存缺失或过期的基本面并写入，返回写入条数。"""
    from .fundamentals import BaostockFundamentals

    stale = cache.fundamentals_stale(codes, max_age_days)
    if not stale:
        return 0
    bf = BaostockFundamentals()
    try:
        df = bf.fetch_many(
            stale,
            today=today,
            time_budget_s=time_budget_s,
            progress=lambda i, n: log.info("基本面 %d/%d", i, n),
        )
    finally:
        bf.close()
    return cache.upsert_fundamentals(df)


__all__ = ["Fetcher", "build_providers", "empty_daily", "update_fundamentals"]
