# Strategies Module
from .ema_rsi import EmaRsiStrategy
from .bollinger import BollingerStrategy
from .zigzag_demark import ZigZagDeMarkerStrategy
from .macd_sr import MacdSupportResistanceStrategy
from .stochastic_rsi import StochasticRsiStrategy
from .adx_filter import ADXFilter
from .candlestick_patterns import CandlestickPatternDetector

__all__ = [
    "EmaRsiStrategy",
    "BollingerStrategy",
    "ZigZagDeMarkerStrategy",
    "MacdSupportResistanceStrategy",
    "StochasticRsiStrategy",
    "ADXFilter",
    "CandlestickPatternDetector",
]
