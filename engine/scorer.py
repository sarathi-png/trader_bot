import logging
from typing import List, Tuple, Dict
from database.models import StrategyResult
from strategies import (
    EmaRsiStrategy, BollingerStrategy, ZigZagDeMarkerStrategy,
    MacdSupportResistanceStrategy, StochasticRsiStrategy,
    ADXFilter, CandlestickPatternDetector
)
from engine.confluence_engine import ConfluenceEngine
from engine.support_resistance import SupportResistanceDetector

logger = logging.getLogger(__name__)


class ConfluenceScorer:
    """Enhanced confluence scorer using multi-layer quality gate.

    Combines traditional strategy signals with a ConfluenceEngine
    that checks agreement across TREND, LEVEL, MOMENTUM,
    PRICE_ACTION, and STRENGTH categories.

    A signal is only emitted when at least 3 of 5 categories agree
    and the total score meets the minimum threshold.
    """

    def __init__(self, min_confidence: int = 50, performance_window: int = 20,
                 min_categories: int = 3, confluence_min_score: int = 60):
        self.min_confidence = min_confidence
        self.performance_window = performance_window
        self.confluence_engine = ConfluenceEngine(
            min_categories=min_categories,
            min_score=confluence_min_score,
        )
        self.sr_detector = SupportResistanceDetector()

        self.strategy_performance = {
            "EMA_RSI": 0.5,
            "BOLLINGER": 0.5,
            "ZIGZAG_DEMARK": 0.5,
            "MACD_SR": 0.5,
            "STOCH_RSI": 0.5,
            "ADX_FILTER": 0.5,
            "CANDLESTICK_PATTERNS": 0.5,
        }
        self.strategy_weights = {
            "EMA_RSI": 0.20,
            "BOLLINGER": 0.15,
            "ZIGZAG_DEMARK": 0.15,
            "MACD_SR": 0.15,
            "STOCH_RSI": 0.15,
            "ADX_FILTER": 0.10,
            "CANDLESTICK_PATTERNS": 0.10,
        }
        self.strategies = [
            EmaRsiStrategy(),
            BollingerStrategy(),
            ZigZagDeMarkerStrategy(),
            MacdSupportResistanceStrategy(),
            StochasticRsiStrategy(),
            ADXFilter(),
            CandlestickPatternDetector(),
        ]

    def analyze(self, candles) -> Tuple[str, int, List[str], Dict]:
        results = []
        for strategy in self.strategies:
            result = strategy.evaluate(candles)
            results.append(result)

        direction, confidence, aligned = self._calculate_confidence(results)

        indicators = {}
        for r in results:
            indicators[r.strategy_name] = r.indicators

        return direction, confidence, aligned, indicators

    def _calculate_confidence(self, results: List[StrategyResult]) -> Tuple[str, int, List[str]]:
        adjusted_weights = self.strategy_weights.copy()
        for strategy_name in self.strategy_performance:
            performance = self.strategy_performance[strategy_name]
            if performance < 0.4:
                adjusted_weights[strategy_name] *= 0.5
            elif performance > 0.7:
                adjusted_weights[strategy_name] *= 1.2

        total_weight = sum(adjusted_weights.values())
        if total_weight > 0:
            adjusted_weights = {k: v / total_weight for k, v in adjusted_weights.items()}

        call_strategies = [r for r in results if r.direction == "CALL"]
        put_strategies = [r for r in results if r.direction == "PUT"]

        if len(call_strategies) > len(put_strategies):
            direction = "CALL"
            agreeing = call_strategies
        elif len(put_strategies) > len(call_strategies):
            direction = "PUT"
            agreeing = put_strategies
        else:
            return "NONE", 0, []

        # Strategy-level weighted score
        strategy_score = 0
        aligned_names = []
        for result in agreeing:
            weight = adjusted_weights.get(result.strategy_name, 0.1)
            strength = max(0.0, min(100.0, float(result.confidence))) / 100.0
            strategy_score += weight * strength
            aligned_names.append(result.strategy_name)

        strategy_score = round(strategy_score * 100, 2)
        strategy_score = max(0, min(100, int(strategy_score)))

        # Extract candle patterns for confluence engine
        candle_results = [r for r in results if r.strategy_name == "CANDLESTICK_PATTERNS"]
        candle_patterns = []
        for cr in candle_results:
            pats = cr.indicators.get("patterns", [])
            if pats:
                candle_patterns = pats

        # Extract ADX value
        adx_result = [r for r in results if r.strategy_name == "ADX_FILTER"]
        adx_value = 0.0
        if adx_result:
            adx_value = float(adx_result[0].indicators.get("adx", 0))

        # Run confluence engine check on the raw candle data
        # (we pass results, candles, and derived values)
        # Note: confluence_engine.evaluate needs List[Candle] which we don't have here
        # The confluence check is done in main.py where candles are available

        # Use strategy score as baseline, then main.py applies confluence gate
        return direction, strategy_score, aligned_names

    def evaluate_confluence(
        self,
        candles,
        strategy_results: List[StrategyResult],
        mtf_trend: str = "NEUTRAL",
        adx_value: float = 0.0,
        candle_patterns: List[str] = None,
    ) -> Tuple[bool, Dict, int, int]:
        """Full confluence evaluation combining strategy signals with
        category-level agreement check.

        Returns:
            (approved, category_scores, total_score, agreeing_categories)
        """
        approved, category_scores, total_score = self.confluence_engine.evaluate(
            strategy_results=strategy_results,
            candles=candles,
            mtf_trend=mtf_trend,
            adx_value=adx_value,
            candle_patterns=candle_patterns,
        )
        agreeing = sum(1 for s in category_scores.values() if s >= 1)
        return approved, category_scores, total_score, agreeing

    def has_signal(self, confidence: int) -> bool:
        return confidence >= self.min_confidence

    def get_break_even_winrate(self, payout: int) -> float:
        return 100 / (100 + payout)

    def update_strategy_performance(self, strategy_name: str, won: bool):
        """Update rolling performance tracking for a strategy."""
        if strategy_name in self.strategy_performance:
            self.strategy_performance[strategy_name] = (
                self.strategy_performance[strategy_name] * 0.9 + (1.0 if won else 0.0) * 0.1
            )
