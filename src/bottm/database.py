"""
Database for storing profitable items.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

DB_PATH = Path("profitable_items.db")


@dataclass
class StoredItem:
    """Item stored in database."""
    id: Optional[int]
    market_hash_name: str
    item_type: str

    # Prices
    steam_buy_order: float
    recommended_buy_order: Optional[float]
    csgo_price: float
    csgo_buy_order: float

    # Profits
    instant_profit_pct: float
    wait_profit_pct: float
    recommended_instant_pct: Optional[float]
    recommended_wait_pct: Optional[float]

    # Orders
    orders_above: Optional[int]

    # Timestamps
    found_at: str
    updated_at: str

    # Status
    is_active: bool = True


class Database:
    """SQLite database for profitable items."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create tables if not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_hash_name TEXT UNIQUE,
                    item_type TEXT,

                    steam_buy_order REAL,
                    recommended_buy_order REAL,
                    csgo_price REAL,
                    csgo_buy_order REAL,

                    instant_profit_pct REAL,
                    wait_profit_pct REAL,
                    recommended_instant_pct REAL,
                    recommended_wait_pct REAL,

                    orders_above INTEGER,

                    found_at TEXT,
                    updated_at TEXT,

                    is_active INTEGER DEFAULT 1
                )
            """)

            # History table for tracking changes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT,
                    steam_buy_order REAL,
                    csgo_price REAL,
                    profit_pct REAL,
                    recorded_at TEXT
                )
            """)
            conn.commit()

    def add_or_update(self, item) -> bool:
        """
        Add new item or update existing.

        Args:
            item: ProfitableItem from scanner

        Returns:
            True if new item added, False if updated
        """
        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # Check if exists
            cur = conn.execute(
                "SELECT id, found_at FROM items WHERE market_hash_name = ?",
                (item.market_hash_name,)
            )
            existing = cur.fetchone()

            profit_pct = item.recommended_wait_profit_pct or item.wait_profit_pct or 0

            if existing:
                # Update existing
                conn.execute("""
                    UPDATE items SET
                        steam_buy_order = ?,
                        recommended_buy_order = ?,
                        csgo_price = ?,
                        csgo_buy_order = ?,
                        instant_profit_pct = ?,
                        wait_profit_pct = ?,
                        recommended_instant_pct = ?,
                        recommended_wait_pct = ?,
                        orders_above = ?,
                        updated_at = ?,
                        is_active = 1
                    WHERE market_hash_name = ?
                """, (
                    item.steam_buy_order,
                    item.recommended_buy_order,
                    item.csgo_price,
                    item.csgo_buy_order,
                    item.instant_profit_pct,
                    item.wait_profit_pct,
                    item.recommended_instant_profit_pct,
                    item.recommended_wait_profit_pct,
                    item.orders_above_recommended,
                    now,
                    item.market_hash_name,
                ))

                # Add to history
                conn.execute("""
                    INSERT INTO history (item_name, steam_buy_order, csgo_price, profit_pct, recorded_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (item.market_hash_name, item.steam_buy_order, item.csgo_price, profit_pct, now))

                conn.commit()
                return False
            else:
                # Insert new
                conn.execute("""
                    INSERT INTO items (
                        market_hash_name, item_type,
                        steam_buy_order, recommended_buy_order, csgo_price, csgo_buy_order,
                        instant_profit_pct, wait_profit_pct, recommended_instant_pct, recommended_wait_pct,
                        orders_above, found_at, updated_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    item.market_hash_name,
                    item.item_type.value if hasattr(item.item_type, 'value') else str(item.item_type),
                    item.steam_buy_order,
                    item.recommended_buy_order,
                    item.csgo_price,
                    item.csgo_buy_order,
                    item.instant_profit_pct,
                    item.wait_profit_pct,
                    item.recommended_instant_profit_pct,
                    item.recommended_wait_profit_pct,
                    item.orders_above_recommended,
                    now,
                    now,
                ))

                # Add to history
                conn.execute("""
                    INSERT INTO history (item_name, steam_buy_order, csgo_price, profit_pct, recorded_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (item.market_hash_name, item.steam_buy_order, item.csgo_price, profit_pct, now))

                conn.commit()
                return True

    def mark_inactive(self, market_hash_name: str):
        """Mark item as inactive (no longer profitable)."""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE items SET is_active = 0, updated_at = ? WHERE market_hash_name = ?",
                (now, market_hash_name)
            )
            conn.commit()

    def get_active_items(self, limit: int = 50) -> list[dict]:
        """Get all active profitable items."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT * FROM items
                WHERE is_active = 1
                ORDER BY
                    COALESCE(recommended_wait_pct, wait_profit_pct) DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def get_all_items(self, limit: int = 100) -> list[dict]:
        """Get all items (including inactive)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT * FROM items
                ORDER BY updated_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def get_item(self, market_hash_name: str) -> Optional[dict]:
        """Get single item by name."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM items WHERE market_hash_name = ?",
                (market_hash_name,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_item_history(self, market_hash_name: str, limit: int = 20) -> list[dict]:
        """Get price history for an item."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT * FROM history
                WHERE item_name = ?
                ORDER BY recorded_at DESC
                LIMIT ?
            """, (market_hash_name, limit))
            return [dict(row) for row in cur.fetchall()]

    def delete_item(self, market_hash_name: str):
        """Delete item from database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM items WHERE market_hash_name = ?", (market_hash_name,))
            conn.execute("DELETE FROM history WHERE item_name = ?", (market_hash_name,))
            conn.commit()

    def clear_inactive(self):
        """Remove all inactive items."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM items WHERE is_active = 0")
            conn.commit()

    def get_stats(self) -> dict:
        """Get database statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM items WHERE is_active = 1").fetchone()[0]
            history_count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]

            # Best profit
            best = conn.execute("""
                SELECT market_hash_name, COALESCE(recommended_wait_pct, wait_profit_pct) as profit
                FROM items WHERE is_active = 1
                ORDER BY profit DESC LIMIT 1
            """).fetchone()

            return {
                "total_items": total,
                "active_items": active,
                "inactive_items": total - active,
                "history_records": history_count,
                "best_item": best[0] if best else None,
                "best_profit": best[1] if best else None,
            }


# Global instance
db = Database()
