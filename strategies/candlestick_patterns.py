from typing import List
import pandas as pd
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy


class CandlestickPatternDetector(BaseStrategy):
    """Detects key candlestick patterns for price action confirmation.

    Patterns detected:
      - BULLISH_ENGULFING / BEARISH_ENGULFING
      - HAMMER / INVERTED_HAMMER
      - PIN_BAR (long lower/upper wick)
      - DOJI (open ≈ close)
      - THREE_SOLDIERS / THREE_CROWS
      - PIERCING_LINE / DARK_CLOUD_COVER

    Returns direction based on detected patterns with confidence scores.
    """

    name = "CANDLESTICK_PATTERNS"
    weight = 15

    # Minimum body-to-range ratio for meaningful candles
    MIN_BODY_RATIO = 0.1
    # Minimum wick-to-body ratio for pin bars
    PIN_BAR_RATIO = 2.0
    # Maximum doji body ratio (open ≈ close)
    DOJI_MAX_RATIO = 0.05

    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        if len(candles) < 3:
            return StrategyResult(strategy_name=self.name, direction="NONE")

        recent = candles[-min(self.lookback, len(candles)):]
        patterns = self._detect_patterns(recent)

        indicators = {"patterns": patterns}

        if not patterns:
            return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

        # Determine direction from patterns
        bullish_count = sum(1 for p in patterns if p in self._BULLISH_PATTERNS)
        bearish_count = sum(1 for p in patterns if p in self._BEARISH_PATTERNS)

        if bullish_count >= 2:
            confidence = min(90, 60 + bullish_count * 10)
            return StrategyResult(
                strategy_name=self.name, direction="CALL",
                confidence=confidence, indicators=indicators
            )
        elif bearish_count >= 2:
            confidence = min(90, 60 + bearish_count * 10)
            return StrategyResult(
                strategy_name=self.name, direction="PUT",
                confidence=confidence, indicators=indicators
            )
        elif bullish_count == 1:
            return StrategyResult(
                strategy_name=self.name, direction="CALL",
                confidence=55, indicators=indicators
            )
        elif bearish_count == 1:
            return StrategyResult(
                strategy_name=self.name, direction="PUT",
                confidence=55, indicators=indicators
            )

        return StrategyResult(strategy_name=self.name, direction="NONE", indicators=indicators)

    def _detect_patterns(self, candles: List[Candle]) -> List[str]:
        """Detect candlestick patterns in the recent candle list."""
        patterns = []
        n = len(candles)

        if n < 2:
            return patterns

        # Single-candle patterns
        last = candles[-1]
        prev = candles[-2]
        body = abs(last.close - last.open)
        full_range = last.high - last.low
        upper_wick = last.high - max(last.open, last.close)
        lower_wick = min(last.open, last.close) - last.low

        if full_range > 0:
            body_ratio = body / full_range
            lower_wick_ratio = lower_wick / body if body > 0 else 0
            upper_wick_ratio = upper_wick / body if body > 0 else 0

            # Doji
            if body_ratio < self.DOJI_MAX_RATIO:
                patterns.append("DOJI")

            # Hammer (bullish): small body at top, long lower wick
            if (body_ratio < 0.4 and lower_wick_ratio > 2.0 and
                    upper_wick_ratio < 0.5):
                patterns.append("HAMMER")

            # Inverted Hammer (bullish): small body at bottom, long upper wick
            elif (body_ratio < 0.4 and upper_wick_ratio > 2.0 and
                  lower_wick_ratio < 0.5):
                patterns.append("INVERTED_HAMMER")

            # Pin Bar (either direction)
            if lower_wick_ratio > self.PIN_BAR_RATIO and body_ratio < 0.3:
                patterns.append("PIN_BAR")
            elif upper_wick_ratio > self.PIN_BAR_RATIO and body_ratio < 0.3:
                patterns.append("PIN_BAR")

        # Two-candle patterns
        if n >= 2:
            prev_body = abs(prev.close - prev.open)
            last_body = body
            prev_range = prev.high - prev.low
            last_range = full_range

            if prev_range > 0 and last_range > 0:
                # Bullish Engulfing: last candle's body engulfs previous bearish body
                if (prev.close < prev.open and  # prev bearish
                    last.close > last.open and   # last bullish
                    last.open < prev.close and   # last open below prev close
                    last.close > prev.open and   # last close above prev open
                    last_body > prev_body):      # last body larger
                    patterns.append("BULLISH_ENGULFING")

                # Bearish Engulfing: last candle's body engulfs previous bullish body
                elif (prev.close > prev.open and  # prev bullish
                      last.close < last.open and   # last bearish
                      last.open > prev.close and   # last open above prev close
                      last.close < prev.open and   # last close below prev open
                      last_body > prev_body):      # last body larger
                    patterns.append("BEARISH_ENGULFING")

                # Piercing Line (bullish)
                if (prev.close < prev.open and  # prev bearish
                    last.open < prev.low and     # last opens below prev low
                    last.close > prev.close and  # last closes above prev close midpoint
                    last.close > (prev.open + prev.close) / 2):
                    patterns.append("PIERCING_LINE")

                # Dark Cloud Cover (bearish)
                if (prev.close > prev.open and  # prev bullish
                    last.open > prev.high and    # last opens above prev high
                    last.close < prev.close and  # last closes below prev close midpoint
                    last.close < (prev.open + prev.close) / 2):
                    patterns.append("DARK_CLOUD_COVER")

        # Three-candle patterns
        if n >= 3:
            third_last = candles[-3]
            second_last = candles[-2]
            last_candle = candles[-1]

            # Three Soldiers (bullish)
            if (third_last.close < third_last.open and
                second_last.close > second_last.open and
                last_candle.close > last_candle.open and
                second_last.close > third_last.close and
                last_candle.close > second_last.close):
                patterns.append("THREE_SOLDIERS")

            # Three Crows (bearish)
            if (third_last.close > third_last.open and
                second_last.close < second_last.open and
                last_candle.close < last_candle.open and
                second_last.close < third_last.close and
                last_candle.close < second_last.close):
                patterns.append("THREE_CROWS")

        return list(set(patterns))

    @staticmethod
    def patterns_to_direction(patterns: List[str]) -> str:
        """Convert pattern list to direction."""
        bullish = {"BULLISH_ENGULFING", "HAMMER", "INVERTED_HAMMER",
                    "PIERCING_LINE", "THREE_SOLDIERS"}
        bearish = {"BEARISH_ENGULFING", "SHOOTING_STAR", "DARK_CLOUD_COVER",
                    "THREE_CROWS"}

        has_bullish = any(p in bullish for p in patterns)
        has_bearish = any(p in bearish for p in patterns)

        if has_bullish and not has_bearish:
            return "CALL"
        elif has_bearish and not has_bullish:
            return "PUT"
        return "NONE"

    _BULLISH_PATTERNS = {"BULLISH_ENGULFING", "HAMMER", "INVERTED_HAMMER",
                         "PIERCING_LINE", "THREE_SOLDIERS"}
    _BEARISH_PATTERNS = {"BEARISH_ENGULFING", "DARK_CLOUD_COVER",
                         "THREE_CROWS"}
