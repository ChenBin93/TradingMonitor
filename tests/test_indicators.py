import pytest
import pandas as pd
import numpy as np
from src.signals.indicators import (
    calc_roc,
    calc_rsi,
    calc_adx,
    calc_bb,
    calc_atr,
    calc_ma,
    compute_all_indicators,
)


@pytest.fixture
def sample_df():
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=100, freq="1h")
    close = 100 + np.cumsum(np.random.randn(100) * 2)
    high = close + np.random.rand(100) * 3
    low = close - np.random.rand(100) * 3
    volume = np.random.rand(100) * 1000 + 500
    return pd.DataFrame({
        "timestamp": dates,
        "open": close - 1,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_calc_roc(sample_df):
    roc = calc_roc(sample_df, 10)
    assert len(roc) == len(sample_df)
    assert roc.iloc[10] == pytest.approx(((sample_df["close"].iloc[10] - sample_df["close"].iloc[0]) / sample_df["close"].iloc[0]) * 100, rel=1e-3)


def test_calc_rsi(sample_df):
    rsi = calc_rsi(sample_df, 14)
    assert len(rsi) == len(sample_df)
    assert 0 <= rsi.iloc[-1] <= 100


def test_calc_adx(sample_df):
    adx = calc_adx(sample_df, 14)
    assert len(adx) == len(sample_df)
    assert adx.iloc[-1] >= 0


def test_calc_bb(sample_df):
    mid, bb_width = calc_bb(sample_df, 20, 2)
    assert len(mid) == len(sample_df)
    assert len(bb_width) == len(sample_df)


def test_calc_atr(sample_df):
    atr = calc_atr(sample_df, 14)
    assert len(atr) == len(sample_df)
    assert atr.iloc[-1] > 0


def test_calc_ma(sample_df):
    ma_dict = calc_ma(sample_df, [5, 20, 60])
    assert "ma_5" in ma_dict
    assert "ma_20" in ma_dict
    assert "ma_60" in ma_dict


def test_compute_all_indicators(sample_df):
    params = {
        "roc_period": 10,
        "rsi_period": 14,
        "adx_period": 14,
        "bb_period": 20,
        "bb_std": 2,
        "atr_period": 14,
        "volume_ma_period": 20,
        "ma_short": 5,
        "ma_mid": 20,
        "ma_long": 60,
    }
    result = compute_all_indicators(sample_df, params)
    assert result is not None
    assert "close" in result
    assert "rsi" in result
    assert "adx" in result
    assert "bb_width_pct" in result
    assert "ma_converge" in result
