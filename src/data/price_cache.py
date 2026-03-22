import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TickPrice:
    symbol: str
    price: float
    volume: float
    timestamp: datetime
    is_buy: bool = True


class PriceCache:
    def __init__(self, max_age_seconds: int = 60):
        self.max_age_seconds = max_age_seconds
        self._prices: dict[str, TickPrice] = {}
        self._lock = threading.RLock()

    def update(self, symbol: str, price: float, volume: float = 0.0,
              timestamp: datetime | None = None, is_buy: bool = True):
        if timestamp is None:
            timestamp = datetime.now()
        with self._lock:
            self._prices[symbol] = TickPrice(
                symbol=symbol,
                price=price,
                volume=volume,
                timestamp=timestamp,
                is_buy=is_buy,
            )

    def get(self, symbol: str) -> Optional[TickPrice]:
        with self._lock:
            return self._prices.get(symbol)

    def get_price(self, symbol: str) -> Optional[float]:
        tick = self.get(symbol)
        return tick.price if tick else None

    def get_all(self) -> dict[str, TickPrice]:
        with self._lock:
            return dict(self._prices)

    def is_stale(self, symbol: str) -> bool:
        tick = self.get(symbol)
        if not tick:
            return True
        age = (datetime.now() - tick.timestamp).total_seconds()
        return age > self.max_age_seconds

    def clear(self):
        with self._lock:
            self._prices.clear()
