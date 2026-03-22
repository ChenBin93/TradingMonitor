import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class AlertEntry:
    signal_type: str
    direction: str
    severity: str
    confidence: float
    details: dict
    time: datetime


class SignalStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._signals: dict[str, AlertEntry] = {}
        self._scan_time: Optional[datetime] = None

    def update(self, alerts: list):
        with self._lock:
            self._signals.clear()
            for a in alerts:
                key = f"{a.symbol}_{a.timeframe}_{a.signal_type}_{a.direction}"
                self._signals[key] = AlertEntry(
                    signal_type=a.signal_type,
                    direction=a.direction,
                    severity=a.severity,
                    confidence=a.confidence,
                    details=a.details or {},
                    time=a.timestamp,
                )
            self._scan_time = datetime.now()

    def get_for_symbol(self, symbol: str) -> list[AlertEntry]:
        with self._lock:
            base = symbol.split(":")[0]
            prefix = base + "_"
            return [v for k, v in self._signals.items() if k.startswith(prefix)]

    def get_for_symbol_by_timeframe(self, symbol: str) -> dict[str, list[AlertEntry]]:
        with self._lock:
            base = symbol.split(":")[0]
            prefix = base + "_"
            result: dict[str, list[AlertEntry]] = {}
            for k, v in self._signals.items():
                if k.startswith(prefix):
                    tf = k.split("_")[1]
                    if tf not in result:
                        result[tf] = []
                    result[tf].append(v)
            return result

    def get_all(self) -> dict[str, AlertEntry]:
        with self._lock:
            return dict(self._signals)

    def last_scan(self) -> Optional[datetime]:
        with self._lock:
            return self._scan_time


_signal_store: Optional[SignalStore] = None
_store_lock = threading.Lock()


def get_signal_store() -> SignalStore:
    global _signal_store
    with _store_lock:
        if _signal_store is None:
            _signal_store = SignalStore()
        return _signal_store
