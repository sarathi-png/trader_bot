import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from config.settings import Settings
from database.repository import Database
from database.models import Signal, User
from core.connection import QuotexConnection, MockQuotexConnection
from core.candles import CandleCollector, MockCandleCollector
from core.events import EventBus, Events
from engine.scorer import ConfluenceScorer
from engine.filter import SessionFilter
from engine.multitimeframe import MultiTimeframeAnalyzer
from engine.news_filter import NewsFilter
from tg_bot.bot import TelegramBot


logger = logging.getLogger(__name__)


class QuotexSignalBot:
    def __init__(self, settings: Settings, use_mock: bool = False):
        self.settings = settings
        self.use_mock = use_mock
        self.db = Database(settings.db_path)
        self.event_bus = EventBus()
        self.scorer = ConfluenceScorer(min_confidence=settings.min_confidence)
        self.session_filter = SessionFilter(blocked_hours=settings.blocked_hours)
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.news_filter = NewsFilter(
            window_minutes=settings.news_window_minutes,
            refresh_hours=settings.news_refresh_hours,
        )
        self.telegram_bot = TelegramBot(settings, self.db)
        self.telegram_bot.handlers.connection_status_provider = self.get_connection_status

        if use_mock:
            self.connection = MockQuotexConnection()
            self.candle_collector = MockCandleCollector(self.db, interval_seconds=settings.mock_signal_interval)
        else:
            self.connection = QuotexConnection(
                email=settings.quotex_email,
                password=settings.quotex_password,
                ssid=settings.quotex_ssid,
                is_demo=settings.quotex_demo
            )
            self.candle_collector = CandleCollector(self.connection, self.db)

        self.running = False
        self._analysis_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._result_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._last_signal: dict = {}
        self._connected = False
        self._collection_started = False

    @staticmethod
    def _parse_duration_minutes(duration: str) -> int:
        """Parse a duration string like '3min' to minutes (default 3)."""
        if not duration:
            return 3
        try:
            digits = "".join(ch for ch in duration if ch.isdigit())
            if not digits:
                return 3
            return max(1, int(digits))
        except (ValueError, TypeError):
            return 3

    async def start(self):
        logger.info("Starting Quotex Signal Bot...")
        await self.db.connect()
        self.telegram_bot.setup()
        await self.telegram_bot.start()

        if self.use_mock:
            await self.candle_collector.start_collection()
            self._connected = True
            self._collection_started = True
        else:
            # Non-fatal: keep Telegram and the scheduler alive even if the
            # first connection attempt fails. A watchdog retries in the
            # background and starts candle collection once connected.
            connected = await self.connection.connect()
            if connected:
                self._connected = True
                await self.candle_collector.start_collection()
                self._collection_started = True
                self._watchdog_task = asyncio.create_task(self._connection_watchdog())
            else:
                logger.error("Initial Quotex connection failed; watchdog will retry")
                self._watchdog_task = asyncio.create_task(self._connection_watchdog())

        self.event_bus.on(Events.SIGNAL_GENERATED, self._on_signal_generated)

        if self.settings.news_filter_enabled:
            await self.news_filter.refresh()
            self.telegram_bot.set_news_filter(self.news_filter)

        self.running = True
        self._analysis_task = asyncio.create_task(self._analysis_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._result_task = asyncio.create_task(self._result_tracking_loop())

        logger.info("Bot started successfully")

        await asyncio.Event().wait()

    async def _connection_watchdog(self):
        """Retry the live Quotex connection until it succeeds, then start
        candle collection. Runs only in live mode."""
        while self.running:
            if self._connected:
                return
            try:
                connected = await self.connection.connect()
                if connected:
                    self._connected = True
                    await self.candle_collector.start_collection()
                    self._collection_started = True
                    logger.info("Quotex connection established via watchdog")
                    return
                logger.warning("Quotex connection retry failed; retrying in 60s")
            except Exception as e:
                logger.error(f"Quotex connection watchdog error: {e}")
            await asyncio.sleep(60)

    def get_connection_status(self) -> dict:
        """Current connection state for /status."""
        if self.use_mock:
            return {"connected": True, "mode": "mock", "collection_started": True}
        return {
            "connected": self._connected,
            "mode": "live",
            "collection_started": self._collection_started,
        }

    async def stop(self):
        self.running = False
        if self._analysis_task:
            self._analysis_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._result_task:
            self._result_task.cancel()
        if self._watchdog_task:
            self._watchdog_task.cancel()
        if hasattr(self.candle_collector, "stop_collection"):
            await self.candle_collector.stop_collection()
        await self.telegram_bot.stop()
        if not self.use_mock:
            await self.connection.disconnect()
        await self.db.close()
        logger.info("Bot stopped")

    async def _on_signal_generated(self, signal: Signal):
        await self.db.save_signal(signal)
        await self.telegram_bot.broadcast_signal(signal)
        logger.info(f"Signal generated: {signal.asset} {signal.direction} ({signal.confidence}%)")

    async def _analysis_loop(self):
        while self.running:
            try:
                if self.settings.news_filter_enabled:
                    await self.news_filter.refresh()

                assets = await self.db.get_active_assets()
                for asset in assets:
                    if not self.session_filter.is_tradable():
                        continue
                    if self.session_filter.should_skip_payout(asset.payout, self.settings.min_payout):
                        continue

                    candles = await self.db.get_candles(asset.name, limit=300)
                    if len(candles) < 15:
                        continue

                    direction, confidence, aligned, indicators = self.scorer.analyze(candles)

                    if direction == "NONE" or confidence == 0:
                        continue

                    confirmed, mtf_trend, mtf_adj = self.mtf_analyzer.confirm(direction, candles)
                    confidence = max(0, min(100, confidence + mtf_adj))

                    if not confirmed or confidence < self.settings.min_confidence:
                        continue

                    if self.settings.news_filter_enabled:
                        now = datetime.now(timezone.utc)
                        if self.news_filter.is_blocked(now):
                            nearest = self.news_filter.get_nearest_event(now)
                            if nearest:
                                mins = int((nearest.dt - now).total_seconds() / 60)
                                logger.info(f"News filter: blocked signal {asset.name} — {nearest.country} {nearest.title} in {mins}min")
                            continue

                    key = f"{asset.name}:{direction}"
                    last = self._last_signal.get(key)
                    if last and (datetime.now(timezone.utc) - last).total_seconds() < 300:
                        continue

                    today_count = await self.db.get_today_signal_count()
                    if today_count >= self.settings.max_signals_per_day:
                        continue

                    # Per-user durations: generate one signal per duration that
                    # any enabled user has configured, and let delivery filter
                    # users by their own duration setting.
                    durations = await self.db.get_active_user_durations()
                    if not durations:
                        durations = [self.settings.durations[1]]

                    for duration in durations:
                        signal = Signal(
                            id=str(uuid.uuid4()),
                            asset=asset.name,
                            direction=direction,
                            confidence=confidence,
                            strategies=aligned,
                            duration=duration,
                            entry_time=datetime.now(timezone.utc) + timedelta(minutes=5),
                            entry_price=candles[-1].close if candles else 0.0,
                            mtf_trend=mtf_trend,
                            payout=asset.payout
                        )
                        self._last_signal[key] = datetime.now(timezone.utc)
                        await self.event_bus.emit(Events.SIGNAL_GENERATED, signal)

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Analysis loop error: {e}")
                await asyncio.sleep(30)

    async def _result_tracking_loop(self):
        while self.running:
            try:
                expired = await self.db.get_expired_pending_signals()
                for signal in expired:
                    if signal.entry_time is None or signal.entry_price == 0:
                        await self.db.update_signal_status(signal.id, "SKIP")
                        continue

                    # Priority 2: grade the real trade window, not the pre-entry gap.
                    # 1) When the pre-entry gap ends (entry_time), capture the actual
                    #    entry price the user would realistically get.
                    if not signal.actual_entry_price:
                        entry_ts = int(signal.entry_time.timestamp())
                        entry_candle = await self.db.get_candle_at(signal.asset, entry_ts)
                        if entry_candle is None:
                            # Grading candle not available yet; try again next pass.
                            continue
                        signal.actual_entry_price = entry_candle.close
                        await self.db.save_signal(signal)
                        continue

                    # 2) Real expiry = entry_time + duration; grade at THAT timestamp.
                    duration_minutes = self._parse_duration_minutes(signal.duration)
                    expiry_dt = signal.entry_time + timedelta(minutes=duration_minutes)
                    if datetime.now(timezone.utc) < expiry_dt:
                        continue

                    expiry_ts = int(expiry_dt.timestamp())
                    candle = await self.db.get_candle_at(signal.asset, expiry_ts)

                    if candle is None:
                        continue

                    if signal.direction == "CALL":
                        won = candle.close > signal.actual_entry_price
                    else:
                        won = candle.close < signal.actual_entry_price

                    status = "WIN" if won else "LOSS"
                    await self.db.update_signal_status(signal.id, status, candle.close)
                    signal.status = status
                    signal.exit_price = candle.close
                    await self.telegram_bot.broadcast_result(signal)
                    logger.info(
                        f"Trade result: {signal.asset} {signal.direction} -> {status} "
                        f"(actual_entry={signal.actual_entry_price:.5f}, exit={candle.close:.5f}, "
                        f"expiry={expiry_dt.strftime('%H:%M:%S')} UTC)"
                    )

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Result tracking error: {e}")
                await asyncio.sleep(30)

    async def _cleanup_loop(self):
        while self.running:
            try:
                await self.db.cleanup_old_candles(self.settings.db_retention_days)
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(300)
