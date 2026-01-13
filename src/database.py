"""
Database module for managing trades in my_trades.db.

Tables:
- purchased_items: Items bought on Steam, waiting for 7-day hold
- sold_items: Items sold on CSGO.TM with profit tracking
- active_orders: Active buy orders on Steam Marketplace
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class TradesDatabase:
    """Database manager for tracking trades."""

    HOLD_DAYS = 7  # Steam trade hold period

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection."""
        self.db_path = db_path or settings.trades_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _check_column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns

    def _migrate_database(self, cursor):
        """Migrate database to latest schema version."""
        # Check if tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]

        tables_to_check = ['purchased_items', 'sold_items', 'active_orders', 'listed_items']

        for table in tables_to_check:
            if table in existing_tables:
                # Check if account_name column exists
                if not self._check_column_exists(cursor, table, 'account_name'):
                    logger.info(f"Migrating {table}: adding account_name column")
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN account_name TEXT DEFAULT 'default'")

                # Check for market_hash_name in tables that need it
                if table in ['purchased_items', 'active_orders', 'listed_items']:
                    if not self._check_column_exists(cursor, table, 'market_hash_name'):
                        logger.info(f"Migrating {table}: adding market_hash_name column")
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN market_hash_name TEXT")

                # Check for quantity in active_orders
                if table == 'active_orders' and not self._check_column_exists(cursor, table, 'quantity'):
                    logger.info(f"Migrating {table}: adding quantity column")
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN quantity INTEGER DEFAULT 1")

                # Check for platform in sold_items
                if table == 'sold_items' and not self._check_column_exists(cursor, table, 'platform'):
                    logger.info(f"Migrating {table}: adding platform column")
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN platform TEXT DEFAULT 'csgotm'")

    def _init_db(self):
        """Initialize database tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # First, run migrations for existing tables
            self._migrate_database(cursor)

            # Table for purchased items waiting for hold period
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchased_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    market_hash_name TEXT,
                    asset_id TEXT,
                    purchase_price REAL NOT NULL,
                    expected_sell_price REAL,
                    expected_profit_pct REAL,
                    purchase_date DATETIME NOT NULL,
                    unlock_date DATETIME NOT NULL,
                    order_id TEXT,
                    status TEXT DEFAULT 'holding',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Table for sold items with profit tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sold_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    purchase_price REAL NOT NULL,
                    sale_price REAL NOT NULL,
                    net_sale_price REAL NOT NULL,
                    profit REAL NOT NULL,
                    profit_pct REAL NOT NULL,
                    purchase_date DATETIME,
                    sale_date DATETIME NOT NULL,
                    hold_days INTEGER,
                    platform TEXT DEFAULT 'csgotm',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Table for active buy orders on Steam
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    market_hash_name TEXT,
                    order_id TEXT UNIQUE,
                    order_price REAL NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    expected_sell_price REAL,
                    expected_profit_pct REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_checked DATETIME,
                    status TEXT DEFAULT 'active'
                )
            """)

            # Table for items listed on CSGO.TM for sale
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listed_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    market_hash_name TEXT,
                    asset_id TEXT,
                    list_price REAL NOT NULL,
                    purchase_price REAL,
                    expected_profit REAL,
                    listed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'listed'
                )
            """)

            # Table for bottm profitable items (from scanner)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS profitable_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_hash_name TEXT UNIQUE,
                    item_type TEXT,

                    steam_buy_order REAL,
                    steam_lowest_sell REAL,
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

            # Add steam_lowest_sell column if it doesn't exist (migration)
            try:
                cursor.execute("ALTER TABLE profitable_items ADD COLUMN steam_lowest_sell REAL")
                logger.info("Added steam_lowest_sell column to profitable_items table")
            except Exception:
                # Column already exists
                pass

            # Add new profit columns (migration from instant/wait to single profit)
            try:
                cursor.execute("ALTER TABLE profitable_items ADD COLUMN profit_pct REAL")
                logger.info("Added profit_pct column to profitable_items table")
            except Exception:
                pass

            try:
                cursor.execute("ALTER TABLE profitable_items ADD COLUMN recommended_profit_pct REAL")
                logger.info("Added recommended_profit_pct column to profitable_items table")
            except Exception:
                pass

            # Table for bottm price history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS profitable_items_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT,
                    steam_buy_order REAL,
                    csgo_price REAL,
                    profit_pct REAL,
                    recorded_at TEXT
                )
            """)

            # Create indexes for faster queries (will skip if already exist)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_purchased_account ON purchased_items(account_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_purchased_unlock ON purchased_items(unlock_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_purchased_status ON purchased_items(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_account ON active_orders(account_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON active_orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listed_account ON listed_items(account_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listed_status ON listed_items(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sold_account ON sold_items(account_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_profitable_items_name ON profitable_items(market_hash_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_profitable_items_active ON profitable_items(is_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_profitable_items_profit ON profitable_items(profit_pct)")

            logger.info(f"Database initialized at {self.db_path}")

    # ============ Active Orders Methods ============

    def add_order(
        self,
        account_name: str,
        item_name: str,
        market_hash_name: str,
        order_id: str,
        order_price: float,
        quantity: int = 1,
        expected_sell_price: Optional[float] = None,
    ) -> int:
        """Add a new buy order to tracking."""
        expected_profit_pct = None
        if expected_sell_price:
            expected_profit_pct = settings.calculate_profit_percent(order_price, expected_sell_price)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO active_orders
                (account_name, item_name, market_hash_name, order_id, order_price, quantity, expected_sell_price, expected_profit_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_name, item_name, market_hash_name, order_id, order_price, quantity, expected_sell_price, expected_profit_pct))

            logger.info(f"[{account_name}] Order added: {item_name} @ ${order_price:.2f} (expected profit: {expected_profit_pct:.1f}%)")
            return cursor.lastrowid

    def get_active_orders(self) -> list[dict]:
        """Get all active buy orders."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM active_orders WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_order_by_id(self, order_id: str) -> Optional[dict]:
        """Get order by Steam order ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM active_orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_total_orders_value(self) -> float:
        """Get total value of all active orders."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(SUM(order_price), 0) as total
                FROM active_orders WHERE status = 'active'
            """)
            return cursor.fetchone()["total"]

    def update_order_status(self, order_id: str, status: str):
        """Update order status (active, filled, cancelled)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE active_orders
                SET status = ?, last_checked = CURRENT_TIMESTAMP
                WHERE order_id = ?
            """, (status, order_id))
            logger.info(f"Order {order_id} status updated to: {status}")

    def cancel_order(self, order_id: str):
        """Mark order as cancelled."""
        self.update_order_status(order_id, "cancelled")

    def get_order_by_item_name(self, item_name: str) -> Optional[dict]:
        """Get active order by item name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM active_orders
                WHERE item_name = ? AND status = 'active'
            """, (item_name,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ============ Purchased Items Methods ============

    def add_purchased_item(
        self,
        account_name: str,
        item_name: str,
        market_hash_name: str,
        purchase_price: float,
        asset_id: Optional[str] = None,
        expected_sell_price: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> int:
        """Add a purchased item to tracking."""
        purchase_date = datetime.now()
        unlock_date = purchase_date + timedelta(days=self.HOLD_DAYS)

        expected_profit_pct = None
        if expected_sell_price:
            expected_profit_pct = settings.calculate_profit_percent(purchase_price, expected_sell_price)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO purchased_items
                (account_name, item_name, market_hash_name, asset_id, purchase_price, expected_sell_price,
                 expected_profit_pct, purchase_date, unlock_date, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                account_name, item_name, market_hash_name, asset_id, purchase_price, expected_sell_price,
                expected_profit_pct, purchase_date, unlock_date, order_id
            ))

            logger.info(
                f"[{account_name}] Purchased: {item_name} @ ${purchase_price:.2f} "
                f"(unlocks: {unlock_date.strftime('%Y-%m-%d %H:%M')})"
            )
            return cursor.lastrowid

    def get_items_ready_to_sell(self) -> list[dict]:
        """Get items that have passed the 7-day hold period."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM purchased_items
                WHERE unlock_date <= CURRENT_TIMESTAMP
                AND status = 'holding'
                ORDER BY unlock_date ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_items_on_hold(self) -> list[dict]:
        """Get items still in hold period."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM purchased_items
                WHERE unlock_date > CURRENT_TIMESTAMP
                AND status = 'holding'
                ORDER BY unlock_date ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def update_purchased_item_status(self, item_id: int, status: str):
        """Update purchased item status (holding, listed, sold)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE purchased_items SET status = ? WHERE id = ?
            """, (status, item_id))

    def update_purchased_item_asset_id(self, item_id: int, asset_id: str):
        """Update asset ID after purchase (needed for selling)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE purchased_items SET asset_id = ? WHERE id = ?
            """, (asset_id, item_id))

    def get_purchased_item_by_id(self, item_id: int) -> Optional[dict]:
        """Get purchased item by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM purchased_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ============ Listed Items Methods ============

    def add_listed_item(
        self,
        account_name: str,
        item_name: str,
        market_hash_name: str,
        list_price: float,
        asset_id: Optional[str] = None,
        purchase_price: Optional[float] = None,
    ) -> int:
        """Add item listed on CSGO.TM for sale."""
        expected_profit = None
        if purchase_price:
            expected_profit = settings.calculate_net_profit(purchase_price, list_price)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO listed_items
                (account_name, item_name, market_hash_name, asset_id, list_price, purchase_price, expected_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (account_name, item_name, market_hash_name, asset_id, list_price, purchase_price, expected_profit))

            logger.info(f"[{account_name}] Listed for sale: {item_name} @ ${list_price:.2f}")
            return cursor.lastrowid

    def get_listed_items(self) -> list[dict]:
        """Get all items currently listed for sale."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM listed_items WHERE status = 'listed'
                ORDER BY listed_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def update_listed_item_status(self, item_id: int, status: str):
        """Update listed item status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE listed_items SET status = ? WHERE id = ?
            """, (status, item_id))

    # ============ Sold Items Methods ============

    def add_sold_item(
        self,
        account_name: str,
        item_name: str,
        purchase_price: float,
        sale_price: float,
        purchase_date: Optional[datetime] = None,
        platform: str = 'csgotm',
    ) -> int:
        """Record a sold item with profit calculation."""
        sale_date = datetime.now()
        net_sale_price = sale_price * (1 - settings.csgotm_commission)
        profit = net_sale_price - purchase_price
        profit_pct = (profit / purchase_price * 100) if purchase_price > 0 else 0

        hold_days = None
        if purchase_date:
            hold_days = (sale_date - purchase_date).days

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sold_items
                (account_name, item_name, purchase_price, sale_price, net_sale_price,
                 profit, profit_pct, purchase_date, sale_date, hold_days, platform)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                account_name, item_name, purchase_price, sale_price, net_sale_price,
                profit, profit_pct, purchase_date, sale_date, hold_days, platform
            ))

            logger.info(
                f"[{account_name}] Sold: {item_name} | Buy: ${purchase_price:.2f} | "
                f"Sell: ${sale_price:.2f} | Profit: ${profit:.2f} ({profit_pct:.1f}%)"
            )
            return cursor.lastrowid

    def get_total_profit(self) -> dict:
        """Get total profit statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total_sales,
                    COALESCE(SUM(profit), 0) as total_profit,
                    COALESCE(AVG(profit_pct), 0) as avg_profit_pct,
                    COALESCE(SUM(purchase_price), 0) as total_invested,
                    COALESCE(SUM(net_sale_price), 0) as total_revenue
                FROM sold_items
            """)
            return dict(cursor.fetchone())

    def get_recent_sales(self, limit: int = 10) -> list[dict]:
        """Get recent sales."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sold_items
                ORDER BY sale_date DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # ============ Statistics ============

    def get_stats(self) -> dict:
        """Get comprehensive trading statistics."""
        profit_stats = self.get_total_profit()
        active_orders = len(self.get_active_orders())
        items_on_hold = len(self.get_items_on_hold())
        items_ready = len(self.get_items_ready_to_sell())
        items_listed = len(self.get_listed_items())
        total_orders_value = self.get_total_orders_value()

        return {
            **profit_stats,
            "active_orders": active_orders,
            "total_orders_value": total_orders_value,
            "items_on_hold": items_on_hold,
            "items_ready_to_sell": items_ready,
            "items_listed": items_listed,
        }

    # ============ Methods for GUI ============

    def get_active_orders_count(self) -> int:
        """Get count of active orders."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM active_orders WHERE status = 'active'")
            return cursor.fetchone()[0]

    def get_purchased_items_count(self) -> int:
        """Get count of items on hold."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM purchased_items WHERE status = 'holding'")
            return cursor.fetchone()[0]

    def get_sold_items_count(self) -> int:
        """Get count of sold items."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sold_items")
            return cursor.fetchone()[0]

    def get_all_active_orders(self) -> list[dict]:
        """Get all active orders for display in GUI."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM active_orders
                WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    # ============ Profitable Items Methods (bottm integration) ============

    def add_or_update_profitable_item(self, item_data: dict) -> bool:
        """
        Add or update profitable item from bottm scanner.

        Args:
            item_data: Dict with item fields (market_hash_name, prices, profits, etc.)

        Returns:
            True if new item added, False if updated
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check if item exists
            cursor.execute(
                "SELECT id FROM profitable_items WHERE market_hash_name = ?",
                (item_data['market_hash_name'],)
            )
            existing = cursor.fetchone()

            if existing:
                # Update existing item
                cursor.execute("""
                    UPDATE profitable_items
                    SET item_type = ?,
                        steam_buy_order = ?,
                        steam_lowest_sell = ?,
                        recommended_buy_order = ?,
                        csgo_price = ?,
                        csgo_buy_order = ?,
                        instant_profit_pct = ?,
                        wait_profit_pct = ?,
                        recommended_instant_pct = ?,
                        recommended_wait_pct = ?,
                        profit_pct = ?,
                        recommended_profit_pct = ?,
                        orders_above = ?,
                        updated_at = ?,
                        is_active = 1
                    WHERE market_hash_name = ?
                """, (
                    item_data.get('item_type'),
                    item_data.get('steam_buy_order'),
                    item_data.get('steam_lowest_sell'),
                    item_data.get('recommended_buy_order'),
                    item_data.get('csgo_price'),
                    item_data.get('csgo_buy_order'),
                    item_data.get('instant_profit_pct'),
                    item_data.get('wait_profit_pct'),
                    item_data.get('recommended_instant_pct'),
                    item_data.get('recommended_wait_pct'),
                    item_data.get('profit_pct'),
                    item_data.get('recommended_profit_pct'),
                    item_data.get('orders_above'),
                    datetime.now().isoformat(),
                    item_data['market_hash_name']
                ))
                return False
            else:
                # Insert new item
                cursor.execute("""
                    INSERT INTO profitable_items (
                        market_hash_name, item_type,
                        steam_buy_order, steam_lowest_sell, recommended_buy_order,
                        csgo_price, csgo_buy_order,
                        instant_profit_pct, wait_profit_pct,
                        recommended_instant_pct, recommended_wait_pct,
                        profit_pct, recommended_profit_pct,
                        orders_above, found_at, updated_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    item_data['market_hash_name'],
                    item_data.get('item_type'),
                    item_data.get('steam_buy_order'),
                    item_data.get('steam_lowest_sell'),
                    item_data.get('recommended_buy_order'),
                    item_data.get('csgo_price'),
                    item_data.get('csgo_buy_order'),
                    item_data.get('instant_profit_pct'),
                    item_data.get('wait_profit_pct'),
                    item_data.get('recommended_instant_pct'),
                    item_data.get('recommended_wait_pct'),
                    item_data.get('profit_pct'),
                    item_data.get('recommended_profit_pct'),
                    item_data.get('orders_above'),
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))
                return True

    def get_active_profitable_items(self, min_profit: Optional[float] = None, limit: int = 100) -> list[dict]:
        """
        Get active profitable items sorted by profit.

        Args:
            min_profit: Minimum profit percentage (None = no filter, show all items)
            limit: Maximum number of items to return

        Returns:
            List of profitable items as dicts
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build query based on whether profit filter is enabled
            if min_profit is not None:
                # With profit filter - only show items with profit_pct >= min_profit
                cursor.execute("""
                    SELECT * FROM profitable_items
                    WHERE is_active = 1
                      AND profit_pct IS NOT NULL
                      AND profit_pct >= ?
                    ORDER BY profit_pct DESC
                    LIMIT ?
                """, (min_profit, limit))
            else:
                # No profit filter - show ALL items (even with NULL profit_pct)
                cursor.execute("""
                    SELECT * FROM profitable_items
                    WHERE is_active = 1
                    ORDER BY
                        CASE WHEN profit_pct IS NULL THEN 1 ELSE 0 END,
                        profit_pct DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

    def mark_items_inactive(self, item_names: list[str]):
        """Mark items as inactive (no longer profitable)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(item_names))
            cursor.execute(f"""
                UPDATE profitable_items
                SET is_active = 0
                WHERE market_hash_name IN ({placeholders})
            """, item_names)

    def add_profitable_item_history(self, item_name: str, steam_price: float, csgo_price: float, profit_pct: float):
        """Add price history entry for tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO profitable_items_history (item_name, steam_buy_order, csgo_price, profit_pct, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (item_name, steam_price, csgo_price, profit_pct, datetime.now().isoformat()))

    def get_profitable_items_count(self) -> int:
        """Get count of active profitable items."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM profitable_items WHERE is_active = 1")
            return cursor.fetchone()[0]

    def get_all_profitable_items(self) -> list[dict]:
        """
        Get ALL profitable items (no limit).

        Used for rescanning all items.

        Returns:
            List of all profitable items as dicts
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM profitable_items
                WHERE is_active = 1
                ORDER BY instant_profit_pct DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def remove_profitable_item(self, market_hash_name: str) -> bool:
        """
        Remove a profitable item from the database.

        Args:
            market_hash_name: Name of the item to remove

        Returns:
            True if item was removed, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM profitable_items WHERE market_hash_name = ?",
                (market_hash_name,)
            )
            return cursor.rowcount > 0

    def add_profitable_item(self, market_hash_name: str, item_type: str,
                           steam_buy_order: float, recommended_buy_order: float,
                           csgo_price: float, csgo_buy_order: float,
                           instant_profit_pct: float, wait_profit_pct: float,
                           recommended_instant_pct: float, recommended_wait_pct: float,
                           orders_above: int) -> bool:
        """
        Add or update a profitable item (wrapper for add_or_update_profitable_item).

        Returns:
            True if new item added, False if updated
        """
        item_data = {
            'market_hash_name': market_hash_name,
            'item_type': item_type,
            'steam_buy_order': steam_buy_order,
            'recommended_buy_order': recommended_buy_order,
            'csgo_price': csgo_price,
            'csgo_buy_order': csgo_buy_order,
            'instant_profit_pct': instant_profit_pct,
            'wait_profit_pct': wait_profit_pct,
            'recommended_instant_pct': recommended_instant_pct,
            'recommended_wait_pct': recommended_wait_pct,
            'orders_above': orders_above
        }
        return self.add_or_update_profitable_item(item_data)


# Singleton instance
trades_db = TradesDatabase()
