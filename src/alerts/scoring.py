from dataclasses import dataclass
from typing import Any, Optional

from src.data.history import SymbolStats


@dataclass
class ConfidenceResult:
    total_score: float
    breakdown: dict[str, float]
    regime_type: str
    recommendation: str
    should_push: bool


class ConfidenceScorer:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.push_thresholds = {
            "high": config.get("alerts", {}).get("push", {}).get("high_confidence_threshold", 0.8),
            "medium": config.get("alerts", {}).get("push", {}).get("medium_confidence_threshold", 0.6),
            "low": config.get("alerts", {}).get("push", {}).get("low_confidence_threshold", 0.4),
        }

    def score(self, signal: dict, state: dict, regime: str, stats: Optional[SymbolStats] = None) -> ConfidenceResult:
        breakdown = {}
        if regime == "trend":
            breakdown = self._score_trend(signal, state, stats)
        else:
            breakdown = self._score_range(signal, state, stats)
        weights = self._get_weights(signal, regime)
        total = self._weighted_average(breakdown, weights)
        total = min(max(total, 0.0), 1.0)
        recommendation = self._get_recommendation(total)
        should_push = self._should_push(total, signal)
        return ConfidenceResult(
            total_score=total,
            breakdown=breakdown,
            regime_type=regime,
            recommendation=recommendation,
            should_push=should_push,
        )

    def _score_trend(self, signal: dict, state: dict, stats: Optional[SymbolStats] = None) -> dict[str, float]:
        scores = {}
        adx = state.get("adx") or 0
        if adx >= 40:
            scores["adx_strength"] = 0.9
        elif adx >= 25:
            scores["adx_strength"] = 0.7
        else:
            scores["adx_strength"] = 0.4
        vol_ratio = state.get("volume_ratio") or 1.0
        scores["volume_confirmation"] = min(vol_ratio / 3.0, 1.0) if vol_ratio > 1 else 0.3
        roc = abs(state.get("roc") or 0)
        scores["roc_momentum"] = min(roc / 3.0, 1.0) if roc > 0 else 0.3
        scores["multi_timeframe"] = self._score_multi_timeframe(state)
        if stats:
            scores["historical_volatility"] = self._score_historical_volatility(stats)
        return scores

    def _score_range(self, signal: dict, state: dict, stats: Optional[SymbolStats] = None) -> dict[str, float]:
        scores = {}
        rsi = state.get("rsi") or 50
        if rsi <= 25 or rsi >= 75:
            scores["rsi_extreme"] = 0.9
        elif rsi <= 30 or rsi >= 70:
            scores["rsi_extreme"] = 0.7
        elif rsi <= 35 or rsi >= 65:
            scores["rsi_extreme"] = 0.5
        else:
            scores["rsi_extreme"] = 0.3
        bb_pct = state.get("bb_width_pct") or 50
        scores["volatility_compression"] = (100 - bb_pct) / 100.0
        vol_ratio = state.get("volume_ratio") or 1.0
        scores["volume_confirmation"] = 0.5 if vol_ratio < 1.5 else 0.7
        if stats:
            scores["historical_reversion"] = self._score_historical_reversion(stats)
        return scores

    def _score_multi_timeframe(self, state: dict) -> float:
        score = 0.5
        if state.get("_confirmed_15m") and state.get("_confirmed_1h"):
            score = 0.9
        elif state.get("_confirmed_15m") or state.get("_confirmed_1h"):
            score = 0.7
        return score

    def _score_historical_volatility(self, stats: SymbolStats) -> float:
        if stats.volatility_percentile_short < 20:
            return 0.9
        elif stats.volatility_percentile_short < 40:
            return 0.7
        elif stats.volatility_percentile_short > 80:
            return 0.3
        return 0.5

    def _score_historical_reversion(self, stats: SymbolStats) -> float:
        if stats.return_percentile_short < 20 or stats.return_percentile_short > 80:
            return 0.9
        return 0.5

    def _get_weights(self, signal: dict, regime: str) -> dict[str, float]:
        if regime == "trend":
            return {
                "adx_strength": 0.25,
                "volume_confirmation": 0.2,
                "roc_momentum": 0.2,
                "multi_timeframe": 0.2,
                "historical_volatility": 0.15,
            }
        return {
            "rsi_extreme": 0.3,
            "volatility_compression": 0.25,
            "volume_confirmation": 0.2,
            "historical_reversion": 0.25,
        }

    def _weighted_average(self, scores: dict[str, float], weights: dict[str, float]) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        for key, score in scores.items():
            weight = weights.get(key, 0.0)
            if weight > 0:
                weighted_sum += score * weight
                total_weight += weight
        if total_weight == 0:
            return 0.5
        return weighted_sum / total_weight

    def _get_recommendation(self, score: float) -> str:
        if score >= 0.8:
            return "HIGH_CONFIDENCE"
        elif score >= 0.6:
            return "MEDIUM_CONFIDENCE"
        elif score >= 0.4:
            return "LOW_CONFIDENCE"
        return "NO_CONFIDENCE"

    def _should_push(self, score: float, signal: dict) -> bool:
        severity = signal.get("severity", "medium")
        if severity == "critical":
            return score >= self.push_thresholds["low"]
        elif severity == "high":
            return score >= self.push_thresholds["medium"]
        return score >= self.push_thresholds["high"]
