from typing import List, Tuple
import pandas as pd
import pandas_ta as ta
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class MacdSupportResistanceStrategy(BaseStrategy):
    name = "MACD_SR"
    weight = 20

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, sr_lookback: int = 50):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.sr_lookback = sr_lookback

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < max(self.slow + self.signal, self.sr_lookback) + 5:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        df = self.candles_to_dataframe(candles)

        macd = ta.macd(df["close"], fast=self.fast, slow=self.slow, signal=self.signal)

        if macd is None:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        macd_line = macd[f"MACD_{self.fast}_{self.slow}_{self.signal}"]
        hist = macd[f"MACDh_{self.fast}_{self.slow}_{self.signal}"]

        curr_hist = hist.iloc[-1]
        prev_hist = hist.iloc[-2]
        curr_macd = macd_line.iloc[-1]
        curr_signal_val = macd[f"MACDs_{self.fast}_{self.slow}_{self.signal}"].iloc[-1]

        indicators = {
            "macd": round(curr_macd, 5) if not pd.isna(curr_macd) else None,
            "signal": round(curr_signal_val, 5) if not pd.isna(curr_signal_val) else None,
            "histogram": round(curr_hist, 5) if not pd.isna(curr_hist) else None
        }

        if pd.isna(curr_hist) or pd.isna(prev_hist):
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        support, resistance = self._find_sr_levels(df)

        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        near_support = support is not None and abs(curr_close - support) / support < 0.002
        near_resistance = resistance is not None and abs(curr_close - resistance) / resistance < 0.002

        bullish_flip = prev_hist < 0 and curr_hist > 0
        bearish_flip = prev_hist > 0 and curr_hist < 0

        indicators["support"] = round(support, 5) if support else None
        indicators["resistance"] = round(resistance, 5) if resistance else None

        if near_support and bullish_flip:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=72, indicators=indicators)
        elif near_resistance and bearish_flip:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=72, indicators=indicators)

        if bullish_flip and curr_close > prev_close:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=65, indicators=indicators)
        elif bearish_flip and curr_close < prev_close:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=65, indicators=indicators)

        if near_support and curr_close > prev_close:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=60, indicators=indicators)
        elif near_resistance and curr_close < prev_close:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=60, indicators=indicators)

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

    def _find_sr_levels(self, df: pd.DataFrame) -> Tuple[float, float]:
        lookback = df.tail(self.sr_lookback)
        lows = lookback["low"].nsmallest(3).values
        highs = lookback["high"].nlargest(3).values

        support = sum(lows) / len(lows) if len(lows) > 0 else None
        resistance = sum(highs) / len(highs) if len(highs) > 0 else None

        return support, resistance
