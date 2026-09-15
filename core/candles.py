import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from database.models import Candle, Asset
from database.repository import Database
from core.connection import QuotexConnection

logger = logging.getLogger(__name__)


class CandleCollector:
    """Collects historical candles and ingests live closed 1-minute candles.

    Live candles are read via a poll (pyquotex exposes a poll, not a push
    callback): we subscribe to the server-side stream once per asset, then
    poll the provider's latest tick each second, aggregate ticks into 1-minute
    buckets, and only persist a bucket once it has closed (i.e. when a tick
    belonging to the next minute has been observed).
    """

    POLL_INTERVAL_SECONDS = 1.0
    STALE_FEED_SECONDS = 90
    TOP_ASSETS = 15

    def __init__(self, connection: QuotexConnection, db: Database):
        self.connection = connection
        self.db = db
        self.callbacks: List[Callable] = []
        self.assets: List[Asset] = []
        self._poll_task: Optional[asyncio.Task] = None
        # per-asset: {minute_start_ts: {open, high, low, close}}
        self._minute_buckets: Dict[str, dict] = {}
        self._last_saved_ts: Dict[str, int] = {}
        self._last_tick_monotonic: Dict[str, float] = {}
        self._last_stale_warn: Dict[str, float] = {}

    def on_new_candle(self, callback: Callable):
        self.callbacks.append(callback)

    async def discover_assets(self):
        try:
            raw_assets = await self.connection.get_assets()
            for raw in raw_assets:
                asset = Asset(
                    name=raw.get("name", ""),
                    category=raw.get("category", "CURRENCIES"),
                    payout=raw.get("payout", 0),
                    active=True
                )
                await self.db.save_asset(asset)
                self.assets.append(asset)
            logger.info(f"Discovered {len(self.assets)} assets")
        except Exception as e:
            logger.error(f"Asset discovery failed: {e}")

    async def subscribe_all(self):
        sorted_assets = sorted(self.assets, key=lambda a: a.payout, reverse=True)[:self.TOP_ASSETS]
        for asset in sorted_assets:
            self.connection.on_candle(asset.name, self._handle_candle)
            try:
                # Actually start the provider-side stream for this asset; without
                # this, get_realtime_candles() has nothing to poll.
                await self.connection.subscribe_candles(asset.name, 60)
            except Exception as e:
                logger.warning(f"Failed to subscribe live stream for {asset.name}: {e}")
        logger.info(f"Subscribed to live candle streams for top {len(sorted_assets)} assets")

    async def _handle_candle(self, asset_name: str, candle_data: dict):
        candle = Candle(
            timestamp=candle_data.get("timestamp", int(datetime.now().timestamp())),
            asset=asset_name,
            open=candle_data.get("open", 0),
            high=candle_data.get("high", 0),
            low=candle_data.get("low", 0),
            close=candle_data.get("close", 0),
            volume=candle_data.get("volume", 0)
        )
        await self.db.save_candle(candle)
        for callback in self.callbacks:
            try:
                await callback(asset_name, candle)
            except Exception as e:
                logger.error(f"Candle callback error for {asset_name}: {e}")

    async def load_historical(self, asset_name: str, count: int = 300):
        try:
            candles = await self.connection.get_candle_data(asset_name, 60, count)
            for c in candles:
                candle = Candle(
                    timestamp=c.get("timestamp", 0),
                    asset=asset_name,
                    open=c.get("open", 0),
                    high=c.get("high", 0),
                    low=c.get("low", 0),
                    close=c.get("close", 0),
                    volume=c.get("volume", 0)
                )
                await self.db.save_candle(candle)
                self._last_saved_ts[asset_name] = max(self._last_saved_ts.get(asset_name, 0), candle.timestamp)
            logger.info(f"Loaded {len(candles)} historical candles for {asset_name}")
        except Exception as e:
            logger.error(f"Failed to load historical for {asset_name}: {e}")

    async def start_collection(self):
        await self.discover_assets()
        await self.subscribe_all()
        sorted_assets = sorted(self.assets, key=lambda a: a.payout, reverse=True)[:self.TOP_ASSETS]
        for asset in sorted_assets:
            await self.load_historical(asset.name, 300)
        # Keep a strong reference so the polling task survives past this call.
        self._poll_task = asyncio.create_task(self.poll_realtime())
        logger.info("Candle collection started (historical + live polling)")

    async def stop_collection(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._poll_task = None
            logger.info("Candle collection stopped")

    async def poll_realtime(self):
        """Poll each subscribed asset's latest tick and emit closed candles."""
        logger.info("Live candle polling started")
        while True:
            try:
                for asset in sorted(self.assets, key=lambda a: a.payout, reverse=True)[:self.TOP_ASSETS]:
                    await self._poll_asset(asset.name)
                self._warn_on_stale_feeds()
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Realtime poll error: {e}")
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def _poll_asset(self, asset_name: str):
        try:
            tick = await self.connection.get_realtime_candles(asset_name)
        except Exception as e:
            logger.debug(f"get_realtime_candles failed for {asset_name}: {e}")
            return

        if not isinstance(tick, (list, tuple)) or len(tick) < 3:
            return

        try:
            ts = int(tick[1])
            price = float(tick[2])
        except (TypeError, ValueError):
            return

        if ts <= 0 or price <= 0:
            return
        # Reject implausibly-far-future timestamps (bad parse / desync).
        now_ts = int(time.time())
        if ts > now_ts + 3600:
            ts = now_ts
        if ts < now_ts - 3600 * 24 * 365:
            return  # stale beyond retention horizon; ignore

        self._last_tick_monotonic[asset_name] = time.monotonic()

        minute = ts // 60 * 60
        bucket = self._minute_buckets.get(asset_name)
        if bucket is None or bucket["minute"] != minute:
            # A tick for a new minute arrived -> the previous minute is closed.
            if bucket is not None:
                await self._flush_closed_candle(asset_name, bucket)
            self._minute_buckets[asset_name] = {
                "minute": minute,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            }
        else:
            bucket["high"] = max(bucket["high"], price)
            bucket["low"] = min(bucket["low"], price)
            bucket["close"] = price

    async def _flush_closed_candle(self, asset_name: str, bucket: dict):
        ts = bucket["minute"]
        if ts <= self._last_saved_ts.get(asset_name, 0):
            return  # already ingested (dedupe)

        self._last_saved_ts[asset_name] = ts
        candle_data = {
            "timestamp": ts,
            "open": bucket["open"],
            "high": bucket["high"],
            "low": bucket["low"],
            "close": bucket["close"],
            "volume": 0,
        }
        logger.debug(
            "Live candle %s @%s open=%.5f close=%.5f",
            asset_name, datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S"),
            bucket["open"], bucket["close"],
        )
        await self._handle_candle(asset_name, candle_data)

    def _warn_on_stale_feeds(self):
        now = time.monotonic()
        for asset_name, last_ts in self._last_tick_monotonic.items():
            stale_for = now - last_ts
            if stale_for > self.STALE_FEED_SECONDS:
                last_warn = self._last_stale_warn.get(asset_name, 0)
                if now - last_warn >= 60:  # throttle warning to once/minute
                    logger.warning(
                        f"Stale candle feed for {asset_name}: no live tick for {int(stale_for)}s"
                    )
                    self._last_stale_warn[asset_name] = now


class MockCandleCollector:
    """Mock collector for testing"""

    def __init__(self, db: Database):
        self.db = db
        self.callbacks = []
        self.assets = []

    def on_new_candle(self, callback):
        self.callbacks.append(callback)

    async def discover_assets(self):
        mock_assets = [
            Asset("EURUSD_otc", "CURRENCIES", 92),
            Asset("GBPUSD_otc", "CURRENCIES", 90),
            Asset("USDJPY_otc", "CURRENCIES", 88),
            Asset("BTCUSD_otc", "CRYPTO", 85),
            Asset("ETHUSD_otc", "CRYPTO", 84),
            Asset("XAUUSD_otc", "COMMODITIES", 86),
            Asset("AAPL_otc", "STOCKS", 82),
        ]
        for a in mock_assets:
            await self.db.save_asset(a)
            self.assets.append(a)

    async def simulate_candles(self, asset_name: str, count: int = 100):
        import random
        base = 1.1000 if "EUR" in asset_name else 1.3000 if "GBP" in asset_name else 150.0
        now = int(datetime.now().timestamp())
        for i in range(count):
            change = random.uniform(-0.002, 0.002)
            o = base * (1 + change)
            c = o * (1 + random.uniform(-0.001, 0.001))
            candle = Candle(
                timestamp=now - (count - i) * 60,
                asset=asset_name, open=o,
                high=max(o, c) * 1.0005,
                low=min(o, c) * 0.9995,
                close=c, volume=random.randint(100, 1000)
            )
            await self.db.save_candle(candle)
            base = c

    async def start_collection(self):
        await self.discover_assets()
        for asset in self.assets:
            await self.simulate_candles(asset.name, 200)

    async def stop_collection(self):
        pass
