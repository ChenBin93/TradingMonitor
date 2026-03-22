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


def _calc_short_percentile(series: pd.Series, lookback: int = 20) -> float | None:
    if len(series) < lookback:
        return None
    recent = series.tail(lookback).dropna()
    if len(recent) < lookback // 2:
        return None
    current = series.iloc[-1]
    if pd.isna(current):
        return None
    rank = (recent < current).sum() / len(recent) * 100
    return float(rank)


def calc_ttm_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_multiplier: float = 1.5,
    min_squeeze_bars: int = 5,
) -> dict | None:
    if len(df) < kc_period + min_squeeze_bars:
        return None

    high = df["high"]
    low = df["low"]
    close = df["close"]

    bb_mid = close.rolling(bb_period).mean()
    bb_std_val = close.rolling(bb_period).std()
    bb_upper = bb_mid + bb_std_val * bb_std
    bb_lower = bb_mid - bb_std_val * bb_std

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    kc_mid = close.ewm(span=kc_period, adjust=False).mean()
    kc_atr = tr.ewm(span=kc_period, adjust=False).mean()
    kc_upper = kc_mid + kc_atr * kc_multiplier
    kc_lower = kc_mid - kc_atr * kc_multiplier

    squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    squeeze_count = 0
    for i in range(len(squeeze_on) - 1, -1, -1):
        if squeeze_on.iloc[i]:
            squeeze_count += 1
        else:
            break

    current_price = close.iloc[-1]
    direction = None
    if not squeeze_on.iloc[-1]:
        if squeeze_count >= min_squeeze_bars:
            if current_price > bb_mid.iloc[-1]:
                direction = "bullish"
            elif current_price < bb_mid.iloc[-1]:
                direction = "bearish"

    return {
        "squeeze_active": bool(squeeze_on.iloc[-1]),
        "squeeze_bars": squeeze_count,
        "min_squeeze_bars": min_squeeze_bars,
        "is_fired": squeeze_count >= min_squeeze_bars and not squeeze_on.iloc[-1],
        "direction": direction,
        "bb_width": float(bb_upper.iloc[-1] - bb_lower.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else None,
        "kc_width": float(kc_upper.iloc[-1] - kc_lower.iloc[-1]) if not pd.isna(kc_upper.iloc[-1]) else None,
    }


def detect_rsi_divergence(
    df: pd.DataFrame,
    rsi: pd.Series,
    period: int = 14,
    pivot_left: int = 5,
    pivot_right: int = 5,
    min_distance_pct: float = 2.0,
) -> dict | None:
    if len(df) < pivot_left + pivot_right + 5:
        return None

    price = df["close"]
    lookback = pivot_left + pivot_right + 1
    if len(rsi) < lookback:
        return None

    rsi_vals = rsi.tail(lookback).values
    price_vals = price.tail(lookback).values
    rsi_idx = pivot_left

    rsi_left = rsi_vals[:rsi_idx]
    price_right = price_vals[rsi_idx + 1:]

    rsi_pivot = rsi_vals[rsi_idx]
    price_pivot = price_vals[rsi_idx]

    price_right_min = np.min(price_right)
    price_right_max = np.max(price_right)

    divergence = None
    distance_pct = abs(price_right_max - price_right_min) / price_right_max * 100 if price_right_max != 0 else 0

    if distance_pct >= min_distance_pct:
        if price_right_min < price_pivot and np.min(rsi_vals[:rsi_idx]) > rsi_pivot:
            divergence = "bullish"
        elif price_right_max > price_pivot and np.max(rsi_vals[:rsi_idx]) < rsi_pivot:
            divergence = "bearish"

    return {
        "divergence": divergence,
        "rsi_value": float(rsi_vals[rsi_idx]),
        "price_at_pivot": float(price_pivot),
        "price_distance_pct": round(distance_pct, 2),
    }


def detect_macd_divergence(
    df: pd.DataFrame,
    macd_line: pd.Series,
    signal_line: pd.Series,
    pivot_left: int = 5,
    pivot_right: int = 5,
    min_distance_pct: float = 2.0,
) -> dict | None:
    if len(df) < pivot_left + pivot_right + 5:
        return None

    price = df["close"]
    lookback = pivot_left + pivot_right + 1
    if len(macd_line) < lookback or len(signal_line) < lookback:
        return None

    macd_vals = macd_line.tail(lookback).values
    price_vals = price.tail(lookback).values
    macd_idx = pivot_left

    price_left = price_vals[:macd_idx]
    price_right = price_vals[macd_idx + 1:]

    price_pivot = price_vals[macd_idx]
    macd_pivot = macd_vals[macd_idx]

    price_right_min = np.min(price_right)
    price_right_max = np.max(price_right)

    divergence = None
    distance_pct = abs(price_right_max - price_right_min) / price_right_max * 100 if price_right_max != 0 else 0

    if distance_pct >= min_distance_pct:
        if price_right_min < price_pivot and macd_pivot > np.min(macd_vals[:macd_idx]):
            divergence = "bullish"
        elif price_right_max > price_pivot and macd_pivot < np.max(macd_vals[:macd_idx]):
            divergence = "bearish"

    return {
        "divergence": divergence,
        "macd_value": float(macd_vals[macd_idx]),
        "price_at_pivot": float(price_pivot),
        "price_distance_pct": round(distance_pct, 2),
    }


def check_volume_breakout(
    df: pd.DataFrame,
    vol_ma: pd.Series,
    vol_ratio: pd.Series,
    threshold: float = 1.5,
) -> dict | None:
    if len(df) < 2 or vol_ratio is None or vol_ma is None:
        return None

    current_vol_ratio = vol_ratio.iloc[-1]
    prev_vol_ratio = vol_ratio.iloc[-2] if len(vol_ratio) > 1 else 1.0

    current_volume = df["volume"].iloc[-1]
    avg_volume = vol_ma.iloc[-1]

    price_change = 0.0
    if len(df) >= 2:
        price_change = abs(df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100

    return {
        "confirmed": current_vol_ratio >= threshold,
        "vol_ratio": float(current_vol_ratio),
        "prev_vol_ratio": float(prev_vol_ratio),
        "volume": float(current_volume),
        "avg_volume": float(avg_volume) if not pd.isna(avg_volume) else None,
        "threshold": threshold,
        "price_change_pct": round(price_change, 2),
        "is_expansion": current_vol_ratio > prev_vol_ratio,
    }


def compute_all_indicators(df: pd.DataFrame, params: dict) -> dict | None:
    """
    计算所有技术指标。

    注意: bb_width (布林带宽度百分比) 和 bb_width_short_pct 是原始计算值，
    用于传递给 Stage1Monitor 进行历史百分位查询。
    历史百分位 (bb_width_long_pct, bb_width_medium_pct) 需要通过 HistoryManager 获取。
    """
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
    macd_line, signal_line, histogram = calc_macd(df)
    ma_converge = calc_ma_converge_score(df, atr, ma5, ma20, ma60)
    idx = len(df) - 1

    def v(series):
        return series.iloc[idx] if len(series) > idx and series.iloc[idx] == series.iloc[idx] else None

    # 计算布林带宽度短期百分位 (最近20根K线内的排名)
    # 这个是局部统计，用于短期变化检测；历史百分位由 HistoryManager 提供
    bb_width_short_pct = _calc_short_percentile(bb_width, lookback=20)

    prev_hist = histogram.iloc[idx - 1] if idx > 0 and not np.isnan(histogram.iloc[idx - 1]) else 0
    curr_hist = v(histogram) or 0
    if prev_hist <= 0 < curr_hist:
        macd_cross = "golden"
    elif prev_hist >= 0 > curr_hist:
        macd_cross = "death"
    else:
        macd_cross = None

    # === 新增指标计算 ===
    # TTM Squeeze 检测
    ttm_squeeze = calc_ttm_squeeze(df)

    # RSI 背离检测
    rsi_div = detect_rsi_divergence(df, rsi)

    # MACD 背离检测
    macd_div = detect_macd_divergence(df, macd_line, signal_line)

    # 成交量突破确认
    vol_breakout = check_volume_breakout(df, vol_ma, vol_ratio)

    return {
        "close": v(df["close"]),
        "roc": v(roc),
        "rsi": v(rsi),
        "adx": v(adx),
        "plus_di": v(plus_di),
        "minus_di": v(minus_di),
        "bb_width": v(bb_width),
        "bb_width_short_pct": bb_width_short_pct,  # 短期局部百分位
        "atr": v(atr),
        "volume_ratio": v(vol_ratio),
        "ma5": v(ma5),
        "ma20": v(ma20),
        "ma60": v(ma60),
        "ma_converge": ma_converge,
        "macd_hist": v(histogram),
        "macd_cross": macd_cross,
        "macd_line": v(macd_line),
        "signal_line": v(signal_line),
        "df_len": len(df),
        "df": df,  # 保存 df 用于信号检测
        # === 新增指标 ===
        "ttm_squeeze": ttm_squeeze,
        "rsi_divergence": rsi_div,
        "macd_divergence": macd_div,
        "volume_breakout": vol_breakout,
    }
