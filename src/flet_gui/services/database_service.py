"""
Database service - integrates real TradesDatabase with GUI state.

Optimized version:
- Added async methods for heavy DB operations to prevent GUI blocking
- Use load_all_data_async() instead of load_all_data() in GUI context
"""

from pathlib import Path
from typing import Optional
import sys
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.database import TradesDatabase
from flet_gui.state.app_state import AppState
from src.logger import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """Service for managing database operations in GUI."""

    def __init__(self, state: AppState, db_path: Optional[Path] = None):
        """Initialize database service."""
        self.state = state
        self.db = TradesDatabase(db_path)
        logger.info("DatabaseService initialized with real TradesDatabase")

    def load_all_data(self):
        """Load all data from database into state."""
        try:
            # Load active orders
            orders = self.db.get_active_orders()
            # Normalize key names for GUI compatibility
            # Note: most order prices in DB are already in RUB,
            # but some older ones might be in EUR (< 100 typically means EUR)
            for order in orders:
                if 'order_price' in order and 'price' not in order:
                    price = order['order_price']
                    # Heuristic: if price < 100, it's likely EUR and needs conversion
                    if price < 100:
                        from src.currency_rates import get_currency_provider
                        provider = get_currency_provider()
                        price = provider.convert_to_rub(price, 'EUR')
                    order['price'] = price
            self.state.active_orders = orders
            logger.info(f"Loaded {len(orders)} active orders")

            # Load items on hold
            items_on_hold = self.db.get_items_on_hold()
            # Normalize key names for GUI compatibility
            # Note: prices in DB are already converted to RUB at purchase time
            for item in items_on_hold:
                if 'purchase_price' in item and 'buy_price' not in item:
                    item['buy_price'] = item['purchase_price']
                if 'current_csgotm_price' in item and 'current_price' not in item:
                    item['current_price'] = item['current_csgotm_price']
                # Calculate hold time remaining (unlock_date is in GMT)
                if 'unlock_date' in item:
                    from datetime import datetime
                    try:
                        unlock = datetime.fromisoformat(item['unlock_date'])
                        now = datetime.utcnow()  # Use UTC/GMT time for comparison
                        hours_remaining = max(0, int((unlock - now).total_seconds() / 3600))
                        item['hold_time_remaining'] = hours_remaining
                    except:
                        item['hold_time_remaining'] = 0
            self.state.items_on_hold = items_on_hold
            logger.info(f"Loaded {len(items_on_hold)} items on hold")

            # Load recent sales
            sales = self.db.get_recent_sales(limit=50)
            # Normalize key names for GUI compatibility
            for sale in sales:
                if 'purchase_price' in sale and 'buy_price' not in sale:
                    sale['buy_price'] = sale['purchase_price']
                if 'sell_price' not in sale and 'sale_price' in sale:
                    sale['sell_price'] = sale['sale_price']
            self.state.recent_sales = sales
            logger.info(f"Loaded {len(sales)} recent sales")

            # Load profitable items with min_profit filter
            min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
            profitable = self.db.get_active_profitable_items(min_profit=min_profit, limit=100)
            self.state.profitable_items = profitable
            logger.info(f"Loaded {len(profitable)} profitable items (min profit: {min_profit}%)")

            # Load stats
            stats = self.db.get_stats()
            self.state.stats = stats
            logger.info(f"Loaded stats: {stats}")

            # Update logs
            self.state.add_log(f"[SUCCESS] Loaded data from database: {len(orders)} orders, {len(items_on_hold)} items, {len(sales)} sales, {len(profitable)} profitable")

        except Exception as e:
            logger.error(f"Failed to load data from database: {e}")
            self.state.add_log(f"[ERROR] Failed to load database: {str(e)}")

    def refresh_orders(self):
        """Refresh active orders from database."""
        try:
            orders = self.db.get_active_orders()
            # Normalize key names
            # Note: most order prices in DB are already in RUB,
            # but some older ones might be in EUR (< 100 typically means EUR)
            for order in orders:
                if 'order_price' in order and 'price' not in order:
                    price = order['order_price']
                    # Heuristic: if price < 100, it's likely EUR and needs conversion
                    if price < 100:
                        from src.currency_rates import get_currency_provider
                        provider = get_currency_provider()
                        price = provider.convert_to_rub(price, 'EUR')
                    order['price'] = price
            self.state.active_orders = orders
            self.state.add_log(f"[INFO] Refreshed {len(orders)} active orders")
            return orders
        except Exception as e:
            logger.error(f"Failed to refresh orders: {e}")
            self.state.add_log(f"[ERROR] Failed to refresh orders: {str(e)}")
            return []

    def refresh_inventory(self):
        """Refresh items on hold from database."""
        try:
            items = self.db.get_items_on_hold()
            # Normalize key names
            # Note: prices in DB are already converted to RUB at purchase time
            for item in items:
                if 'purchase_price' in item and 'buy_price' not in item:
                    item['buy_price'] = item['purchase_price']
                # Map current_csgotm_price to current_price (check for both key existence and non-None value)
                csgotm_price = item.get('current_csgotm_price')
                if csgotm_price is not None and csgotm_price > 0:
                    item['current_price'] = csgotm_price
                if 'unlock_date' in item:
                    from datetime import datetime
                    try:
                        unlock = datetime.fromisoformat(item['unlock_date'])
                        now = datetime.utcnow()  # Use UTC/GMT time for comparison
                        hours_remaining = max(0, int((unlock - now).total_seconds() / 3600))
                        item['hold_time_remaining'] = hours_remaining
                    except:
                        item['hold_time_remaining'] = 0
            self.state.items_on_hold = items
            self.state.add_log(f"[INFO] Refreshed {len(items)} items on hold")
            return items
        except Exception as e:
            logger.error(f"Failed to refresh inventory: {e}")
            self.state.add_log(f"[ERROR] Failed to refresh inventory: {str(e)}")
            return []

    def refresh_history(self):
        """Refresh sales history from database."""
        try:
            sales = self.db.get_recent_sales(limit=50)
            # Normalize key names
            for sale in sales:
                if 'purchase_price' in sale and 'buy_price' not in sale:
                    sale['buy_price'] = sale['purchase_price']
                if 'sell_price' not in sale and 'sale_price' in sale:
                    sale['sell_price'] = sale['sale_price']
            self.state.recent_sales = sales
            self.state.add_log(f"[INFO] Refreshed {len(sales)} recent sales")
            return sales
        except Exception as e:
            logger.error(f"Failed to refresh history: {e}")
            self.state.add_log(f"[ERROR] Failed to refresh history: {str(e)}")
            return []

    def refresh_stats(self):
        """Refresh statistics from database."""
        try:
            stats = self.db.get_stats()
            self.state.stats = stats
            self.state.add_log("[INFO] Refreshed statistics")
            return stats
        except Exception as e:
            logger.error(f"Failed to refresh stats: {e}")
            self.state.add_log(f"[ERROR] Failed to refresh stats: {str(e)}")
            return {}

    def get_total_profit(self) -> dict:
        """Get total profit statistics."""
        try:
            return self.db.get_total_profit()
        except Exception as e:
            logger.error(f"Failed to get total profit: {e}")
            return {'total': 0, 'today': 0, 'week': 0, 'month': 0}

    def cancel_order(self, order_id: str):
        """Cancel an active order."""
        try:
            self.db.cancel_order(order_id)
            self.refresh_orders()
            self.state.add_log(f"[SUCCESS] Cancelled order {order_id}")
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            self.state.add_log(f"[ERROR] Failed to cancel order: {str(e)}")

    def delete_profitable_item(self, market_hash_name: str) -> bool:
        """Delete a profitable item from database."""
        try:
            self.db.remove_profitable_item(market_hash_name)
            # Refresh profitable items in state
            min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
            profitable = self.db.get_active_profitable_items(min_profit=min_profit, limit=100)
            self.state.profitable_items = profitable
            self.state.add_log(f"[SUCCESS] Deleted item: {market_hash_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete profitable item: {e}")
            self.state.add_log(f"[ERROR] Failed to delete item: {str(e)}")
            return False

    def refresh_profitable_items(self):
        """Refresh profitable items from database."""
        try:
            min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
            profitable = self.db.get_active_profitable_items(min_profit=min_profit, limit=100)
            self.state.profitable_items = profitable
            self.state.add_log(f"[INFO] Refreshed {len(profitable)} profitable items (min profit: {min_profit}%)")
            return profitable
        except Exception as e:
            logger.error(f"Failed to refresh profitable items: {e}")
            self.state.add_log(f"[ERROR] Failed to refresh profitable items: {str(e)}")
            return []

    def update_profitable_item(self, market_hash_name: str, **kwargs) -> bool:
        """Update a profitable item in database."""
        try:
            self.db.add_profitable_item(market_hash_name=market_hash_name, **kwargs)
            return True
        except Exception as e:
            logger.error(f"Failed to update profitable item: {e}")
            return False

    def mark_items_inactive(self, market_hash_names: list) -> bool:
        """Mark items as inactive (no longer profitable)."""
        try:
            self.db.mark_items_inactive(market_hash_names)
            return True
        except Exception as e:
            logger.error(f"Failed to mark items inactive: {e}")
            return False

    def get_order_by_id(self, order_id: str):
        """Get order by ID."""
        try:
            return self.db.get_order_by_id(order_id)
        except Exception as e:
            logger.error(f"Failed to get order by ID: {e}")
            return None

    def add_order(self, **kwargs):
        """Add new order to database."""
        try:
            self.db.add_order(**kwargs)
            return True
        except Exception as e:
            logger.error(f"Failed to add order: {e}")
            return False

    def update_order_status(self, order_id: str, status: str):
        """Update order status."""
        try:
            self.db.update_order_status(order_id, status)
            return True
        except Exception as e:
            logger.error(f"Failed to update order status: {e}")
            return False

    def add_purchased_item(self, **kwargs):
        """Add purchased item to database."""
        try:
            self.db.add_purchased_item(**kwargs)
            return True
        except Exception as e:
            logger.error(f"Failed to add purchased item: {e}")
            return False

    def get_purchased_items(self, account_name: str = None):
        """Get purchased items, optionally filtered by account."""
        try:
            return self.db.get_purchased_items(account_name=account_name)
        except Exception as e:
            logger.error(f"Failed to get purchased items: {e}")
            return []

    # ========================================================================
    # ASYNC METHODS (use these in GUI to prevent blocking)
    # ========================================================================

    async def load_all_data_async(self):
        """Load all data from database into state (non-blocking)."""
        await asyncio.to_thread(self.load_all_data)

    async def refresh_orders_async(self):
        """Refresh active orders from database (non-blocking)."""
        return await asyncio.to_thread(self.refresh_orders)

    async def refresh_inventory_async(self):
        """Refresh items on hold from database (non-blocking)."""
        return await asyncio.to_thread(self.refresh_inventory)

    async def refresh_history_async(self):
        """Refresh sales history from database (non-blocking)."""
        return await asyncio.to_thread(self.refresh_history)

    async def refresh_stats_async(self):
        """Refresh statistics from database (non-blocking)."""
        return await asyncio.to_thread(self.refresh_stats)

    async def refresh_profitable_items_async(self):
        """Refresh profitable items from database (non-blocking)."""
        return await asyncio.to_thread(self.refresh_profitable_items)

    async def delete_profitable_item_async(self, market_hash_name: str) -> bool:
        """Delete a profitable item from database (non-blocking)."""
        return await asyncio.to_thread(self.delete_profitable_item, market_hash_name)

    async def cancel_order_async(self, order_id: str):
        """Cancel an active order (non-blocking)."""
        await asyncio.to_thread(self.cancel_order, order_id)
