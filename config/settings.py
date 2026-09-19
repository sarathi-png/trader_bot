import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv


@dataclass
class Settings:
    # Quotex
    quotex_email: str = ""
    quotex_password: str = ""
    quotex_ssid: str = ""
    quotex_demo: bool = True
    # Headless Chromium for --login (servers / scheduled refresh). Default
    # False preserves the interactive first-login browser window.
    quotex_headless: bool = False

    # Telegram
    telegram_token: str = ""
    allowed_users: List[int] = field(default_factory=list)

    # Signal Engine
    min_confidence: int = 50
    min_payout: int = 80
    max_signals_per_day: int = 15
    min_confluence_categories: int = 3
    confluence_min_score: int = 60
    enable_adx_filter: bool = True
    enable_candlestick_patterns: bool = True
    enable_session_filter: bool = True
    session_minutes_start: int = 8
    session_minutes_end: int = 17

    # Database
    db_path: str = "data/signals.db"
    db_retention_days: int = 8

    # Sessions
    sessions_dir: str = "sessions"

    # Session Filters (UTC hours to block)
    blocked_hours: List[int] = field(default_factory=lambda: [1, 11, 17, 20])

    # Asset Categories
    categories: List[str] = field(default_factory=lambda: [
        "CURRENCIES", "CRYPTO", "COMMODITIES", "STOCKS"
    ])

    # Duration Options
    durations: List[str] = field(default_factory=lambda: [
        "1min", "3min", "5min", "15min"
    ])

    # News Filter
    news_filter_enabled: bool = True
    news_window_minutes: int = 30
    news_refresh_hours: int = 6

    # Mock mode
    mock_signal_interval: int = 60

    # WebSocket
    websocket_port: int = 8765
    websocket_enabled: bool = True

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/bot.log"

    @classmethod
    def from_env(cls):
        load_dotenv()

        allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
        allowed_list = [int(x.strip()) for x in allowed.split(",") if x.strip()]

        blocked = os.getenv("BLOCKED_HOURS", "1,11,17,20")
        blocked_list = [int(x.strip()) for x in blocked.split(",") if x.strip()]

        return cls(
            quotex_email=os.getenv("QUOTEX_EMAIL", ""),
            quotex_password=os.getenv("QUOTEX_PASSWORD", ""),
            quotex_ssid=os.getenv("QUOTEX_SSID", ""),
            quotex_demo=os.getenv("QUOTEX_DEMO", "true").lower() == "true",
            quotex_headless=os.getenv("QUOTEX_HEADLESS", "false").lower() == "true",
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            allowed_users=allowed_list,
            min_confidence=int(os.getenv("MIN_CONFIDENCE", "50")),
            min_payout=int(os.getenv("MIN_PAYOUT", "80")),
            max_signals_per_day=int(os.getenv("MAX_SIGNALS_PER_DAY", "15")),
            min_confluence_categories=int(os.getenv("MIN_CONFLUENCE_CATEGORIES", "3")),
            confluence_min_score=int(os.getenv("CONFLUENCE_MIN_SCORE", "60")),
            enable_adx_filter=os.getenv("ENABLE_ADX_FILTER", "true").lower() == "true",
            enable_candlestick_patterns=os.getenv("ENABLE_CANDLESTICK_PATTERNS", "true").lower() == "true",
            enable_session_filter=os.getenv("ENABLE_SESSION_FILTER", "true").lower() == "true",
            session_minutes_start=int(os.getenv("SESSION_MINUTES_START", "8")),
            session_minutes_end=int(os.getenv("SESSION_MINUTES_END", "17")),
            db_path=os.getenv("DB_PATH", "data/signals.db"),
            db_retention_days=int(os.getenv("DB_RETENTION_DAYS", "8")),
            sessions_dir=os.getenv("SESSIONS_DIR", "sessions"),
            blocked_hours=blocked_list,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE", "logs/bot.log"),
            news_filter_enabled=os.getenv("NEWS_FILTER_ENABLED", "true").lower() == "true",
            news_window_minutes=int(os.getenv("NEWS_WINDOW_MINUTES", "30")),
            news_refresh_hours=int(os.getenv("NEWS_REFRESH_HOURS", "6")),
            mock_signal_interval=int(os.getenv("MOCK_SIGNAL_INTERVAL", "60")),
            websocket_port=int(os.getenv("WEBSOCKET_PORT", "8765")),
            websocket_enabled=os.getenv("WEBSOCKET_ENABLED", "true").lower() == "true",
        )
