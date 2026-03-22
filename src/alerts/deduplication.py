import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional


class DeduplicationStore:
    def __init__(self, db_path: str = "data/dedup.db", window_minutes: int = 30):
        self.db_path = db_path
        self.window_minutes = window_minutes
        self._memory_store: dict[str, list[datetime]] = defaultdict(list)
        self._lock = threading.RLock()
        self._dirty = False
        self._init_db()

    def _init_db(self):
        import os
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else "data", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS dedup_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                timestamp DATETIME NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_dedup_key_ts ON dedup_log(key, timestamp)")
        conn.commit()
        conn.close()
        self._load_from_db()

    def _load_from_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=self.window_minutes)
        c.execute("SELECT key, timestamp FROM dedup_log WHERE timestamp > ?", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))
        for key, ts_str in c.fetchall():
            self._memory_store[key].append(datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
        conn.close()

    def _save_to_db(self, key: str, timestamp: datetime):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO dedup_log (key, timestamp) VALUES (?, ?)", (key, timestamp.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

    def should_notify(self, symbol: str, signal_type: str, stage: str = "stage1") -> bool:
        key = f"{symbol}:{signal_type}:{stage}"
        with self._lock:
            cutoff = datetime.now() - timedelta(minutes=self.window_minutes)
            recent = [t for t in self._memory_store[key] if t > cutoff]
            if recent:
                return False
            now = datetime.now()
            self._memory_store[key] = recent + [now]
            self._save_to_db(key, now)
            self._dirty = True
            return True

    def cleanup(self):
        with self._lock:
            cutoff = datetime.now() - timedelta(minutes=self.window_minutes * 2)
            for key in list(self._memory_store.keys()):
                self._memory_store[key] = [t for t in self._memory_store[key] if t > cutoff]
                if not self._memory_store[key]:
                    del self._memory_store[key]
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("DELETE FROM dedup_log WHERE timestamp < ?", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))
            conn.commit()
            conn.close()

    def get_last_notification(self, symbol: str, signal_type: str, stage: str = "stage1") -> Optional[datetime]:
        key = f"{symbol}:{signal_type}:{stage}"
        with self._lock:
            times = self._memory_store.get(key, [])
            return times[-1] if times else None
