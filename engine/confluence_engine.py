import logging
from typing import List, Tuple, Dict
from database.models import Candle, StrategyResult
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

CATEGORIES = {
    "TREND": ["EMA_RSI", "ZIGZAG_DEMARK", "MACD_SR"],
    "LEVEL": ["BOLLINGER", "MACD_SR"],
    "MOMENTUM": ["EMA_RSI", "STOCH_RSI"],
    "PRICE_ACTION": [],
    "STRENGTH": ["ZIGZAG_DEMARK", "STOCH_RSI"],
}


class ConfluenceEngine:
    """Multi-layer quality gate requiring agreement across 3-4 of 5 categories.

    Categories:
      1. TREND    — direction from EMA, ZigZag, MACD
      2. LEVEL    — signal near support/resistance or Bollinger band
      3. MOMENTUM — RSI / Stochastic confirming direction
      4. PRICE_ACTION — candlestick pattern confirmation
      5. STRENGTH — ADX / volatility confirming trend strength

    A signal is only emitted when at least MIN_CATEGORIES categories agree.
    """

    MIN_CATEGORIES = 3
    MIN_SCORE = 60

    def __init__(self, min_categories: int = 3, min_score: int = 60):
        self.min_categories = min_categories
        self.min_score = min_score
        self.category_scores: Dict[str, int] = {}

    def evaluate(
        self,
        strategy_results: List[StrategyResult],
        candles: List[Candle],
        mtf_trend: str = "NEUTRAL",
        adx_value: float = 0.0,
        candle_patterns: List[str] = None,
    ) -> Tuple[bool, Dict, int]:
        """Evaluate confluence across all categories.

        Returns:
            (approved, category_scores, total_score)
        """
        candle_patterns = candle_patterns or []
        self.category_scores = {}

        # Build lookup by strategy name
        result_map = {r.strategy_name: r for r in strategy_results}

        # Category 1: TREND
        trend_agreement = self._check_trend(result_map, mtf_trend)
        self.category_scores["TREND"] = trend_agreement

        # Category 2: LEVEL — check if price is near Bollinger band or S/R
        level_agreement = self._check_level(result_map, candles)
        self.category_scores["LEVEL"] = level_agreement

        # Category 3: MOMENTUM
        momentum_agreement = self._check_momentum(result_map)
        self.category_scores["MOMENTUM"] = momentum_agreement

        # Category 4: PRICE_ACTION — candlestick patterns
        price_action_agreement = self._check_price_action(candle_patterns, mtf_trend)
        self.category_scores["PRICE_ACTION"] = price_action_agreement

        # Category 5: STRENGTH — ADX and volatility
        strength_agreement = self._check_strength(adx_value)
        self.category_scores["STRENGTH"] = strength_agreement

        # Count agreeing categories
        agreeing = sum(1 for score in self.category_scores.values() if score >= 1)
        total_score = sum(self.category_scores.values())

        approved = agreeing >= self.min_categories and total_score >= self.MIN_SCORE

        if not approved:
            logger.debug(
                f"Confluence rejected: {agreeing}/{len(self.category_scores)} categories, "
                f"score={total_score}, min={self.min_categories}/{self.MIN_SCORE}"
            )

        return approved, self.category_scores, total_score

    def _check_trend(self, result_map: Dict, mtf_trend: str) -> int:
        """Check if trend indicators agree with direction."""
        trend_strategies = ["EMA_RSI", "ZIGZAG_DEMARK", "MACD_SR"]
        call_count = sum(1 for s in trend_strategies if result_map.get(s) and result_map[s].direction == "CALL")
        put_count = sum(1 for s in trend_strategies if result_map.get(s) and result_map[s].direction == "PUT")

        if mtf_trend == "UP" and call_count >= 1:
            return 2
        elif mtf_trend == "DOWN" and put_count >= 1:
            return 2
        elif call_count >= 2:
            return 2
        elif put_count >= 2:
            return 2
        elif call_count >= 1 or put_count >= 1:
            return 1
        return 0

    def _check_level(self, result_map: Dict, candles: List[Candle]) -> int:
        """Check if signal is near a support/resistance level or Bollinger band."""
        if not candles or len(candles) < 20:
            return 0

        close = candles[-1].close
        highs = [c.high for c in candles[-20:]]
        lows = [c.low for c in candles[-20:]]

        recent_high = max(highs)
        recent_low = min(lows)
        range_pct = (recent_high - recent_low) / close * 100 if close > 0 else 0

        # Near recent low (support) → CALL level check
        # Near recent high (resistance) → PUT level check
        distance_from_low = (close - recent_low) / (recent_high - recent_low) * 100 if recent_high != recent_low else 50

        score = 0
        # Bollinger band check
        bollinger_strat = result_map.get("BOLLINGER")
        if bollinger_strat:
            if bollinger_strat.direction == "CALL" and distance_from_low < 40:
                score += 2
            elif bollinger_strat.direction == "PUT" and distance_from_low > 60:
                score += 2

        # S/R proximity check
        if distance_from_low < 20 or distance_from_low > 80:
            score += 1

        if bollinger_strat:
            score += 1  # Bollinger strategy itself indicates a level

        return min(score, 2)

    def _check_momentum(self, result_map: Dict) -> int:
        """Check if momentum indicators confirm direction."""
        rsi_strat = result_map.get("EMA_RSI")
        stoch_strat = result_map.get("STOCH_RSI")

        call_momentum = 0
        put_momentum = 0

        if rsi_strat and rsi_strat.direction != "NONE":
            if rsi_strat.direction == "CALL":
                call_momentum += 1
            else:
                put_momentum += 1

        if stoch_strat and stoch_strat.direction != "NONE":
            if stoch_strat.direction == "CALL":
                call_momentum += 1
            else:
                put_momentum += 1

        if call_momentum >= 2:
            return 2
        elif put_momentum >= 2:
            return 2
        elif call_momentum >= 1 or put_momentum >= 1:
            return 1
        return 0

    def _check_price_action(self, candle_patterns: List[str], mtf_trend: str) -> int:
        """Check for confirming candlestick patterns."""
        if not candle_patterns:
            return 0

        bullish_patterns = {"BULLISH_ENGULFING", "HAMMER", "PIN_BAR", "PIERCING_LINE", "THREE_SOLDIERS"}
        bearish_patterns = {"BEARISH_ENGULFING", "SHOOTING_STAR", "PIN_BAR", "DARK_CLOUD", "THREE_CROWS"}

        has_bullish = any(p in bullish_patterns for p in candle_patterns)
        has_bearish = any(p in bearish_patterns for p in candle_patterns)

        if mtf_trend == "UP" and has_bullish:
            return 2
        elif mtf_trend == "DOWN" and has_bearish:
            return 2
        elif has_bullish:
            return 1
        elif has_bearish:
            return 1
        return 0

    def _check_strength(self, adx_value: float) -> int:
        """Check if ADX confirms trend strength."""
        if adx_value >= 25:
            return 2
        elif adx_value >= 20:
            return 1
        return 0

    def get_summary(self) -> Dict:
        return {
            "categories": self.category_scores,
            "agreeing_count": sum(1 for s in self.category_scores.values() if s >= 1),
            "total_score": sum(self.category_scores.values()),
            "approved": self.category_scores.get("TREND", 0) > 0,
        }
