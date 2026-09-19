import logging
from typing import List, Tuple
import pandas as pd
import pandas_ta as ta
from database.models import Candle

logger = logging.getLogger(__name__)


class MultiTimeframeAnalyzer:
    def __init__(self, ema_period: int = 20, ema_period_15m: int = 10,
                 ema_period_1h: int = 14):
        self.ema_period = ema_period
        self.ema_period_15m = ema_period_15m
        self.ema_period_1h = ema_period_1h

    def resample(self, candles: List[Candle], minutes: int) -> List[Candle]:
        if not candles:
            return []

        df = pd.DataFrame([
            {"timestamp": c.timestamp, "open": c.open, "high": c.high,
             "low": c.low, "close": c.close, "volume": c.volume}
            for c in candles
        ])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("datetime", inplace=True)

        bucket_seconds = minutes * 60
        grouped = df.groupby(df.index.floor(f"{minutes}min"))

        resampled = []
        for _, group in grouped:
            resampled.append(Candle(
                timestamp=int(group["timestamp"].iloc[0]),
                asset=candles[0].asset,
                open=group["open"].iloc[0],
                high=group["high"].max(),
                low=group["low"].min(),
                close=group["close"].iloc[-1],
                volume=group["volume"].sum(),
            ))

        return resampled

    def get_trend(self, candles: List[Candle], ema_period: int = None) -> str:
        period = ema_period or self.ema_period
        if len(candles) < period + 3:
            return "NEUTRAL"

        df = pd.DataFrame([
            {"close": c.close} for c in candles
        ])

        ema = ta.ema(df["close"], length=period)
        if ema is None or len(ema) < 3:
            return "NEUTRAL"

        curr_ema = ema.iloc[-1]
        prev_ema = ema.iloc[-3]
        curr_close = df["close"].iloc[-1]

        if pd.isna(curr_ema) or pd.isna(prev_ema):
            return "NEUTRAL"

        slope = curr_ema - prev_ema
        spread = (curr_close - curr_ema) / curr_ema * 100 if curr_ema != 0 else 0

        if curr_close > curr_ema and slope > 0 and spread > 0.005:
            return "UP"
        elif curr_close < curr_ema and slope < 0 and spread < -0.005:
            return "DOWN"

        return "NEUTRAL"

    def analyze(self, candles_1min: List[Candle]) -> Tuple[str, int]:
        trend_5m = "NEUTRAL"
        trend_15m = "NEUTRAL"
        trend_1h = "NEUTRAL"

        candles_5m = self.resample(candles_1min, 5)
        if len(candles_5m) >= self.ema_period + 3:
            trend_5m = self.get_trend(candles_5m, self.ema_period)

        candles_15m = self.resample(candles_1min, 15)
        if len(candles_15m) >= self.ema_period_15m + 3:
            trend_15m = self.get_trend(candles_15m, self.ema_period_15m)

        candles_1h = self.resample(candles_1min, 60)
        if len(candles_1h) >= self.ema_period_1h + 3:
            trend_1h = self.get_trend(candles_1h, self.ema_period_1h)

        trends = [t for t in [trend_5m, trend_15m, trend_1h] if t != "NEUTRAL"]
        if not trends:
            return "NEUTRAL", 0

        up_count = trends.count("UP")
        down_count = trends.count("DOWN")

        if up_count >= 2:
            return "UP", 8
        elif down_count >= 2:
            return "DOWN", 8
        elif up_count == 1 and down_count == 0:
            return "UP", 5
        elif down_count == 1 and up_count == 0:
            return "DOWN", 5
        elif up_count == 1 and down_count == 1:
            return "CONFLICT", -5

        return "NEUTRAL", 0

    def confirm(self, direction: str, candles_1min: List[Candle]) -> Tuple[bool, str, int]:
        trend, strength = self.analyze(candles_1min)

        if trend == "CONFLICT":
            return False, trend, -5

        if trend == "NEUTRAL":
            return True, trend, 0

        if direction == "CALL" and trend == "UP":
            return True, trend, strength
        elif direction == "PUT" and trend == "DOWN":
            return True, trend, strength
        else:
            return False, trend, -strength
