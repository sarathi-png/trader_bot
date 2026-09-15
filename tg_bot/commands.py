import logging
from telegram import Update
from telegram.ext import CallbackContext
from database.repository import Database
from database.models import User

logger = logging.getLogger(__name__)


class CommandHandlers:
    def __init__(self, db: Database, settings=None):
        self.db = db
        self.settings = settings
        self.news_filter = None

    def set_news_filter(self, news_filter):
        self.news_filter = news_filter

    async def start(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        username = update.effective_user.username or ""

        existing = await self.db.get_user(user_id)
        if not existing:
            user = User(telegram_id=user_id, username=username)
            await self.db.save_user(user)
            await update.message.reply_text(
                "Welcome to Quotex Signal Bot!\n\n"
                "I analyze market data and send you high-confidence trading signals.\n\n"
                "Use /help to see available commands.\n"
                "Use /categories to select which assets you want signals for.\n"
                "Use /duration to set your preferred trade duration."
            )
        else:
            await update.message.reply_text("Welcome back! Use /help for commands.")

    async def help(self, update: Update, context: CallbackContext):
        text = (
            "Quotex Signal Bot Commands:\n\n"
            "/start - Start the bot\n"
            "/help - Show this help\n"
            "/signals - Enable/disable signal notifications\n"
            "/categories - Set asset categories (Currencies, Crypto, etc.)\n"
            "/assets - List available assets by category\n"
            "/duration - Set trade duration (1min, 3min, 5min, 15min)\n"
            "/settings - View your current settings\n"
            "/stats - View measured signal performance\n"
            "/backtest - Run backtest on historical candles (validation window)\n"
            "/status - Check bot connection status\n"
            "/calendar - Upcoming high-impact news events\n"
        )
        await update.message.reply_text(text)

    async def toggle_signals(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)

        if not user:
            await update.message.reply_text("Please /start the bot first.")
            return

        user.enabled = not user.enabled
        await self.db.save_user(user)
        status = "ENABLED" if user.enabled else "DISABLED"
        await update.message.reply_text(f"Signal notifications: {status}")

    async def set_categories(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)

        if not user:
            await update.message.reply_text("Please /start the bot first.")
            return

        if not context.args:
            current = ", ".join(user.categories)
            text = (
                f"Current categories: {current}\n\n"
                "Available categories:\n"
                "- CURRENCIES (EURUSD, GBPUSD, USDJPY...)\n"
                "- CRYPTO (BTCUSD, ETHUSD, XRPUSD...)\n"
                "- COMMODITIES (XAUUSD, XAGUSD, OIL...)\n"
                "- STOCKS (AAPL, GOOGL, TSLA...)\n\n"
                "Usage: /categories CURRENCIES,CRYPTO\n"
                "Or toggle: /categories toggle CRYPTO\n"
                "See full lists: /assets"
            )
            await update.message.reply_text(text)
            return

        arg = " ".join(context.args).upper()

        if arg.startswith("TOGGLE "):
            cat = arg.replace("TOGGLE ", "").strip()
            if cat in user.categories:
                user.categories.remove(cat)
            else:
                user.categories.append(cat)
        else:
            user.categories = [c.strip() for c in arg.split(",")]

        await self.db.save_user(user)
        await update.message.reply_text(f"Categories updated: {', '.join(user.categories)}")

    async def list_assets(self, update: Update, context: CallbackContext):
        if not context.args:
            categories = await self.db.get_asset_categories()
            text = (
                "📊 AVAILABLE ASSETS\n\n"
                "Usage: /assets <CATEGORY>\n\n"
                "Categories:\n"
            )
            for cat in categories:
                text += f"  • {cat}\n"
            text += "\nExample: /assets CURRENCIES"
            await update.message.reply_text(text)
            return

        category = context.args[0].upper()
        assets = await self.db.get_assets_by_category(category)

        if not assets:
            await update.message.reply_text(f"No assets found for category: {category}")
            return

        lines = [f"📊 {category} ASSETS\n"]
        for a in assets:
            otc = " (OTC)" if a.is_otc else ""
            lines.append(f"  • {a.name}{otc} — {a.payout}%")

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n…"

        await update.message.reply_text(text)

    async def set_duration(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)

        if not user:
            await update.message.reply_text("Please /start the bot first.")
            return

        if not context.args:
            text = (
                f"Current duration: {user.duration}\n\n"
                "Available durations:\n"
                "- 1min (Scalping)\n"
                "- 3min (Standard)\n"
                "- 5min (Standard)\n"
                "- 15min (Extended)\n\n"
                "Usage: /duration 5min"
            )
            await update.message.reply_text(text)
            return

        duration = context.args[0].lower()
        if duration in ("1min", "3min", "5min", "15min"):
            user.duration = duration
            await self.db.save_user(user)
            await update.message.reply_text(f"Duration set to: {duration}")
        else:
            await update.message.reply_text("Invalid duration. Use: 1min, 3min, 5min, or 15min")

    async def show_settings(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        user = await self.db.get_user(user_id)

        if not user:
            await update.message.reply_text("Please /start the bot first.")
            return

        text = (
            "Your Settings:\n\n"
            f"Status: {'Enabled' if user.enabled else 'Disabled'}\n"
            f"Categories: {', '.join(user.categories)}\n"
            f"Duration: {user.duration}\n"
            f"Frequency: {user.frequency}\n"
            f"Quiet Hours: {user.quiet_hours_start}:00 - {user.quiet_hours_end}:00 UTC\n"
        )
        await update.message.reply_text(text)

    async def show_stats(self, update: Update, context: CallbackContext):
        stats = await self.db.get_performance(days=7)

        # Break-even win rate for context (from actual measured payouts).
        breakeven = ""
        try:
            from database.repository import Database as _Db
            payout = await self._average_payout()
            if payout > 0:
                from engine.scorer import ConfluenceScorer
                be = ConfluenceScorer.get_break_even_winrate(payout)
                breakeven = f"Break-even win rate: {be * 100:.1f}% (avg payout {payout}%)\n"
        except Exception as e:
            logger.debug(f"Could not compute break-even: {e}")

        text = (
            "Performance (Last 7 Days):\n\n"
            f"Total Signals: {stats.total_signals}\n"
            f"Wins: {stats.wins}\n"
            f"Losses: {stats.losses}\n"
            f"Win Rate: {stats.win_rate}%\n"
            f"Today: {stats.today_wins}/{stats.today_signals}\n"
            f"{breakeven}"
        )
        await update.message.reply_text(text)

    async def _average_payout(self) -> int:
        """Average payout among graded signals in the last 7 days."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        cursor = await self.db.db.execute(
            "SELECT AVG(payout) FROM signals WHERE created_at >= ? AND status IN ('WIN','LOSS') AND payout > 0",
            (cutoff,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] else 0

    async def show_backtest(self, update: Update, context: CallbackContext):
        try:
            from backtest.engine import run_backtest, format_backtest
            settings = self.settings
            durations = settings.durations if settings else ["1min", "3min", "5min", "15min"]
            min_conf = settings.min_confidence if settings else 50
            min_payout = settings.min_payout if settings else 80
            result = await run_backtest(
                self.db,
                min_confidence=min_conf,
                min_payout=min_payout,
                durations=tuple(durations),
            )
            await update.message.reply_text(format_backtest(result))
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            await update.message.reply_text("Backtest could not run right now. Check the logs.")

    async def show_status(self, update: Update, context: CallbackContext):
        from datetime import datetime
        today_count = await self.db.get_today_signal_count()

        account = "🧪 DEMO" if (self.settings and self.settings.quotex_demo) else "💰 LIVE"

        news_enabled = ""
        if self.settings and self.settings.news_filter_enabled:
            news_enabled = f"News Filter: ON ({self.settings.news_window_minutes}min window)\n"

        text = (
            "Bot Status:\n\n"
            f"Account: {account}\n"
            f"Connected: Yes\n"
            f"Signals Today: {today_count}\n"
            f"{news_enabled}"
            f"Last Check: {datetime.now().strftime('%H:%M:%S')}\n"
        )
        await update.message.reply_text(text)

    async def show_calendar(self, update: Update, context: CallbackContext):
        if not self.news_filter:
            await update.message.reply_text("News filter not available.")
            return

        events = self.news_filter.get_upcoming_events(hours=72)
        if not events:
            await update.message.reply_text("No upcoming high-impact events in the next 72 hours.")
            return

        lines = ["📅 HIGH-IMPACT EVENTS (Next 72h)\n"]
        for event in events[:15]:
            lines.append(self.news_filter.format_event(event))

        blocked = self.news_filter.is_blocked()
        if blocked:
            nearest = self.news_filter.get_nearest_event()
            if nearest:
                lines.append(f"\n🔴 Signals BLOCKED — near: {nearest.country} {nearest.title}")

        text = "\n".join(lines)
        await update.message.reply_text(text)
