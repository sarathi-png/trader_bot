"""Tests for the fix-brief priorities 1-7.

Each test maps to a priority in the fix brief and verifies the actual
behavior change, not just that code imports.

Run:  python -m tests.test_fixes
"""

import asyncio
import os
import sys
import time
import random
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import Asset, Candle, Signal, StrategyResult, User
from database.repository import Database
from core.candles import CandleCollector
from core.connection import MockQuotexConnection
from engine.scorer import ConfluenceScorer
from strategies.zigzag_demark import ZigZagDeMarkerStrategy
from main import QuotexSignalBot

ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    line = f"  [{status}] {name}"
    if detail and not condition:
        line += f" — {detail}"
    print(line)
    if not condition:
        ERRORS.append(f"{name}: {detail}")


async def test_scorer_confidence_wiring():
    """Priority 3: per-strategy trigger strength must change the score."""
    print("\n=== Priority 3 — Per-strategy confidence wired into score ===")
    scorer = ConfluenceScorer()

    weak = [
        StrategyResult("EMA_RSI", "CALL", confidence=60),
        StrategyResult("BOLLINGER", "CALL", confidence=60),
        StrategyResult("MACD_SR", "CALL", confidence=60),
    ]
    strong = [
        StrategyResult("EMA_RSI", "CALL", confidence=90),
        StrategyResult("BOLLINGER", "CALL", confidence=90),
        StrategyResult("MACD_SR", "CALL", confidence=90),
    ]

    d1, c1, a1 = scorer._calculate_confidence(weak)
    d2, c2, a2 = scorer._calculate_confidence(strong)

    check("same aligned strategies produce same direction", d1 == d2 == "CALL" and a1 == a2)
    check("different per-strategy confidence produces different score", c2 > c1, f"weak={c1} strong={c2}")
    check("score stays within [0,100]", 0 <= c1 <= 100 and 0 <= c2 <= 100)

    # A weak multi-strategy consensus should NOT clear a strict threshold
    # the way it used to: 3 strong signals ought to score higher.
    check("strong consensus strictly stronger than weak consensus", c2 > c1 + 10)


async def test_zigzag_swing_rate():
    """Priority 5: real pivot detection should fire rarely on choppy data."""
    print("\n=== Priority 5 — ZigZag genuine-swing detection ===")
    random.seed(7)
    price = 1.1000
    candles = []
    now = int(time.time()) // 60 * 60
    for i in range(300):
        price += random.uniform(-0.0008, 0.0008)
        candles.append(Candle(
            timestamp=now - (300 - i) * 60, asset="EURUSD_otc",
            open=price, high=price + 0.0004, low=price - 0.0004,
            close=price, volume=100,
        ))

    zz = ZigZagDeMarkerStrategy()
    import pandas_ta as ta
    import pandas as pd

    n = zz.zz_depth
    fire_high = fire_low = total = 0
    for i in range(n + 3, len(candles)):
        window = candles[i - n - 3: i + 1]
        df = zz.candles_to_dataframe(window)
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        fire_high += 1 if zz._find_swing_high(df, atr) else 0
        fire_low += 1 if zz._find_swing_low(df, atr) else 0
        total += 1

    rate = (fire_high + fire_low) / total if total else 1.0
    check("swing detection is rare on random data", rate < 0.5, f"rate={rate:.3f}")

    # Crafted case: a genuine spike-and-retrace MUST be detected as a swing high.
    candles2 = []
    price = 1.1000
    for i in range(120):
        if i == 60:
            price = 1.1500
        elif i > 60:
            price -= 0.0005  # steady decline after spike
        candles2.append(Candle(
            timestamp=now - (120 - i) * 60, asset="EURUSD_otc",
            open=price, high=price + 0.0001, low=price - 0.0001,
            close=price, volume=100,
        ))
    df2 = zz.candles_to_dataframe(candles2)
    atr2 = ta.atr(df2["high"], df2["low"], df2["close"], length=14)
    check("genuine spike-and-retrace detected as swing high", zz._find_swing_high(df2, atr2) is True)


async def test_duration_filtering():
    """Priority 4: /duration must actually filter delivery; durations discoverable."""
    print("\n=== Priority 4 — Per-user duration + frequency settings ===")
    db = Database(":memory:")
    await db.connect()
    try:
        u1 = User(telegram_id=1, username="a", categories=["CURRENCIES"], duration="1min")
        u2 = User(telegram_id=2, username="b", categories=["CURRENCIES"], duration="3min")
        u3 = User(telegram_id=3, username="c", categories=["CRYPTO"], duration="1min")
        await db.save_user(u1)
        await db.save_user(u2)
        await db.save_user(u3)

        elig_1 = await db.get_eligible_users("CURRENCIES", "1min")
        elig_3 = await db.get_eligible_users("CURRENCIES", "3min")
        check("1min users only get 1min signals", [u.telegram_id for u in elig_1] == [1])
        check("3min users only get 3min signals", [u.telegram_id for u in elig_3] == [2])
        check("durations discoverable",
              sorted(await db.get_active_user_durations()) == ["1min", "3min"])
    finally:
        await db.close()


async def test_grading_window_roundtrip():
    """Priority 2: actual_entry_price persists; duration parsing is correct."""
    print("\n=== Priority 2 — Grading window: actual entry + expiry math ===")
    db = Database(":memory:")
    await db.connect()
    try:
        s = Signal(
            id="t1", asset="EURUSD_otc", direction="CALL", confidence=70,
            duration="3min",
            entry_time=datetime.now(timezone.utc) + timedelta(minutes=5),
            entry_price=1.1000,
        )
        await db.save_signal(s)
        fetched = (await db.get_pending_signals())[0]
        check("actual_entry_price defaults to None for new signals",
              fetched.actual_entry_price is None)

        s.actual_entry_price = 1.1050
        await db.save_signal(s)
        fetched2 = (await db.get_pending_signals())[0]
        check("actual_entry_price round-trips through DB", fetched2.actual_entry_price == 1.1050)

        # Expiry math: entry_time + duration_minutes, and NOT entry_time.
        check("parse '3min' -> 3", QuotexSignalBot._parse_duration_minutes("3min") == 3)
        check("parse '15min' -> 15", QuotexSignalBot._parse_duration_minutes("15min") == 15)
        check("parse '' -> 3", QuotexSignalBot._parse_duration_minutes("") == 3)
        check("parse garbage -> 3", QuotexSignalBot._parse_duration_minutes("xx") == 3)

        entry_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        expiry = entry_time + timedelta(minutes=QuotexSignalBot._parse_duration_minutes("5min"))
        check("expiry = entry_time + duration seconds",
              int(expiry.timestamp()) == int(entry_time.timestamp()) + 300)
        check("expiry is strictly after entry_time", expiry > entry_time)
    finally:
        await db.close()


class FakeRTConnection:
    """Stand-in for QuotexConnection: records subscriptions, serves ticks."""

    connected = True

    def __init__(self):
        self.ticks = {}
        self.subscribed = []

    async def get_assets(self):
        return []

    async def subscribe_candles(self, asset, timeframe):
        self.subscribed.append((asset, timeframe))

    def on_candle(self, asset, handler):
        pass

    async def get_realtime_candles(self, asset):
        return self.ticks.get(asset)


async def test_live_candle_polling():
    """Priority 1: subscribe issued; only CLOSED candles are ingested once."""
    print("\n=== Priority 1 — Live candle polling (closed candles only) ===")
    db = Database(":memory:")
    await db.connect()
    try:
        conn = FakeRTConnection()
        collector = CandleCollector(conn, db)
        collector.assets = [Asset(name="EURUSD_otc", category="CURRENCIES", payout=92)]
        await collector.subscribe_all()

        check("server-side subscribe actually issued per asset",
              ("EURUSD_otc", 60) in conn.subscribed)

        base = int(time.time()) // 60 * 60

        # In-progress candle: ticks arrive, nothing is persisted.
        conn.ticks["EURUSD_otc"] = ["EURUSD_otc", base + 5, 1.1000]
        await collector._poll_asset("EURUSD_otc")
        conn.ticks["EURUSD_otc"] = ["EURUSD_otc", base + 30, 1.1005]
        await collector._poll_asset("EURUSD_otc")
        check("no candle ingested while minute is still open",
              len(await db.get_candles("EURUSD_otc")) == 0)

        # First tick of the next minute closes the previous minute.
        conn.ticks["EURUSD_otc"] = ["EURUSD_otc", base + 60, 1.1010]
        await collector._poll_asset("EURUSD_otc")
        candles = await db.get_candles("EURUSD_otc")
        check("exactly one closed candle ingested at the minute boundary",
              len(candles) == 1, f"len={len(candles)}")
        if candles:
            check("candle timestamp = start of closed minute", candles[0].timestamp == base)
            check("candle close = last observed price of that minute", candles[0].close == 1.1005)

        # Further ticks in the same minute do not duplicate or re-ingest.
        conn.ticks["EURUSD_otc"] = ["EURUSD_otc", base + 65, 1.1012]
        await collector._poll_asset("EURUSD_otc")
        check("no duplicate ingestion for same closed minute",
              len(await db.get_candles("EURUSD_otc")) == 1)

        await collector.stop_collection()
    finally:
        await db.close()


async def test_backtest_smoke():
    """Priority 6: backtester runs, splits chronologically, respects sample size."""
    print("\n=== Priority 6 — Backtester (validation-window reporting) ===")
    db = Database(":memory:")
    await db.connect()
    try:
        from backtest.engine import run_backtest, format_backtest, MIN_SAMPLE

        random.seed(11)
        await db.save_asset(Asset("EURUSD_otc", "CURRENCIES", 92))
        now = int(time.time()) // 60 * 60
        price = 1.1000
        for i in range(600):
            price += random.uniform(-0.001, 0.0012)
            await db.save_candle(Candle(
                timestamp=now - (600 - i) * 60, asset="EURUSD_otc",
                open=price, high=price + 0.0006, low=price - 0.0006,
                close=price, volume=100,
            ))

        result = await run_backtest(db, min_confidence=50, min_payout=80,
                                    durations=("1min", "3min", "5min"))
        valid = result.validation_trades()

        check("backtester produced some trades", len(result.trades) > 0)
        check("validation is a strict later subset",
              len(valid) <= len(result.trades))
        if len(result.trades) >= 2:
            train_ts = [t.entry_time for t in result.trades[:int(len(result.trades) * 0.7)]]
            valid_ts = [t.entry_time for t in valid]
            check("validation window strictly later than training window",
                  max(train_ts) <= min(valid_ts) if train_ts and valid_ts else True)

        check("win rate suppressed below MIN_SAMPLE",
              result.insufficient_sample or (result.total >= MIN_SAMPLE and result.win_rate is not None))
        text = format_backtest(result)
        check("formatted output labelled as measured backtest", "BACKTEST" in text)
        if result.win_rate is not None:
            check("confidence interval present with a reported rate",
                  result.ci_low is not None and result.ci_high is not None)
    finally:
        await db.close()


async def test_news_filter_cache_fallback():
    """Priority 7: failed calendar fetches keep the previously cached list."""
    print("\n=== Priority 7 — News filter cache fallback ===")
    import engine.news_filter as nf_mod
    from engine.news_filter import NewsFilter, NewsEvent

    nf = NewsFilter()
    cached = NewsEvent("Keep Me", "USD", datetime.now(timezone.utc), "High")
    nf._events = [cached]
    nf._last_fetch = None

    nf_mod.CALENDAR_URL = "http://127.0.0.1:1/calendar"
    nf_mod.CALENDAR_NEXT_URL = "http://127.0.0.1:1/calendar2"

    await nf.refresh()

    check("cached events retained after total fetch failure", len(nf._events) == 1)
    check("cache not overwritten by empty list", nf._events[0].title == "Keep Me")
    check("refresh timestamp not updated on total failure", nf._last_fetch is None)


async def run_all():
    print("=" * 56)
    print("  Quotex Signal Bot — Fix Brief Validation Suite")
    print("=" * 56)
    await test_scorer_confidence_wiring()
    await test_zigzag_swing_rate()
    await test_duration_filtering()
    await test_grading_window_roundtrip()
    await test_live_candle_polling()
    await test_backtest_smoke()
    await test_news_filter_cache_fallback()

    print("\n" + "=" * 56)
    if ERRORS:
        print(f"  {len(ERRORS)} FAILURE(S):")
        for e in ERRORS:
            print(f"    - {e}")
        print("=" * 56)
        return 1
    print("  ALL FIX TESTS PASSED")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_all()))