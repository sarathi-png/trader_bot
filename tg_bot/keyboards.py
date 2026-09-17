from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

ASSETS_PER_PAGE = 8


def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📊 Categories", callback_data="menu:categories")],
        [InlineKeyboardButton("💰 Assets", callback_data="menu:assets")],
        [InlineKeyboardButton("⏱ Duration", callback_data="menu:duration")],
        [InlineKeyboardButton("🔔 Signals", callback_data="menu:signals")],
        [InlineKeyboardButton("⚙️ Frequency", callback_data="menu:frequency")],
        [InlineKeyboardButton("🌙 Quiet Hours", callback_data="menu:quiet_hours")],
        [
            InlineKeyboardButton("📈 Stats", callback_data="menu:stats"),
            InlineKeyboardButton("🗓 Calendar", callback_data="menu:calendar"),
        ],
        [
            InlineKeyboardButton("🔌 Status", callback_data="menu:status"),
            InlineKeyboardButton("📊 Backtest", callback_data="menu:backtest"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
        [InlineKeyboardButton("📖 Help", callback_data="menu:help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def category_toggle(selected: List[str], all_categories: List[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for cat in all_categories:
        mark = "✅" if cat in selected else "⬜"
        keyboard.append([InlineKeyboardButton(f"{mark} {cat}", callback_data=f"cat:{cat}")])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="cats:done")])
    return InlineKeyboardMarkup(keyboard)


def asset_category_picker(categories: List[str]) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(f"📂 {cat}", callback_data=f"assets:cat:{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(keyboard)


def asset_picker(category: str, assets: List[str], page: int, selected: List[str]) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(assets) + ASSETS_PER_PAGE - 1) // ASSETS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ASSETS_PER_PAGE
    chunk = assets[start:start + ASSETS_PER_PAGE]

    keyboard = []
    for asset in chunk:
        mark = "⭐" if asset in selected else "▫️"
        keyboard.append([InlineKeyboardButton(f"{mark} {asset}", callback_data=f"asset:{asset}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"assets:page:{page - 1}:{category}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="assets:noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"assets:page:{page + 1}:{category}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔙 Categories", callback_data="assets:back")])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="assets:done")])
    return InlineKeyboardMarkup(keyboard)


def duration_picker(current: str) -> InlineKeyboardMarkup:
    options = [("1min", "1min (Scalping)"), ("3min", "3min (Standard)"),
               ("5min", "5min (Standard)"), ("15min", "15min (Extended)")]
    keyboard = []
    for value, label in options:
        mark = "✅" if value == current else ""
        text = f"{mark} {label}".strip()
        keyboard.append([InlineKeyboardButton(text, callback_data=f"dur:{value}")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(keyboard)


def frequency_picker(current: str) -> InlineKeyboardMarkup:
    options = [("conservative", "🐢 Conservative"), ("normal", "⚖️ Normal"), ("aggressive", "🚀 Aggressive")]
    keyboard = []
    for value, label in options:
        mark = "✅" if value == current else ""
        text = f"{mark} {label}".strip()
        keyboard.append([InlineKeyboardButton(text, callback_data=f"freq:{value}")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(keyboard)


def quiet_hours_picker(current_start: int, current_end: int) -> InlineKeyboardMarkup:
    presets = [
        ("off", "🔕 Off (24/7)", 0, 0),
        ("night", "🌙 23:00 - 07:00 UTC", 23, 7),
        ("day", "☀️ 09:00 - 17:00 UTC", 9, 17),
    ]
    keyboard = []
    for key, label, start, end in presets:
        active = (start == current_start and end == current_end)
        mark = "✅" if active else ""
        text = f"{mark} {label}".strip()
        keyboard.append([InlineKeyboardButton(text, callback_data=f"qh:{key}")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(keyboard)


def signals_toggle(enabled: bool) -> InlineKeyboardMarkup:
    state = "ON" if enabled else "OFF"
    keyboard = [
        [InlineKeyboardButton(f"🔔 Signals: {state}", callback_data="sig:toggle")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def help_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📖 How to use", callback_data="menu:help")]])


def setup_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🚀 Start Setup", callback_data="setup:start")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def setup_step(step: int) -> InlineKeyboardMarkup:
    """Guided setup navigation. step: 1..5 (5 = done)."""
    if step >= 5:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done", callback_data="setup:done")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
        ])
    keyboard = [
        [InlineKeyboardButton("▶️ Next", callback_data=f"setup:step:{step + 1}")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def signal_action_buttons(signal_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📖 How to trade", callback_data=f"trade:howto:{signal_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)