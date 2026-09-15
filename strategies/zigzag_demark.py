from typing import List
import pandas as pd
import pandas_ta as ta
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class ZigZagDeMarkerStrategy(BaseStrategy):
    name = "ZIGZAG_DEMARK"
    weight = 20

    def __init__(self, zz_depth: int = 12, rsi_period: int = 14,
                 rsi_overbought: int = 70, rsi_oversold: int = 30,
                 zz_retrace_pct: float = 0.003, zz_atr_mult: float = 0.5):
        self.zz_depth = zz_depth
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        # ZigZag reversal confirmation: a pivot only counts as a swing once
        # price has retraced from it by at least max(pct*price, atr_mult*ATR).
        self.zz_retrace_pct = zz_retrace_pct
        self.zz_atr_mult = zz_atr_mult

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < max(self.zz_depth, self.rsi_period) + 10:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        df = self.candles_to_dataframe(candles)

        rsi = ta.rsi(df["close"], length=self.rsi_period)
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)

        if rsi is None:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        indicators = {
            "rsi": round(curr_rsi, 2) if not pd.isna(curr_rsi) else None
        }

        if pd.isna(curr_rsi) or pd.isna(prev_rsi):
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        swing_high = self._find_swing_high(df, atr)
        swing_low = self._find_swing_low(df, atr)

        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        bullish_reversal = (
            swing_low is not None and
            curr_close > prev_close and
            prev_rsi < self.rsi_oversold + 10 and
            curr_rsi > prev_rsi
        )

        bearish_reversal = (
            swing_high is not None and
            curr_close < prev_close and
            prev_rsi > self.rsi_overbought - 10 and
            curr_rsi < prev_rsi
        )

        if bullish_reversal:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=70, indicators=indicators)
        elif bearish_reversal:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=70, indicators=indicators)

        if curr_rsi < 35 and curr_rsi > prev_rsi and curr_close > prev_close:
            return StrategyResult(strategy_name=self.name, direction="CALL", confidence=60, indicators=indicators)
        elif curr_rsi > 65 and curr_rsi < prev_rsi and curr_close < prev_close:
            return StrategyResult(strategy_name=self.name, direction="PUT", confidence=60, indicators=indicators)

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

    def _reversal_threshold(self, df: pd.DataFrame, atr) -> float:
        """Minimum retracement (absolute price units) required to confirm a swing."""
        pct_threshold = df["close"].iloc[-1] * self.zz_retrace_pct
        atr_value = 0.0
        if atr is not None and not atr.empty and not pd.isna(atr.iloc[-1]):
            atr_value = float(atr.iloc[-1]) * self.zz_atr_mult
        return max(pct_threshold, atr_value)

    def _find_swing_low(self, df: pd.DataFrame, atr) -> bool:
        """A genuine swing low: a local minimum confirmed only after price has
        retraced upward by at least the reversal threshold from that low.

        Returns False in choppy conditions where every N candles happens to
        contain a local min/max — a retracement must actually occur.
        """
        n = self.zz_depth
        if len(df) < n + 2:
            return False
        threshold = self._reversal_threshold(df, atr)
        if threshold <= 0:
            return False

        lows = df["low"].tolist()
        closes = df["close"].tolist()
        total = len(df)

        # Scan backward for the most recent confirmed pivot low.
        for i in range(total - 2, max(n - 1, 0), -1):
            left = lows[max(0, i - n):i]
            right = lows[i + 1:min(total, i + n + 1)]
            if not left or not right:
                continue
            if lows[i] >= min(left) or lows[i] >= min(right):
                continue
            # A retracement upward from the pivot must have occurred since.
            if max(closes[i + 1:]) >= lows[i] + threshold:
                return True
        return False

    def _find_swing_high(self, df: pd.DataFrame, atr) -> bool:
        """Genuine swing high: a local maximum confirmed only after price has
        retraced downward by at least the reversal threshold from that high."""
        n = self.zz_depth
        if len(df) < n + 2:
            return False
        threshold = self._reversal_threshold(df, atr)
        if threshold <= 0:
            return False

        highs = df["high"].tolist()
        closes = df["close"].tolist()
        total = len(df)

        for i in range(total - 2, max(n - 1, 0), -1):
            left = highs[max(0, i - n):i]
            right = highs[i + 1:min(total, i + n + 1)]
            if not left or not right:
                continue
            if highs[i] <= max(left) or highs[i] <= max(right):
                continue
            if min(closes[i + 1:]) <= highs[i] - threshold:
                return True
        return False
