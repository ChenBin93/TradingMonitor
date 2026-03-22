import asyncio
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from loguru import logger


@dataclass
class ScanResult:
    scan_time: datetime
    duration_seconds: float
    symbols_processed: int
    stage1_alerts: dict
    stage2_signals: list
    snapshots_count: int


class Scanner:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._shutdown = False
        self._symbols: list[str] = []
        self._scan_count = 0

    def run(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self._run_loop()

    def _signal_handler(self, sig, frame):
        logger.info("Shutdown signal received")
        self._shutdown = True

    def _run_loop(self):
        interval = self.config.get("scanner", {}).get("interval_seconds", 300)
        while not self._shutdown:
            self.run_once()
            if self._shutdown:
                break
            logger.info(f"Sleeping {interval}s until next scan")
            for _ in range(interval):
                if self._shutdown:
                    break
                time.sleep(1)
        logger.info("Scanner loop ended")

    def run_once(self) -> ScanResult | None:
        scan_start = datetime.now()
        logger.info(f"Scan started at {scan_start}")
        try:
            symbols = self._fetch_symbols()
            if not symbols:
                logger.error("No symbols fetched, skipping scan")
                return None
            self._symbols = symbols
            data = self._fetch_all_data(symbols)
            result = self._process_scan(symbols, data, scan_start)
            self._scan_count += 1
            return result
        except Exception as e:
            logger.error(f"Scan failed: {e}")
            return None

    def _fetch_symbols(self) -> list[str]:
        from src.data.exchange import OKXAdapter
        adapter = OKXAdapter()
        top_n = self.config.get("data", {}).get("top_n", 200)
        return adapter.get_symbol_list(top_n)

    def _fetch_all_data(self, symbols: list[str]) -> dict[str, dict[str, pd.DataFrame]]:
        import time
        results = {}
        timeframes = self.config.get("data", {}).get("timeframes", ["15m", "1h", "4h"])
        for i, sym in enumerate(symbols):
            if self._shutdown:
                break
            try:
                data = self._fetch_symbol_data(sym, timeframes)
                if data:
                    results[sym] = data
                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{len(symbols)} symbols fetched")
            except Exception as e:
                logger.warning(f"Error fetching {sym}: {e}")
            # Rate limit: 1 request per 100ms = 10 req/s max
            time.sleep(0.1)
        return results

    def _fetch_symbol_data(self, symbol: str, timeframes: list[str]) -> dict[str, pd.DataFrame] | None:
        from src.data.exchange import OKXAdapter
        adapter = OKXAdapter()
        result = {}
        for tf in timeframes:
            candles = adapter.fetch_ohlcv(symbol, tf, limit=200)
            if candles:
                df = pd.DataFrame(candles)
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp").reset_index(drop=True)
                result[tf] = df
        return result if result else None

    def _process_scan(
        self, symbols: list[str], data: dict[str, dict[str, pd.DataFrame]], scan_time: datetime
    ) -> ScanResult:
        from src.signals.stage1 import Stage1Monitor
        from src.signals.stage2 import Stage2Detector
        from src.alerts.manager import AlertManager
        from src.alerts.push import PushController

        monitor = Stage1Monitor(self.config)
        stage2 = Stage2Detector(self.config)
        alert_mgr = AlertManager(self.config)

        symbols_data = {}
        all_alerts = []
        stage2_signals = []

        for sym in symbols:
            raw = data.get(sym, {})
            states = {}
            for tf, df in raw.items():
                if df is not None and len(df) >= 30:
                    ind_data = self._compute_indicators(df, tf)
                    if ind_data:
                        state = monitor.create_state(sym, tf, ind_data)
                        states[tf] = state
                        sigs = self._generate_signals(state, monitor)
                        for sig in sigs:
                            sig["stage"] = "stage1"
                            all_alerts.append(sig)
            symbols_data[sym] = states
            stage2_sig = stage2.check_trend_entry(states)
            if stage2_sig:
                stage2_sig["symbol"] = sym
                stage2_sig["stage"] = "stage2"
                stage2_signals.append(stage2_sig)
            range_sig = stage2.check_range_entry(states)
            if range_sig:
                range_sig["symbol"] = sym
                range_sig["stage"] = "stage2"
                stage2_signals.append(range_sig)

        ranking = self._compute_ranking(symbols_data)
        ranked_alerts = alert_mgr.rank_alerts(all_alerts, ranking)

        scan_end = datetime.now()
        duration = (scan_end - scan_time).total_seconds()

        # 发飞书通知
        self._send_feishu(scan_time, duration, symbols_data, ranked_alerts, stage2_signals)

        logger.info(f"Scan completed in {duration:.1f}s")
        logger.info(f"Symbols: {len(symbols_data)}, Alerts: {len(ranked_alerts)}, Signals: {len(stage2_signals)}")

        return ScanResult(
            scan_time=scan_time,
            duration_seconds=duration,
            symbols_processed=len(symbols_data),
            stage1_alerts={"all": ranked_alerts, "ranking": ranking},
            stage2_signals=stage2_signals,
            snapshots_count=len(all_alerts),
        )

    def _compute_indicators(self, df: pd.DataFrame, timeframe: str) -> dict | None:
        from src.signals.indicators import compute_all_indicators
        ind_cfg = self.config.get("indicators", {})
        roc_periods = ind_cfg.get("roc_periods", {})
        params = {
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
        return compute_all_indicators(df, params)

    def _generate_signals(self, state, monitor) -> list[dict]:
        signals = monitor.evaluate_signals(state)
        for sig in signals:
            sig["symbol"] = state.symbol
            sig["timeframe"] = state.timeframe
            sig["regime"] = state.regime
            sig["direction"] = sig.get("direction", state.direction)
            sig["roc"] = state.data.get("roc")
            sig["rsi"] = state.data.get("rsi")
            sig["adx"] = state.data.get("adx")
            sig["bb_width_pct"] = state.data.get("bb_width_pct")
            sig["volume_ratio"] = state.data.get("volume_ratio")
        return signals

    def _send_feishu(self, scan_time, duration, symbols_data, ranked_alerts, stage2_signals):
        feishu_cfg = self.config.get("feishu", {})
        if not feishu_cfg.get("enabled", True):
            return
        app_id = feishu_cfg.get("app_id") or os.environ.get("FEISHU_APP_ID", "")
        app_secret = feishu_cfg.get("app_secret") or os.environ.get("FEISHU_APP_SECRET", "")
        chat_id = feishu_cfg.get("chat_id") or os.environ.get("FEISHU_CHAT_ID", "")
        if not app_id or not app_secret or not chat_id:
            return

        from src.notification.feishu import FeishuClient
        client = FeishuClient(app_id=app_id, app_secret=app_secret, chat_id=chat_id)

        # 格式化扫描摘要
        time_str = scan_time.strftime("%Y-%m-%d %H:%M")
        top_long = [a for a in ranked_alerts if a.get("direction") == "long"][:5]
        top_short = [a for a in ranked_alerts if a.get("direction") == "short"][:5]

        lines = [
            f"📊 OKX监控扫描报告 [{time_str}]",
            f"⏱ 耗时: {duration:.1f}s | 标的: {len(symbols_data)} | 预警: {len(ranked_alerts)} | Stage2: {len(stage2_signals)}",
        ]

        if top_long:
            lines.append("\n🔼 做多机会 TOP5:")
            for a in top_long:
                sym = a.get("symbol", "").replace("-USDT-SWAP", "/USDT")
                tf = a.get("timeframe", "")
                roc = a.get("roc")
                roc_str = f"{roc:+.2f}%" if roc is not None else "N/A"
                sig = a.get("signal_type", "")
                lines.append(f"  {sym}[{tf}] ROC:{roc_str} {sig}")

        if top_short:
            lines.append("\n🔽 做空机会 TOP5:")
            for a in top_short:
                sym = a.get("symbol", "").replace("-USDT-SWAP", "/USDT")
                tf = a.get("timeframe", "")
                roc = a.get("roc")
                roc_str = f"{roc:+.2f}%" if roc is not None else "N/A"
                sig = a.get("signal_type", "")
                lines.append(f"  {sym}[{tf}] ROC:{roc_str} {sig}")

        if stage2_signals:
            lines.append("\n🟢 Stage2 入场信号:")
            for s in stage2_signals[:3]:
                sym = s.get("symbol", "").replace("-USDT-SWAP", "/USDT")
                stype = s.get("type", "")
                entry = s.get("entry_price", "")
                sl = s.get("stop_loss", "")
                tp = s.get("take_profit", "")
                rw = s.get("risk_reward", "")
                lines.append(f"  {sym} {stype} 入场:{entry} 止损:{sl} 止盈:{tp} RR:{rw}")

        client.send_message("\n".join(lines))

    def _compute_ranking(self, symbols_data: dict) -> dict:
        weights = self.config.get("alerts", {}).get("ranking", {}).get("weights", {})
        scored = []
        for sym, states in symbols_data.items():
            score_15m = 0.0
            score_1h = 0.0
            score_4h = 0.0
            for tf, state in states.items():
                if state and state.data.get("roc") is not None:
                    roc = state.data["roc"]
                    if tf == "15m":
                        score_15m = roc
                    elif tf == "1h":
                        score_1h = roc
                    elif tf == "4h":
                        score_4h = roc
            combined = (
                score_15m * weights.get("15m", 0.4)
                + score_1h * weights.get("1h", 0.3)
                + score_4h * weights.get("4h", 0.3)
            )
            scored.append((sym, combined, score_15m, score_1h, score_4h))
        scored.sort(key=lambda x: x[1], reverse=True)
        ranking = {}
        for i, (sym, combined, s15, s1h, s4h) in enumerate(scored):
            ranking[sym] = {
                "rank": i + 1,
                "combined_score": round(combined, 3),
                "roc_15m": round(s15, 2),
                "roc_1h": round(s1h, 2),
                "roc_4h": round(s4h, 2),
            }
        return ranking
