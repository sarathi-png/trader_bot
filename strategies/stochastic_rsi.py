from typing import List
import pandas as pd
import pandas_ta as ta
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class StochasticRsiStrategy(BaseStrategy):
    name = "STOCH_RSI"
    weight = 15

    def __init__(self, stoch_k: int = 14, stoch_d: int = 3, stoch_smooth: int = 3,
                 rsi_period: int = 14, overbought: int = 80, oversold: int = 20):
        self.stoch_k = stoch_k
        self.stoch_d = stoch_d
        self.stoch_smooth = stoch_smooth
        self.rsi_period = rsi_period
        self.overbought = overbought
        self.oversold = oversold

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < max(self.stoch_k, self.rsi_period) + 10:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        df = self.candles_to_dataframe(candles)

        stoch = ta.stoch(df["high"], df["low"], df["close"],
                         k=self.stoch_k, d=self.stoch_d, smooth_k=self.stoch_smooth)
        rsi = ta.rsi(df["close"], length=self.rsi_period)

        if stoch is None or rsi is None:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        k_col = f"STOCHk_{self.stoch_k}_{self.stoch_d}_{self.stoch_smooth}"
        d_col = f"STOCHd_{self.stoch_k}_{self.stoch_d}_{self.stoch_smooth}"

        curr_k = stoch[k_col].iloc[-1]
        prev_k = stoch[k_col].iloc[-2]
        curr_d = stoch[d_col].iloc[-1]
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        indicators = {
            "stoch_k": round(curr_k, 2) if not pd.isna(curr_k) else None,
            "stoch_d": round(curr_d, 2) if not pd.isna(curr_d) else None,
            "rsi": round(curr_rsi, 2) if not pd.isna(curr_rsi) else None
        }

        if pd.isna(curr_k) or pd.isna(curr_d) or pd.isna(curr_rsi):
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        k_crosses_above_d = prev_k < stoch[d_col].iloc[-2] and curr_k > curr_d
        k_crosses_below_d = prev_k > stoch[d_col].iloc[-2] and curr_k < curr_d

        bullish = (
            curr_k < self.oversold + 10 and
            k_crosses_above_d and
            curr_rsi < 40
        )

        bearish = (
            curr_k > self.overbought - 10 and
            k_crosses_below_d and
            curr_rsi > 60
        )

        if bullish:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=78, indicators=indicators)
        elif bearish:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=78, indicators=indicators)

        if curr_k < 30 and curr_k > prev_k and curr_rsi < 45:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=62, indicators=indicators)
        elif curr_k > 70 and curr_k < prev_k and curr_rsi > 55:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=62, indicators=indicators)

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)
