import hashlib
import hmac
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.notification.feishu import FeishuClient


@dataclass
class Position:
    symbol: str
    side: str
    size: float
    entry_price: float
    current_price: float
    pnl_pct: float
    pnl_abs: float
    inst_id: str
    open_time: datetime | None = None


@dataclass
class PositionAlert:
    kind: str
    symbol: str
    side: str
    details: str
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0
    signal_type: str = ""
    signal_direction: str = ""
    matched_signal: str = ""


class PositionMonitor:
    def __init__(self, config: dict):
        self.config = config
        self._shutdown = False
        self._lock = threading.Lock()
        self._last_positions: dict[str, Position] = {}
        self._last_alert_time: dict[str, datetime] = {}
        self._feishu = self._init_feishu()
        self._interval = config.get("position_alert", {}).get("interval_seconds", 60)
        self._pnl_loss = config.get("position_alert", {}).get("pnl_loss_pct", 5.0)
        self._pnl_profit = config.get("position_alert", {}).get("pnl_profit_pct", 10.0)
        self._creds = config.get("okx_credentials", {})
        self._testnet = self._creds.get("testnet", False)
        self._active = bool(self._creds.get("api_key"))
        self._silence_seconds = 600
        self._max_position_hours = config.get("position_alert", {}).get("max_position_hours", 4)

    def _init_feishu(self) -> Optional[FeishuClient]:
        cfg = self.config.get("feishu_position", {})
        if not cfg.get("enabled", True):
            return None
        app_id = cfg.get("app_id", "")
        app_secret = cfg.get("app_secret", "")
        chat_id = cfg.get("chat_id", "")
        if not app_id or not app_secret or not chat_id:
            return None
        return FeishuClient(app_id=app_id, app_secret=app_secret, chat_id=chat_id)

    def _is_silent(self, key: str) -> bool:
        last = self._last_alert_time.get(key)
        if last is None:
            return False
        return (datetime.now() - last).total_seconds() < self._silence_seconds

    def _set_alerted(self, key: str):
        self._last_alert_time[key] = datetime.now()

    def _sign(self, ts: str, method: str, path: str) -> str:
        msg = f"{ts}{method}{path}"
        mac = hmac.new(
            self._creds["api_secret"].encode("utf-8"),
            msg.encode("utf-8"),
            hashlib.sha256,
        )
        return __import__("base64").b64encode(mac.digest()).decode()

    def _fetch_positions(self) -> list[dict]:
        import base64
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        path = "/api/v5/account/positions"
        sig = self._sign(ts, "GET", path)
        base_url = "https://www.okx.com"
        if self._testnet:
            base_url = "https://www.okx.com"

        result = subprocess.run(
            [
                "curl", "-s", "-X", "GET",
                f"{base_url}{path}",
                "-H", f"OK-ACCESS-KEY: {self._creds['api_key']}",
                "-H", f"OK-ACCESS-SIGN: {sig}",
                "-H", f"OK-ACCESS-TIMESTAMP: {ts}",
                "-H", f"OK-ACCESS-PASSPHRASE: {self._creds['passphrase']}",
                "-H", "Content-Type: application/json",
                "-H", "Accept: application/json",
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        if data.get("code") != "0":
            return []
        return data.get("data", [])

    def fetch_positions(self) -> list[Position]:
        if not self._active:
            return []
        try:
            raw = self._fetch_positions()
            positions = []
            for pos in raw:
                inst_id = pos.get("instId", "")
                if not inst_id or not inst_id.endswith("-SWAP"):
                    continue
                pos_sz = float(pos.get("pos", 0) or 0)
                if abs(pos_sz) <= 0:
                    continue
                avg_px = float(pos.get("avgPx", 0) or 0)
                last_px = float(pos.get("last", 0) or 0)
                if avg_px <= 0 or last_px <= 0:
                    continue
                side = "long" if pos_sz > 0 else "short"
                mult = 1 if side == "long" else -1
                pnl_pct = (last_px - avg_px) / avg_px * 100 * mult
                notional = abs(pos_sz) * avg_px
                pnl_abs = (last_px - avg_px) * abs(pos_sz) * mult
                sym = self._symbol_from_inst(inst_id)
                open_time = None
                ts_str = pos.get("openMaxPos", "") or pos.get("openTime", "")
                if ts_str:
                    try:
                        if len(ts_str) == 13:
                            open_time = datetime.fromtimestamp(int(ts_str) / 1000)
                        else:
                            open_time = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                    except Exception:
                        pass
                positions.append(Position(
                    symbol=sym, side=side, size=abs(pos_sz),
                    entry_price=avg_px, current_price=last_px,
                    pnl_pct=pnl_pct, pnl_abs=pnl_abs, inst_id=inst_id,
                    open_time=open_time,
                ))
            return positions
        except Exception:
            return []

    def _symbol_from_inst(self, inst_id: str) -> str:
        if inst_id.endswith("-USD-SWAP"):
            return inst_id.replace("-USD-SWAP", "")
        if inst_id.endswith("-USDT-SWAP"):
            return inst_id.replace("-USDT-SWAP", "/USDT")
        return inst_id

    def _summarize_signals(self, symbol: str) -> str:
        from src.core.signal_store import get_signal_store
        sig_map = get_signal_store().get_for_symbol_by_timeframe(symbol)
        if not sig_map:
            return ""
        parts = []
        for tf in ("15m", "1h", "4h"):
            entries = sorted(sig_map.get(tf, []), key=lambda x: (
                0 if x.severity == "critical" else 1 if x.severity == "high" else 2,
                -x.confidence,
            ))
            if not entries:
                parts.append(f"{tf}: 无信号")
            else:
                tags = []
                for e in entries[:3]:
                    tag = {
                        "bb_width_squeeze": "BB收窄", "ma_converge": "MA汇聚",
                        "rsi_extreme": "RSI极值", "macd_cross": "MACD",
                        "volume_spike": "量能",
                    }.get(e.signal_type, e.signal_type)
                    tags.append(f"{tag}({e.severity[0].upper()})")
                parts.append(f"{tf}: {'·'.join(tags)}")
        return " | " + " | ".join(parts)

    def _detect_changes(self, current: list[Position]) -> list[PositionAlert]:
        alerts = []
        current_map = {p.inst_id: p for p in current}
        prev_map = self._last_positions

        for inst_id, pos in current_map.items():
            if inst_id not in prev_map:
                alerts.append(PositionAlert(
                    kind="new_position", symbol=pos.symbol, side=pos.side,
                    details=f"开仓 {pos.side} {pos.size}张 @ {pos.entry_price:.4f}",
                    pnl_pct=pos.pnl_pct, pnl_abs=pos.pnl_abs,
                ))
            pnl = pos.pnl_pct
            if pnl <= -self._pnl_loss:
                loss_key = f"loss_{inst_id}"
                if not self._is_silent(loss_key):
                    sig_summary = self._summarize_signals(pos.symbol)
                    alerts.append(PositionAlert(
                        kind="pnl_loss", symbol=pos.symbol, side=pos.side,
                        details=f"浮亏 {pnl:.1f}% | {pos.entry_price:.4f} → {pos.current_price:.4f}{sig_summary}",
                        pnl_pct=pnl, pnl_abs=pos.pnl_abs,
                    ))
                    self._set_alerted(loss_key)
            elif pnl >= self._pnl_profit:
                profit_key = f"profit_{inst_id}"
                if not self._is_silent(profit_key):
                    alerts.append(PositionAlert(
                        kind="pnl_profit", symbol=pos.symbol, side=pos.side,
                        details=f"浮盈 {pnl:.1f}% | {pos.entry_price:.4f} → {pos.current_price:.4f}",
                        pnl_pct=pnl, pnl_abs=pos.pnl_abs,
                    ))
                    self._set_alerted(profit_key)
            if pos.open_time:
                age_hours = (datetime.now() - pos.open_time).total_seconds() / 3600
                if age_hours >= self._max_position_hours:
                    age_key = f"age_{inst_id}"
                    if not self._is_silent(age_key):
                        sig_summary = self._summarize_signals(pos.symbol)
                        alerts.append(PositionAlert(
                            kind="position_age", symbol=pos.symbol, side=pos.side,
                            details=f"持仓过久 {age_hours:.1f}h | {pos.entry_price:.4f} → {pos.current_price:.4f}{sig_summary}",
                            pnl_pct=pnl, pnl_abs=pos.pnl_abs,
                        ))
                        self._set_alerted(age_key)

        for inst_id, pos in prev_map.items():
            if inst_id not in current_map:
                alerts.append(PositionAlert(
                    kind="closed_position", symbol=pos.symbol, side=pos.side,
                    details=f"平仓 | {pos.pnl_pct:.1f}% ({pos.pnl_abs:+.2f}U)",
                    pnl_pct=pos.pnl_pct, pnl_abs=pos.pnl_abs,
                ))
        return alerts

    def _send_alerts(self, alerts: list[PositionAlert]):
        if not alerts or not self._feishu:
            return
        now = datetime.now().strftime("%H:%M")
        lines = [f"💼 持仓提醒 [{now}]"]
        for a in alerts:
            tag = {
                "new_position": "🟢 新仓", "closed_position": "🔴 平仓",
                "pnl_loss": "⚠️ 浮亏", "pnl_profit": "🎯 浮盈",
                "signal_match": "📡 持仓信号",
                "position_age": "⏰ 持仓过久",
            }.get(a.kind, a.kind)
            lines.append(f"\n{tag} {a.symbol} ({a.side})")
            lines.append(f"  {a.details}")
            if a.pnl_abs != 0:
                lines.append(f"  PnL: {a.pnl_pct:+.1f}% ({a.pnl_abs:+.2f}U)")
            if a.matched_signal:
                lines.append(f"  信号: {a.matched_signal}")
        self._feishu.send_message("\n".join(lines))

    def _loop(self):
        from loguru import logger
        from src.core.signal_store import get_signal_store
        logger.info(f"[PosMonitor] Started loop — _active={self._active}, _feishu={self._feishu is not None}")
        while not self._shutdown:
            try:
                positions = self.fetch_positions()
                logger.info(f"[PosMonitor] Fetched {len(positions)} positions")
                alerts = self._detect_changes(positions)
                sig_store = get_signal_store()
                sig_count = len(sig_store.get_all())
                logger.info(f"[PosMonitor] Signals in store: {sig_count}")
                signal_alerts = self._detect_signal_matches(positions, sig_store)
                all_alerts = alerts + signal_alerts
                if all_alerts:
                    logger.info(f"[PosMonitor] Sending {len(all_alerts)} alerts")
                    self._send_alerts(all_alerts)
                with self._lock:
                    self._last_positions = {p.inst_id: p for p in positions}
            except Exception as e:
                logger.warning(f"Position monitor error: {e}")
            for _ in range(self._interval):
                if self._shutdown:
                    break
                time.sleep(1)

    def _detect_signal_matches(self, positions: list, signal_store) -> list[PositionAlert]:
        cfg_enabled = self.config.get("position_alert", {}).get("signal_match", True)
        if not cfg_enabled:
            return []
        alerts = []
        for pos in positions:
            base = pos.symbol.split("/")[0].split(":")[0]
            sig_entries = signal_store.get_for_symbol(base)
            for entry in sig_entries:
                opposed = (pos.side == "long" and entry.direction == "short") or \
                          (pos.side == "short" and entry.direction == "long")
                if opposed and entry.severity in ("critical", "high") and entry.confidence >= 0.6:
                    sig_key = f"sig_{pos.inst_id}_{entry.signal_type}"
                    if not self._is_silent(sig_key):
                        sig_tag = {
                            "bb_width_squeeze": "BB收窄",
                            "ma_converge": "MA汇聚",
                            "rsi_extreme": "RSI极值",
                            "macd_cross": "MACD",
                            "volume_spike": "量能",
                        }.get(entry.signal_type, entry.signal_type)
                        alerts.append(PositionAlert(
                            kind="signal_match",
                            symbol=pos.symbol,
                            side=pos.side,
                            details=f"你持有{pos.side}仓位，但出现反向信号",
                            matched_signal=f"{sig_tag} {entry.direction}",
                            pnl_pct=pos.pnl_pct,
                        ))
                        self._set_alerted(sig_key)
        return alerts

    def start(self):
        from loguru import logger
        logger.info(f"[PosMonitor] start() called — _active={self._active}, creds_keys={list(self._creds.keys())}")
        if not self._active:
            return
        logger.info("Position monitor started")
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self):
        self._shutdown = True

    def get_positions(self) -> list[Position]:
        with self._lock:
            return list(self._last_positions.values())
