from typing import List
import pandas as pd
import pandas_ta as ta
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class ADXFilter(BaseStrategy):
    """ADX(14) trend strength filter.

    Returns CALL/PUT when ADX >= 25 (trending market) and
    +DI/-DI direction confirms. Returns NONE in sideways markets
    (ADX < 20) to avoid false signals.
    """

    name = "ADX_FILTER"
    weight = 15

    def __init__(self, adx_period: int = 14, adx_threshold: float = 20.0,
                 trending_threshold: float = 25.0):
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.trending_threshold = trending_threshold

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < self.adx_period + 5:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        df = self.candles_to_dataframe(candles)

        adx = ta.adx(df["high"], df["low"], df["close"], length=self.adx_period)
        di_plus = ta.dm(df["high"], df["low"], length=self.adx_period)

        if adx is None or di_plus is None:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        curr_adx = adx[f"ADX_{self.adx_period}"].iloc[-1]
        curr_di_plus = di_plus[f"DI+_{self.adx_period}"].iloc[-1]
        curr_di_minus = di_plus[f"DI-{self.adx_period}"].iloc[-1]

        if pd.isna(curr_adx) or pd.isna(curr_di_plus) or pd.isna(curr_di_minus):
            return StrategyResult(strategy_name=self.name, direction="NONE")

        indicators = {
            "adx": round(curr_adx, 2),
            "di_plus": round(curr_di_plus, 2),
            "di_minus": round(curr_di_minus, 2),
        }

        if curr_adx >= self.trending_threshold and curr_di_plus > curr_di_minus:
            return StrategyResult(
                strategy_name=self.name, direction="CALL",
                confidence=85, indicators=indicators
            )
        elif curr_adx >= self.trending_threshold and curr_di_minus > curr_di_plus:
            return StrategyResult(
                strategy_name=self.name, direction="PUT",
                confidence=85, indicators=indicators
            )
        elif curr_adx >= self.adx_threshold:
            direction = "CALL" if curr_di_plus > curr_di_minus else "PUT"
            return StrategyResult(
                strategy_name=self.name, direction=direction,
                confidence=50, indicators=indicators
            )

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)
