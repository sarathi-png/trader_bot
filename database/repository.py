import aiosqlite
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from .models import Candle, Signal, User, Asset, PerformanceStats

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        # Zip-upload hosts (e.g. Tranger Cloud) start from a fresh filesystem
        # with no data/ dir — create the parent so first boot can't crash.
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self):
        if self.db:
            await self.db.close()

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                asset TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL DEFAULT 0,
                UNIQUE(timestamp, asset)
            );

            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                strategies TEXT DEFAULT '[]',
                duration TEXT DEFAULT '3min',
                entry_time TEXT,
                entry_price REAL DEFAULT 0,
                actual_entry_price REAL,
                exit_price REAL DEFAULT 0,
                mtf_trend TEXT DEFAULT '',
                payout INTEGER DEFAULT 0,
                status TEXT DEFAULT 'PENDING',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                categories TEXT DEFAULT '["CURRENCIES","CRYPTO","COMMODITIES","STOCKS"]',
                duration TEXT DEFAULT '3min',
                frequency TEXT DEFAULT 'normal',
                quiet_hours_start INTEGER DEFAULT 23,
                quiet_hours_end INTEGER DEFAULT 7,
                enabled INTEGER DEFAULT 1,
                favorite_assets TEXT DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS assets (
                name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                payout INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_candles_asset ON candles(asset);
            CREATE INDEX IF NOT EXISTS idx_candles_timestamp ON candles(timestamp);
            CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
            CREATE INDEX IF NOT EXISTS idx_users_enabled ON users(enabled);
        """)
        await self._migrate()
        await self.db.commit()

    async def _migrate(self):
        cursor = await self.db.execute("PRAGMA table_info(signals)")
        columns = [r[1] for r in await cursor.fetchall()]
        if "entry_price" not in columns:
            await self.db.execute("ALTER TABLE signals ADD COLUMN entry_price REAL DEFAULT 0")
            logger.info("Migrated signals table: added entry_price column")
        if "exit_price" not in columns:
            await self.db.execute("ALTER TABLE signals ADD COLUMN exit_price REAL DEFAULT 0")
            logger.info("Migrated signals table: added exit_price column")
        if "mtf_trend" not in columns:
            await self.db.execute("ALTER TABLE signals ADD COLUMN mtf_trend TEXT DEFAULT ''")
            logger.info("Migrated signals table: added mtf_trend column")
        if "actual_entry_price" not in columns:
            await self.db.execute("ALTER TABLE signals ADD COLUMN actual_entry_price REAL")
            logger.info("Migrated signals table: added actual_entry_price column")

        cursor = await self.db.execute("PRAGMA table_info(users)")
        columns = [r[1] for r in await cursor.fetchall()]
        if "favorite_assets" not in columns:
            await self.db.execute("ALTER TABLE users ADD COLUMN favorite_assets TEXT DEFAULT '[]'")
            logger.info("Migrated users table: added favorite_assets column")

    async def cleanup_old_candles(self, retention_days: int):
        cutoff = int((datetime.now() - timedelta(days=retention_days)).timestamp())
        await self.db.execute("DELETE FROM candles WHERE timestamp < ?", (cutoff,))
        await self.db.commit()

    # Candle operations
    async def save_candle(self, candle: Candle):
        await self.db.execute(
            "INSERT OR REPLACE INTO candles (timestamp, asset, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (candle.timestamp, candle.asset, candle.open, candle.high, candle.low, candle.close, candle.volume)
        )
        await self.db.commit()

    async def save_candles_bulk(self, candles: List[Candle]):
        """Insert many candles in a single transaction (fast seeding/backfill)."""
        if not candles:
            return
        await self.db.executemany(
            "INSERT OR REPLACE INTO candles (timestamp, asset, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(c.timestamp, c.asset, c.open, c.high, c.low, c.close, c.volume) for c in candles]
        )
        await self.db.commit()

    async def get_candles(self, asset: str, limit: int = 100) -> List[Candle]:
        cursor = await self.db.execute(
            "SELECT timestamp, asset, open, high, low, close, volume FROM candles WHERE asset = ? ORDER BY timestamp DESC LIMIT ?",
            (asset, limit)
        )
        rows = await cursor.fetchall()
        return [
            Candle(timestamp=r[0], asset=r[1], open=r[2], high=r[3], low=r[4], close=r[5], volume=r[6])
            for r in reversed(rows)
        ]

    # Signal operations
    async def save_signal(self, signal: Signal):
        await self.db.execute(
            "INSERT OR REPLACE INTO signals (id, asset, direction, confidence, strategies, duration, entry_time, entry_price, actual_entry_price, exit_price, mtf_trend, payout, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (signal.id, signal.asset, signal.direction, signal.confidence,
             json.dumps(signal.strategies), signal.duration,
             signal.entry_time.isoformat() if signal.entry_time else None,
             signal.entry_price, signal.actual_entry_price, signal.exit_price,
             signal.mtf_trend, signal.payout, signal.status,
             signal.created_at.isoformat() if signal.created_at else None)
        )
        await self.db.commit()

    async def get_pending_signals(self) -> List[Signal]:
        cursor = await self.db.execute(
            "SELECT id, asset, direction, confidence, strategies, duration, entry_time, entry_price, actual_entry_price, exit_price, mtf_trend, payout, status, created_at FROM signals WHERE status = 'PENDING'"
        )
        rows = await cursor.fetchall()
        return [self._row_to_signal(r) for r in rows]

    async def get_expired_pending_signals(self) -> List[Signal]:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.db.execute(
            "SELECT id, asset, direction, confidence, strategies, duration, entry_time, entry_price, actual_entry_price, exit_price, mtf_trend, payout, status, created_at FROM signals WHERE status = 'PENDING' AND entry_time IS NOT NULL AND entry_time <= ?",
            (now,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_signal(r) for r in rows]

    async def get_candle_at(self, asset: str, timestamp: int) -> Optional[Candle]:
        cursor = await self.db.execute(
            "SELECT timestamp, asset, open, high, low, close, volume FROM candles WHERE asset = ? AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
            (asset, timestamp)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Candle(timestamp=row[0], asset=row[1], open=row[2], high=row[3], low=row[4], close=row[5], volume=row[6])

    async def get_signal_history(self, days: int = 7) -> List[Signal]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await self.db.execute(
            "SELECT id, asset, direction, confidence, strategies, duration, entry_time, entry_price, actual_entry_price, exit_price, mtf_trend, payout, status, created_at FROM signals WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_signal(r) for r in rows]

    async def update_signal_status(self, signal_id: str, status: str, exit_price: float = 0.0):
        await self.db.execute(
            "UPDATE signals SET status = ?, exit_price = ? WHERE id = ?",
            (status, exit_price, signal_id)
        )
        await self.db.commit()

    async def get_today_signal_count(self) -> int:
        today = datetime.now().date().isoformat()
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (today,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    def _row_to_signal(self, row) -> Signal:
        return Signal(
            id=row[0], asset=row[1], direction=row[2], confidence=row[3],
            strategies=json.loads(row[4]) if row[4] else [],
            duration=row[5],
            entry_time=datetime.fromisoformat(row[6]) if row[6] else None,
            entry_price=row[7] if row[7] else 0.0,
            actual_entry_price=row[8] if row[8] else None,
            exit_price=row[9] if row[9] else 0.0,
            mtf_trend=row[10] if row[10] else "",
            payout=row[11], status=row[12],
            created_at=datetime.fromisoformat(row[13]) if row[13] else None
        )

    # User operations
    async def save_user(self, user: User):
        await self.db.execute(
            "INSERT OR REPLACE INTO users (telegram_id, username, categories, duration, frequency, quiet_hours_start, quiet_hours_end, enabled, favorite_assets) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user.telegram_id, user.username, json.dumps(user.categories),
             user.duration, user.frequency, user.quiet_hours_start, user.quiet_hours_end,
             1 if user.enabled else 0, json.dumps(user.favorite_assets))
        )
        await self.db.commit()

    async def get_user(self, telegram_id: int) -> Optional[User]:
        cursor = await self.db.execute(
            "SELECT telegram_id, username, categories, duration, frequency, quiet_hours_start, quiet_hours_end, enabled, favorite_assets FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return User(
            telegram_id=row[0], username=row[1],
            categories=json.loads(row[2]) if row[2] else [],
            duration=row[3], frequency=row[4],
            quiet_hours_start=row[5], quiet_hours_end=row[6],
            enabled=bool(row[7]),
            favorite_assets=json.loads(row[8]) if row[8] else []
        )

    async def get_eligible_users(self, category: str, duration: str, asset: str = "") -> List[User]:
        cursor = await self.db.execute(
            "SELECT telegram_id, username, categories, duration, frequency, quiet_hours_start, quiet_hours_end, enabled, favorite_assets FROM users WHERE enabled = 1 AND duration = ?",
            (duration,)
        )
        rows = await cursor.fetchall()
        users = []
        for r in rows:
            user = User(
                telegram_id=r[0], username=r[1],
                categories=json.loads(r[2]) if r[2] else [],
                duration=r[3], frequency=r[4],
                quiet_hours_start=r[5], quiet_hours_end=r[6],
                enabled=bool(r[7]),
                favorite_assets=json.loads(r[8]) if r[8] else []
            )
            if user.favorite_assets:
                # Pair-first flow: favorites override category filtering.
                if asset and asset in user.favorite_assets:
                    users.append(user)
            elif category in user.categories:
                users.append(user)
        return users

    async def get_active_user_durations(self) -> List[str]:
        """Distinct durations any enabled user has configured (signal engine
        generates one signal per configured duration)."""
        cursor = await self.db.execute(
            "SELECT DISTINCT duration FROM users WHERE enabled = 1"
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows if r[0]]

    # Asset operations
    async def save_asset(self, asset: Asset):
        await self.db.execute(
            "INSERT OR REPLACE INTO assets (name, category, payout, active) VALUES (?, ?, ?, ?)",
            (asset.name, asset.category, asset.payout, 1 if asset.active else 0)
        )
        await self.db.commit()

    async def get_payout(self, asset_name: str) -> int:
        cursor = await self.db.execute(
            "SELECT payout FROM assets WHERE name = ?", (asset_name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_asset_category(self, asset_name: str) -> str:
        cursor = await self.db.execute(
            "SELECT category FROM assets WHERE name = ?", (asset_name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else "CURRENCIES"

    async def get_active_assets(self) -> List[Asset]:
        cursor = await self.db.execute(
            "SELECT name, category, payout, active FROM assets WHERE active = 1"
        )
        rows = await cursor.fetchall()
        return [Asset(name=r[0], category=r[1], payout=r[2], active=bool(r[3])) for r in rows]

    async def get_assets_by_category(self, category: str) -> List[Asset]:
        cursor = await self.db.execute(
            "SELECT name, category, payout, active FROM assets WHERE active = 1 AND category = ? ORDER BY payout DESC",
            (category,)
        )
        rows = await cursor.fetchall()
        return [Asset(name=r[0], category=r[1], payout=r[2], active=bool(r[3])) for r in rows]

    async def get_asset_categories(self) -> List[str]:
        cursor = await self.db.execute(
            "SELECT DISTINCT category FROM assets WHERE active = 1 ORDER BY category"
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    # Performance stats
    async def get_performance(self, days: int = 7) -> PerformanceStats:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        today = datetime.now().date().isoformat()

        # Total signals
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ? AND status IN ('WIN', 'LOSS')", (cutoff,)
        )
        total = (await cursor.fetchone())[0]

        # Wins
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ? AND status = 'WIN'", (cutoff,)
        )
        wins = (await cursor.fetchone())[0]

        # Losses
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ? AND status = 'LOSS'", (cutoff,)
        )
        losses = (await cursor.fetchone())[0]

        # Today stats
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (today,)
        )
        today_total = (await cursor.fetchone())[0]

        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ? AND status = 'WIN'", (today,)
        )
        today_wins = (await cursor.fetchone())[0]

        win_rate = (wins / total * 100) if total > 0 else 0

        return PerformanceStats(
            total_signals=total,
            wins=wins,
            losses=losses,
            win_rate=round(win_rate, 1),
            today_signals=today_total,
            today_wins=today_wins
        )
