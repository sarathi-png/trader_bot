import pandas as pd
import numpy as np


def _check_series(s, length=None):
    if s is None:
        return None
    if length and len(s) < length:
        return None
    if s.isna().all():
        return None
    return s


def rsi(close, length=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1/length, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high, low, close, length=14):
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, min_periods=length).mean()


def ema(close, length=20):
    return close.ewm(span=length, adjust=False).mean()


def bbands(close, length=20, std=2.0):
    ma = close.ewm(span=length, adjust=False).mean()
    rolling = close.rolling(window=length)
    std_val = rolling.std()
    upper = ma + std_val * std
    lower = ma - std_val * std
    return pd.DataFrame({
        f"BBU_{length}_{std}_{std}": upper,
        f"BBL_{length}_{std}_{std}": lower,
        f"BBM_{length}_{std}_{std}": ma,
    })


def adx(high, low, close, length=14):
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr_val = atr(high, low, close, length)
    plus_di = 100 * plus_dm.ewm(alpha=1/length, min_periods=length).mean() / atr_val.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/length, min_periods=length).mean() / atr_val.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1/length, min_periods=length).mean()
    return pd.DataFrame({"ADX_" + str(length): adx_val})


def stoch(high, low, close, k=14, d=3, smooth_k=3):
    lowest_low = low.rolling(window=k).min()
    highest_high = high.rolling(window=k).max()
    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    k_val = raw_k.ewm(alpha=1/smooth_k, adjust=False).mean()
    d_val = k_val.ewm(alpha=1/d, adjust=False).mean()
    return pd.DataFrame({
        f"STOCHk_{k}_{d}_{smooth_k}": k_val,
        f"STOCHd_{k}_{d}_{smooth_k}": d_val,
    })


def macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({
        f"MACD_{fast}_{slow}_{signal}": macd_line,
        f"MACDs_{fast}_{slow}_{signal}": signal_line,
        f"MACDh_{fast}_{slow}_{signal}": hist,
    })
