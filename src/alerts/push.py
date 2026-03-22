import threading
from datetime import datetime
from typing import Any, Callable, Optional

from loguru import logger


class PushController:
    def __init__(self, config: dict[str, Any], notifier: Optional[Callable[[str], None]] = None):
        self.config = config
        self.notifier = notifier
        self._queue: list[dict] = []
        self._lock = threading.RLock()
        self._min_confidence = config.get("alerts", {}).get("push", {}).get("min_confidence_threshold", 0.6)
        self._channels: list[str] = ["feishu"]
        self._last_push_time: dict[str, datetime] = {}

    def set_notifier(self, notifier: Callable[[str], None]):
        self.notifier = notifier

    def add_channel(self, channel: str):
        self._channels.append(channel)

    def remove_channel(self, channel: str):
        if channel in self._channels:
            self._channels.remove(channel)

    def enqueue(self, alert: dict[str, Any]):
        confidence = alert.get("confidence", 0.5)
        alert["_enqueued_at"] = datetime.now()
        if confidence >= self._min_confidence:
            with self._lock:
                self._queue.append(alert)
            logger.debug(f"Alert enqueued: {alert.get('symbol')} confidence={confidence:.2f}")

    def should_push(self, alert: dict[str, Any]) -> bool:
        confidence = alert.get("confidence", 0.0)
        if confidence < self._min_confidence:
            return False
        stage = alert.get("stage", "stage1")
        feishu_cfg = self.config.get("feishu", {})
        if stage == "stage1" and not feishu_cfg.get("stage1_enabled", True):
            return False
        if stage == "stage2" and not feishu_cfg.get("stage2_enabled", True):
            return False
        if self._in_silent_hours():
            return False
        return True

    def _in_silent_hours(self) -> bool:
        silent_hours = self.config.get("feishu", {}).get("silent_hours", [])
        if not silent_hours:
            return False
        now = datetime.now()
        hour, minute = now.hour, now.minute
        current_mins = hour * 60 + minute
        for start_h, start_m, end_h, end_m in silent_hours:
            start = start_h * 60 + start_m
            end = end_h * 60 + end_m
            if start <= end:
                if start <= current_mins <= end:
                    return True
            else:
                if current_mins >= start or current_mins <= end:
                    return True
        return False

    def flush(self) -> list[str]:
        messages = []
        with self._lock:
            queue = self._queue[:]
            self._queue.clear()
        for alert in queue:
            if self.should_push(alert):
                msg = self._format_message(alert)
                messages.append(msg)
                if self.notifier:
                    try:
                        self.notifier(msg)
                    except Exception as e:
                        logger.error(f"Notification failed: {e}")
        return messages

    def push_immediately(self, alert: dict[str, Any]) -> Optional[str]:
        if self.should_push(alert):
            msg = self._format_message(alert)
            if self.notifier:
                try:
                    self.notifier(msg)
                except Exception as e:
                    logger.error(f"Immediate notification failed: {e}")
            return msg
        return None

    def _format_message(self, alert: dict) -> str:
        stage = alert.get("stage", "stage1")
        symbol = alert.get("symbol", "")
        regime = alert.get("regime", "unknown")
        direction = alert.get("direction", "neutral")
        confidence = alert.get("confidence", 0.0)
        regime_cn = "趋势" if regime == "trend" else "震荡"
        direction_cn = "做多" if direction == "long" else "做空"
        timestamp = alert.get("_enqueued_at", datetime.now()).strftime("%H:%M")
        if stage == "stage1":
            sig_type = alert.get("signal_type", "")
            severity = alert.get("severity", "medium")
            emoji = "🔴" if severity == "critical" else "🟠" if severity == "high" else "🟡"
            tf = alert.get("timeframe", "")
            rsi = alert.get("rsi")
            adx = alert.get("adx")
            roc = alert.get("roc")
            details = alert.get("details", {})
            lines = [
                f"{emoji} [Stage1预警] {symbol}[{tf}] | {regime_cn} | {direction_cn} | {sig_type}",
                f"  ROC: {roc:+.2f}% | RSI: {rsi:.1f} | ADX: {adx:.1f}" if rsi and adx else "",
                f"  置信度: {confidence:.0%} | {timestamp}",
            ]
            return "\n".join(filter(None, lines))
        else:
            sig_type = alert.get("type", alert.get("signal_type", ""))
            entry = alert.get("entry_price")
            sl = alert.get("stop_loss")
            tp = alert.get("take_profit")
            rw = alert.get("risk_reward", 0)
            adx = alert.get("adx_15m", 0)
            rsi = alert.get("rsi")
            lines = [
                f"🟢 [Stage2入场] {symbol} | {sig_type}",
                f"  入场: {entry} | 止损: {sl} | 止盈: {tp}",
                f"  风险回报比: {rw:.1f}:1 | ADX: {adx:.1f} | RSI: {rsi:.1f}" if rsi else "",
                f"  置信度: {confidence:.0%} | {timestamp}",
            ]
            return "\n".join(filter(None, lines))


class EventDrivenPush:
    def __init__(self, push_controller: PushController, deduplication: Any):
        self.push = push_controller
        self.dedup = deduplication

    def on_signal(self, signal: dict):
        symbol = signal.get("symbol", "")
        signal_type = signal.get("signal_type", "")
        stage = signal.get("stage", "stage1")
        if self.dedup.should_notify(symbol, signal_type, stage):
            self.push.enqueue(signal)

    def on_trade_signal(self, signal: dict):
        self.push.push_immediately(signal)
