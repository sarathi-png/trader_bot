from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Candle:
    timestamp: int
    asset: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Signal:
    id: str
    asset: str
    direction: str  # "CALL" or "PUT"
    confidence: int  # 0-100
    strategies: List[str] = field(default_factory=list)
    duration: str = "3min"
    entry_time: Optional[datetime] = None
    entry_price: float = 0.0  # display estimate shown in the alert (T0)
    actual_entry_price: Optional[float] = None  # authoritative entry used for grading (T0 + pre-entry gap)
    exit_price: float = 0.0
    mtf_trend: str = ""  # "UP", "DOWN", "NEUTRAL", "CONFLICT"
    payout: int = 0
    status: str = "PENDING"  # PENDING, WIN, LOSS, SKIP
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class User:
    telegram_id: int
    username: str = ""
    categories: List[str] = field(default_factory=lambda: ["CURRENCIES", "CRYPTO", "COMMODITIES", "STOCKS"])
    duration: str = "3min"
    frequency: str = "normal"  # conservative, normal, aggressive
    quiet_hours_start: int = 23
    quiet_hours_end: int = 7
    enabled: bool = True
    favorite_assets: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Asset:
    name: str
    category: str  # CURRENCIES, CRYPTO, COMMODITIES, STOCKS
    payout: int = 0
    active: bool = True
    is_otc: bool = False

    def __post_init__(self):
        self.is_otc = "_otc" in self.name.lower()


@dataclass
class StrategyResult:
    strategy_name: str
    direction: str  # "CALL", "PUT", or "NONE"
    confidence: int = 0
    indicators: dict = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class PerformanceStats:
    total_signals: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    best_asset: str = ""
    best_asset_wr: float = 0.0
    today_signals: int = 0
    today_wins: int = 0
