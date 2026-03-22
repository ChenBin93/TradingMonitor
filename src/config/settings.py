from pathlib import Path
from typing import Any
import os
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ExchangeConfig(BaseModel):
    name: str = "okx"
    type: str = "swap"
    quote_currency: str = "USDT"
    enabled: bool = True


class DataConfig(BaseModel):
    top_n: int = 200
    timeframes: list[str] = Field(default_factory=lambda: ["15m", "1h", "4h"])
    websocket: dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "reconnect_delay_seconds": 5,
        "max_reconnect_attempts": 10,
        "ping_interval_seconds": 30,
    })
    history: dict[str, Any] = Field(default_factory=lambda: {
        "retention_days": {"15m": 90, "1h": 90, "4h": 365},
        "short_window": 20,
        "medium_window": 60,
        "long_window": 240,
        "download_batch_size": 50,
        "download_interval_seconds": 60,
    })


class ScannerConfig(BaseModel):
    interval_seconds: int = 300
    historical_bars: int = 300
    symbol_refresh_interval: int = 12


class IndicatorsConfig(BaseModel):
    roc_periods: dict[str, int] = Field(default_factory=lambda: {"15m": 5, "1h": 10, "4h": 20})
    rsi: dict[str, int] = Field(default_factory=lambda: {"period": 14, "oversold": 35, "overbot": 65})
    adx: dict[str, int] = Field(default_factory=lambda: {
        "period": 14,
        "trend_threshold": 20,
        "entry_threshold": 25,
        "strong_trend": 40,
    })
    bb: dict[str, int] = Field(default_factory=lambda: {"period": 20, "std": 2})
    atr_period: int = 14
    volume_ma_period: int = 20
    ma: dict[str, int] = Field(default_factory=lambda: {"short": 5, "mid": 20, "long": 60})
    macd: dict[str, int] = Field(default_factory=lambda: {"fast": 12, "slow": 26, "signal": 9, "bars_confirm": 3})


class SignalsConfig(BaseModel):
    config_file: str = "configs/signals.yaml"
    regime: dict[str, Any] = Field(default_factory=lambda: {"adx_threshold": 20})


class AlertsConfig(BaseModel):
    dedup: dict[str, int] = Field(default_factory=lambda: {
        "window_minutes": 30,
        "stage1_volatile_window_minutes": 60,
    })
    summary_level: str = "extended"
    ranking: dict[str, Any] = Field(default_factory=lambda: {
        "weights": {"15m": 0.4, "1h": 0.3, "4h": 0.3},
        "long_top_n": 20,
        "short_top_n": 10,
    })


class FeishuConfig(BaseModel):
    enabled: bool = True
    app_id: str = ""
    app_secret: str = ""
    chat_id: str = ""
    webhook_url: str = ""
    long_connection: bool = True
    allow_commands: bool = True
    stage1_enabled: bool = True
    stage2_enabled: bool = True
    silent_hours: list[tuple[int, int, int, int]] = Field(default_factory=list)


class OKXCredentials(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    testnet: bool = False


class PositionAlertConfig(BaseModel):
    pnl_loss_pct: float = 5.0
    pnl_profit_pct: float = 10.0
    signal_match: bool = True
    interval_seconds: int = 60


class DatabaseConfig(BaseModel):
    path: str = "data/screening.db"
    retention: dict[str, int] = Field(default_factory=lambda: {"snapshots_days": 90, "alerts_days": 180})


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/screening.log"
    console: bool = True
    rotation: dict[str, Any] = Field(default_factory=lambda: {"max_size_mb": 100, "backup_count": 5})


class HealthConfig(BaseModel):
    enabled: bool = True
    port: int = 8080
    endpoint: str = "/health"


class Settings(BaseModel):
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    indicators: IndicatorsConfig = Field(default_factory=IndicatorsConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    okx_credentials: OKXCredentials = Field(default_factory=OKXCredentials)
    position_alert: PositionAlertConfig = Field(default_factory=PositionAlertConfig)
    feishu_position: FeishuConfig = Field(default_factory=FeishuConfig)

    @classmethod
    def load_from_yaml(cls, path: str) -> "Settings":
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        cls._expand_env_vars(data)
        secrets_path = Path(path).parent / "secrets.yaml"
        if secrets_path.exists():
            with open(secrets_path, "r") as f:
                secrets = yaml.safe_load(f) or {}
            cls._merge_secrets(data, secrets)
        return cls(**data)

    @classmethod
    def _merge_secrets(cls, data: dict, secrets: dict):
        if "okx" in secrets:
            data["okx_credentials"] = secrets["okx"]
        if "feishu_signal" in secrets:
            fs = data.get("feishu", {})
            fs.update(secrets["feishu_signal"])
            data["feishu"] = fs
        if "feishu_position" in secrets:
            data["feishu_position"] = secrets["feishu_position"]

    @classmethod
    def _expand_env_vars(cls, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    env_key = v[2:-1]
                    obj[k] = os.environ.get(env_key, "")
                else:
                    cls._expand_env_vars(v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    env_key = v[2:-1]
                    obj[i] = os.environ.get(env_key, "")
                else:
                    cls._expand_env_vars(v)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        config_path = os.environ.get("CONFIG_PATH", "configs/default.yaml")
        if Path(config_path).exists():
            _settings = Settings.load_from_yaml(config_path)
        else:
            _settings = Settings()
    return _settings
