import asyncio
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd
from loguru import logger

from src.core.signal_store import get_signal_store
from src.data.cache import CacheManager, CandleData
from src.data.websocket import OKXWebSocketManager, KlineData
from src.signals.indicators import compute_all_indicators


@dataclass
class AlertFilter:
    min_confidence: float = 0.65
    silence_minutes: int = 30
    rsi_change_threshold: float = 5.0
    bb_change_threshold_pct: float = 10.0
    conf_change_threshold: float = 0.15

    def __post_init__(self):
        self._last: dict[str, dict] = {}

    def _key(self, alert: "RealtimeAlert") -> str:
        return f"{alert.symbol}_{alert.timeframe}_{alert.signal_type}_{alert.direction}"

    def _score(self, alert: "RealtimeAlert") -> float:
        conf = alert.confidence
        details = alert.details or {}

        if alert.signal_type == "bb_width_squeeze":
            bb_pct = details.get("bb_pct", 0) or 0
            if bb_pct <= 5:
                conf *= 1.15
            elif bb_pct <= 10:
                conf *= 1.05

        elif alert.signal_type == "rsi_extreme":
            rsi = details.get("rsi", 50) or 50
            dist = abs(rsi - 50) - 15
            if dist > 30:
                conf *= 1.2
            elif dist > 15:
                conf *= 1.05

        elif alert.signal_type == "ma_converge":
            mc = details.get("ma_converge", 1) or 1
            if mc <= 0.2:
                conf *= 1.15
            elif mc <= 0.35:
                conf *= 1.05

        return min(conf, 1.0)

    def _significant_change(self, key: str, alert: "RealtimeAlert") -> bool:
        if key not in self._last:
            return True
        prev = self._last[key]
        details = alert.details or {}

        if prev.get("severity") == "high" and alert.severity == "critical":
            return True

        conf_change = abs(alert.confidence - prev.get("confidence", 0))
        if conf_change >= self.conf_change_threshold:
            return True

        rsi_key = details.get("rsi")
        if rsi_key is not None and prev.get("rsi") is not None:
            if abs(rsi_key - prev["rsi"]) >= self.rsi_change_threshold:
                return True

        bb_key = details.get("bb_pct")
        if bb_key is not None and prev.get("bb_pct") is not None:
            if prev["bb_pct"] > 0:
                pct_change = abs(bb_key - prev["bb_pct"]) / prev["bb_pct"] * 100
                if pct_change >= self.bb_change_threshold_pct:
                    return True

        return False

    def _is_silent(self, key: str) -> bool:
        if key not in self._last:
            return False
        last_time = self._last[key].get("time")
        if last_time is None:
            return False
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed < self.silence_minutes * 60

    def filter(self, alerts: list["RealtimeAlert"]) -> tuple[list["RealtimeAlert"], list["RealtimeAlert"]]:
        to_push = []
        for alert in alerts:
            score = self._score(alert)
            alert.confidence = score
            if score < self.min_confidence:
                continue
            key = self._key(alert)
            if self._is_silent(key) and not self._significant_change(key, alert):
                continue
            to_push.append(alert)
            self._last[key] = {
                "confidence": alert.confidence,
                "severity": alert.severity,
                "time": datetime.now(),
                "rsi": alert.details.get("rsi") if alert.details else None,
                "bb_pct": alert.details.get("bb_pct") if alert.details else None,
            }
        return to_push, alerts


@dataclass
class RealtimeAlert:
    symbol: str
    timeframe: str
    signal_type: str
    regime: str
    direction: str
    severity: str
    confidence: float
    details: dict
    timestamp: datetime
    stage: int = 1


class RealtimeScanner:
    def __init__(self, config: dict[str, Any], history_manager=None, price_cache=None):
        self.config = config
        self.history_manager = history_manager
        self.price_cache = price_cache
        self._shutdown = False
        self._symbols: list[str] = []
        self._timeframes: list[str] = config.get("data", {}).get("timeframes", ["15m", "1h", "4h"])
        self._cache = CacheManager(max_candles=500)
        self._ws: Optional[OKXWebSocketManager] = None
        self._callbacks: list[Callable[[RealtimeAlert], None]] = []
        self._last_scan_time: dict[str, datetime] = {}
        self._scan_interval = config.get("scanner", {}).get("interval_seconds", 300)
        self._lock = threading.RLock()
        self._feishu_client = self._init_feishu()
        self._filter = AlertFilter(min_confidence=0.75, silence_minutes=30)
        self._last_report_time: datetime | None = None
        self._first_scan_done = asyncio.Event()

    def _init_feishu(self):
        feishu_cfg = self.config.get("feishu", {})
        if not feishu_cfg.get("enabled", True):
            return None
        app_id = feishu_cfg.get("app_id") or os.environ.get("FEISHU_APP_ID", "")
        app_secret = feishu_cfg.get("app_secret") or os.environ.get("FEISHU_APP_SECRET", "")
        chat_id = feishu_cfg.get("chat_id") or os.environ.get("FEISHU_CHAT_ID", "")
        if not app_id or not app_secret or not chat_id:
            logger.warning("Feishu not configured, realtime push disabled")
            return None
        from src.notification.feishu import FeishuClient
        return FeishuClient(app_id=app_id, app_secret=app_secret, chat_id=chat_id)

    def register_callback(self, callback: Callable[[RealtimeAlert], None]):
        self._callbacks.append(callback)

    def _on_kline(self, kline: KlineData):
        candle = CandleData(
            timestamp=kline.timestamp,
            open=kline.open,
            high=kline.high,
            low=kline.low,
            close=kline.close,
            volume=kline.volume,
        )
        self._cache.update(kline.symbol, kline.timeframe, candle)
        self._last_scan_time[f"{kline.symbol}_{kline.timeframe}"] = datetime.now()

    def _on_trade(self, symbol: str, price: float, volume: float, timestamp: datetime):
        if self.price_cache:
            self.price_cache.update(symbol, price, volume, timestamp)

    async def _setup_websocket(self):
        self._ws = OKXWebSocketManager(on_kline=self._on_kline, on_trade=self._on_trade)
        await self._ws.connect()
        for symbol in self._symbols:
            for tf in self._timeframes:
                self._ws.subscribe(symbol, tf)
            if self.price_cache:
                self._ws.subscribe_trades(symbol)
        logger.info(f"WebSocket subscribed: {len(self._symbols)} symbols x {len(self._timeframes)} candles + trades")

    async def start_and_wait_first_scan(self, symbols: list[str]):
        self._symbols = symbols
        self._prefill_cache(symbols)
        await self._setup_websocket()
        await asyncio.sleep(5)
        await self._perform_scan()
        self._first_scan_done.set()
        asyncio.create_task(self._scan_loop())

    async def wait_until_shutdown(self):
        while not self._shutdown:
            await asyncio.sleep(1)
        await self._cleanup()

    def _prefill_cache(self, symbols: list[str]):
        from src.data.exchange import OKXAdapter
        adapter = OKXAdapter()
        for sym in symbols:
            for tf in self._timeframes:
                candles = adapter.fetch_ohlcv(sym, tf, limit=200)
                for bar in candles:
                    candle = CandleData(
                        timestamp=bar["timestamp"],
                        open=bar["open"],
                        high=bar["high"],
                        low=bar["low"],
                        close=bar["close"],
                        volume=bar["volume"],
                    )
                    self._cache.update(sym, tf, candle)
        logger.info(f"Cache prefilled for {len(symbols)} symbols")

    async def stop(self):
        self._shutdown = True
        if self._ws:
            await self._ws.close()

    async def _cleanup(self):
        if self._ws:
            await self._ws.close()

    async def _scan_loop(self):
        while not self._shutdown:
            await asyncio.sleep(self._scan_interval)
            if self._shutdown:
                break
            try:
                await self._perform_scan()
            except Exception as e:
                logger.error(f"Scan error: {e}")

    async def _perform_scan(self):
        scan_start = datetime.now()
        logger.info(f"Realtime scan started at {scan_start}")
        alerts = []
        for symbol in self._symbols:
            for tf in self._timeframes:
                candles = self._cache.get_closed(symbol, tf)
                if len(candles) < 30:
                    continue
                df = self._candles_to_df(candles)
                params = self._get_indicator_params(tf)
                ind_data = compute_all_indicators(df, params)
                if not ind_data:
                    continue
                sigs = self._check_signals(symbol, tf, ind_data)
                for sig in sigs:
                    sig.confidence = self._score_with_history(sig, ind_data)
                alerts.extend(sigs)
        for alert in alerts:
            for callback in self._callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        # 发飞书摘要报告
        self._send_feishu_report(scan_start, alerts)
        # 写入共享信号存储，供持仓监控使用
        get_signal_store().update(alerts)
        logger.info(f"Realtime scan completed: {len(alerts)} alerts")

    def _send_feishu_report(self, scan_time: datetime, alerts: list):
        if not self._feishu_client:
            return
        if self._last_report_time:
            elapsed = (datetime.now() - self._last_report_time).total_seconds()
            if elapsed < 30:
                return
        to_push, _ = self._filter.filter(alerts)
        if not to_push:
            return
        self._last_report_time = datetime.now()
        logger.info(f"Filter: {len(alerts)} alerts -> {len(to_push)} to_push")

        time_str = scan_time.strftime("%Y-%m-%d %H:%M")
        lines = [f"📡 OKX实时监控 [{time_str}]"]

        critical = [a for a in to_push if a.severity == "critical"]
        high = [a for a in to_push if a.severity == "high"]

        if critical:
            lines.append(f"\n🔴 严重预警 ({len(critical)}):")
            for a in critical:
                lines.append(self._fmt_alert(a))
        if high:
            lines.append(f"\n🟠 高级预警 ({len(high)}):")
            for a in high:
                lines.append(self._fmt_alert(a))

        self._feishu_client.send_message("\n".join(lines))

    def _candles_to_df(self, candles: list[CandleData]) -> pd.DataFrame:
        data = [{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        } for c in candles]
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)

    def _get_indicator_params(self, timeframe: str) -> dict:
        ind_cfg = self.config.get("indicators", {})
        roc_periods = ind_cfg.get("roc_periods", {})
        return {
            "roc_period": roc_periods.get(timeframe, 10),
            "rsi_period": ind_cfg.get("rsi", {}).get("period", 14),
            "adx_period": ind_cfg.get("adx", {}).get("period", 14),
            "bb_period": ind_cfg.get("bb", {}).get("period", 20),
            "bb_std": ind_cfg.get("bb", {}).get("std", 2),
            "atr_period": ind_cfg.get("atr_period", 14),
            "volume_ma_period": ind_cfg.get("volume_ma_period", 20),
            "ma_short": ind_cfg.get("ma", {}).get("short", 5),
            "ma_mid": ind_cfg.get("ma", {}).get("mid", 20),
            "ma_long": ind_cfg.get("ma", {}).get("long", 60),
        }

    def _score_with_history(self, alert: RealtimeAlert, ind_data: dict) -> float:
        base = alert.confidence
        if not self.history_manager:
            return base

        symbol = alert.symbol
        tf = alert.timeframe
        lookback = self.config.get("data", {}).get("history", {}).get("default_lookback", 90)
        boost = 0.0

        vol_rank = self.history_manager.get_volatility_squeeze_rank(symbol, tf, lookback)

        if alert.signal_type == "bb_width_squeeze":
            if vol_rank < 20:
                boost += 0.10
            elif vol_rank < 35:
                boost += 0.05

        elif alert.signal_type == "volume_spike":
            vol_short_rank = self.history_manager.get_percentile_rank(
                symbol, tf, lookback, "volume", "short", 0
            )
            if vol_short_rank > 80:
                boost += 0.08

        elif alert.signal_type == "rsi_extreme":
            rsi = ind_data.get("rsi") or 50
            if rsi <= 25 or rsi >= 75:
                boost += 0.05

        elif alert.signal_type == "ma_converge":
            if vol_rank < 25:
                boost += 0.07

        return min(base + boost, 1.0)

    def _check_signals(self, symbol: str, tf: str, ind_data: dict) -> list[RealtimeAlert]:
        alerts = []
        adx = ind_data.get("adx")
        rsi = ind_data.get("rsi")
        bb_pct = ind_data.get("bb_width_pct")
        ma_converge = ind_data.get("ma_converge")
        macd_hist = ind_data.get("macd_hist")
        volume_ratio = ind_data.get("volume_ratio")
        regime = "trend" if (adx or 0) >= 20 else "range"
        direction = self._get_direction(ind_data)

        bb_threshold = self.config.get("indicators", {}).get("bb_width_pct_threshold", 20)
        if bb_pct and bb_pct <= bb_threshold:
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="bb_width_squeeze",
                regime=regime,
                direction=direction,
                severity="critical" if bb_pct <= 10 else "high",
                confidence=0.7,
                details={"bb_pct": bb_pct, "threshold": bb_threshold},
                timestamp=datetime.now(),
            ))
        ma_threshold = self.config.get("indicators", {}).get("ma_converge_threshold", 0.5)
        if ma_converge and ma_converge <= ma_threshold:
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="ma_converge",
                regime=regime,
                direction=direction,
                severity="critical" if ma_converge <= 0.3 else "high",
                confidence=0.6,
                details={"ma_converge": ma_converge, "threshold": ma_threshold},
                timestamp=datetime.now(),
            ))
        rsi_oversold = self.config.get("indicators", {}).get("rsi", {}).get("oversold", 35)
        rsi_overbot = self.config.get("indicators", {}).get("rsi", {}).get("overbot", 65)
        if rsi:
            if rsi <= rsi_oversold:
                alerts.append(RealtimeAlert(
                    symbol=symbol,
                    timeframe=tf,
                    signal_type="rsi_extreme",
                    regime=regime,
                    direction="long",
                    severity="critical" if rsi <= 25 else "high",
                    confidence=0.8,
                    details={"rsi": rsi, "direction": "long"},
                    timestamp=datetime.now(),
                ))
            elif rsi >= rsi_overbot:
                alerts.append(RealtimeAlert(
                    symbol=symbol,
                    timeframe=tf,
                    signal_type="rsi_extreme",
                    regime=regime,
                    direction="short",
                    severity="critical" if rsi >= 80 else "high",
                    confidence=0.8,
                    details={"rsi": rsi, "direction": "short"},
                    timestamp=datetime.now(),
                ))

        macd_cross = ind_data.get("macd_cross")
        if macd_cross:
            macd_hist = ind_data.get("macd_hist") or 0
            conf = 0.7 if abs(macd_hist) > 0.001 else 0.55
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="macd_cross",
                regime=regime,
                direction="long" if macd_cross == "golden" else "short",
                severity="critical" if abs(macd_hist) > 0.005 else "high",
                confidence=conf,
                details={"macd_cross": macd_cross, "macd_hist": macd_hist},
                timestamp=datetime.now(),
            ))

        vol_ratio = ind_data.get("volume_ratio")
        if vol_ratio and vol_ratio > 2.0:
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="volume_spike",
                regime=regime,
                direction=direction,
                severity="critical" if vol_ratio > 3.0 else "high",
                confidence=min(0.6 + (vol_ratio - 2.0) * 0.1, 0.9),
                details={"volume_ratio": vol_ratio},
                timestamp=datetime.now(),
            ))

        return alerts

    def _fmt_alert(self, a: RealtimeAlert) -> str:
        sym = a.symbol.replace("-USDT-SWAP", "/USDT")
        conf = a.confidence
        d = a.details or {}
        if a.signal_type == "rsi_extreme":
            detail = f" RSI:{d.get('rsi', 0):.0f}"
        elif a.signal_type == "bb_width_squeeze":
            detail = f" BB:{d.get('bb_pct', 0):.1f}%"
        elif a.signal_type == "ma_converge":
            detail = f" MA汇聚:{d.get('ma_converge', 0):.2f}"
        elif a.signal_type == "macd_cross":
            tag = "金叉" if d.get("macd_cross") == "golden" else "死叉"
            detail = f" MACD{tag}"
        elif a.signal_type == "volume_spike":
            detail = f" 量:{d.get('volume_ratio', 0):.1f}x"
        else:
            detail = ""
        sig_tag = {
            "bb_width_squeeze": "BB收窄",
            "ma_converge": "MA汇聚",
            "rsi_extreme": "RSI极值",
            "macd_cross": "MACD",
            "volume_spike": "量能",
        }.get(a.signal_type, a.signal_type)
        return f"  {sym}[{a.timeframe}] {sig_tag}{detail} 置信:{conf:.0%}"

    def _get_direction(self, ind_data: dict) -> str:
        plus_di = ind_data.get("plus_di", 0) or 0
        minus_di = ind_data.get("minus_di", 0) or 0
        if plus_di > minus_di:
            return "long"
        elif minus_di > plus_di:
            return "short"
        return "neutral"
