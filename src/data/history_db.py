import json
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger


class HistoryDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()

    def init_schema(self):
        import os as _os
        _dir = _os.path.dirname(self.db_path)
        if _dir:
            _os.makedirs(_dir, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS history_candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    UNIQUE(symbol, timeframe, timestamp)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS symbol_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    lookback_days INTEGER NOT NULL,
                    computed_at DATETIME NOT NULL,
                    volatility TEXT NOT NULL DEFAULT '{}',
                    bb_width TEXT NOT NULL DEFAULT '{}',
                    return_stat TEXT NOT NULL DEFAULT '{}',
                    volume TEXT NOT NULL DEFAULT '{}',
                    drawdown TEXT NOT NULL DEFAULT '{}',
                    streak TEXT NOT NULL DEFAULT '{}'
                )
            """)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_symbol_tf_lookback "
                      "ON symbol_stats(symbol, timeframe, lookback_days)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_ts "
                      "ON history_candles(symbol, timeframe, timestamp)")
            conn.commit()
            conn.close()
        logger.info(f"History DB schema initialized at {self.db_path}")

    def save_candles(self, symbol: str, timeframe: str, candles: list[dict]):
        if not candles:
            return
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for candle in candles:
                ts = candle.get("timestamp")
                if isinstance(ts, datetime):
                    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    ts_str = ts
                c.execute("""
                    INSERT OR REPLACE INTO history_candles
                    (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol, timeframe, ts_str,
                    candle.get("open"), candle.get("high"),
                    candle.get("low"), candle.get("close"),
                    candle.get("volume")
                ))
            conn.commit()
            conn.close()

    def get_candles(self, symbol: str, timeframe: str,
                    since: datetime | None = None, limit: int = 10000) -> list[dict]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            if since:
                since_str = since.strftime("%Y-%m-%d %H:%M:%S")
                c.execute("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM history_candles
                    WHERE symbol=? AND timeframe=? AND timestamp>=?
                    ORDER BY timestamp ASC LIMIT ?
                """, (symbol, timeframe, since_str, limit))
            else:
                c.execute("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM history_candles
                    WHERE symbol=? AND timeframe=?
                    ORDER BY timestamp DESC LIMIT ?
                """, (symbol, timeframe, limit))
            rows = c.fetchall()
            conn.close()
            if not rows:
                return []
            if not since:
                rows = list(reversed(rows))
            return [
                {
                    "timestamp": datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S"),
                    "open": r[1], "high": r[2], "low": r[3],
                    "close": r[4], "volume": r[5]
                }
                for r in rows
            ]

    def save_stats(self, stats: dict):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO symbol_stats
                (symbol, timeframe, lookback_days, computed_at,
                 volatility, bb_width, return_stat, volume, drawdown, streak)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stats["symbol"], stats["timeframe"], stats["lookback_days"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps(stats.get("volatility", {})),
                json.dumps(stats.get("bb_width", {})),
                json.dumps(stats.get("return_stat", {})),
                json.dumps(stats.get("volume", {})),
                json.dumps(stats.get("drawdown", {})),
                json.dumps(stats.get("streak", {})),
            ))
            conn.commit()
            conn.close()

    def get_stats(self, symbol: str, timeframe: str,
                  lookback_days: int = 90) -> Optional[dict]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT volatility, bb_width, return_stat, volume, drawdown, streak, computed_at
                FROM symbol_stats
                WHERE symbol=? AND timeframe=? AND lookback_days=?
                ORDER BY computed_at DESC LIMIT 1
            """, (symbol, timeframe, lookback_days))
            row = c.fetchone()
            conn.close()
            if not row:
                return None
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "lookback_days": lookback_days,
                "computed_at": row["computed_at"],
                "volatility": json.loads(row["volatility"]),
                "bb_width": json.loads(row["bb_width"]),
                "return_stat": json.loads(row["return_stat"]),
                "volume": json.loads(row["volume"]),
                "drawdown": json.loads(row["drawdown"]),
                "streak": json.loads(row["streak"]),
            }

    def get_existing_symbols(self, lookback_days: int) -> set[tuple[str, str]]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT symbol, timeframe
                FROM symbol_stats
                WHERE lookback_days=?
            """, (lookback_days,))
            rows = c.fetchall()
            conn.close()
            return {(row[0], row[1]) for row in rows}

    def cleanup_old_data(self, retention_days: dict[str, int]):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for tf, days in retention_days.items():
                cutoff = datetime.now() - timedelta(days=days)
                c.execute("""
                    DELETE FROM history_candles
                    WHERE timeframe=? AND timestamp<? AND id NOT IN (
                        SELECT id FROM history_candles
                        WHERE timeframe=? AND timestamp>=?
                        ORDER BY timestamp DESC LIMIT 100
                    )
                """, (tf, cutoff.strftime("%Y-%m-%d %H:%M:%S"),
                      tf, cutoff.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()
        logger.info("History data cleanup completed")


class HistoryManager:
    def __init__(self, db: HistoryDB, default_lookback: int = 90):
        self.db = db
        self.default_lookback = default_lookback
        self._cache: dict[str, dict] = {}

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to DB format (BTC/USDT:USDT)."""
        if "/" in symbol:
            return symbol
        if symbol.endswith("-USDT-SWAP"):
            base = symbol.replace("-USDT-SWAP", "")
            return f"{base}/USDT:USDT"
        if "-" in symbol:
            base = symbol.replace("-", "/")
            return f"{base}:USDT"
        return symbol

    def get_stats(self, symbol: str, timeframe: str,
                  lookback_days: int | None = None) -> dict | None:
        symbol = self._normalize_symbol(symbol)
        if lookback_days is None:
            lookback_days = self.default_lookback
        key = f"{symbol}_{timeframe}_{lookback_days}"
        if key in self._cache:
            return self._cache[key]
        stats = self.db.get_stats(symbol, timeframe, lookback_days)
        if stats:
            self._cache[key] = stats
        return stats

    def get_percentile_rank(self, symbol: str, timeframe: str,
                           lookback_days: int | None = None,
                           category: str = "volatility",
                           window: str = "long",
                           current_value: float = 0.0) -> float:
        stats = self.get_stats(symbol, timeframe, lookback_days)
        if not stats:
            return 50.0

        cat = stats.get(category, {})
        if not cat:
            return 50.0

        if window == "short":
            percs = cat.get("percentiles_short", {})
        elif window == "medium":
            percs = cat.get("percentiles_medium", {})
        else:
            percs = cat.get("percentiles", {})

        if not percs:
            return 50.0

        p_values = sorted([k for k in percs.keys() if k not in ("current_rank",)])
        if not p_values:
            return 50.0

        p_values = [float(k) for k in p_values]
        v_values = [percs[str(int(p))] for p in p_values]
        return self._interpolate_rank(p_values, v_values, current_value)

    def _interpolate_rank(self, p_values: list, v_values: list, current: float) -> float:
        if len(p_values) != len(v_values) or len(p_values) < 2:
            return 50.0
        if current <= v_values[0]:
            return max(0.0, p_values[0])
        if current >= v_values[-1]:
            return min(100.0, p_values[-1])
        for i in range(len(v_values) - 1):
            if v_values[i] <= current <= v_values[i + 1]:
                t = (current - v_values[i]) / (v_values[i + 1] - v_values[i]) if v_values[i + 1] > v_values[i] else 0.5
                return p_values[i] + t * (p_values[i + 1] - p_values[i])
        return 50.0

    def get_streak_prob(self, symbol: str, timeframe: str,
                        lookback_days: int | None = None,
                        direction: str = "up",
                        min_length: int = 3) -> float:
        stats = self.get_stats(symbol, timeframe, lookback_days)
        if not stats:
            return 0.0
        streak = stats.get("streak", {})
        dist = streak.get(direction, {})
        prob = 0.0
        for k, v in dist.items():
            k_int = int(k.replace("p_", ""))
            if k_int >= min_length:
                prob += v
        return prob

    def get_volatility_squeeze_rank(self, symbol: str, timeframe: str,
                                    lookback_days: int | None = None) -> float:
        return self.get_percentile_rank(
            symbol, timeframe, lookback_days, "volatility", "long", 0.0
        )

    def get_bbw_percentile_rank(self, symbol: str, timeframe: str,
                               lookback_days: int | None = None,
                               current_bbw: float = 0.0) -> float:
        """BBW历史百分位排名：当前BBW在历史分布中的位置。
        排名越低 = BBW越窄 = 越压缩。"""
        stats = self.get_stats(symbol, timeframe, lookback_days)
        if not stats:
            return 50.0

        bbw = stats.get("bb_width", {})
        if not bbw:
            return 50.0

        # 使用 long window (全量数据) 的 percentiles
        percs = bbw.get("percentiles", {})
        if not percs:
            return 50.0

        p_values = sorted([float(k) for k in percs.keys() if k not in ("current_rank",)])
        if not p_values:
            return 50.0

        v_values = [percs[str(int(p))] for p in p_values]
        return self._interpolate_rank(p_values, v_values, current_bbw)

    def invalidate_cache(self):
        self._cache.clear()