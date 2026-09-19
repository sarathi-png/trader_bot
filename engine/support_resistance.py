import logging
from typing import List, Tuple, Optional
from database.models import Candle

logger = logging.getLogger(__name__)


class SupportResistanceDetector:
    """Calculates support and resistance levels using pivot points
    and recent price action.

    Methods:
      - Pivot points (classic formula)
      - Recent swing highs/lows
      - Round number levels
    """

    def __init__(self, lookback: int = 50, swing_depth: int = 5):
        self.lookback = lookback
        self.swing_depth = swing_depth

    def detect(self, candles: List[Candle]) -> dict:
        """Detect support and resistance levels.

        Returns:
            dict with 'supports', 'resistances', 'nearest_support',
            'nearest_resistance', and 'distance_to_sr' (0-100%)
        """
        if not candles or len(candles) < self.swing_depth + 2:
            return self._empty_result()

        recent = candles[-self.lookback:] if len(candles) > self.lookback else candles
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        closes = [c.close for c in recent]

        # Calculate pivot points (classic)
        pivot = self._calc_pivot(highs[-1], lows[-1], closes[-1]) if len(highs) >= 3 else None

        # Find swing highs and lows
        swing_highs = self._find_swing_highs(recent)
        swing_lows = self._find_swing_lows(recent)

        # Round number levels (psychological levels)
        round_levels = self._calc_round_levels(closes[-1])

        # Combine all resistance levels
        resistances = sorted(set(
            [p["r1"], p["r2"], p["r3"]] if pivot else [] +
            [h for h in swing_highs[-3:]] +
            round_levels["resistances"]
        ), reverse=True)[:5]

        # Combine all support levels
        supports = sorted(set(
            [p["s1"], p["s2"], p["s3"]] if pivot else [] +
            [l for l in swing_lows[-3:]] +
            round_levels["supports"]
        ))[:5]

        current_price = closes[-1]
        nearest_support = self._nearest_level(current_price, supports, direction="below")
        nearest_resistance = self._nearest_level(current_price, resistances, direction="above")

        # Distance to nearest S/R as percentage (0-100% where 0 = at level)
        if supports and resistances:
            dist_to_support = abs(current_price - nearest_support) / current_price * 100 if nearest_support else 100
            dist_to_resistance = abs(nearest_resistance - current_price) / current_price * 100 if nearest_resistance else 100
            min_dist = min(dist_to_support, dist_to_resistance)
            distance_pct = max(0, 100 - min_dist * 10)  # 0% = at level, 100% = far
        else:
            distance_pct = 50
            nearest_support = current_price
            nearest_resistance = current_price

        return {
            "supports": supports,
            "resistances": resistances,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "distance_to_sr": round(distance_pct, 1),
            "pivot": pivot,
        }

    def _calc_pivot(self, high: float, low: float, close: float) -> dict:
        """Calculate classic pivot points."""
        pivot = (high + low + close) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        r3 = high + 2 * (pivot - low)
        s3 = low - 2 * (high - pivot)
        return {"pivot": pivot, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}

    def _find_swing_highs(self, candles: List[Candle]) -> List[float]:
        """Find swing high points."""
        highs = []
        for i in range(self.swing_depth, len(candles) - self.swing_depth):
            current_high = candles[i].high
            is_swing = all(current_high >= candles[i + j].high for j in range(-self.swing_depth, self.swing_depth + 1) if j != 0)
            if is_swing:
                highs.append(current_high)
        return highs

    def _find_swing_lows(self, candles: List[Candle]) -> List[float]:
        """Find swing low points."""
        lows = []
        for i in range(self.swing_depth, len(candles) - self.swing_depth):
            current_low = candles[i].low
            is_swing = all(current_low <= candles[i + j].low for j in range(-self.swing_depth, self.swing_depth + 1) if j != 0)
            if is_swing:
                lows.append(current_low)
        return lows

    def _calc_round_levels(self, price: float) -> dict:
        """Calculate psychological round number levels near current price."""
        magnitude = 10 ** (len(str(int(price))) - 1) if price > 0 else 1
        base = round(price / magnitude) * magnitude

        resistances = [base + magnitude * i for i in range(1, 4)]
        supports = [base - magnitude * i for i in range(1, 4)]
        return {"resistances": resistances, "supports": supports}

    def _nearest_level(self, price: float, levels: List[float], direction: str) -> float:
        """Find the nearest level above or below the current price."""
        if not levels:
            return price

        if direction == "below":
            below = [l for l in levels if l < price]
            return max(below) if below else levels[0] if levels else price
        else:
            above = [l for l in levels if l > price]
            return min(above) if above else levels[-1] if levels else price

    def _empty_result(self) -> dict:
        return {
            "supports": [], "resistances": [],
            "nearest_support": 0, "nearest_resistance": 0,
            "distance_to_sr": 50, "pivot": None,
        }

    def is_near_support(self, candles: List[Candle], threshold_pct: float = 1.0) -> bool:
        """Check if current price is near a support level."""
        if not candles:
            return False
        result = self.detect(candles)
        if not result["supports"]:
            return False
        current = candles[-1].close
        nearest = result["nearest_support"]
        if nearest <= 0:
            return False
        return abs(current - nearest) / current * 100 <= threshold_pct

    def is_near_resistance(self, candles: List[Candle], threshold_pct: float = 1.0) -> bool:
        """Check if current price is near a resistance level."""
        if not candles:
            return False
        result = self.detect(candles)
        if not result["resistances"]:
            return False
        current = candles[-1].close
        nearest = result["nearest_resistance"]
        if nearest <= 0:
            return False
        return abs(current - nearest) / current * 100 <= threshold_pct
