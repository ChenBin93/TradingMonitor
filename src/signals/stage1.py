from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from src.signals.registry import SignalRegistry, MarketRegime

if TYPE_CHECKING:
    from src.data.history_db import HistoryManager


@dataclass
class SymbolState:
    symbol: str
    timeframe: str
    data: dict[str, Any]
    regime: str = "unknown"
    direction: str = "neutral"
    bb_width_long_pct: float | None = None
    bb_width_medium_pct: float | None = None
    bb_width_short_pct: float | None = None

    @property
    def adx(self) -> float | None:
        return self.data.get("adx")

    @property
    def rsi(self) -> float | None:
        return self.data.get("rsi")

    @property
    def roc(self) -> float | None:
        return self.data.get("roc")

    @property
    def bb_width(self) -> float | None:
        return self.data.get("bb_width")

    @property
    def bb_width_pct(self) -> float | None:
        return self.data.get("bb_width_short_pct")

    @property
    def volume_ratio(self) -> float | None:
        return self.data.get("volume_ratio")

    @property
    def ma_converge(self) -> float | None:
        return self.data.get("ma_converge")

    @property
    def atr(self) -> float | None:
        return self.data.get("atr")

    @property
    def close(self) -> float | None:
        return self.data.get("close")

    @property
    def ttm_squeeze(self) -> dict | None:
        return self.data.get("ttm_squeeze")

    @property
    def rsi_divergence(self) -> dict | None:
        return self.data.get("rsi_divergence")

    @property
    def macd_divergence(self) -> dict | None:
        return self.data.get("macd_divergence")

    @property
    def volume_breakout(self) -> dict | None:
        return self.data.get("volume_breakout")


class Stage1Monitor:
    def __init__(
        self,
        config: dict[str, Any],
        registry: Optional[SignalRegistry] = None,
        history_manager: Optional["HistoryManager"] = None,
    ):
        self.config = config
        self.registry = registry
        self.history_manager = history_manager

    def set_registry(self, registry: SignalRegistry):
        self.registry = registry

    def set_history_manager(self, history_manager: "HistoryManager"):
        self.history_manager = history_manager

    def detect_regime(self, adx: float | None) -> str:
        if adx is None:
            return "unknown"
        threshold = self.config.get("indicators", {}).get("adx", {}).get("trend_threshold", 20)
        return "trend" if adx >= threshold else "range"

    def detect_direction(self, plus_di: float | None, minus_di: float | None) -> str:
        if plus_di is None or minus_di is None:
            return "neutral"
        if plus_di > minus_di:
            return "long"
        elif minus_di > plus_di:
            return "short"
        return "neutral"

    def _get_bb_width_ranks(self, symbol: str, timeframe: str, bb_width: float | None) -> tuple[float | None, float | None]:
        if not self.history_manager or bb_width is None:
            return None, None
        lookback = self.config.get("data", {}).get("history", {}).get("default_lookback", 90)
        try:
            long_pct = self.history_manager.get_bbw_percentile_rank(
                symbol, timeframe, lookback, bb_width
            )
            medium_pct = self.history_manager.get_percentile_rank(
                symbol, timeframe, lookback, "bb_width", "medium", bb_width
            )
            return long_pct, medium_pct
        except Exception:
            return None, None

    def evaluate_signals(self, state: SymbolState) -> list[dict]:
        if not self.registry:
            return self._legacy_check(state)
        signals = []
        regime = MarketRegime.TREND if state.regime == "trend" else MarketRegime.RANGE
        for signal in self.registry.get_by_regime(regime):
            if signal.check_func:
                result = signal.check_func(signal, state)
                if result:
                    result["direction"] = self._get_direction(signal, state)
                    result["regime"] = state.regime
                    signals.append(result)
        return signals

    def _legacy_check(self, state: SymbolState) -> list[dict]:
        signals = []
        bb_width = state.bb_width
        threshold_pct = self.config.get("indicators", {}).get("bb_width_pct_rank_threshold", 25)
        if bb_width is not None and state.bb_width_long_pct is not None:
            if state.bb_width_long_pct <= threshold_pct:
                signals.append({
                    "signal_type": "bb_width_squeeze",
                    "severity": "critical" if state.bb_width_long_pct <= 10 else "high",
                    "details": {
                        "bb_width": round(bb_width, 2),
                        "bbw_rank": round(state.bb_width_long_pct, 1),
                        "threshold": threshold_pct,
                    },
                })
        ma_converge = state.ma_converge
        ma_threshold = self.config.get("indicators", {}).get("ma_converge_threshold", 0.5)
        if ma_converge is not None and ma_converge <= ma_threshold:
            signals.append({
                "signal_type": "ma_converge",
                "severity": "critical" if ma_converge <= 0.3 else "high",
                "details": {"ma_converge": round(ma_converge, 3), "threshold": ma_threshold},
            })
        return signals

    def _get_direction(self, signal, state: SymbolState) -> str:
        if hasattr(signal, "direction_from"):
            if signal.direction_from == "trend_direction":
                return state.direction
            elif signal.direction_from == "rsi_direction":
                rsi = state.rsi
                return "long" if (rsi or 50) < 50 else "short"
        return state.direction

    def create_state(self, symbol: str, timeframe: str, ind_data: dict) -> SymbolState:
        adx = ind_data.get("adx")
        plus_di = ind_data.get("plus_di")
        minus_di = ind_data.get("minus_di")
        bb_width = ind_data.get("bb_width")
        long_pct, medium_pct = self._get_bb_width_ranks(symbol, timeframe, bb_width)
        short_pct = ind_data.get("bb_width_short_pct")
        return SymbolState(
            symbol=symbol,
            timeframe=timeframe,
            data=ind_data,
            regime=self.detect_regime(adx),
            direction=self.detect_direction(plus_di, minus_di),
            bb_width_long_pct=long_pct,
            bb_width_medium_pct=medium_pct,
            bb_width_short_pct=short_pct,
        )
