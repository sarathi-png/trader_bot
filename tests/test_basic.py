import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Settings
from database.repository import Database
from database.models import Candle, Signal, User, Asset
from core.candles import MockCandleCollector
from engine.scorer import ConfluenceScorer
from engine.filter import SessionFilter
from tg_bot.signals import SignalFormatter


async def test_database():
    print("\n=== Testing Database ===")
    db = Database(":memory:")
    await db.connect()

    candle = Candle(timestamp=1000000, asset="EURUSD_otc", open=1.1, high=1.101, low=1.099, close=1.1005)
    await db.save_candle(candle)
    candles = await db.get_candles("EURUSD_otc")
    assert len(candles) == 1, f"Expected 1 candle, got {len(candles)}"
    print("  Database: OK")

    user = User(telegram_id=12345, username="test_user", categories=["CURRENCIES", "CRYPTO"])
    await db.save_user(user)
    fetched = await db.get_user(12345)
    assert fetched is not None
    assert fetched.username == "test_user"
    print("  User CRUD: OK")

    asset = Asset(name="EURUSD_otc", category="CURRENCIES", payout=92)
    await db.save_asset(asset)
    payout = await db.get_payout("EURUSD_otc")
    assert payout == 92
    print("  Asset CRUD: OK")

    await db.close()
    print("  Database tests passed!")


async def test_strategies():
    print("\n=== Testing Strategies ===")
    db = Database(":memory:")
    await db.connect()

    collector = MockCandleCollector(db)
    await collector.simulate_candles("EURUSD_otc", 200)

    scorer = ConfluenceScorer(min_confidence=65)
    candles = await db.get_candles("EURUSD_otc", limit=100)
    assert len(candles) > 50, f"Need at least 50 candles, got {len(candles)}"

    direction, confidence, aligned, indicators = scorer.analyze(candles)
    print(f"  Signal: {direction} ({confidence}% confidence)")
    print(f"  Aligned: {aligned}")
    print(f"  Indicators: {list(indicators.keys())}")
    print("  Strategies: OK")

    await db.close()


async def test_session_filter():
    print("\n=== Testing Session Filter ===")
    filt = SessionFilter(blocked_hours=[1, 11, 17, 20])
    tradable = filt.is_tradable()
    session = filt.get_current_session()
    print(f"  Current session: {session}")
    print(f"  Tradable: {tradable}")
    print("  Session filter: OK")


async def test_formatter():
    print("\n=== Testing Signal Formatter ===")
    from datetime import datetime, timezone, timedelta
    formatter = SignalFormatter()

    signal = Signal(
        id="test-123",
        asset="EURUSD_otc",
        direction="CALL",
        confidence=78,
        strategies=["EMA_RSI", "BOLLINGER"],
        duration="3min",
        entry_time=datetime.now(timezone.utc) + timedelta(minutes=5),
        payout=92
    )

    msg = formatter.format_signal(signal)
    assert "EURUSD_otc" in msg
    assert "CALL" in msg
    assert "78%" in msg
    print("  Signal formatting: OK")

    result_msg = formatter.format_result(signal)
    assert "TRADE RESULT" in result_msg
    print("  Result formatting: OK")


async def run_all_tests():
    print("=" * 50)
    print("  Quotex Signal Bot - Test Suite")
    print("=" * 50)

    await test_database()
    await test_strategies()
    await test_session_filter()
    await test_formatter()

    print("\n" + "=" * 50)
    print("  All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
