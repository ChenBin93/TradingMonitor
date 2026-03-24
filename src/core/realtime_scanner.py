import asyncio
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from src.core.realtime_scanner import RealtimeAlert

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
class SymbolRanking:
    symbol: str
    timeframe: str
    direction: str
    regime: str
    score: float
    confidence: float
    signal_types: list[str]
    momentum_score: float
    compression_score: float
    volume_score: float
    history_score: float
    details: dict


class SymbolRanker:
    WEIGHTS = {
        "signal_strength": 0.25,
        "momentum": 0.20,
        "compression": 0.20,
        "volume": 0.15,
        "history": 0.10,
        "relative_strength": 0.10,
    }

    def __init__(self, history_manager=None, config: dict | None = None):
        self.history_manager = history_manager
        self.config = config or {}
        self._btc_symbols: set[str] = set()

    def rank_symbols(
        self, alerts: "list[RealtimeAlert]", ind_data_map: dict
    ) -> tuple:
        symbol_scores: dict[str, dict] = {}

        for alert in alerts:
            sym = alert.symbol
            tf = alert.timeframe
            if sym not in symbol_scores:
                symbol_scores[sym] = {
                    "direction": alert.direction,
                    "regime": alert.regime,
                    "timeframe": tf,
                    "signals": [],
                    "max_confidence": 0,
                    "max_severity": "low",
                    "momentum_score": 0,
                    "compression_score": 0,
                    "volume_score": 0,
                    "history_score": 0,
                    "details": {},
                }
            score = symbol_scores[sym]
            score["signals"].append(alert.signal_type)
            score["max_confidence"] = max(score["max_confidence"], alert.confidence)
            severity_order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
            if severity_order.get(alert.severity, 0) > severity_order.get(score["max_severity"], 0):
                score["max_severity"] = alert.severity
                score["timeframe"] = tf
            ind_data = ind_data_map.get(sym, {})
            self._update_dimension_scores(score, alert, ind_data)

        rankings = []
        for sym, score in symbol_scores.items():
            if not score["signals"]:
                continue
            total = self._calculate_total_score(score)
            rankings.append(
                SymbolRanking(
                    symbol=sym,
                    timeframe=score.get("timeframe", "15m"),
                    direction=score["direction"],
                    regime=score["regime"],
                    score=total,
                    confidence=score["max_confidence"],
                    signal_types=score["signals"],
                    momentum_score=score["momentum_score"],
                    compression_score=score["compression_score"],
                    volume_score=score["volume_score"],
                    history_score=score["history_score"],
                    details=score["details"],
                )
            )

        rankings.sort(key=lambda x: x.score, reverse=True)
        trending = [r for r in rankings if r.regime == "trend"][:5]
        consolidating = [r for r in rankings if r.regime == "range"][:5]

        if len(trending) < 5:
            trending = rankings[: 5 - len(trending) + len(trending)]
        if len(consolidating) < 5:
            consolidating = [r for r in rankings if r not in trending][:5]

        return trending, consolidating

    def _update_dimension_scores(self, score: dict, alert: "RealtimeAlert", ind_data: dict):
        d = alert.details or {}
        self._btc_symbols.add("BTC/USDT")

        if alert.signal_type in ("bb_width_squeeze", "ttm_squeeze"):
            bb_rank = d.get("bbw_rank", 50)
            if isinstance(bb_rank, (int, float)) and bb_rank > 0:
                score["compression_score"] = max(score["compression_score"], (100 - bb_rank) / 100)
                score["details"]["bb_rank"] = bb_rank

        if alert.signal_type in ("volume_spike", "volume_breakout"):
            vol_ratio = d.get("volume_ratio", d.get("vol_ratio", 1))
            score["volume_score"] = max(score["volume_score"], min(vol_ratio / 3, 1))
            score["details"]["vol_ratio"] = vol_ratio

        if alert.signal_type in ("rsi_divergence", "macd_divergence"):
            dist = d.get("price_distance_pct", 0)
            score["compression_score"] = max(score["compression_score"], min(dist / 5, 1) * 0.8)

        rsi = ind_data.get("rsi")
        if rsi:
            rsi_score = abs(rsi - 50) / 50
            score["details"]["rsi"] = rsi

        adx = ind_data.get("adx")
        if adx:
            adx_score = min(adx / 40, 1)
            score["momentum_score"] = max(score["momentum_score"], adx_score)
            score["details"]["adx"] = adx

        roc = ind_data.get("roc")
        if roc:
            roc_score = min(abs(roc) / 3, 1)
            score["momentum_score"] = max(score["momentum_score"], roc_score * 0.7)
            score["details"]["roc"] = roc

    def _calculate_total_score(self, score: dict) -> float:
        signal_count = len(score["signals"])
        signal_boost = min(signal_count * 0.05, 0.15)

        severity_scores = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.3}
        severity_score = severity_scores.get(score["max_severity"], 0.3)

        return (
            score["max_confidence"] * self.WEIGHTS["signal_strength"]
            + score["momentum_score"] * self.WEIGHTS["momentum"]
            + score["compression_score"] * self.WEIGHTS["compression"]
            + score["volume_score"] * self.WEIGHTS["volume"]
            + score["history_score"] * self.WEIGHTS["history"]
            + severity_score * signal_boost
        )


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
        self._filter = AlertFilter(min_confidence=0.85, silence_minutes=30)
        self._ranker = SymbolRanker(history_manager=history_manager, config=config)
        self._last_report_time: datetime | None = None
        self._last_ranking_time: datetime | None = None
        self._ranking_interval = config.get("scanner", {}).get("ranking_interval_minutes", 5) * 60
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
        ind_data_map: dict[str, dict] = {}
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
                ind_data_map[symbol] = ind_data
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

        # TOP5 标的排序推荐
        self._send_ranking_report(scan_start, alerts, ind_data_map)

    def _send_feishu_report(self, scan_time: datetime, alerts: list):
        if not self._feishu_client:
            return
        if self._last_report_time:
            elapsed = (datetime.now() - self._last_report_time).total_seconds()
            if elapsed < 30:
                return
        
        # Deduplicate: keep only highest confidence per symbol/timeframe/direction
        deduped = self._deduplicate_alerts(alerts)
        to_push, _ = self._filter.filter(deduped)
        
        if not to_push:
            return
        self._last_report_time = datetime.now()
        logger.info(f"Filter: {len(alerts)} alerts -> {len(to_push)} to_push")

        time_str = scan_time.strftime("%Y-%m-%d %H:%M")
        lines = [f"[信号预警] {time_str}"]

        critical = [a for a in to_push if a.severity == "critical"]
        high = [a for a in to_push if a.severity == "high"]

        if critical:
            lines.append(f"\n【强烈信号】({len(critical)}个)")
            for a in critical:
                lines.append(self._fmt_alert(a))
        if high:
            lines.append(f"\n【准备信号】({len(high)}个)")
            for a in high:
                lines.append(self._fmt_alert(a))

        self._feishu_client.send_message("\n".join(lines))

    def _deduplicate_alerts(self, alerts: list) -> list:
        """Remove conflicting signals: keep highest confidence per symbol/timeframe."""
        grouped = {}
        for a in alerts:
            key = f"{a.symbol}_{a.timeframe}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(a)
        
        result = []
        for key, group in grouped.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                # Multiple alerts for same symbol/timeframe
                # Keep only the one with highest confidence
                best = max(group, key=lambda x: x.confidence)
                result.append(best)
        return result

    def _send_ranking_report(self, scan_time: datetime, alerts: list, ind_data_map: dict):
        if not self._feishu_client:
            return
        if self._last_ranking_time:
            elapsed = (datetime.now() - self._last_ranking_time).total_seconds()
            if elapsed < self._ranking_interval:
                return
        if not alerts:
            return

        self._last_ranking_time = datetime.now()
        trending, consolidating = self._ranker.rank_symbols(alerts, ind_data_map)

        if not trending and not consolidating:
            return

        time_str = scan_time.strftime("%Y-%m-%d %H:%M")
        lines = [f"\n[TOP5推荐] {time_str}"]

        if trending:
            lines.append("\n【趋势市场】TOP5:")
            for i, r in enumerate(trending, 1):
                dir_text = "做多" if r.direction == "long" else "做空"
                sig_tags = "/".join([self._get_signal_tag(s) for s in r.signal_types[:3]])
                reason = self._get_ranking_reason(r)
                lines.append(f"{i}. {self._fmt_symbol(r.symbol)}[{r.timeframe}] {dir_text} {r.score:.0%}")
                lines.append(f"   理由:{reason}")
                lines.append(f"   信号:{sig_tags} 置信:{r.confidence:.0%}")

        if consolidating:
            lines.append("\n【震荡市场】TOP5:")
            for i, r in enumerate(consolidating, 1):
                dir_text = "做多" if r.direction == "long" else "做空"
                sig_tags = "/".join([self._get_signal_tag(s) for s in r.signal_types[:3]])
                reason = self._get_ranking_reason(r)
                lines.append(f"{i}. {self._fmt_symbol(r.symbol)}[{r.timeframe}] {dir_text} {r.score:.0%}")
                lines.append(f"   理由:{reason}")
                lines.append(f"   信号:{sig_tags} 置信:{r.confidence:.0%}")

        self._feishu_client.send_message("\n".join(lines))
        logger.info(f"Ranking sent: {len(trending)} trending, {len(consolidating)} consolidating")

    def _fmt_symbol(self, symbol: str) -> str:
        return symbol.replace("-USDT-SWAP", "/USDT").replace("USDT:USDT", "")

    def _get_signal_tag(self, sig_type: str) -> str:
        tags = {
            "bb_width_squeeze": "BB",
            "ma_converge": "MA",
            "rsi_extreme": "RSI",
            "macd_cross": "MACD",
            "volume_spike": "VOL",
            "ttm_squeeze": "TTM",
            "rsi_divergence": "RSI背",
            "macd_divergence": "MACD背",
            "volume_breakout": "突破",
        }
        return tags.get(sig_type, sig_type[:4])

    def _score_bar(self, score: float) -> str:
        filled = int(score * 10)
        return "█" * filled + "░" * (10 - filled)

    def _get_ranking_reason(self, r) -> str:
        parts = []
        if r.momentum_score > 0.6:
            parts.append("动量强")
        if r.compression_score > 0.6:
            parts.append("蓄力中")
        if r.volume_score > 0.6:
            parts.append("量能足")
        if r.confidence > 0.8:
            parts.append("信号强")
        if len(r.signal_types) >= 2:
            parts.append("多信号")
        return "/".join(parts) if parts else "综合评估"

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

        if alert.signal_type == "bb_width_squeeze":
            bb_width_val = ind_data.get("bb_width") or 0
            bbw_rank = self.history_manager.get_bbw_percentile_rank(symbol, tf, lookback, bb_width_val)
            if bbw_rank <= 10:
                boost += 0.15
            elif bbw_rank <= 20:
                boost += 0.10
            elif bbw_rank <= 30:
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
            vol_rank = self.history_manager.get_volatility_squeeze_rank(symbol, tf, lookback)
            if vol_rank < 25:
                boost += 0.07

        elif alert.signal_type == "ttm_squeeze":
            details = alert.details or {}
            squeeze_bars = details.get("squeeze_bars", 0)
            is_fired = details.get("is_fired", False)
            if is_fired:
                boost += 0.15
            elif squeeze_bars >= 8:
                boost += 0.12
            elif squeeze_bars >= 5:
                boost += 0.08

        elif alert.signal_type == "rsi_divergence":
            details = alert.details or {}
            price_dist = details.get("price_distance_pct", 0)
            if price_dist >= 5:
                boost += 0.15
            elif price_dist >= 3:
                boost += 0.10

        elif alert.signal_type == "macd_divergence":
            details = alert.details or {}
            price_dist = details.get("price_distance_pct", 0)
            if price_dist >= 5:
                boost += 0.12
            elif price_dist >= 3:
                boost += 0.08

        elif alert.signal_type == "volume_breakout":
            details = alert.details or {}
            vol_ratio = details.get("vol_ratio", 0)
            if vol_ratio >= 3:
                boost += 0.12
            elif vol_ratio >= 2:
                boost += 0.08

        return min(base + boost, 1.0)

    def _check_signals(self, symbol: str, tf: str, ind_data: dict) -> list[RealtimeAlert]:
        alerts = []
        adx = ind_data.get("adx")
        rsi = ind_data.get("rsi")
        bb_pct = ind_data.get("bb_width_pct")
        bb_actual = ind_data.get("bb_width")
        ma_converge = ind_data.get("ma_converge")
        macd_hist = ind_data.get("macd_hist")
        volume_ratio = ind_data.get("volume_ratio")
        regime = "trend" if (adx or 0) >= 20 else "range"
        direction = self._get_direction(ind_data)

        bb_threshold_pct_rank = self.config.get("indicators", {}).get("bb_width_pct_rank_threshold", 25)
        if bb_actual and bb_pct and self.history_manager:
            lookback = self.config.get("data", {}).get("history", {}).get("default_lookback", 90)
            bbw_rank = self.history_manager.get_bbw_percentile_rank(symbol, tf, lookback, bb_actual)
            if bbw_rank <= bb_threshold_pct_rank:
                alerts.append(RealtimeAlert(
                    symbol=symbol,
                    timeframe=tf,
                    signal_type="bb_width_squeeze",
                    regime=regime,
                    direction=direction,
                    severity="critical" if bbw_rank <= 10 else "high",
                    confidence=0.7,
                    details={
                        "bb_pct": bb_pct,
                        "bb_width": bb_actual,
                        "bbw_rank": bbw_rank,
                        "threshold_rank": bb_threshold_pct_rank,
                    },
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
        rsi_oversold = self.config.get("indicators", {}).get("rsi", {}).get("oversold", 30)
        rsi_overbot = self.config.get("indicators", {}).get("rsi", {}).get("overbot", 70)
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

        ttm_squeeze = ind_data.get("ttm_squeeze")
        if ttm_squeeze:
            squeeze_bars = ttm_squeeze.get("squeeze_bars", 0)
            is_fired = ttm_squeeze.get("is_fired", False)
            squeeze_dir = ttm_squeeze.get("direction")
            if squeeze_bars >= 3 or is_fired:
                conf = 0.75 if is_fired else 0.65
                alerts.append(RealtimeAlert(
                    symbol=symbol,
                    timeframe=tf,
                    signal_type="ttm_squeeze",
                    regime=regime,
                    direction=squeeze_dir or direction,
                    severity="critical" if squeeze_bars >= 8 or is_fired else "high",
                    confidence=conf,
                    details={
                        "squeeze_bars": squeeze_bars,
                        "is_fired": is_fired,
                        "direction": squeeze_dir,
                    },
                    timestamp=datetime.now(),
                ))

        rsi_div = ind_data.get("rsi_divergence")
        if rsi_div and rsi_div.get("divergence"):
            div = rsi_div.get("divergence")
            price_dist = rsi_div.get("price_distance_pct", 0)
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="rsi_divergence",
                regime=regime,
                direction="long" if div == "bullish" else "short",
                severity="critical" if price_dist >= 5 else "high",
                confidence=0.8,
                details={
                    "divergence": div,
                    "rsi_value": rsi_div.get("rsi_value"),
                    "price_distance_pct": price_dist,
                },
                timestamp=datetime.now(),
            ))

        macd_div = ind_data.get("macd_divergence")
        if macd_div and macd_div.get("divergence"):
            div = macd_div.get("divergence")
            price_dist = macd_div.get("price_distance_pct", 0)
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="macd_divergence",
                regime=regime,
                direction="long" if div == "bullish" else "short",
                severity="critical" if price_dist >= 5 else "high",
                confidence=0.75,
                details={
                    "divergence": div,
                    "macd_value": macd_div.get("macd_value"),
                    "price_distance_pct": price_dist,
                },
                timestamp=datetime.now(),
            ))

        vol_breakout = ind_data.get("volume_breakout")
        if vol_breakout and vol_breakout.get("confirmed"):
            vol_ratio_break = vol_breakout.get("vol_ratio", 0)
            price_chg = vol_breakout.get("price_change_pct", 0)
            alerts.append(RealtimeAlert(
                symbol=symbol,
                timeframe=tf,
                signal_type="volume_breakout",
                regime=regime,
                direction=direction,
                severity="critical" if vol_ratio_break >= 3 else "high",
                confidence=min(0.7 + (vol_ratio_break - 1.5) * 0.15, 0.95),
                details={
                    "vol_ratio": vol_ratio_break,
                    "price_change_pct": price_chg,
                    "is_expansion": vol_breakout.get("is_expansion"),
                },
                timestamp=datetime.now(),
            ))

        return alerts

    def _fmt_alert(self, a: RealtimeAlert) -> str:
        sym = a.symbol.replace("-USDT-SWAP", "/USDT")
        conf = a.confidence
        d = a.details or {}

        dir_text = "做多" if a.direction == "long" else "做空" if a.direction == "short" else "观望"
        regime_text = "趋势" if a.regime == "trend" else "震荡"

        sig_name = self._get_signal_name(a.signal_type)
        evidence = self._get_evidence(a)

        hist_bar = self._get_histogram(a)

        lines = [
            f"{sym}[{a.timeframe}] {dir_text} {sig_name}",
            f"------------------",
            f"方向: {dir_text} | 状态: {regime_text}市场",
            f"信号: {evidence}",
            f"历史: {hist_bar}",
            f"置信: {conf:.0%}",
        ]
        return "\n  ".join(lines)

    def _get_signal_name(self, sig_type: str) -> str:
        names = {
            "bb_width_squeeze": "BB压缩",
            "ma_converge": "MA汇聚",
            "rsi_extreme": "RSI极值",
            "macd_cross": "MACD交叉",
            "volume_spike": "量能爆发",
            "ttm_squeeze": "TTM压缩",
            "rsi_divergence": "RSI背离",
            "macd_divergence": "MACD背离",
            "volume_breakout": "量价突破",
        }
        return names.get(sig_type, sig_type)

    def _get_evidence(self, a: RealtimeAlert) -> str:
        d = a.details or {}
        parts = []

        if a.signal_type == "bb_width_squeeze":
            rank = d.get("bbw_rank", 0)
            parts.append(f"压缩位{int(rank)}%")
        elif a.signal_type == "rsi_extreme":
            rsi = d.get("rsi", 50)
            parts.append(f"RSI={rsi:.0f}")
        elif a.signal_type == "macd_cross":
            tag = "金叉" if d.get("macd_cross") == "golden" else "死叉"
            parts.append(f"MACD{tag}")
        elif a.signal_type == "volume_spike":
            vol = d.get("volume_ratio", 0)
            parts.append(f"量{vol:.1f}x")
        elif a.signal_type == "ttm_squeeze":
            bars = d.get("squeeze_bars", 0)
            fired = d.get("is_fired", False)
            parts.append(f"压缩{bars}根{'【释放】' if fired else ''}")
        elif a.signal_type == "rsi_divergence":
            div = d.get("divergence", "")
            price_dist = d.get("price_distance_pct", 0)
            parts.append(f"{'底背离' if div == 'bullish' else '顶背离'} {price_dist:.1f}%")
        elif a.signal_type == "macd_divergence":
            div = d.get("divergence", "")
            price_dist = d.get("price_distance_pct", 0)
            parts.append(f"{'底背离' if div == 'bullish' else '顶背离'} {price_dist:.1f}%")
        elif a.signal_type == "volume_breakout":
            vol = d.get("vol_ratio", 0)
            price_chg = d.get("price_change_pct", 0)
            parts.append(f"量{vol:.1f}x | 涨跌{price_chg:.1f}%")

        return " | ".join(parts) if parts else "综合信号"

    def _get_histogram(self, a: RealtimeAlert) -> str:
        d = a.details or {}

        if a.signal_type == "bb_width_squeeze":
            rank = d.get("bbw_rank", 50)
            bar = "█" * int(rank // 5) + "░" * (20 - int(rank // 5))
            label = "极度压缩" if rank <= 10 else "高度压缩" if rank <= 20 else "中度压缩"
            return f"BB {rank:.0f}% {bar} [{label}]"
        elif a.signal_type == "volume_spike":
            vol = d.get("volume_ratio", 1)
            bar = "█" * min(int(vol), 10) + "░" * (10 - min(int(vol), 10))
            return f"量 {vol:.1f}x {bar}"
        elif a.signal_type == "rsi_divergence" or a.signal_type == "macd_divergence":
            dist = d.get("price_distance_pct", 0)
            bar = "█" * min(int(dist // 2), 10) + "░" * (10 - min(int(dist // 2), 10))
            return f"背离 {dist:.1f}% {bar}"
        elif a.signal_type == "ttm_squeeze":
            bars = d.get("squeeze_bars", 0)
            bar = "█" * min(int(bars), 10) + "░" * (10 - min(int(bars), 10))
            return f"TTM {bars}根 {bar}"
        else:
            return ""

    def _get_direction(self, ind_data: dict) -> str:
        plus_di = ind_data.get("plus_di", 0) or 0
        minus_di = ind_data.get("minus_di", 0) or 0
        if plus_di > minus_di:
            return "long"
        elif minus_di > plus_di:
            return "short"
        return "neutral"
