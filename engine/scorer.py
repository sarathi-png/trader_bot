from typing import List, Tuple, Dict
from database.models import StrategyResult
from strategies import (
    EmaRsiStrategy, BollingerStrategy, ZigZagDeMarkerStrategy,
    MacdSupportResistanceStrategy, StochasticRsiStrategy
)


class ConfluenceScorer:
    def __init__(self, min_confidence: int = 70, performance_window: int = 20):
        self.min_confidence = min_confidence
        self.performance_window = performance_window
        self.strategy_performance = {
            "EMA_RSI": 0.5,
            "BOLLINGER": 0.5,
            "ZIGZAG_DEMARK": 0.5,
            "MACD_SR": 0.5,
            "STOCH_RSI": 0.5,
        }
        self.strategy_weights = {
            "EMA_RSI": 0.25,
            "BOLLINGER": 0.20,
            "ZIGZAG_DEMARK": 0.20,
            "MACD_SR": 0.20,
            "STOCH_RSI": 0.15,
        }
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
        # Adjust weights based on recent performance
        adjusted_weights = self.strategy_weights.copy()
        for strategy_name in self.strategy_performance:
            performance = self.strategy_performance[strategy_name]
            if performance < 0.4:             # Poor performance, reduce weight
                adjusted_weights[strategy_name] *= 0.5
            elif performance > 0.7:  # Good performance, increase weight
                adjusted_weights[strategy_name] *= 1.2

        # Normalize weights
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

        score = 0
        aligned_names = []
        for result in agreeing:
            weight = adjusted_weights.get(result.strategy_name, 0.1)
            strength = max(0.0, min(100.0, float(result.confidence))) / 100.0
            score += weight * strength
            aligned_names.append(result.strategy_name)

        score = round(score * 100, 2)
        score = max(0, min(100, int(score)))

        return direction, score, aligned_names

    def has_signal(self, confidence: int) -> bool:
        return confidence >= self.min_confidence

    def get_break_even_winrate(self, payout: int) -> float:
        return 100 / (100 + payout)
