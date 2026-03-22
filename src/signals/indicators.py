import pandas as pd
import numpy as np


def calc_roc(df: pd.DataFrame, period: int) -> pd.Series:
    if len(df) < period + 1:
        return pd.Series([np.nan] * len(df), index=df.index)
    roc = (df["close"] - df["close"].shift(period)) / df["close"].shift(period) * 100
    return roc


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if len(df) < period + 1:
        return pd.Series([np.nan] * len(df), index=df.index)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(to_replace=0, value=np.nan)
    rs = rs.fillna(float("inf"))
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.fillna(100.0)
    return rsi


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if len(df) < period * 2 + 1:
        return pd.Series([np.nan] * len(df), index=df.index)
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    plus_dm = high - prev_high
    minus_dm = prev_low - low
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    atr_safe = atr.replace(to_replace=0, value=np.nan)
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe)
    plus_di = plus_di.fillna(0)
    minus_di = minus_di.fillna(0)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(to_replace=0, value=np.nan))
    dx = dx.fillna(0)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx


def calc_plus_minus_di(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series]:
    if len(df) < period * 2 + 1:
        return pd.Series([np.nan] * len(df)), pd.Series([np.nan] * len(df))
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    plus_dm = high - prev_high
    minus_dm = prev_low - low
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    atr_safe = atr.replace(to_replace=0, value=np.nan)
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe)
    plus_di = plus_di.fillna(0)
    minus_di = minus_di.fillna(0)
    return plus_di, minus_di


def calc_bb(df: pd.DataFrame, period: int = 20, std: float = 2) -> tuple[pd.Series, pd.Series]:
    if len(df) < period:
        return pd.Series([np.nan] * len(df), index=df.index), pd.Series([np.nan] * len(df), index=df.index)
    mid = df["close"].rolling(period).mean()
    std_val = df["close"].rolling(period).std()
    upper = mid + std_val * std
    lower = mid - std_val * std
    bb_range = upper - lower
    mid_safe = mid.replace(to_replace=0, value=np.nan)
    bb_width = (bb_range / mid_safe) * 100
    bb_width = bb_width.fillna(0)
    return mid, bb_width


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if len(df) < period + 1:
        return pd.Series([np.nan] * len(df), index=df.index)
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def calc_ma(df: pd.DataFrame, periods: list[int] | None = None) -> dict[str, pd.Series]:
    if periods is None:
        periods = [5, 20, 60]
    result = {}
    for p in periods:
        if len(df) >= p:
            result[f"ma_{p}"] = df["close"].rolling(p).mean()
        else:
            result[f"ma_{p}"] = pd.Series([np.nan] * len(df), index=df.index)
    return result


def calc_ma_converge_score(df: pd.DataFrame, atr: pd.Series, ma5: pd.Series, ma20: pd.Series, ma60: pd.Series) -> float:
    if len(df) < 5 or atr is None or atr.iloc[-1] != atr.iloc[-1]:
        return 0.0
    m5, m20, m60 = ma5.iloc[-1], ma20.iloc[-1], ma60.iloc[-1]
    c = df["close"].iloc[-1]
    a = atr.iloc[-1]
    if np.isnan(m5) or np.isnan(m20) or np.isnan(m60) or np.isnan(a) or a == 0:
        return 0.0
    dist = abs(c - m5) + abs(m5 - m20) + abs(m20 - m60)
    score = dist / (a * 3)
    return min(score, 10.0)


def calc_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    if len(df) < period:
        return pd.Series([np.nan] * len(df), index=df.index)
    return df["volume"].rolling(period).mean()


def calc_volume_ratio(df: pd.DataFrame, vol_ma: pd.Series) -> pd.Series:
    if len(df) < 2 or vol_ma is None:
        return pd.Series([np.nan] * len(df), index=df.index)
    return df["volume"] / vol_ma


def calc_bb_width_percentile(bb_width_series: pd.Series, lookback: int = 20) -> pd.Series:
    if len(bb_width_series) < lookback:
        return pd.Series([np.nan] * len(bb_width_series), index=bb_width_series.index)
    recent = bb_width_series.tail(lookback)
    current = bb_width_series.iloc[-1]
    if np.isnan(current):
        return pd.Series([np.nan] * len(bb_width_series), index=bb_width_series.index)
    pct = (recent < current).sum() / lookback * 100
    pct_series = pd.Series([np.nan] * len(bb_width_series), index=bb_width_series.index)
    pct_series.iloc[-1] = pct
    return pct_series


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    if len(df) < slow + signal:
        return (
            pd.Series([np.nan] * len(df), index=df.index),
            pd.Series([np.nan] * len(df), index=df.index),
            pd.Series([np.nan] * len(df), index=df.index),
        )
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_all_indicators(df: pd.DataFrame, params: dict) -> dict | None:
    if df is None or len(df) < 30:
        return None
    roc_period = params.get("roc_period", 10)
    rsi_period = params.get("rsi_period", 14)
    adx_period = params.get("adx_period", 14)
    bb_period = params.get("bb_period", 20)
    bb_std = params.get("bb_std", 2)
    atr_period = params.get("atr_period", 14)
    vol_ma_period = params.get("volume_ma_period", 20)
    ma_s = params.get("ma_short", 5)
    ma_m = params.get("ma_mid", 20)
    ma_l = params.get("ma_long", 60)
    roc = calc_roc(df, roc_period)
    rsi = calc_rsi(df, rsi_period)
    adx = calc_adx(df, adx_period)
    plus_di, minus_di = calc_plus_minus_di(df, adx_period)
    bb_mid, bb_width = calc_bb(df, bb_period, bb_std)
    atr = calc_atr(df, atr_period)
    ma_dict = calc_ma(df, [ma_s, ma_m, ma_l])
    ma5, ma20, ma60 = ma_dict[f"ma_{ma_s}"], ma_dict[f"ma_{ma_m}"], ma_dict[f"ma_{ma_l}"]
    vol_ma = calc_volume_ma(df, vol_ma_period)
    vol_ratio = calc_volume_ratio(df, vol_ma)
    bb_width_pct = calc_bb_width_percentile(bb_width, lookback=20)
    macd_line, signal_line, histogram = calc_macd(df)
    ma_converge = calc_ma_converge_score(df, atr, ma5, ma20, ma60)
    idx = len(df) - 1
    def v(series):
        return series.iloc[idx] if len(series) > idx and series.iloc[idx] == series.iloc[idx] else None
    prev_hist = histogram.iloc[idx - 1] if idx > 0 and not np.isnan(histogram.iloc[idx - 1]) else 0
    curr_hist = v(histogram) or 0
    if prev_hist <= 0 < curr_hist:
        macd_cross = "golden"
    elif prev_hist >= 0 > curr_hist:
        macd_cross = "death"
    else:
        macd_cross = None
    return {
        "close": v(df["close"]),
        "roc": v(roc),
        "rsi": v(rsi),
        "adx": v(adx),
        "plus_di": v(plus_di),
        "minus_di": v(minus_di),
        "bb_width": v(bb_width),
        "bb_width_pct": v(bb_width_pct),
        "atr": v(atr),
        "volume_ratio": v(vol_ratio),
        "ma5": v(ma5),
        "ma20": v(ma20),
        "ma60": v(ma60),
        "ma_converge": ma_converge,
        "macd_hist": v(histogram),
        "macd_cross": macd_cross,
        "df_len": len(df),
    }
