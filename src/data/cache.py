import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class CandleData:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_dict(cls, data: dict) -> "CandleData":
        ts = data.get("timestamp")
        if isinstance(ts, int):
            ts = datetime.fromtimestamp(ts / 1000)
        elif ts is None:
            ts = datetime.now()
        return cls(
            timestamp=ts,
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            volume=float(data.get("volume", 0)),
        )


class CacheManager:
    def __init__(self, max_candles: int = 500, cleanup_interval_hours: int = 6):
        self.max_candles = max_candles
        self.cleanup_interval_hours = cleanup_interval_hours
        self._cache: dict[str, dict[str, list[CandleData]]] = defaultdict(lambda: defaultdict(list))
        self._lock = threading.RLock()
        self._last_update: dict[str, dict[str, datetime]] = defaultdict(dict)
        self._last_cleanup = datetime.now()
        self._symbol_count = 0

    def update(self, symbol: str, timeframe: str, candle: CandleData):
        with self._lock:
            if symbol not in [k for cache in self._cache.values() for k in cache.keys()]:
                self._symbol_count += 1
            candles = self._cache[symbol][timeframe]
            if candles and candles[-1].timestamp == candle.timestamp:
                candles[-1] = candle
            else:
                candles.append(candle)
                if len(candles) > self.max_candles:
                    self._cache[symbol][timeframe] = candles[-self.max_candles:]
            self._last_update[symbol][timeframe] = datetime.now()
            self._maybe_cleanup()

    def _maybe_cleanup(self):
        now = datetime.now()
        hours_since = (now - self._last_cleanup).total_seconds() / 3600
        if hours_since >= self.cleanup_interval_hours:
            self.cleanup()
            self._last_cleanup = now

    def get_latest(self, symbol: str, timeframe: str) -> Optional[CandleData]:
        with self._lock:
            candles = self._cache.get(symbol, {}).get(timeframe, [])
            return candles[-1] if candles else None

    def get_all(self, symbol: str, timeframe: str) -> list[CandleData]:
        with self._lock:
            return list(self._cache.get(symbol, {}).get(timeframe, []))

    def get_since(self, symbol: str, timeframe: str, since: datetime) -> list[CandleData]:
        with self._lock:
            candles = self._cache.get(symbol, {}).get(timeframe, [])
            return [c for c in candles if c.timestamp >= since]

    def is_stale(self, symbol: str, timeframe: str, max_age_seconds: int = 60) -> bool:
        with self._lock:
            last = self._last_update.get(symbol, {}).get(timeframe)
            if last is None:
                return True
            age = (datetime.now() - last).total_seconds()
            return age > max_age_seconds

    def cleanup(self, max_age_hours: int = 24):
        with self._lock:
            cutoff = datetime.now().timestamp() - max_age_hours * 3600
            removed_count = 0
            for symbol in list(self._cache.keys()):
                for tf in list(self._cache[symbol].keys()):
                    before = len(self._cache[symbol][tf])
                    self._cache[symbol][tf] = [
                        c for c in self._cache[symbol][tf] if c.timestamp.timestamp() > cutoff
                    ]
                    removed_count += before - len(self._cache[symbol][tf])
            return removed_count

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total_candles = sum(len(tf_list) for symbol_cache in self._cache.values() for tf_list in symbol_cache.values())
            return {
                "symbol_count": len(self._cache),
                "total_candles": total_candles,
                "last_cleanup": self._last_cleanup.isoformat(),
            }

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._last_update.clear()
            self._symbol_count = 0
