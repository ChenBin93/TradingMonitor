from dataclasses import dataclass
from typing import Any


@dataclass
class SymbolStats:
    symbol: str
    timeframe: str

    volatility_percentile_short: float = 0.0
    volatility_percentile_medium: float = 0.0
    volatility_percentile_long: float = 0.0

    return_percentile_short: float = 0.0
    return_percentile_medium: float = 0.0
    return_percentile_long: float = 0.0

    volume_percentile_short: float = 0.0
    volume_percentile_medium: float = 0.0
    volume_percentile_long: float = 0.0

    bb_width_mean: float = 0.0
    bb_width_std: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "volatility_short": self.volatility_percentile_short,
            "volatility_medium": self.volatility_percentile_medium,
            "volatility_long": self.volatility_percentile_long,
            "return_short": self.return_percentile_short,
            "return_medium": self.return_percentile_medium,
            "return_long": self.return_percentile_long,
            "volume_short": self.volume_percentile_short,
            "volume_medium": self.volume_percentile_medium,
            "volume_long": self.volume_percentile_long,
            "bb_width_mean": self.bb_width_mean,
            "bb_width_std": self.bb_width_std,
        }


class HistoryManager:
    def __init__(
        self,
        db_path: str,
        short_window: int = 20,
        medium_window: int = 60,
        long_window: int = 240,
    ):
        self.db_path = db_path
        self.short_window = short_window
        self.medium_window = medium_window
        self.long_window = long_window
        self._stats_cache: dict[str, SymbolStats] = {}

    def compute_stats(self, candles: list[dict]) -> SymbolStats | None:
        if len(candles) < self.long_window:
            return None
        import numpy as np
        closes = np.array([c["close"] for c in candles])
        volumes = np.array([c["volume"] for c in candles])

        returns = np.diff(closes) / closes[:-1]
        volatility = np.abs(returns)

        def percentile(arr: np.ndarray, value: float) -> float:
            if len(arr) == 0:
                return 50.0
            return float(np.sum(arr < value) / len(arr) * 100)

        stats = SymbolStats(symbol="", timeframe="")
        stats.volatility_percentile_short = percentile(
            volatility[-self.short_window :], volatility[-1]
        )
        stats.volatility_percentile_medium = percentile(
            volatility[-self.medium_window :], volatility[-1]
        )
        stats.volatility_percentile_long = percentile(volatility, volatility[-1])

        cum_returns = np.cumprod(1 + returns)
        if len(cum_returns) >= self.short_window:
            stats.return_percentile_short = percentile(
                cum_returns[-self.short_window :], cum_returns[-1]
            )
        if len(cum_returns) >= self.medium_window:
            stats.return_percentile_medium = percentile(
                cum_returns[-self.medium_window :], cum_returns[-1]
            )

        stats.volume_percentile_short = percentile(
            volumes[-self.short_window :], volumes[-1]
        )
        stats.volume_percentile_medium = percentile(
            volumes[-self.medium_window :], volumes[-1]
        )

        return stats

    def get_stats(self, symbol: str, timeframe: str) -> SymbolStats | None:
        key = f"{symbol}_{timeframe}"
        if key in self._stats_cache:
            return self._stats_cache[key]
        return None

    def update_stats(self, stats: SymbolStats):
        key = f"{stats.symbol}_{stats.timeframe}"
        self._stats_cache[key] = stats
