import asyncio
import logging
from typing import Callable, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class QuotexConnection:
    def __init__(self, email: str = "", password: str = "", ssid: str = "", is_demo: bool = True):
        self.email = email
        self.password = password
        self.ssid = ssid
        self.is_demo = is_demo
        self.client = None
        self.connected = False
        self.candle_handlers: Dict[str, Callable] = {}
        self._reconnect_attempts = 3
        self._reconnect_delay = 5

    async def connect(self) -> bool:
        for attempt in range(self._reconnect_attempts):
            try:
                from pyquotex.stable_api import Quotex

                self.client = Quotex(
                    email=self.email,
                    password=self.password,
                    lang="en"
                )

                ssid = self.ssid
                if not ssid:
                    ssid = await self._load_or_fetch_ssid()

                if ssid:
                    logger.info("Connecting with SSID (bypassing HTTP login)...")
                    self.client.set_session(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                        ssid=ssid
                    )
                else:
                    logger.info("Connecting with email/password...")

                result = await self.client.connect()
                if isinstance(result, tuple):
                    success, reason = result
                else:
                    success = bool(result)
                    reason = str(result)

                if success:
                    self.connected = True
                    logger.info("Connected to Quotex successfully")
                    return True
                else:
                    logger.warning(f"Connection attempt {attempt + 1} rejected: {reason}")
                    if "token" in reason.lower() or "session" in reason.lower() or "auth" in reason.lower():
                        logger.info("SSID may be expired, attempting refresh...")
                        new_ssid = await self._refresh_ssid()
                        if new_ssid:
                            self.ssid = new_ssid
                            continue
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < self._reconnect_attempts - 1:
                    await asyncio.sleep(self._reconnect_delay)
        logger.error("Failed to connect to Quotex after all attempts")
        return False

    async def _load_or_fetch_ssid(self) -> Optional[str]:
        try:
            from auth.ssid_extractor import load_session, get_or_refresh_ssid
            session = load_session()
            if session:
                ssid = session.get("ssid", "")
                if ssid:
                    logger.info("Loaded SSID from session file")
                    return ssid

            if self.email and self.password:
                logger.info("No cached SSID, running extractor...")
                return await get_or_refresh_ssid(
                    email=self.email,
                    password=self.password,
                    headless=True,
                    is_demo=self.is_demo,
                )
        except ImportError:
            logger.debug("auth module not available")
        return None

    async def _refresh_ssid(self) -> Optional[str]:
        try:
            from auth.ssid_extractor import get_or_refresh_ssid
            if self.email and self.password:
                return await get_or_refresh_ssid(
                    email=self.email,
                    password=self.password,
                    force_refresh=True,
                    headless=True,
                    is_demo=self.is_demo,
                )
        except ImportError:
            logger.debug("auth module not available for refresh")
        return None

    async def disconnect(self):
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass
        self.connected = False

    async def reconnect(self) -> bool:
        await self.disconnect()
        return await self.connect()

    async def get_balance(self) -> float:
        if not self.connected:
            raise ConnectionError("Not connected to Quotex")
        try:
            balance = await self.client.get_balance()
            if hasattr(balance, 'balance'):
                return balance.balance
            return float(balance) if balance else 0.0
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise

    async def get_assets(self) -> list:
        if not self.connected:
            raise ConnectionError("Not connected to Quotex")
        try:
            raw_assets = await self.client.get_all_assets()
            assets = []
            if isinstance(raw_assets, dict):
                for name, payout in raw_assets.items():
                    category = self._categorize_asset(name)
                    assets.append({
                        "name": name,
                        "payout": int(payout) if payout else 0,
                        "category": category
                    })
            return assets
        except Exception as e:
            logger.error(f"Failed to get assets: {e}")
            return []

    def _categorize_asset(self, name: str) -> str:
        name_upper = name.upper().replace("_OTC", "")

        crypto_tickers = [
            "BTC", "ETH", "XRP", "BNB", "SOL", "ADA", "DOGE", "DOT",
            "LTC", "BCH", "ETC", "ZEC", "LINK", "LIN", "AXS", "AVA",
            "ATOM", "ATO", "DASH", "DAS", "TON", "TRU", "SHIB", "MATIC",
            "UNI", "AAVE", "FIL", "NEAR", "APT", "ARB", "OP", "SUI",
            "PEPE", "WLD", "INJ", "SEI", "TIA", "JUP", "RUNE", "FTM",
        ]

        commodities = [
            "XAU", "XAG", "GOLD", "SILVER", "OIL", "CRUDE", "BRENT",
            "UKBRENT", "USCRUDE", "WTI", "NATGAS", "COPPER", "PLATINUM",
        ]

        indices = [
            "F40EUR", "FTSGBP", "HSIHKD", "IBXEUR", "JPXJPY", "STXEUR",
            "CHIA50", "AXJAUD", "SPX", "NAS", "DAX", "CAC", "NIKKEI",
            "HANG", "SENSEX", "NIFTY", "ASX", "DOW", "S&P", "FTSE",
        ]

        for c in crypto_tickers:
            if name_upper.startswith(c) or f"{c}USD" in name_upper:
                return "CRYPTO"
        for c in commodities:
            if c in name_upper:
                return "COMMODITIES"
        for i in indices:
            if i in name_upper:
                return "STOCKS"
        return "CURRENCIES"

    async def get_candle_data(self, asset: str, timeframe: int = 60, count: int = 100) -> list:
        if not self.connected:
            raise ConnectionError("Not connected to Quotex")
        try:
            seconds_needed = timeframe * (count + 20)
            raw_candles = await self.client.get_historical_candles(
                asset=asset,
                amount_of_seconds=seconds_needed,
                period=timeframe,
                timeout=30,
            )
            if not raw_candles:
                return []

            result = []
            for c in raw_candles:
                result.append({
                    "timestamp": c.get("time", 0),
                    "open": c.get("open", 0),
                    "high": c.get("high", 0),
                    "low": c.get("low", 0),
                    "close": c.get("close", 0),
                    "volume": c.get("volume", 0)
                })
            result.sort(key=lambda x: x["timestamp"])
            return result[-count:]
        except Exception as e:
            logger.error(f"Failed to get candles for {asset}: {e}")
            return []

    async def subscribe_candles(self, asset: str, timeframe: int = 60):
        if not self.connected:
            raise ConnectionError("Not connected to Quotex")
        try:
            if hasattr(self.client, 'start_candles_one_stream'):
                await self.client.start_candles_one_stream(asset, timeframe)
                logger.info(f"Subscribed to candles for {asset}")
            else:
                logger.debug(f"No candle streaming available for {asset}")
        except Exception as e:
            logger.debug(f"Failed to subscribe to candles for {asset}: {e}")

    async def get_realtime_candles(self, asset: str):
        """Fetch the latest realtime candle tick for an asset.

        pyquotex exposes a poll (not a push callback): after the server-side
        stream has been started with subscribe_candles(), the latest tick is
        read from shared state via get_realtime_candles(). A tick is a list of
        the form [symbol, timestamp, price] (some versions append direction).
        """
        if not self.connected:
            raise ConnectionError("Not connected to Quotex")
        try:
            if hasattr(self.client, 'get_realtime_candles'):
                return await self.client.get_realtime_candles(asset)
            logger.debug(f"get_realtime_candles not available on client for {asset}")
        except Exception as e:
            logger.debug(f"Failed to read realtime candles for {asset}: {e}")
        return []

    def on_candle(self, asset: str, handler: Callable):
        self.candle_handlers[asset] = handler

    async def listen_for_candles(self):
        if not self.connected:
            return
        try:
            while self.connected:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Candle listener error: {e}")
            self.connected = False


class MockQuotexConnection:
    """Mock connection for testing without real Quotex account"""

    def __init__(self):
        self.connected = False
        self.candle_handlers = {}
        self._mock_data = []
        self._mock_drift = {}

    async def connect(self) -> bool:
        self.connected = True
        logger.info("Mock Quotex connection established")
        return True

    async def disconnect(self):
        self.connected = False

    async def reconnect(self) -> bool:
        return await self.connect()

    async def get_balance(self) -> float:
        return 10000.0

    async def get_assets(self) -> list:
        return [
            {"name": "EURUSD_otc", "payout": 92, "category": "CURRENCIES"},
            {"name": "GBPUSD_otc", "payout": 90, "category": "CURRENCIES"},
            {"name": "USDJPY_otc", "payout": 88, "category": "CURRENCIES"},
            {"name": "BTCUSD_otc", "payout": 85, "category": "CRYPTO"},
            {"name": "ETHUSD_otc", "payout": 84, "category": "CRYPTO"},
            {"name": "XAUUSD_otc", "payout": 86, "category": "COMMODITIES"},
            {"name": "AAPL_otc", "payout": 82, "category": "STOCKS"},
            {"name": "GOOGL_otc", "payout": 83, "category": "STOCKS"},
        ]

    async def subscribe_candles(self, asset: str, timeframe: int = 60):
        logger.info(f"Mock: Subscribed to {asset}")

    async def get_realtime_candles(self, asset: str) -> list:
        """Simulate a live price tick feed for testing the polling path."""
        import random
        base_price = 1.1000 if "EUR" in asset else 1.3000 if "GBP" in asset else 150.0
        drift = self._mock_drift.get(asset, base_price)
        change = random.uniform(-0.0005, 0.0005)
        drift = max(drift * 0.5, min(drift * 1.5, drift + change))
        self._mock_drift[asset] = drift
        ts = int(datetime.now().timestamp())
        return [asset, ts, round(drift, 5)]

    async def get_candle_data(self, asset: str, timeframe: int = 60, count: int = 100) -> list:
        import random
        base_price = 1.1000 if "EUR" in asset else 1.3000 if "GBP" in asset else 150.0
        candles = []
        now = int(datetime.now().timestamp())
        for i in range(count):
            change = random.uniform(-0.002, 0.002)
            o = base_price * (1 + change)
            h = o * (1 + random.uniform(0, 0.001))
            l = o * (1 - random.uniform(0, 0.001))
            c = o * (1 + random.uniform(-0.001, 0.001))
            candles.append({
                "timestamp": now - (count - i) * 60,
                "open": o, "high": h, "low": l, "close": c, "volume": random.randint(100, 1000)
            })
            base_price = c
        return candles

    def on_candle(self, asset: str, handler):
        self.candle_handlers[asset] = handler

    async def listen_for_candles(self):
        while self.connected:
            await asyncio.sleep(1)
