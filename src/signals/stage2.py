from typing import Any


class Stage2Detector:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def check_trend_entry(self, states: dict[str, Any]) -> dict | None:
        state_15m = states.get("15m")
        state_1h = states.get("1h")
        if not state_15m or not state_1h:
            return None
        d15 = state_15m.data if hasattr(state_15m, "data") else state_15m
        d1h = state_1h.data if hasattr(state_1h, "data") else state_1h
        adx_cfg = self.config.get("indicators", {}).get("adx", {})
        adx_entry = adx_cfg.get("entry_threshold", 25)
        adx_trend = adx_cfg.get("trend_threshold", 20)
        adx_15m = d15.get("adx") or 0
        adx_1h = d1h.get("adx") or 0
        if adx_15m < adx_entry:
            return None
        if adx_1h < adx_trend:
            return None
        plus_15m = d15.get("plus_di") or 0
        minus_15m = d15.get("minus_di") or 0
        if plus_15m <= minus_15m:
            return None
        stage2_cfg = self.config.get("signals", {}).get("trend_breakout_long", {})
        roc_short = stage2_cfg.get("roc_entry_short", 0.5)
        roc_mid = stage2_cfg.get("roc_entry_mid", 1.0)
        roc_15m = d15.get("roc") or 0
        roc_1h = d1h.get("roc") or 0
        if roc_15m < roc_short and roc_1h < roc_mid:
            return None
        vol_ratio = d15.get("volume_ratio") or 0
        vol_mult = stage2_cfg.get("volume_multiplier", 2.0)
        if vol_ratio < vol_mult:
            return None
        close = d15.get("close")
        atr = d15.get("atr")
        if not close or not atr or atr == 0:
            return None
        sl_mult = stage2_cfg.get("stop_loss_atr", 2.0)
        stop_loss = round(close - atr * sl_mult, 4)
        take_profit = round(close + atr * sl_mult * 2.0, 4)
        return {
            "type": "trend_breakout_long",
            "direction": "long",
            "entry_price": close,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": 2.0,
            "adx_15m": round(adx_15m, 1),
            "adx_1h": round(adx_1h, 1),
            "roc_15m": round(roc_15m, 2),
            "roc_1h": round(roc_1h, 2),
            "rsi": round(d15.get("rsi"), 1) if d15.get("rsi") else None,
            "vol_ratio": round(vol_ratio, 2),
            "atr": round(atr, 4),
        }

    def check_range_entry(self, states: dict[str, Any]) -> dict | None:
        state_15m = states.get("15m")
        if not state_15m:
            return None
        d15 = state_15m.data if hasattr(state_15m, "data") else state_15m
        adx_15m = d15.get("adx") or 0
        rsi = d15.get("rsi")
        if rsi is None:
            return None
        stage2_cfg = self.config.get("signals", {}).get("range_reversion_long", {})
        adx_max = stage2_cfg.get("adx_max", 20)
        rsi_low = stage2_cfg.get("rsi_rebound_from", 35)
        rsi_high = stage2_cfg.get("rsi_rebound_from", 65)
        if adx_15m >= adx_max:
            return None
        close = d15.get("close")
        atr = d15.get("atr")
        if not close or not atr or atr == 0:
            return None
        sl_mult = stage2_cfg.get("stop_loss_atr", 1.5)
        vol_ratio = d15.get("volume_ratio") or 1.0
        if rsi <= rsi_low:
            return {
                "type": "range_reversion_long",
                "direction": "long",
                "entry_price": close,
                "stop_loss": round(close - atr * sl_mult, 4),
                "take_profit": round(close + atr * sl_mult * 2.0, 4),
                "risk_reward": 2.0,
                "adx_15m": round(adx_15m, 1),
                "rsi": round(rsi, 1),
                "atr": round(atr, 4),
                "vol_ratio": round(vol_ratio, 2),
            }
        elif rsi >= rsi_high:
            return {
                "type": "range_reversion_short",
                "direction": "short",
                "entry_price": close,
                "stop_loss": round(close + atr * sl_mult, 4),
                "take_profit": round(close - atr * sl_mult * 2.0, 4),
                "risk_reward": 2.0,
                "adx_15m": round(adx_15m, 1),
                "rsi": round(rsi, 1),
                "atr": round(atr, 4),
                "vol_ratio": round(vol_ratio, 2),
            }
        return None
