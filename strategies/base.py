from abc import ABC, abstractmethod
from typing import List
import pandas as pd
from database.models import Candle, StrategyResult


class BaseStrategy(ABC):
    name: str = "BaseStrategy"
    weight: int = 10

    @abstractmethod
    def evaluate(self, candles: List[Candle]) -> StrategyResult:
        pass

    def candles_to_dataframe(self, candles: List[Candle]) -> pd.DataFrame:
        data = {
            "timestamp": [c.timestamp for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df
