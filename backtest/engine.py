"""Backtesting and validation module (Priority 6 of the fix brief).

Replays stored historical 1-minute candles through the *same* live pipeline —
strategies -> confluence scorer -> MTF confirmation -> the fixed grading
window (actual entry at entry_time, expiry at entry_time + duration) — and
reports performance exclusively from a strictly later, untouched validation
window.

Honesty rules enforced here (per the fix brief):
* parameter/weight tuning must only ever use the training window;
* never report a win rate on fewer than ``min_sample`` graded trades;
* always show a confidence interval, never a bare percentage;
* output is "measured performance", never a marketed accuracy claim.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from database.repository import Database
from engine.scorer import ConfluenceScorer
from engine.multitimeframe import MultiTimeframeAnalyzer

MIN_SAMPLE = 100
PRE_ENTRY_GAP_MINUTES = 5
SIGNAL_COOLDOWN_SECONDS = 300
TRAIN_RATIO = 0.7
DEFAULT_DURATIONS = ("1min", "3min", "5min", "15min")


@dataclass
class BacktestTrade:
    asset: str
    direction: str
    confidence: int
    duration: str
    entry_time: int  # epoch seconds; the trade actually starts here
    actual_entry_price: float
    exit_price: float
    result: str  # WIN / LOSS / SKIP


@dataclass
class BacktestResult:
    trades: List[BacktestTrade] = field(default_factory=list)
    total: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    insufficient_sample: bool = False
    evaluated_minutes: int = 0
    notes: List[str] = field(default_factory=list)

    def validation_trades(self) -> List[BacktestTrade]:
        """Trades in the strictly-later validation window (chronological split)."""
        count = len(self.trades)
        split = int(count * TRAIN_RATIO)
        return self.trades[split:]


def wilson_interval(wins: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """95% Wilson score interval for a binary proportion."""
    if n == 0:
        return (0.0, 1.0)
    phat = wins / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / denom
    return (centre - half, centre + half)


def _parse_duration_minutes(duration: str) -> int:
    if not duration:
        return 3
    try:
        digits = "".join(ch for ch in duration if ch.isdigit())
        if not digits:
            return 3
        return max(1, int(digits))
    except (ValueError, TypeError):
        return 3


async def run_backtest(
    db: Database,
    min_confidence: int = 50,
    min_payout: int = 80,
    durations: Tuple[str, ...] = DEFAULT_DURATIONS,
    max_candles_per_asset: int = 3000,
    max_signals_per_day: int = 15,
) -> BacktestResult:
    """Replay stored candles and grade trades exactly like the live loop.

    Approximations (documented, not hidden):
    - The news filter is not applied (it depends on live calendar fetches).
    - User-driven duration sets are approximated by evaluating all configured
      durations; per-user frequency thresholds are not applied.
    - The daily signal cap is approximated per UTC day across all assets.
    """
    scorer = ConfluenceScorer(min_confidence=min_confidence)
    mtf = MultiTimeframeAnalyzer()

    result = BacktestResult()
    result.notes.append("News filter not applied in backtest (live-calendar dependent).")
    result.notes.append("Durations: all configured durations evaluated per signal.")

    assets = await db.get_active_assets()
    assets = [a for a in assets if a.payout >= min_payout]
    if not assets:
        result.notes.append("No active assets with payout >= min_payout.")
        return result

    last_signal: Dict[str, int] = {}
    daily_counts: Dict[str, int] = {}

    for asset in assets:
        candles = await db.get_candles(asset.name, limit=max_candles_per_asset)

        for i in range(len(candles)):
            candle_ts = candles[i].timestamp
            day_key = datetime.fromtimestamp(candle_ts, tz=timezone.utc).date().isoformat()

            # --- live-identical signal evaluation on the trailing window ---
            window = candles[max(0, i - 299): i + 1]
            if len(window) < 15:
                continue
            result.evaluated_minutes += 1

            direction, confidence, aligned, indicators = scorer.analyze(window)
            if direction == "NONE" or confidence == 0:
                continue

            confirmed, mtf_trend, mtf_adj = mtf.confirm(direction, window)
            confidence = max(0, min(100, confidence + mtf_adj))
            if not confirmed or confidence < min_confidence:
                continue

            key = f"{asset.name}:{direction}"
            last_ts = last_signal.get(key)
            if last_ts and candle_ts - last_ts < SIGNAL_COOLDOWN_SECONDS:
                continue

            # --- trade simulation with the fixed grading window ---
            emitted_any = False
            for duration in durations:
                duration_minutes = _parse_duration_minutes(duration)

                # Pre-entry gap: signal at T0, actual entry at T0 + 5min.
                entry_ts = candle_ts + PRE_ENTRY_GAP_MINUTES * 60
                entry_candle = _candle_at(candles, entry_ts)
                if entry_candle is None:
                    continue

                # Real expiry = entry + duration; grade at THAT timestamp.
                expiry_ts = entry_ts + duration_minutes * 60
                exit_candle = _candle_at(candles, expiry_ts)
                if exit_candle is None:
                    continue

                if daily_counts.get(day_key, 0) >= max_signals_per_day:
                    break

                won = (
                    exit_candle.close > entry_candle.close
                    if direction == "CALL"
                    else exit_candle.close < entry_candle.close
                )
                result.trades.append(BacktestTrade(
                    asset=asset.name,
                    direction=direction,
                    confidence=confidence,
                    duration=duration,
                    entry_time=entry_ts,
                    actual_entry_price=entry_candle.close,
                    exit_price=exit_candle.close,
                    result="WIN" if won else "LOSS",
                ))
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
                emitted_any = True

            if emitted_any:
                last_signal[key] = candle_ts

    # --- report performance from the validation window only ---
    result.trades.sort(key=lambda t: t.entry_time)
    valid = result.validation_trades()
    result.total = len(valid)
    result.wins = sum(1 for t in valid if t.result == "WIN")
    result.losses = result.total - result.wins

    if result.total < MIN_SAMPLE:
        result.insufficient_sample = True
        result.notes.append(
            f"Validation window has {result.total} graded trades "
            f"(min {MIN_SAMPLE} required); win rate not reported."
        )
    elif result.total > 0:
        result.win_rate = round(result.wins / result.total * 100, 1)
        lo, hi = wilson_interval(result.wins, result.total)
        result.ci_low = round(lo * 100, 1)
        result.ci_high = round(hi * 100, 1)

    return result


def _candle_at(candles: List, timestamp: int):
    """First candle whose timestamp >= timestamp (matches get_candle_at)."""
    for c in candles:
        if c.timestamp >= timestamp:
            return c
    return None


def format_backtest(result: BacktestResult) -> str:
    lines = [
        "📉 BACKTEST (validation window, measured)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if result.insufficient_sample:
        lines.append(
            f"Sample: {result.total} graded trades (< {MIN_SAMPLE})\n"
            f"→ Not enough data for a meaningful win rate."
        )
    else:
        lines.append(f"Trades:  {result.total}")
        lines.append(f"Wins:    {result.wins}")
        lines.append(f"Losses:  {result.losses}")
        lines.append(f"Win Rate: {result.win_rate}%")
        if result.ci_low is not None and result.ci_high is not None:
            lines.append(f"95% CI:  {result.ci_low}% – {result.ci_high}%")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for note in result.notes[:4]:
        lines.append(f"• {note}")
    lines.append("Measured performance — not a guarantee of future results.")
    return "\n".join(lines)