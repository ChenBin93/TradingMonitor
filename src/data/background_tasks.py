import asyncio
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

from loguru import logger


class BackgroundTask:
    def __init__(self, name: str, interval_seconds: int, task_func: Callable, auto_start: bool = True):
        self.name = name
        self.interval_seconds = interval_seconds
        self.task_func = task_func
        self.auto_start = auto_start
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._running = True
        if self.auto_start:
            await asyncio.sleep(5)
            while self._running:
                try:
                    logger.debug(f"Running background task: {self.name}")
                    await self.task_func()
                except Exception as e:
                    logger.error(f"Background task {self.name} failed: {e}")
                for _ in range(self.interval_seconds):
                    if not self._running:
                        break
                    await asyncio.sleep(1)
        logger.info(f"Background task {self.name} stopped")

    def stop(self):
        self._running = False


class BackgroundScheduler:
    def __init__(self):
        self._tasks: dict[str, BackgroundTask] = {}
        self._running = False
        self._lock = threading.Lock()

    def add_task(self, name: str, interval_seconds: int, task_func: Callable, auto_start: bool = True):
        with self._lock:
            task = BackgroundTask(name, interval_seconds, task_func, auto_start)
            self._tasks[name] = task
            logger.info(f"Added background task: {name} (interval: {interval_seconds}s)")

    def remove_task(self, name: str):
        with self._lock:
            if name in self._tasks:
                self._tasks[name].stop()
                del self._tasks[name]
                logger.info(f"Removed background task: {name}")

    async def start_all(self):
        self._running = True
        for task in list(self._tasks.values()):
            if task.auto_start:
                self._task = asyncio.create_task(task.start())
        logger.info(f"Started {len(self._tasks)} background tasks")

    async def stop_all(self):
        self._running = False
        for task in self._tasks.values():
            task.stop()
        logger.info("Stopped all background tasks")

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "tasks": {name: {"interval": t.interval_seconds, "active": t._running} for name, t in self._tasks.items()},
        }


class WeeklyRefreshManager:
    def __init__(self, db, stats_computer, config: dict[str, Any]):
        self.db = db
        self.stats_computer = stats_computer
        self.config = config
        self._last_full_refresh: Optional[datetime] = None
        self._refresh_weekday = 0

    async def check_and_refresh(self, symbols: list[str], timeframes: list[str]):
        now = datetime.now()
        if now.weekday() == self._refresh_weekday:
            if self._last_full_refresh is None or (now - self._last_full_refresh).days >= 7:
                logger.info("Weekly refresh triggered")
                await self._full_refresh(symbols, timeframes)
                self._last_full_refresh = now

    async def _full_refresh(self, symbols: list[str], timeframes: list[str]):
        from src.data.history_downloader import HistoryDownloader
        history_cfg = self.config.get("data", {}).get("history", {})
        retention_days = history_cfg.get("retention_days", {"15m": 90, "1h": 90, "4h": 365})
        self.db.cleanup_old_data(retention_days)
        self.stats_computer.compute_for_all_symbols(symbols, timeframes)
        logger.info("Weekly refresh completed")
