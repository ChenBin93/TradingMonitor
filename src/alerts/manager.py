import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any


class DeduplicationStore:
    def __init__(self, window_minutes: int = 30):
        self.window_minutes = window_minutes
        self._store: dict[str, list[datetime]] = defaultdict(list)
        self._lock = threading.RLock()

    def should_notify(self, symbol: str, signal_type: str, stage: str = "stage1") -> bool:
        key = f"{symbol}:{signal_type}:{stage}"
        with self._lock:
            cutoff = datetime.now() - timedelta(minutes=self.window_minutes)
            recent = [t for t in self._store[key] if t > cutoff]
            if recent:
                return False
            self._store[key] = recent + [datetime.now()]
            return True

    def cleanup(self):
        with self._lock:
            cutoff = datetime.now() - timedelta(minutes=self.window_minutes * 2)
            for key in list(self._store.keys()):
                self._store[key] = [t for t in self._store[key] if t > cutoff]
                if not self._store[key]:
                    del self._store[key]


class AlertManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        dedup_cfg = config.get("alerts", {}).get("dedup", {})
        self.dedup = DeduplicationStore(window_minutes=dedup_cfg.get("window_minutes", 30))
        self.dedup_volatile = DeduplicationStore(
            window_minutes=dedup_cfg.get("stage1_volatile_window_minutes", 60)
        )

    def should_notify(self, alert: dict) -> bool:
        symbol = alert.get("symbol", "")
        signal_type = alert.get("signal_type", "")
        stage = alert.get("stage", "stage1")
        if "squeeze" in signal_type or "consolidation" in signal_type:
            return self.dedup_volatile.should_notify(symbol, signal_type, stage)
        return self.dedup.should_notify(symbol, signal_type, stage)

    def rank_alerts(
        self, alerts: list[dict], ranking: dict[str, Any]
    ) -> list[dict]:
        weights = self.config.get("alerts", {}).get("ranking", {}).get("weights", {})
        for alert in alerts:
            sym = alert.get("symbol", "")
            rank_info = ranking.get(sym, {})
            alert["ranking"] = rank_info.get("rank", 0)
            alert["combined_score"] = rank_info.get("combined_score", 0)
        alerts.sort(
            key=lambda x: (x.get("combined_score", -999) or -999, x.get("severity") == "critical"),
            reverse=True,
        )
        return alerts
