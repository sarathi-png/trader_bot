import logging
from typing import Optional
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext
from config.settings import Settings
from database.repository import Database
from database.models import User
from tg_bot.commands import CommandHandlers
from tg_bot.signals import SignalFormatter
from tg_bot.keyboards import signal_action_buttons

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.app: Optional[Application] = None
        self.started = False
        self.handlers = CommandHandlers(db, settings)
        self.formatter = SignalFormatter(is_demo=settings.quotex_demo)

    def set_news_filter(self, news_filter):
        self.handlers.set_news_filter(news_filter)

    def setup(self):
        self.app = (
            Application.builder()
            .token(self.settings.telegram_token)
            .build()
        )

        self.app.add_handler(CommandHandler("start", self.handlers.start))
        self.app.add_handler(CommandHandler("help", self.handlers.help))
        self.app.add_handler(CommandHandler("signals", self.handlers.toggle_signals))
        self.app.add_handler(CommandHandler("categories", self.handlers.set_categories))
        self.app.add_handler(CommandHandler("assets", self.handlers.list_assets))
        self.app.add_handler(CommandHandler("duration", self.handlers.set_duration))
        self.app.add_handler(CommandHandler("settings", self.handlers.show_settings))
        self.app.add_handler(CommandHandler("stats", self.handlers.show_stats))
        self.app.add_handler(CommandHandler("backtest", self.handlers.show_backtest))
        self.app.add_handler(CommandHandler("status", self.handlers.show_status))
        self.app.add_handler(CommandHandler("calendar", self.handlers.show_calendar))
        self.app.add_handler(CallbackQueryHandler(self.handlers.on_callback))

        logger.info("Telegram bot handlers registered")

    async def start(self):
        if not self.app:
            self.setup()

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("signals", "Enable/disable signals"),
            BotCommand("categories", "Set asset categories"),
            BotCommand("assets", "List available assets"),
            BotCommand("duration", "Set trade duration"),
            BotCommand("settings", "View settings"),
            BotCommand("stats", "View measured performance"),
            BotCommand("backtest", "Backtest on historical candles"),
            BotCommand("status", "Bot status"),
            BotCommand("calendar", "Upcoming news events"),
        ]
        await self.app.bot.set_my_commands(commands)

        self.started = True
        logger.info("Telegram bot started")

    async def stop(self):
        if self.app and self.started:
            try:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.warning(f"Error stopping bot: {e}")
            self.started = False

    async def send_signal(self, signal, user: User):
        message = self.formatter.format_signal(signal)
        try:
            await self.app.bot.send_message(
                chat_id=user.telegram_id,
                text=message,
                parse_mode="HTML",
                reply_markup=signal_action_buttons(signal.id)
            )
        except Exception as e:
            logger.error(f"Failed to send signal to {user.telegram_id}: {e}")

    async def send_result(self, signal, user: User):
        message = self.formatter.format_result(signal)
        try:
            await self.app.bot.send_message(
                chat_id=user.telegram_id,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send result to {user.telegram_id}: {e}")

    def _frequency_threshold(self, frequency: str) -> int:
        """Map a user's frequency preference to a per-user confidence threshold.

        conservative -> stricter than the global minimum (fewer, higher-conviction
        signals); aggressive -> looser. This makes the stored User.frequency
        setting actually affect delivery instead of being dead data.
        """
        base = self.settings.min_confidence if self.settings else 50
        adjustments = {"conservative": 15, "normal": 0, "aggressive": -10}
        return max(0, base + adjustments.get(frequency, 0))

    async def broadcast_signal(self, signal):
        category = await self.db.get_asset_category(signal.asset)
        eligible = await self.db.get_eligible_users(
            category=category,
            duration=signal.duration,
            asset=signal.asset
        )
        for user in eligible:
            if signal.confidence < self._frequency_threshold(user.frequency):
                continue
            hour = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).hour
            if user.quiet_hours_start > user.quiet_hours_end:
                in_quiet = hour >= user.quiet_hours_start or hour < user.quiet_hours_end
            else:
                in_quiet = user.quiet_hours_start <= hour < user.quiet_hours_end
            if not in_quiet:
                await self.send_signal(signal, user)

    async def broadcast_result(self, signal):
        category = await self.db.get_asset_category(signal.asset)
        eligible = await self.db.get_eligible_users(
            category=category,
            duration=signal.duration,
            asset=signal.asset
        )
        for user in eligible:
            if signal.confidence < self._frequency_threshold(user.frequency):
                continue
            hour = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).hour
            if user.quiet_hours_start > user.quiet_hours_end:
                in_quiet = hour >= user.quiet_hours_start or hour < user.quiet_hours_end
            else:
                in_quiet = user.quiet_hours_start <= hour < user.quiet_hours_end
            if not in_quiet:
                await self.send_result(signal, user)
