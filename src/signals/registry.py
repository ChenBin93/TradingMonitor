from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class SignalType(Enum):
    STAGE1 = 1
    STAGE2 = 2


class MarketRegime(Enum):
    TREND = "trend"
    RANGE = "range"
    UNKNOWN = "unknown"


@dataclass
class SignalDefinition:
    id: str
    name: str
    stage: int
    category: str
    regimes: list[str]
    params: dict[str, Any]
    severity: dict[str, float] = field(default_factory=dict)
    direction_from: str = "trend_direction"
    confidence: dict[str, float] = field(default_factory=dict)
    entry_conditions: list[str] = field(default_factory=list)
    description: str = ""
    check_func: Any = field(default=None, repr=False)
    enabled: bool = True


class SignalRegistry:
    def __init__(self):
        self._signals: dict[str, SignalDefinition] = {}
        self._stage1_signals: list[SignalDefinition] = []
        self._stage2_signals: list[SignalDefinition] = []

    def register(self, signal: SignalDefinition):
        self._signals[signal.id] = signal
        if signal.stage == 1:
            self._stage1_signals.append(signal)
        elif signal.stage == 2:
            self._stage2_signals.append(signal)

    def register_func(self, signal_id: str, func: Callable):
        signal = self._signals.get(signal_id)
        if signal:
            signal.check_func = func

    def get(self, signal_id: str) -> SignalDefinition | None:
        return self._signals.get(signal_id)

    def get_stage1_signals(self) -> list[SignalDefinition]:
        return [s for s in self._stage1_signals if s.enabled]

    def get_stage2_signals(self) -> list[SignalDefinition]:
        return [s for s in self._stage2_signals if s.enabled]

    def get_by_regime(self, regime: MarketRegime) -> list[SignalDefinition]:
        regime_str = regime.value
        return [s for s in self._stage1_signals if s.enabled and (regime_str in s.regimes or "trend" in s.regimes)]

    def get_by_category(self, category: str) -> list[SignalDefinition]:
        return [s for s in self._stage1_signals if s.enabled and s.category == category]

    def enable(self, signal_id: str):
        if signal_id in self._signals:
            self._signals[signal_id].enabled = True

    def disable(self, signal_id: str):
        if signal_id in self._signals:
            self._signals[signal_id].enabled = False

    def load_from_yaml(self, path: str):
        import yaml
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        for sig_data in data.get("signals", []):
            signal = SignalDefinition(
                id=sig_data["id"],
                name=sig_data.get("name", ""),
                stage=sig_data["stage"],
                category=sig_data["category"],
                regimes=sig_data.get("regimes", []),
                params=sig_data.get("params", {}),
                severity=sig_data.get("severity", {}),
                direction_from=sig_data.get("direction_from", "trend_direction"),
                confidence=sig_data.get("confidence", {}),
                entry_conditions=sig_data.get("entry_conditions", []),
                description=sig_data.get("description", ""),
                enabled=sig_data.get("enabled", True),
            )
            self.register(signal)
        self._register_builtin_funcs()

    def _register_builtin_funcs(self):
        self.register_func("bb_width_squeeze", self._check_bb_width_squeeze)
        self.register_func("ma_converge", self._check_ma_converge)
        self.register_func("rsi_extreme", self._check_rsi_extreme)
        self.register_func("volume_contraction", self._check_volume_contraction)
        self.register_func("consolidation", self._check_consolidation)
        self.register_func("volume_spike", self._check_volume_spike)

    def _check_bb_width_squeeze(self, signal: SignalDefinition, state: dict) -> dict | None:
        bb_pct = state.get("bb_width_pct")
        if bb_pct is None:
            return None
        threshold = signal.params.get("bb_width_pct_threshold", 20)
        if bb_pct <= threshold:
            severity = "critical" if bb_pct <= 10 else "high" if bb_pct <= 15 else "medium"
            return {
                "signal_type": signal.id,
                "severity": severity,
                "details": {"bb_pct": bb_pct, "threshold": threshold},
            }
        return None

    def _check_ma_converge(self, signal: SignalDefinition, state: dict) -> dict | None:
        ma_converge = state.get("ma_converge")
        if ma_converge is None:
            return None
        threshold = signal.params.get("converge_threshold", 0.5)
        if ma_converge <= threshold:
            severity = "critical" if ma_converge <= 0.3 else "high" if ma_converge <= 0.4 else "medium"
            return {
                "signal_type": signal.id,
                "severity": severity,
                "details": {"ma_converge": ma_converge, "threshold": threshold},
            }
        return None

    def _check_rsi_extreme(self, signal: SignalDefinition, state: dict) -> dict | None:
        rsi = state.get("rsi")
        if rsi is None:
            return None
        oversold = signal.params.get("oversold", 35)
        overbot = signal.params.get("overbot", 65)
        if rsi <= oversold:
            return {
                "signal_type": signal.id,
                "direction": "long",
                "severity": "critical" if rsi <= 25 else "high",
                "details": {"rsi": rsi, "direction": "long"},
            }
        elif rsi >= overbot:
            return {
                "signal_type": signal.id,
                "direction": "short",
                "severity": "critical" if rsi >= 80 else "high",
                "details": {"rsi": rsi, "direction": "short"},
            }
        return None

    def _check_volume_contraction(self, signal: SignalDefinition, state: dict) -> dict | None:
        vol_ratio = state.get("volume_ratio")
        if vol_ratio is None:
            return None
        threshold = signal.params.get("volume_threshold", 0.5)
        if vol_ratio <= threshold:
            return {
                "signal_type": signal.id,
                "severity": "medium",
                "details": {"vol_ratio": vol_ratio, "threshold": threshold},
            }
        return None

    def _check_consolidation(self, signal: SignalDefinition, state: dict) -> dict | None:
        df = state.get("_df")
        atr = state.get("atr")
        if df is None or atr is None or atr == 0:
            return None
        bars = signal.params.get("consolidation_bars", 20)
        range_atr = signal.params.get("consolidation_range", 3.0)
        if len(df) >= bars:
            recent = df.tail(bars)
            price_range = (recent["high"].max() - recent["low"].min()) / atr
            if price_range <= range_atr:
                return {
                    "signal_type": signal.id,
                    "severity": "critical" if price_range <= 2.0 else "high",
                    "details": {"range_atr": round(price_range, 2), "bars": bars},
                }
        return None

    def _check_volume_spike(self, signal: SignalDefinition, state: dict) -> dict | None:
        vol_ratio = state.get("volume_ratio")
        if vol_ratio is None:
            return None
        threshold = signal.params.get("volume_spike_threshold", 5.0)
        if vol_ratio >= threshold:
            return {
                "signal_type": signal.id,
                "severity": "critical",
                "details": {"vol_ratio": vol_ratio, "threshold": threshold},
            }
        return None
