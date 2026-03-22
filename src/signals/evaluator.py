from dataclasses import dataclass
from typing import Any, Optional

from src.signals.registry import SignalRegistry


@dataclass
class SignalResult:
    signal_type: str
    symbol: str
    timeframe: str
    regime: str
    direction: str
    severity: str
    confidence: float
    details: dict[str, Any]
    stage: int = 1


class SignalEvaluator:
    def __init__(self, registry: SignalRegistry, config: dict[str, Any]):
        self.registry = registry
        self.config = config

    def evaluate(self, state: dict, regime: str) -> list[SignalResult]:
        results = []
        for signal in self.registry.get_stage1_signals():
            if regime not in signal.regimes and "trend" not in signal.regimes:
                continue
            result = self._check_signal(signal, state)
            if result:
                results.append(result)
        return results

    def _check_signal(self, signal, state: dict) -> Optional[SignalResult]:
        if signal.check_func:
            result = signal.check_func(signal, state)
            if result:
                return self._build_result(signal, state, result)
        return None

    def _build_result(self, signal, state: dict, check_result: dict) -> SignalResult:
        severity = check_result.get("severity", "medium")
        return SignalResult(
            signal_type=signal.id,
            symbol=state.get("symbol", ""),
            timeframe=state.get("timeframe", ""),
            regime=state.get("regime", "unknown"),
            direction=check_result.get("direction", state.get("direction", "neutral")),
            severity=severity,
            confidence=self._calc_confidence(signal, state, severity),
            details=check_result.get("details", {}),
            stage=signal.stage,
        )

    def _calc_confidence(self, signal, state: dict, severity: str) -> float:
        confidence = 0.5
        weights = signal.confidence
        if "regime_match" in weights:
            if state.get("regime") in signal.regimes:
                confidence += weights["regime_match"]
        if "severity" in weights:
            if severity in ["critical", "high"]:
                confidence += weights["severity"]
        if "volume_confirmation" in weights:
            vol_ratio = state.get("volume_ratio", 1.0)
            if vol_ratio and vol_ratio > 1.5:
                confidence += weights["volume_confirmation"]
        return min(confidence, 1.0)
