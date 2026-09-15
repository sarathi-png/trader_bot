# Quotex Signal Bot

A Telegram-based trading signal bot for Quotex binary options. Analyzes market data across all asset categories (Currencies, Crypto, Commodities, Stocks) and delivers high-confidence CALL/PUT signals for manual trade execution.

## Features

- **5 Strategy Confluence System**: EMA+RSI, Bollinger Bands, ZigZag+DeMarker, MACD+S/R, Stochastic+RSI
- **Confidence Scoring**: Signals above `MIN_CONFIDENCE` (50 by default) are sent; per-strategy trigger strength now feeds the confluence score
- **Live Candle Streaming**: M1 candles are polled in real time and only closed candles are ingested
- **Correct Trade Grading**: WIN/LOSS is measured from the actual entry (at alert expiry) to the real trade expiry (`entry + duration`)
- **Per-User Settings**: `duration` and `frequency` genuinely filter delivery per user
- **Telegram Integration**: Real-time signal delivery with pre-entry alerts
- **All Asset Categories**: Currencies, Crypto, Commodities, Stocks
- **Session Filters**: Avoids choppy rollover hours
- **Backtesting**: Replays stored candles and reports a validation-window win rate with a 95% confidence interval
- **Performance Tracking**: Measured win/loss statistics and history

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp config/.env.example .env
# Edit .env with your credentials
```

### 3. Run the Bot

```bash
python run.py
```

## Configuration

Edit `.env` file:

```bash
# Quotex (leave blank for mock mode)
QUOTEX_EMAIL=your_email@example.com
QUOTEX_PASSWORD=your_password
QUOTEX_DEMO=true

# Telegram Bot (get from @BotFather)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_ALLOWED_USERS=123456

# Signal Engine
MIN_CONFIDENCE=50
MIN_PAYOUT=80
MAX_SIGNALS_PER_DAY=15
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show available commands |
| `/signals` | Enable/disable signal notifications |
| `/categories` | Set asset categories |
| `/duration` | Set trade duration |
| `/settings` | View your settings |
| `/stats` | View measured performance (incl. break-even win rate) |
| `/backtest` | Backtest on historical candles (validation window) |
| `/status` | Check bot status |
| `/calendar` | Upcoming news events |

## Architecture

```
pyquotex (WebSocket) → Candle Store (SQLite) → Analysis Engine (5 Strategies)
                                                       ↓
                                              Confluence Scorer (65%+ threshold)
                                                       ↓
                                              Signal Generator → Telegram Bot
```

## Project Structure

```
quotex-signal-bot/
├── config/           # Configuration management
├── core/             # Connection, candles, events
├── strategies/       # 5 trading strategies
├── engine/           # Scorer and session filter
├── telegram/         # Bot interface
├── database/         # SQLite models and operations
├── tests/            # Test suite
├── main.py           # Main orchestrator
└── run.py            # Entry point
```

## Testing

```bash
python -m tests.test_basic
```

## How It Works

1. **Data Collection**: Connects to Quotex, subscribes to the live candle stream, and polls realtime ticks each second. Ticks are aggregated into 1-minute candles and only **closed** candles are stored.
2. **Analysis**: Runs 5 strategies on each asset every minute.
3. **Scoring**: Confidence = sum of each aligned strategy's weight × its own trigger strength, capped at 100.
4. **Grading**: A signal is generated at T0, the actual entry is captured at `T0 + 5min`, and WIN/LOSS is measured at `entry + duration` against that actual entry.
5. **Filtering**: Blocks signals during rollover hours, low-payout assets, high-impact news windows, and per-user frequency thresholds.
6. **Delivery**: Sends qualifying signals only to users whose category **and** `duration` match, outside their quiet hours.

## Backtesting

```bash
python -m backtest.engine   # (run via the bot: /backtest)
```

The backtester replays stored candles through the same strategies, scorer, and
grading logic as live trading. Trades are split chronologically: parameters
may only be tuned on the training window, and the reported win rate comes
**only** from the untouched validation window. A win rate is never reported on
fewer than 100 graded trades, and results include a 95% confidence interval.
Output is labelled "measured performance" — not a guarantee of future results.

## Security Note (important)

Earlier versions of this project included live credentials (Quotex
email/password, SSID session tokens, and the Telegram bot token) inside the
project folder. If you used any of those credentials:

1. **Rotate your Quotex password** and sign out of all sessions.
2. **Regenerate your Telegram bot token** via @BotFather (the old token is burned).
3. Delete the old `session.json` / `sessions/` files and re-run `python run.py --login`.

`.env`, `sessions/`, `data/*.db*`, and `logs/` are now excluded from Git. The
Windows-only `.venv` was removed — create a fresh one per deployment target:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

## Risk Disclaimer

This bot is for **educational and research purposes only**. Binary options trading involves substantial risk of loss. Past performance does not guarantee future results. Always test on demo accounts before using real funds.
