from datetime import datetime
from database.models import Signal


class SignalFormatter:
    def __init__(self, is_demo: bool = True):
        self.is_demo = is_demo

    def _account_badge(self) -> str:
        return "🧪 DEMO ACCOUNT" if self.is_demo else "💰 LIVE ACCOUNT"

    def format_signal(self, signal: Signal) -> str:
        direction_emoji = "▲" if signal.direction == "CALL" else "▼"
        direction_text = "UP (CALL)" if signal.direction == "CALL" else "DOWN (PUT)"
        action = "BUY" if signal.direction == "CALL" else "SELL"

        confidence_bar = self._confidence_bar(signal.confidence)

        strategies_text = "  ".join([f"✓ {s}" for s in signal.strategies])

        mtf_text = ""
        if signal.mtf_trend:
            mtf_emoji = {"UP": "🟢", "DOWN": "🔴", "NEUTRAL": "⚪", "CONFLICT": "🟡"}.get(signal.mtf_trend, "⚪")
            mtf_text = f"\nMTF Trend:  {mtf_emoji} {signal.mtf_trend}"

        entry_time = signal.entry_time.strftime("%H:%M UTC") if signal.entry_time else "Now"
        entry_price = f"{signal.entry_price:.5f}" if signal.entry_price else "—"

        return (
            f"{'🟢' if signal.direction == 'CALL' else '🔴'} {action} SIGNAL  |  {self._account_badge()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Asset:      {signal.asset}\n"
            f"Direction:  {direction_emoji} {direction_text}\n"
            f"Entry:      {entry_price} (est.)\n"
            f"Expiry:     {entry_time}  ({signal.duration})\n"
            f"Confidence: [{confidence_bar}] {signal.confidence}%\n"
            f"Payout:     {signal.payout}%{mtf_text}\n"
            f"Strategies: {strategies_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Risk: Max 2% of account per trade"
        )

    def format_result(self, signal: Signal) -> str:
        direction_emoji = "▲" if signal.direction == "CALL" else "▼"
        result_emoji = "✅" if signal.status == "WIN" else "❌"
        result_text = "WIN" if signal.status == "WIN" else "LOSS"

        # Grading uses the actual entry captured at entry_time; the value shown
        # in the alert was only an estimate.
        graded_entry = signal.actual_entry_price or signal.entry_price
        entry_price = f"{graded_entry:.5f}" if graded_entry else "—"
        exit_price = f"{signal.exit_price:.5f}" if signal.exit_price else "—"
        pnl = ""
        if graded_entry and signal.exit_price:
            diff = signal.exit_price - graded_entry
            pnl = f"{diff:+.5f}"

        return (
            f"📊 TRADE RESULT  |  {self._account_badge()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Asset:      {signal.asset}\n"
            f"Direction:  {direction_emoji} {signal.direction}\n"
            f"Entry:      {entry_price}\n"
            f"Exit:       {exit_price}\n"
            f"Change:     {pnl}\n"
            f"Result:     {result_emoji} {result_text}\n"
            f"Duration:   {signal.duration}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    def _confidence_bar(self, confidence: int) -> str:
        filled = confidence // 10
        empty = 10 - filled
        return "█" * filled + "░" * empty

    def format_stats(self, stats) -> str:
        return (
            "📈 PERFORMANCE (Last 7 Days)\n\n"
            f"Total Signals: {stats.total_signals}\n"
            f"Wins: {stats.wins}\n"
            f"Losses: {stats.losses}\n"
            f"Win Rate: {stats.win_rate}%\n\n"
            f"Today: {stats.today_wins}/{stats.today_signals}\n"
        )