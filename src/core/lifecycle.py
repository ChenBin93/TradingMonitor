from datetime import datetime
from typing import Any

from loguru import logger


class LifecycleManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._started_at: datetime | None = None
        self._scan_count = 0
        self._error_count = 0

    def on_start(self):
        self._started_at = datetime.now()
        logger.info(f"System started at {self._started_at}")

    def on_scan_start(self):
        pass

    def on_scan_end(self, duration: float, symbols: int, alerts: int):
        self._scan_count += 1
        logger.info(f"Scan #{self._scan_count} completed: {duration:.1f}s, {symbols} symbols, {alerts} alerts")

    def on_error(self, error: Exception):
        self._error_count += 1
        logger.error(f"Error #{self._error_count}: {error}")

    def on_stop(self):
        if self._started_at:
            uptime = datetime.now() - self._started_at
            logger.info(f"System stopped. Uptime: {uptime}, Scans: {self._scan_count}, Errors: {self._error_count}")

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._started_at is not None,
            "started_at": self._started_at,
            "scan_count": self._scan_count,
            "error_count": self._error_count,
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds() if self._started_at else 0,
        }
