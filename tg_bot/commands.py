import logging
from telegram import Update
from telegram.ext import CallbackContext
from database.repository import Database
from database.models import User
from tg_bot.keyboards import (
    main_menu,
    category_toggle,
    asset_category_picker,
    asset_picker,
    duration_picker,
    frequency_picker,
    quiet_hours_picker,
    signals_toggle,
    setup_menu,
    help_button,
)

logger = logging.getLogger(__name__)

ALL_CATEGORIES = ["CURRENCIES", "CRYPTO", "COMMODITIES", "STOCKS"]
VALID_DURATIONS = ["1min", "3min", "5min", "15min"]

QUIET_PRESETS = {
    "off": (0, 0),
    "night": (23, 7),
    "day": (9, 17),
}

SETUP_STEPS = [
    "📊 **Step 1/4 — Categories**\nPick which asset groups you want signals for. Tap a category to toggle it, then tap ✅ Done.",
    "💰 **Step 2/4 — Assets**\nPick specific currencies/assets you want signals for (optional). Tap ⭐ on your favorites, then ✅ Done.",
    "⏱ **Step 3/4 — Duration**\nChoose your trade duration.",
    "🔔 **Step 4/4 — Signals**\nTurn signal notifications ON to start receiving alerts.",
]


class CommandHandlers:
    def __init__(self, db: Database, settings=None):
        self.db = db
        self.settings = settings
        self.news_filter = None
        self.connection_status_provider = None

    def set_news_filter(self, news_filter):
        self.news_filter = news_filter

    async def _get_or_create_user(self, update: Update) -> User:
        user_id = update.effective_user.id
        username = update.effective_user.username or ""
        user = await self.db.get_user(user_id)
        if not user:
            user = User(telegram_id=user_id, username=username)
            await self.db.save_user(user)
        return user

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    async def start(self, update: Update, context: CallbackContext):
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        existing = await self.db.get_user(user_id)
        if existing:
            await update.message.reply_text(
                "Welcome back! 👋\n\n"
                "Tap a button below to control your bot — no typing needed.",
                reply_markup=main_menu(),
            )
        else:
            user = User(telegram_id=user_id, username=update.effective_user.username or "")
            await self.db.save_user(user)
            await update.message.reply_text(
                "🚀 **Welcome to Quotex Signal Bot!**\n\n"
                "I analyze market data and send you high-confidence trading signals.\n\n"
                "Let's set you up in 4 quick steps.",
                parse_mode="Markdown",
                reply_markup=setup_menu(),
            )

    async def help(self, update: Update, context: CallbackContext):
        text = (
            "📖 **How to use Quotex Signal Bot**\n\n"
            "Everything is button-based — no typing needed.\n\n"
            "**1. Set up your preferences**\n"
            "   • 📊 Categories — which markets (Currencies, Crypto...)\n"
            "   • 💰 Assets — specific pairs you want (optional)\n"
            "   • ⏱ Duration — 1min/3min/5min/15min trades\n"
            "   • 🔔 Signals — turn alerts ON\n\n"
            "**2. Receive signals**\n"
            "   When a signal fires, you'll get a card with:\n"
            "   Asset • Direction (CALL/PUT) • Entry • Expiry • Confidence\n"
            "   Tap 📖 How to trade for placement steps.\n\n"
            "**3. Track performance**\n"
            "   • 📈 Stats — your win rate\n"
            "   • 🗓 Calendar — news events that block signals\n"
            "   • 🔌 Status — connection state\n\n"
            "Use the Main Menu buttons below 👇"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

    async def toggle_signals(self, update: Update, context: CallbackContext):
        user = await self._get_or_create_user(update)
        user.enabled = not user.enabled
        await self.db.save_user(user)
        if update.message:
            await update.message.reply_text(
                f"Signal notifications: {'ENABLED ✅' if user.enabled else 'DISABLED ❌'}",
                reply_markup=signals_toggle(user.enabled),
            )

    async def set_categories(self, update: Update, context: CallbackContext):
        user = await self._get_or_create_user(update)
        if update.message:
            await update.message.reply_text(
                "📊 **Categories**\nTap to toggle, then ✅ Done.",
                parse_mode="Markdown",
                reply_markup=category_toggle(user.categories, ALL_CATEGORIES),
            )

    async def list_assets(self, update: Update, context: CallbackContext):
        user = await self._get_or_create_user(update)
        categories = await self.db.get_asset_categories()
        if not categories:
            categories = ALL_CATEGORIES
        if update.message:
            await update.message.reply_text(
                "💰 **Assets**\nPick a category to choose specific assets.",
                parse_mode="Markdown",
                reply_markup=asset_category_picker(categories),
            )

    async def set_duration(self, update: Update, context: CallbackContext):
        user = await self._get_or_create_user(update)
        if update.message:
            await update.message.reply_text(
                f"⏱ **Duration**\nCurrent: {user.duration}",
                parse_mode="Markdown",
                reply_markup=duration_picker(user.duration),
            )

    async def show_settings(self, update: Update, context: CallbackContext):
        user = await self._get_or_create_user(update)
        text = self._format_settings(user)
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

    async def show_stats(self, update: Update, context: CallbackContext):
        stats = await self.db.get_performance(days=7)
        text = (
            "📈 **Performance (Last 7 Days)**\n\n"
            f"Total Signals: {stats.total_signals}\n"
            f"Wins: {stats.wins}\n"
            f"Losses: {stats.losses}\n"
            f"Win Rate: {stats.win_rate}%\n"
            f"Today: {stats.today_wins}/{stats.today_signals}\n"
        )
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu())

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
            text = format_backtest(result)
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            text = "Backtest could not run right now. Check the logs."
        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu())
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=main_menu())

    async def show_status(self, update: Update, context: CallbackContext):
        from datetime import datetime
        today_count = await self.db.get_today_signal_count()
        account = "🧪 DEMO" if (self.settings and self.settings.quotex_demo) else "💰 LIVE"

        conn = "Yes"
        if self.connection_status_provider:
            try:
                status = self.connection_status_provider()
                conn = "Yes" if status.get("connected") else "No (retrying...)"
            except Exception:
                pass

        news_enabled = ""
        if self.settings and self.settings.news_filter_enabled:
            news_enabled = f"News Filter: ON ({self.settings.news_window_minutes}min window)\n"

        text = (
            "🔌 **Bot Status**\n\n"
            f"Account: {account}\n"
            f"Connected: {conn}\n"
            f"Signals Today: {today_count}\n"
            f"{news_enabled}"
            f"Last Check: {datetime.now().strftime('%H:%M:%S')}\n"
        )
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu())

    async def show_calendar(self, update: Update, context: CallbackContext):
        if not self.news_filter:
            text = "News filter not available."
        else:
            events = self.news_filter.get_upcoming_events(hours=72)
            if not events:
                text = "No upcoming high-impact events in the next 72 hours."
            else:
                lines = ["📅 **HIGH-IMPACT EVENTS (Next 72h)**\n"]
                for event in events[:15]:
                    lines.append(self.news_filter.format_event(event))
                blocked = self.news_filter.is_blocked()
                if blocked:
                    nearest = self.news_filter.get_nearest_event()
                    if nearest:
                        lines.append(f"\n🔴 Signals BLOCKED — near: {nearest.country} {nearest.title}")
                text = "\n".join(lines)
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu())

    # ------------------------------------------------------------------ #
    # Callback router
    # ------------------------------------------------------------------ #

    async def on_callback(self, update: Update, context: CallbackContext):
        query = update.callback_query
        if not query:
            return
        await query.answer()
        data = query.data or ""
        user_id = query.from_user.id
        user = await self.db.get_user(user_id)
        if not user:
            user = User(telegram_id=user_id, username=query.from_user.username or "")
            await self.db.save_user(user)

        parts = data.split(":", 2)
        action = parts[0]

        if action == "menu":
            await self._handle_menu(update, context, user, parts)
        elif action == "cat":
            await self._handle_category_toggle(update, context, user, parts)
        elif action == "cats":
            await self._handle_categories_done(update, context, user)
        elif action == "assets":
            await self._handle_assets(update, context, user, parts)
        elif action == "asset":
            await self._handle_asset_toggle(update, context, user, parts)
        elif action == "dur":
            await self._handle_duration(update, context, user, parts)
        elif action == "freq":
            await self._handle_frequency(update, context, user, parts)
        elif action == "qh":
            await self._handle_quiet_hours(update, context, user, parts)
        elif action == "sig":
            await self._handle_signals(update, context, user)
        elif action == "setup":
            await self._handle_setup(update, context, user, parts)
        elif action == "trade":
            await self._handle_trade_help(update, context, parts)
        else:
            await query.edit_message_text("Unknown action.", reply_markup=main_menu())

    async def _handle_menu(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        target = parts[1] if len(parts) > 1 else "home"

        if target == "home":
            await query.edit_message_text("🏠 **Main Menu**", parse_mode="Markdown", reply_markup=main_menu())
        elif target == "categories":
            await query.edit_message_text(
                "📊 **Categories**\nTap to toggle, then ✅ Done.",
                parse_mode="Markdown",
                reply_markup=category_toggle(user.categories, ALL_CATEGORIES),
            )
        elif target == "assets":
            categories = await self.db.get_asset_categories()
            if not categories:
                categories = ALL_CATEGORIES
            await query.edit_message_text(
                "💰 **Assets**\nPick a category to choose specific assets.",
                parse_mode="Markdown",
                reply_markup=asset_category_picker(categories),
            )
        elif target == "duration":
            await query.edit_message_text(
                f"⏱ **Duration**\nCurrent: {user.duration}",
                parse_mode="Markdown",
                reply_markup=duration_picker(user.duration),
            )
        elif target == "signals":
            await query.edit_message_text(
                f"🔔 **Signals**\nCurrent: {'ON' if user.enabled else 'OFF'}",
                parse_mode="Markdown",
                reply_markup=signals_toggle(user.enabled),
            )
        elif target == "frequency":
            await query.edit_message_text(
                f"⚙️ **Frequency**\nCurrent: {user.frequency}",
                parse_mode="Markdown",
                reply_markup=frequency_picker(user.frequency),
            )
        elif target == "quiet_hours":
            await query.edit_message_text(
                f"🌙 **Quiet Hours**\nCurrent: {user.quiet_hours_start}:00 - {user.quiet_hours_end}:00 UTC",
                parse_mode="Markdown",
                reply_markup=quiet_hours_picker(user.quiet_hours_start, user.quiet_hours_end),
            )
        elif target == "settings":
            await query.edit_message_text(
                self._format_settings(user), parse_mode="Markdown", reply_markup=main_menu()
            )
        elif target == "stats":
            await self.show_stats(update, context)
        elif target == "calendar":
            await self.show_calendar(update, context)
        elif target == "status":
            await self.show_status(update, context)
        elif target == "backtest":
            await self.show_backtest(update, context)
        elif target == "help":
            text = (
                "📖 **How to use Quotex Signal Bot**\n\n"
                "Everything is button-based — no typing needed.\n\n"
                "**1. Set up your preferences**\n"
                "   • 📊 Categories — which markets\n"
                "   • 💰 Assets — specific pairs (optional)\n"
                "   • ⏱ Duration — trade length\n"
                "   • 🔔 Signals — turn alerts ON\n\n"
                "**2. Receive signals**\n"
                "   Cards show Asset • CALL/PUT • Entry • Expiry • Confidence.\n"
                "   Tap 📖 How to trade for placement steps.\n\n"
                "**3. Track performance**\n"
                "   📈 Stats • 🗓 Calendar • 🔌 Status\n"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu())

    async def _handle_category_toggle(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        cat = parts[1] if len(parts) > 1 else ""
        if cat in user.categories:
            user.categories.remove(cat)
        else:
            user.categories.append(cat)
        await self.db.save_user(user)
        await query.edit_message_text(
            "📊 **Categories**\nTap to toggle, then ✅ Done.",
            parse_mode="Markdown",
            reply_markup=category_toggle(user.categories, ALL_CATEGORIES),
        )

    async def _handle_categories_done(self, update: Update, context: CallbackContext, user: User):
        query = update.callback_query
        await query.edit_message_text(
            f"✅ Categories saved: {', '.join(user.categories) or 'None'}",
            reply_markup=main_menu(),
        )

    async def _handle_assets(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        sub = parts[1] if len(parts) > 1 else ""

        if sub == "back":
            categories = await self.db.get_asset_categories()
            if not categories:
                categories = ALL_CATEGORIES
            await query.edit_message_text(
                "💰 **Assets**\nPick a category to choose specific assets.",
                parse_mode="Markdown",
                reply_markup=asset_category_picker(categories),
            )
            return
        if sub == "done":
            favs = ", ".join(user.favorite_assets) if user.favorite_assets else "None (all assets in your categories)"
            await query.edit_message_text(
                f"✅ Favorite assets saved:\n{favs}",
                reply_markup=main_menu(),
            )
            return
        if sub == "noop":
            return
        if sub == "cat":
            category = parts[2] if len(parts) > 2 else ""
            assets = await self.db.get_assets_by_category(category)
            names = [a.name for a in assets]
            context.user_data["asset_category"] = category
            context.user_data["asset_page"] = 0
            await query.edit_message_text(
                f"💰 **{category} assets**\nTap ⭐ to favorite, then ✅ Done.",
                parse_mode="Markdown",
                reply_markup=asset_picker(category, names, 0, user.favorite_assets),
            )
            return
        if sub == "page":
            rest = parts[2] if len(parts) > 2 else ""
            # rest = "<page>:<category>"
            page_str, _, category = rest.partition(":")
            try:
                page = int(page_str)
            except ValueError:
                page = 0
            assets = await self.db.get_assets_by_category(category)
            names = [a.name for a in assets]
            context.user_data["asset_category"] = category
            context.user_data["asset_page"] = page
            await query.edit_message_text(
                f"💰 **{category} assets**\nTap ⭐ to favorite, then ✅ Done.",
                parse_mode="Markdown",
                reply_markup=asset_picker(category, names, page, user.favorite_assets),
            )

    async def _handle_asset_toggle(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        asset = parts[1] if len(parts) > 1 else ""
        if not asset:
            return
        if asset in user.favorite_assets:
            user.favorite_assets.remove(asset)
        else:
            user.favorite_assets.append(asset)
        await self.db.save_user(user)

        category = context.user_data.get("asset_category") or ""
        page = context.user_data.get("asset_page") or 0
        assets = await self.db.get_assets_by_category(category) if category else []
        names = [a.name for a in assets]
        await query.edit_message_text(
            f"💰 **{category} assets**\nTap ⭐ to favorite, then ✅ Done.",
            parse_mode="Markdown",
            reply_markup=asset_picker(category, names, page, user.favorite_assets),
        )

    async def _handle_duration(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        duration = parts[1] if len(parts) > 1 else ""
        if duration not in VALID_DURATIONS:
            return
        user.duration = duration
        await self.db.save_user(user)
        await query.edit_message_text(
            f"✅ Duration set to: {duration}",
            reply_markup=duration_picker(user.duration),
        )

    async def _handle_frequency(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        freq = parts[1] if len(parts) > 1 else ""
        if freq not in ("conservative", "normal", "aggressive"):
            return
        user.frequency = freq
        await self.db.save_user(user)
        await query.edit_message_text(
            f"✅ Frequency set to: {freq}",
            reply_markup=frequency_picker(user.frequency),
        )

    async def _handle_quiet_hours(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        key = parts[1] if len(parts) > 1 else "off"
        start, end = QUIET_PRESETS.get(key, (0, 0))
        user.quiet_hours_start = start
        user.quiet_hours_end = end
        await self.db.save_user(user)
        label = "Off (24/7)" if start == end == 0 else f"{start}:00 - {end}:00 UTC"
        await query.edit_message_text(
            f"✅ Quiet hours set to: {label}",
            reply_markup=quiet_hours_picker(user.quiet_hours_start, user.quiet_hours_end),
        )

    async def _handle_signals(self, update: Update, context: CallbackContext, user: User):
        query = update.callback_query
        user.enabled = not user.enabled
        await self.db.save_user(user)
        await query.edit_message_text(
            f"🔔 **Signals**\nCurrent: {'ON' if user.enabled else 'OFF'}",
            parse_mode="Markdown",
            reply_markup=signals_toggle(user.enabled),
        )

    async def _handle_setup(self, update: Update, context: CallbackContext, user: User, parts):
        query = update.callback_query
        sub = parts[1] if len(parts) > 1 else "start"

        if sub == "start":
            await query.edit_message_text(
                SETUP_STEPS[0],
                parse_mode="Markdown",
                reply_markup=category_toggle(user.categories, ALL_CATEGORIES),
            )
            return
        if sub == "done":
            await query.edit_message_text(
                "🎉 **Setup complete!**\n\n" + self._format_settings(user),
                parse_mode="Markdown",
                reply_markup=main_menu(),
            )
            return
        if sub == "step":
            try:
                step = int(parts[2])
            except (IndexError, ValueError):
                step = 2
            if step == 2:
                categories = await self.db.get_asset_categories()
                if not categories:
                    categories = ALL_CATEGORIES
                await query.edit_message_text(
                    SETUP_STEPS[1],
                    parse_mode="Markdown",
                    reply_markup=asset_category_picker(categories),
                )
            elif step == 3:
                await query.edit_message_text(
                    SETUP_STEPS[2],
                    parse_mode="Markdown",
                    reply_markup=duration_picker(user.duration),
                )
            elif step == 4:
                await query.edit_message_text(
                    SETUP_STEPS[3],
                    parse_mode="Markdown",
                    reply_markup=signals_toggle(user.enabled),
                )
            elif step >= 5:
                await query.edit_message_text(
                    "🎉 **Setup complete!**\n\n" + self._format_settings(user),
                    parse_mode="Markdown",
                    reply_markup=main_menu(),
                )

    async def _handle_trade_help(self, update: Update, context: CallbackContext, parts):
        query = update.callback_query
        text = (
            "📖 **How to place this trade**\n\n"
            "1️⃣ Open Quotex and select the **asset** shown on the signal\n"
            "2️⃣ Choose the **direction** (CALL = up ▲, PUT = down ▼)\n"
            "3️⃣ Set the **expiry duration** shown on the signal\n"
            "4️⃣ Enter your **amount** (max 2% of account)\n"
            "5️⃣ Tap **BUY** and confirm\n\n"
            "⚠️ Signals are educational. Trade at your own risk."
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=help_button())

    def _format_settings(self, user: User) -> str:
        favs = ", ".join(user.favorite_assets) if user.favorite_assets else "All in categories"
        return (
            "⚙️ **Your Settings**\n\n"
            f"Status: {'Enabled ✅' if user.enabled else 'Disabled ❌'}\n"
            f"Categories: {', '.join(user.categories) or 'None'}\n"
            f"Favorite Assets: {favs}\n"
            f"Duration: {user.duration}\n"
            f"Frequency: {user.frequency}\n"
            f"Quiet Hours: {user.quiet_hours_start}:00 - {user.quiet_hours_end}:00 UTC\n"
        )