"""
Parser for bottm database (main.db).

Reads item prices and recommendations from the bottm price database.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ItemData:
    """Represents an item from bottm database."""

    id: int
    market_hash_name: str
    item_type: Optional[str]

    # Current prices
    steam_buy_order: Optional[float]
    csgo_price: Optional[float]
    csgo_buy_order: Optional[float]

    # Recommended prices (20th percentile)
    recommended_buy_order: Optional[float]

    # Profit calculations
    instant_profit_pct: Optional[float]
    wait_profit_pct: Optional[float]
    recommended_instant_pct: Optional[float]
    recommended_wait_pct: Optional[float]

    # Metadata
    orders_above: Optional[int]
    is_active: bool
    found_at: Optional[str]
    updated_at: Optional[str]

    @property
    def has_valid_prices(self) -> bool:
        """Check if item has all required prices for trading."""
        return (
            self.recommended_buy_order is not None
            and self.recommended_buy_order > 0
            and self.csgo_price is not None
            and self.csgo_price > 0
        )

    @property
    def net_profit_after_commission(self) -> float:
        """Calculate net profit after CSGO.TM commission (10%)."""
        if not self.has_valid_prices:
            return 0.0
        return settings.calculate_net_profit(
            self.recommended_buy_order,
            self.csgo_price
        )

    @property
    def net_profit_pct(self) -> float:
        """Calculate net profit percentage after commission."""
        if not self.has_valid_prices:
            return 0.0
        return settings.calculate_profit_percent(
            self.recommended_buy_order,
            self.csgo_price
        )

    def is_profitable(self, min_profit_pct: Optional[float] = None) -> bool:
        """Check if item meets minimum profit threshold."""
        threshold = min_profit_pct or settings.min_profit_percent
        return self.net_profit_pct >= threshold

    def is_in_price_range(
        self,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None
    ) -> bool:
        """Check if item price is within allowed range."""
        min_p = min_price or settings.min_item_price
        max_p = max_price or settings.max_item_price

        if not self.recommended_buy_order:
            return False

        return min_p <= self.recommended_buy_order <= max_p


class BottmParser:
    """Parser for bottm price database."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize parser with database path."""
        self.db_path = db_path or settings.bottm_db_path

        if not self.db_path.exists():
            logger.warning(f"Bottm database not found at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Bottm database not found: {self.db_path}")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_item(self, row: sqlite3.Row) -> ItemData:
        """Convert database row to ItemData object."""
        return ItemData(
            id=row["id"],
            market_hash_name=row["market_hash_name"],
            item_type=row["item_type"],
            steam_buy_order=row["steam_buy_order"],
            csgo_price=row["csgo_price"],
            csgo_buy_order=row["csgo_buy_order"],
            recommended_buy_order=row["recommended_buy_order"],
            instant_profit_pct=row["instant_profit_pct"],
            wait_profit_pct=row["wait_profit_pct"],
            recommended_instant_pct=row["recommended_instant_pct"],
            recommended_wait_pct=row["recommended_wait_pct"],
            orders_above=row["orders_above"],
            is_active=bool(row["is_active"]),
            found_at=row["found_at"],
            updated_at=row["updated_at"],
        )

    def get_all_items(self, active_only: bool = True) -> list[ItemData]:
        """Get all items from database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM items"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY recommended_wait_pct DESC"

            cursor.execute(query)
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def get_profitable_items(
        self,
        min_profit_pct: Optional[float] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        max_orders_above: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[ItemData]:
        """
        Get items that meet profit and price criteria.

        Args:
            min_profit_pct: Minimum profit after commission (default from settings)
            min_price: Minimum item price (default from settings)
            max_price: Maximum item price (default from settings)
            max_orders_above: Maximum competing orders (optional filter)
            limit: Maximum number of items to return

        Returns:
            List of profitable items sorted by expected profit
        """
        min_profit = min_profit_pct or settings.min_profit_percent
        min_p = min_price or settings.min_item_price
        max_p = max_price or settings.max_item_price

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build query with filters
            query = """
                SELECT * FROM items
                WHERE is_active = 1
                AND recommended_buy_order IS NOT NULL
                AND recommended_buy_order > 0
                AND csgo_price IS NOT NULL
                AND csgo_price > 0
                AND recommended_buy_order >= ?
                AND recommended_buy_order <= ?
            """
            params = [min_p, max_p]

            if max_orders_above is not None:
                query += " AND (orders_above IS NULL OR orders_above <= ?)"
                params.append(max_orders_above)

            query += " ORDER BY recommended_wait_pct DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor.execute(query, params)
            items = [self._row_to_item(row) for row in cursor.fetchall()]

        # Filter by net profit after commission
        profitable = [
            item for item in items
            if item.net_profit_pct >= min_profit
        ]

        logger.info(
            f"Found {len(profitable)} profitable items "
            f"(min profit: {min_profit}%, price range: ${min_p}-${max_p})"
        )

        return profitable

    def get_item_by_name(self, market_hash_name: str) -> Optional[ItemData]:
        """Get item by market hash name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM items WHERE market_hash_name = ?",
                (market_hash_name,)
            )
            row = cursor.fetchone()
            return self._row_to_item(row) if row else None

    def get_current_price(self, market_hash_name: str) -> Optional[float]:
        """Get current CSGO.TM sell price for an item."""
        item = self.get_item_by_name(market_hash_name)
        return item.csgo_price if item else None

    def get_recommended_buy_price(self, market_hash_name: str) -> Optional[float]:
        """Get recommended buy order price for an item."""
        item = self.get_item_by_name(market_hash_name)
        return item.recommended_buy_order if item else None

    def check_price_changed(
        self,
        market_hash_name: str,
        original_price: float,
        threshold_pct: Optional[float] = None
    ) -> tuple[bool, float]:
        """
        Check if recommended price has changed significantly.

        Args:
            market_hash_name: Item name
            original_price: Original order price
            threshold_pct: Change threshold percentage (default from settings)

        Returns:
            Tuple of (has_changed, new_price)
        """
        threshold = threshold_pct or settings.price_change_threshold

        item = self.get_item_by_name(market_hash_name)
        if not item or not item.recommended_buy_order:
            return True, 0.0

        new_price = item.recommended_buy_order
        change_pct = abs(new_price - original_price) / original_price * 100

        return change_pct >= threshold, new_price

    def get_items_by_type(self, item_type: str) -> list[ItemData]:
        """Get items by type (Weapon, Sticker, Agent, etc.)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM items WHERE item_type = ? AND is_active = 1",
                (item_type,)
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM items WHERE is_active = 1")
            total_items = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM items
                WHERE is_active = 1
                AND recommended_buy_order IS NOT NULL
                AND csgo_price IS NOT NULL
            """)
            items_with_prices = cursor.fetchone()[0]

            cursor.execute("""
                SELECT AVG(recommended_wait_pct) FROM items
                WHERE is_active = 1
                AND recommended_wait_pct IS NOT NULL
            """)
            avg_profit = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT item_type, COUNT(*) as count
                FROM items
                WHERE is_active = 1
                GROUP BY item_type
            """)
            by_type = {row["item_type"]: row["count"] for row in cursor.fetchall()}

            return {
                "total_items": total_items,
                "items_with_prices": items_with_prices,
                "avg_profit_pct": avg_profit,
                "by_type": by_type,
            }


# Singleton instance
bottm_parser = BottmParser()
