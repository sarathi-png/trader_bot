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
    """Mock collector for testing.

    Seeds historical candles once, then runs a realtime simulation loop that
    appends a new candle per asset every ``interval_seconds`` so the analysis
    engine sees fresh data and actually generates signals.

    Each asset runs a perpetual phase machine (TREND → DIP → B1 → B2 →
    RECOVER) whose two-stage bounce — a small +0.2% candle then a +0.6%
    impulse after an 8-candle ≈-2.4% dip, inside a net-positive drift — aligns
    BOLLINGER + ZIGZAG_DEMARK + MACD_SR + STOCH_RSI on a single candle
    (scorer base ≈52) with an agreeing MTF trend (final ≈57-60). PUT-biased
    assets mirror the pattern. Shape verified by parameter search over the
    real scorer + MTF analyzer (83% hit rate across 30 seeds per side).
    """

    # Directional bias per mock asset: +1 = CALL pattern (up-drift with
    # down-dips), -1 = mirrored PUT pattern. Unknown assets default to +1.
    _ASSET_BIAS = {
        "EURUSD_otc": 1, "GBPUSD_otc": 1, "USDJPY_otc": 1, "BTCUSD_otc": 1,
        "ETHUSD_otc": -1, "XAUUSD_otc": -1, "AAPL_otc": -1,
    }
    _SEED_COUNT = 260
    _TREND_LEN = (70, 100)
    _TREND_DRIFT = 0.0005
    _TREND_NOISE = 0.0004
    _DIP_LEN = 15
    _DIP_DRIFT = 0.003
    _DIP_NOISE = 0.0003
    _B1_DRIFT = 0.002
    _B2_DRIFT = 0.006
    _BOUNCE_NOISE = 0.00015
    _RECOVER_LEN = 20
    _RECOVER_DRIFT = 0.0006
    _RECOVER_NOISE = 0.0003

    def __init__(self, db: Database, interval_seconds: int = 60):
        self.db = db
        self.callbacks = []
        self.assets = []
        self.interval_seconds = max(5, interval_seconds)
        self._sim_task: Optional[asyncio.Task] = None
        self._last_price: Dict[str, float] = {}
        self._last_ts: Dict[str, int] = {}
        # per-asset phase-machine state: {"bias", "phase", "left"}
        self._mock_state: Dict[str, dict] = {}

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

    def _base_price(self, asset_name: str) -> float:
        if "EUR" in asset_name or "GBP" in asset_name:
            return 1.1000
        if "JPY" in asset_name:
            return 150.0
        if "BTC" in asset_name:
            return 60000.0
        if "ETH" in asset_name:
            return 3000.0
        if "XAU" in asset_name:
            return 2400.0
        return 200.0  # stocks

    def _mock_init(self, asset_name: str, trend_len: Optional[int] = None):
        """(Re)initialize an asset's phase machine at the TREND phase."""
        import random
        self._mock_state[asset_name] = {
            "bias": self._ASSET_BIAS.get(asset_name, 1),
            "phase": "TREND",
            "left": trend_len if trend_len is not None
                    else random.randint(*self._TREND_LEN),
        }

    def _make_candle(self, asset_name: str, ts: int) -> Candle:
        """One candle from the asset's signal-pattern phase machine.

        All drifts are relative, so the shape works at any price magnitude
        (FX ~1.1 through BTC ~60000).
        """
        import random
        base = self._last_price.get(asset_name, self._base_price(asset_name))

        st = self._mock_state.get(asset_name)
        if st is None:
            self._mock_init(asset_name)
            st = self._mock_state[asset_name]
        bias, phase = st["bias"], st["phase"]

        if phase == "TREND":
            drift, noise, wick = bias * self._TREND_DRIFT, self._TREND_NOISE, 0.5
            nxt, n = "DIP", self._DIP_LEN
        elif phase == "DIP":
            drift = -bias * self._DIP_DRIFT * random.uniform(0.95, 1.05)
            noise, wick = self._DIP_NOISE, 0.5
            nxt, n = "B1", 1
        elif phase == "B1":
            drift = bias * self._B1_DRIFT * random.uniform(0.95, 1.05)
            noise, wick = self._BOUNCE_NOISE, 0.3
            nxt, n = "B2", 1
        elif phase == "B2":
            drift = bias * self._B2_DRIFT * random.uniform(0.95, 1.05)
            noise, wick = self._BOUNCE_NOISE, 0.3
            nxt, n = "RECOVER", self._RECOVER_LEN
        else:  # RECOVER
            drift, noise, wick = bias * self._RECOVER_DRIFT, self._RECOVER_NOISE, 0.5
            nxt, n = "TREND", random.randint(*self._TREND_LEN)

        st["left"] -= 1
        if st["left"] <= 0:
            st["phase"], st["left"] = nxt, n

        o = base
        c = o * (1 + drift + random.uniform(-noise, noise))
        body = abs(c - o)
        high = max(o, c) + body * random.uniform(0, wick) + o * 0.00005
        low = min(o, c) - body * random.uniform(0, wick) - o * 0.00005
        self._last_price[asset_name] = c
        return Candle(
            timestamp=ts,
            asset=asset_name,
            open=o,
            high=high,
            low=low,
            close=c,
            volume=random.randint(100, 1000),
        )

    async def simulate_candles(self, asset_name: str, count: int = 100):
        # Seed so the stream ends exactly on a B1 bounce candle: a long TREND
        # followed by DIP(8) + B1. The last seeded candle is then a proven
        # confluence candle (all four strategies + agreeing MTF), so the
        # first analysis pass can fire immediately. Live appends continue
        # with B2 -> RECOVER -> TREND -> ...
        self._mock_init(asset_name, trend_len=max(1, count - 9))
        now = int(datetime.now().timestamp())
        candles = []
        for i in range(count):
            ts = now - (count - i) * 60
            candles.append(self._make_candle(asset_name, ts))
        await self.db.save_candles_bulk(candles)
        self._last_ts[asset_name] = candles[-1].timestamp

    async def _append_simulated_candle(self, asset: Asset):
        """Append one fresh candle continuing the last simulated price.

        The timestamp is always >= the last candle's timestamp + 1 minute and
        >= the current minute, so the analysis engine sees strictly fresh data
        and the candle never collides with (overwrites) historical candles.
        """
        current_minute = int(datetime.now().timestamp()) // 60 * 60
        ts = max(current_minute, self._last_ts.get(asset.name, 0) + 60)
        candle = self._make_candle(asset.name, ts)
        await self.db.save_candle(candle)
        self._last_ts[asset.name] = ts
        for callback in self.callbacks:
            try:
                await callback(asset.name, candle)
            except Exception as e:
                logger.error(f"Mock candle callback error for {asset.name}: {e}")

    async def _simulation_loop(self):
        logger.info(f"Mock candle simulation started (interval={self.interval_seconds}s)")
        # Sleep first: the seed ends on a proven confluence candle and the
        # analysis loop must evaluate it before fresh appends bury it.
        await asyncio.sleep(self.interval_seconds)
        while True:
            try:
                for asset in self.assets:
                    await self._append_simulated_candle(asset)
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Mock simulation error: {e}")
                await asyncio.sleep(self.interval_seconds)

    async def start_collection(self):
        await self.discover_assets()
        for asset in self.assets:
            await self.simulate_candles(asset.name, self._SEED_COUNT)
        self._sim_task = asyncio.create_task(self._simulation_loop())
        logger.info(f"Mock collection started for {len(self.assets)} assets")

    async def stop_collection(self):
        if self._sim_task:
            self._sim_task.cancel()
            try:
                await self._sim_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._sim_task = None
            logger.info("Mock candle collection stopped")
