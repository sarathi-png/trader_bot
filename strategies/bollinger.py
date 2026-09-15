from typing import List
import pandas as pd
import pandas_ta as ta
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class BollingerStrategy(BaseStrategy):
    name = "BOLLINGER"
    weight = 20

    def __init__(self, period: int = 20, std_dev: float = 2.0, adx_period: int = 14):
        self.period = period
        self.std_dev = std_dev
        self.adx_period = adx_period

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < max(self.period, self.adx_period) + 5:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        df = self.candles_to_dataframe(candles)

        bb = ta.bbands(df["close"], length=self.period, std=self.std_dev)
        adx = ta.adx(df["high"], df["low"], df["close"], length=self.adx_period)

        if bb is None or adx is None:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        upper = bb[f"BBU_{self.period}_{self.std_dev}_{self.std_dev}"]
        lower = bb[f"BBL_{self.period}_{self.std_dev}_{self.std_dev}"]
        adx_val = adx[f"ADX_{self.adx_period}"]

        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        curr_upper = upper.iloc[-1]
        curr_lower = lower.iloc[-1]
        curr_adx = adx_val.iloc[-1]

        indicators = {
            "close": round(curr_close, 5),
            "upper_band": round(curr_upper, 5),
            "lower_band": round(curr_lower, 5),
            "adx": round(curr_adx, 2)
        }

        if pd.isna(curr_adx) or pd.isna(curr_upper) or pd.isna(curr_lower):
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        band_width = curr_upper - curr_lower
        if band_width <= 0:
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        touch_tolerance = band_width * 0.15

        if curr_close <= curr_lower + touch_tolerance and curr_close > prev_close:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=72, indicators=indicators)
        elif curr_close >= curr_upper - touch_tolerance and curr_close < prev_close:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=72, indicators=indicators)

        mid = (curr_upper + curr_lower) / 2
        if curr_close < mid and curr_close > prev_close and curr_adx < 30:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=60, indicators=indicators)
        elif curr_close > mid and curr_close < prev_close and curr_adx < 30:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=60, indicators=indicators)

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)
