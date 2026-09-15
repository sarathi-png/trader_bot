from typing import List, Tuple, Dict
from database.models import StrategyResult
from strategies import (
    EmaRsiStrategy, BollingerStrategy, ZigZagDeMarkerStrategy,
    MacdSupportResistanceStrategy, StochasticRsiStrategy
)


class ConfluenceScorer:
    def __init__(self, min_confidence: int = 65):
        self.min_confidence = min_confidence
        self.strategies = [
            EmaRsiStrategy(),
            BollingerStrategy(),
            ZigZagDeMarkerStrategy(),
            MacdSupportResistanceStrategy(),
            StochasticRsiStrategy(),
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
        weights = {
            "EMA_RSI": 25,
            "BOLLINGER": 20,
            "ZIGZAG_DEMARK": 20,
            "MACD_SR": 20,
            "STOCH_RSI": 15,
        }

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

        # Weighted confluence: each aligned strategy contributes its fixed
        # weight scaled by its own trigger strength (confidence/100). This
        # makes a weak trigger (60) count for less than a strong one (90+).
        # The scale is capped so the theoretical maximum score is still 100.
        score = 0
        aligned_names = []
        for result in agreeing:
            weight = weights.get(result.strategy_name, 10)
            strength = max(0.0, min(100.0, float(result.confidence))) / 100.0
            score += weight * strength
            aligned_names.append(result.strategy_name)

        score = round(score, 1)
        score = max(0, min(100, int(score)))

        return direction, score, aligned_names

    def has_signal(self, confidence: int) -> bool:
        return confidence >= self.min_confidence

    def get_break_even_winrate(self, payout: int) -> float:
        return 100 / (100 + payout)
