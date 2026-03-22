import os
from typing import Any

from src.signals.registry import SignalRegistry, SignalDefinition, MarketRegime


class SignalFactory:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._registry = SignalRegistry()
        self._loaded = False

    def get_registry(self) -> SignalRegistry:
        if not self._loaded:
            self.load_signals()
        return self._registry

    def load_signals(self, config_path: str | None = None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, "configs", "signals.yaml")
        if os.path.exists(config_path):
            self._registry.load_from_yaml(config_path)
            self._loaded = True
        else:
            self._load_default_signals()

    def _load_default_signals(self):
        default_signals = [
            SignalDefinition(
                id="bb_width_squeeze",
                name="波动率压缩",
                stage=1,
                category="trend_accumulation",
                regimes=["trend", "range"],
                params={"bb_width_pct_rank_threshold": 25, "lookback": 20},
                severity={"critical": 10, "high": 20, "medium": 25},
                direction_from="trend_direction",
                description="布林带宽度处于历史低位",
            ),
            SignalDefinition(
                id="ma_converge",
                name="均线收敛",
                stage=1,
                category="trend_accumulation",
                regimes=["trend", "range"],
                params={"converge_threshold": 0.5, "atr_multiplier": 3},
                severity={"critical": 0.3, "high": 0.5, "medium": 1.0},
                direction_from="trend_direction",
                description="多条均线收敛",
            ),
            SignalDefinition(
                id="rsi_extreme",
                name="RSI极值",
                stage=1,
                category="range_extremes",
                regimes=["range"],
                params={"oversold": 35, "overbot": 65},
                severity={"critical": 30, "high": 35, "medium": 100},
                direction_from="rsi_direction",
                description="RSI达到超买超卖区域",
            ),
            SignalDefinition(
                id="volume_contraction",
                name="缩量整理",
                stage=1,
                category="trend_accumulation",
                regimes=["trend", "range"],
                params={"volume_threshold": 0.5, "price_fluctuation_max": 0.5},
                severity={"medium": 1.0},
                direction_from="trend_direction",
                description="成交量萎缩且价格波动减小",
            ),
            SignalDefinition(
                id="consolidation",
                name="窄幅盘整",
                stage=1,
                category="trend_accumulation",
                regimes=["trend", "range"],
                params={"consolidation_bars": 20, "consolidation_range": 3.0},
                severity={"critical": 2.0, "high": 3.0, "medium": 5.0},
                direction_from="trend_direction",
                description="价格在一段时间内波动极小",
            ),
            SignalDefinition(
                id="volume_spike",
                name="成交量爆发",
                stage=1,
                category="trend_accumulation",
                regimes=["trend"],
                params={"volume_spike_threshold": 5.0},
                severity={"critical": 10.0},
                direction_from="trend_direction",
                description="成交量急剧放大",
            ),
            SignalDefinition(
                id="ttm_squeeze",
                name="TTM压缩",
                stage=1,
                category="advanced_momentum",
                regimes=["trend", "range"],
                params={"bb_period": 20, "bb_std": 2.0, "kc_period": 20, "kc_multiplier": 1.5, "min_squeeze_bars": 5},
                severity={"critical": 8, "high": 5, "medium": 3},
                direction_from="trend_direction",
                description="布林带收缩到肯特纳通道内，压缩后释放",
            ),
            SignalDefinition(
                id="rsi_divergence",
                name="RSI背离",
                stage=1,
                category="advanced_momentum",
                regimes=["trend", "range"],
                params={"period": 14, "pivot_left": 5, "pivot_right": 5, "min_distance_pct": 2.0},
                severity={"critical": 3.0, "high": 5.0, "medium": 10.0},
                direction_from="divergence_direction",
                description="价格与RSI产生背离",
            ),
            SignalDefinition(
                id="macd_divergence",
                name="MACD背离",
                stage=1,
                category="advanced_momentum",
                regimes=["trend", "range"],
                params={"pivot_left": 5, "pivot_right": 5, "min_distance_pct": 2.0},
                severity={"critical": 3.0, "high": 5.0, "medium": 10.0},
                direction_from="divergence_direction",
                description="价格与MACD产生背离",
            ),
            SignalDefinition(
                id="volume_breakout",
                name="成交量突破确认",
                stage=1,
                category="advanced_momentum",
                regimes=["trend"],
                params={"breakout_threshold": 1.5},
                severity={"critical": 3.0, "high": 5.0, "medium": 10.0},
                direction_from="trend_direction",
                description="成交量超过均量倍数确认突破",
            ),
            SignalDefinition(
                id="trend_breakout_long",
                name="趋势突破做多",
                stage=2,
                category="trend_entry",
                regimes=["trend"],
                params={
                    "adx_entry_threshold": 25,
                    "adx_1h_threshold": 20,
                    "roc_entry_short": 0.5,
                    "roc_entry_mid": 1.0,
                    "volume_multiplier": 2.0,
                    "stop_loss_atr": 2.0,
                    "risk_reward": 2.0,
                },
                direction_from="long",
                description="趋势确认后的突破做多信号",
            ),
            SignalDefinition(
                id="trend_breakout_short",
                name="趋势突破做空",
                stage=2,
                category="trend_entry",
                regimes=["trend"],
                params={
                    "adx_entry_threshold": 25,
                    "adx_1h_threshold": 20,
                    "roc_entry_short": -0.5,
                    "roc_entry_mid": -1.0,
                    "volume_multiplier": 2.0,
                    "stop_loss_atr": 2.0,
                    "risk_reward": 2.0,
                },
                direction_from="short",
                description="趋势确认后的突破做空信号",
            ),
            SignalDefinition(
                id="range_reversion_long",
                name="震荡反弹做多",
                stage=2,
                category="range_entry",
                regimes=["range"],
                params={
                    "adx_max": 20,
                    "rsi_rebound_from": 35,
                    "stop_loss_atr": 1.5,
                    "risk_reward": 2.0,
                },
                direction_from="long",
                description="震荡市场中的反弹做多信号",
            ),
            SignalDefinition(
                id="range_reversion_short",
                name="震荡回调做空",
                stage=2,
                category="range_entry",
                regimes=["range"],
                params={
                    "adx_max": 20,
                    "rsi_rebound_from": 65,
                    "stop_loss_atr": 1.5,
                    "risk_reward": 2.0,
                },
                direction_from="short",
                description="震荡市场中的回调做空信号",
            ),
        ]
        for signal in default_signals:
            self._registry.register(signal)
        self._registry._register_builtin_funcs()
        self._loaded = True

    def enable_signal(self, signal_id: str):
        self._registry.enable(signal_id)

    def disable_signal(self, signal_id: str):
        self._registry.disable(signal_id)

    def reload(self):
        self._loaded = False
        self._registry = SignalRegistry()
        self.load_signals()
