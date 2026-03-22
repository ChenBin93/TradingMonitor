import asyncio
import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from loguru import logger

from src.data.exchange import OKXAdapter
from src.data.history_db import HistoryDB


class HistoryDownloader:
    def __init__(
        self,
        db: HistoryDB,
        config: dict[str, Any],
        batch_size: int = 50,
        download_interval: int = 60,
    ):
        self.db = db
        self.config = config
        self.batch_size = batch_size
        self.download_interval = download_interval
        self._running = False
        self._symbols = []
        self._timeframes = []
        self._lock = threading.RLock()
        self._callbacks = []

    def register_callback(self, callback: Callable):
        self._callbacks.append(callback)

    def set_symbols(self, symbols: list, timeframes: list):
        with self._lock:
            self._symbols = symbols
            self._timeframes = timeframes

    async def download_historical_data(self, symbol: str, timeframe: str, days: int = 90) -> int:
        adapter = OKXAdapter()
        candles = adapter.fetch_ohlcv(symbol, timeframe, limit=10000)
        if candles:
            self.db.save_candles(symbol, timeframe, candles)
            logger.debug(f"Downloaded {len(candles)} candles for {symbol} {timeframe} ({days}d)")
            return len(candles)
        return 0

    async def download_batch(self, batch: list[tuple[str, str]], days: int = 90):
        tasks = [self.download_historical_data(sym, tf, days) for sym, tf in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total = sum(r for r in results if isinstance(r, int))
        return total

    async def full_sync(self, days_list: list[int] = None):
        if days_list is None:
            days_list = [90, 180, 365]
        for days in days_list:
            logger.info(f"Starting full history sync ({days} days) for {len(self._symbols)} symbols")
            total_downloaded = 0
            pairs = [(s, tf) for s in self._symbols for tf in self._timeframes]
            for i in range(0, len(pairs), self.batch_size):
                batch = pairs[i:i + self.batch_size]
                count = await self.download_batch(batch, days)
                total_downloaded += count
                logger.info(f"Progress ({days}d): {min(i + self.batch_size, len(pairs))}/{len(pairs)}, downloaded: {total_downloaded}")
                if i + self.batch_size < len(pairs):
                    await asyncio.sleep(self.download_interval)
            logger.info(f"Full sync ({days}d) completed: {total_downloaded} total candles")


class HistoryStatsComputer:
    def __init__(self, db: HistoryDB, config: dict[str, Any]):
        self.db = db
        self.config = config
        self.windows = {
            "short": config.get("data", {}).get("history", {}).get("short_window", 20),
            "medium": config.get("data", {}).get("history", {}).get("medium_window", 60),
            "long": config.get("data", {}).get("history", {}).get("long_window", 240),
        }

    def _percentiles(self, arr, cuts):
        import numpy as np
        if len(arr) == 0:
            return {p: 50.0 for p in cuts}
        a = np.array(arr, dtype=float)
        return {p: float(np.percentile(a, p)) for p in cuts}

    def _summary_stats(self, arr):
        import numpy as np
        if len(arr) == 0:
            return {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
        a = np.array(arr, dtype=float)
        return {
            "min": float(np.min(a)),
            "max": float(np.max(a)),
            "mean": float(np.mean(a)),
            "std": float(np.std(a)),
        }

    def _prob_dist(self, values: list[int]) -> dict[str, float]:
        if not values:
            return {}
        total = len(values)
        counts = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return {f"p_{k}": round(counts[k] / total, 4) for k in sorted(counts)}

    def _drawdown_dist(self, drawdowns: list[float]) -> dict[str, float]:
        if not drawdowns:
            return {}
        buckets = {"<1%": 0, "1-3%": 0, "3-5%": 0, "5-10%": 0, ">10%": 0}
        total = len(drawdowns)
        for dd in drawdowns:
            pct = abs(dd) * 100
            if pct < 1:
                buckets["<1%"] += 1
            elif pct < 3:
                buckets["1-3%"] += 1
            elif pct < 5:
                buckets["3-5%"] += 1
            elif pct < 10:
                buckets["5-10%"] += 1
            else:
                buckets[">10%"] += 1
        return {k: round(v / total, 4) for k, v in buckets.items()}

    def compute_stats(self, symbol: str, timeframe: str,
                      candles: list[dict], lookback_days: int) -> dict:
        if len(candles) < 2:
            return {}
        import numpy as np

        closes = np.array([c["close"] for c in candles])
        volumes = np.array([c["volume"] for c in candles])
        returns = np.diff(closes) / closes[:-1]
        volatility = np.abs(returns)
        cum_rets = np.cumprod(1 + returns)

        peak = np.maximum.accumulate(cum_rets)
        drawdowns = (cum_rets - peak) / peak

        pct_cuts = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]

        vol_percents = self._percentiles(volatility.tolist(), pct_cuts)
        vol_summary = self._summary_stats(volatility.tolist())
        vol_mean = vol_summary["mean"]

        ret_percents = self._percentiles(returns.tolist(), pct_cuts)
        ret_summary = self._summary_stats(returns.tolist())

        bb_period = self.config.get("indicators", {}).get("bb", {}).get("period", 20)
        bb_std_mult = self.config.get("indicators", {}).get("bb", {}).get("std", 2)
        bb_widths = []
        for i in range(bb_period, len(closes)):
            bb_s = closes[i - bb_period:i]
            mid = np.mean(bb_s)
            std = np.std(bb_s)
            if mid > 0:
                bb_widths.append((2 * bb_std_mult * std) / mid * 100)

        vol_duration = float(np.sum(volatility > vol_mean) / len(volatility)) if len(volatility) > 0 else 0.0

        dd_durations = []
        in_dd = False
        dd_len = 0
        for dd in drawdowns:
            if dd < 0:
                in_dd = True
                dd_len += 1
            else:
                if in_dd and dd_len > 0:
                    dd_durations.append(dd_len)
                in_dd = False
                dd_len = 0
        if in_dd and dd_len > 0:
            dd_durations.append(dd_len)

        up_streaks = []
        down_streaks = []
        up_len = 0
        down_len = 0
        for r in returns:
            if r > 0:
                if down_len > 0:
                    down_streaks.append(down_len)
                    down_len = 0
                up_len += 1
            elif r < 0:
                if up_len > 0:
                    up_streaks.append(up_len)
                    up_len = 0
                down_len += 1
            else:
                if up_len > 0:
                    up_streaks.append(up_len)
                    up_len = 0
                if down_len > 0:
                    down_streaks.append(down_len)
                    down_len = 0
        if up_len > 0:
            up_streaks.append(up_len)
        if down_len > 0:
            down_streaks.append(down_len)

        vol_perc_short = self._percentiles(
            volatility[-self.windows["short"]:].tolist(), pct_cuts
        ) if len(volatility) >= self.windows["short"] else {p: 0.0 for p in pct_cuts}
        vol_perc_medium = self._percentiles(
            volatility[-self.windows["medium"]:].tolist(), pct_cuts
        ) if len(volatility) >= self.windows["medium"] else {p: 0.0 for p in pct_cuts}

        vol_perc_long = self._percentiles(volatility.tolist(), pct_cuts)

        volatility_stats = {
            "percentiles": vol_percents,
            "percentiles_short": vol_perc_short,
            "percentiles_medium": vol_perc_medium,
            "percentiles_long": vol_perc_long,
            "summary": vol_summary,
            "bb_width_summary": self._summary_stats(bb_widths),
        }

        volume_stats = {
            "percentiles": self._percentiles(volumes.tolist(), pct_cuts),
            "summary": self._summary_stats(volumes.tolist()),
            "volume_short_mean": float(np.mean(volumes[-self.windows["short"]:])) if len(volumes) >= self.windows["short"] else 0.0,
            "volume_medium_mean": float(np.mean(volumes[-self.windows["medium"]:])) if len(volumes) >= self.windows["medium"] else 0.0,
        }

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback_days": lookback_days,
            "volatility": volatility_stats,
            "return_stat": {
                "percentiles": ret_percents,
                "summary": ret_summary,
            },
            "volume": volume_stats,
            "drawdown": {
                "max": float(np.min(drawdowns)),
                "mean": float(np.mean(drawdowns)) if len(drawdowns) > 0 else 0.0,
                "distribution": self._drawdown_dist(drawdowns.tolist()),
                "ddd_max": max(dd_durations) if dd_durations else 0,
                "ddd_prob": self._prob_dist(dd_durations),
            },
            "streak": {
                "up": self._prob_dist(up_streaks),
                "down": self._prob_dist(down_streaks),
                "up_max": max(up_streaks) if up_streaks else 0,
                "down_max": max(down_streaks) if down_streaks else 0,
            },
        }

    def compute_for_all_symbols(self, symbols: list[str], timeframes: list[str],
                                 days_list: list[int] = None):
        if days_list is None:
            days_list = [90, 180, 365]
        logger.info(f"Computing statistics for {len(symbols)} symbols x {timeframes} x {days_list}")
        computed = 0
        for days in days_list:
            for symbol in symbols:
                for tf in timeframes:
                    since = datetime.now() - timedelta(days=days)
                    candles = self.db.get_candles(symbol, tf, since=since, limit=10000)
                    stats = self.compute_stats(symbol, tf, candles, days)
                    if stats:
                        self.db.save_stats(stats)
                        computed += 1
                        if computed % 100 == 0:
                            logger.info(f"Computed {computed} records...")
        logger.info(f"Computed {computed} statistic records")
        return computed