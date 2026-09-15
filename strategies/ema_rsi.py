from typing import List
import pandas as pd
import pandas_ta as ta
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class EmaRsiStrategy(BaseStrategy):
    name = "EMA_RSI"
    weight = 25

    def __init__(self, ema_fast: int = 9, ema_slow: int = 21, rsi_period: int = 14):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < max(self.ema_slow, self.rsi_period) + 5:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        df = self.candles_to_dataframe(candles)

        ema_fast = ta.ema(df["close"], length=self.ema_fast)
        ema_slow = ta.ema(df["close"], length=self.ema_slow)
        rsi = ta.rsi(df["close"], length=self.rsi_period)

        if ema_fast is None or ema_slow is None or rsi is None:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        curr_ema_fast = ema_fast.iloc[-1]
        prev_ema_fast = ema_fast.iloc[-2]
        curr_ema_slow = ema_slow.iloc[-1]
        prev_ema_slow = ema_slow.iloc[-2]
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        indicators = {
            "ema_fast": round(curr_ema_fast, 5),
            "ema_slow": round(curr_ema_slow, 5),
            "rsi": round(curr_rsi, 2)
        }

        if pd.isna(curr_ema_fast) or pd.isna(curr_ema_slow) or pd.isna(curr_rsi):
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        bullish_cross = (curr_ema_fast > curr_ema_slow) and (prev_ema_fast <= prev_ema_slow)
        bearish_cross = (curr_ema_fast < curr_ema_slow) and (prev_ema_fast >= prev_ema_slow)

        if bullish_cross and curr_rsi > 45:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=80, indicators=indicators)
        elif bearish_cross and curr_rsi < 55:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=80, indicators=indicators)

        ema_spread = (curr_ema_fast - curr_ema_slow) / curr_ema_slow * 100
        rsi_slope = curr_rsi - prev_rsi if not pd.isna(prev_rsi) else 0

        if ema_spread > 0.01 and curr_rsi > 45 and rsi_slope > 0:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=65, indicators=indicators)
        elif ema_spread < -0.01 and curr_rsi < 55 and rsi_slope < 0:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=65, indicators=indicators)

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)
