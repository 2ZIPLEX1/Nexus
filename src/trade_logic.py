"""
Trade logic module.

Orchestrates the buying and selling process:
1. Find profitable items from bottm database
2. Place buy orders on Steam
3. Track purchases and 7-day hold
4. Sell items on CSGO.TM after hold
5. Monitor and cancel stale orders
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import settings
from src.bottm_parser import bottm_parser, ItemData
from src.csgotm_client import csgotm_client
from src.database import trades_db
from src.logger import get_logger
from src.steam_client import steam_client

logger = get_logger(__name__)


@dataclass
class TradeResult:
    """Result of a trade operation."""
    success: bool
    message: str
    item_name: Optional[str] = None
    price: Optional[float] = None


class TradeLogic:
    """
    Main trade logic coordinator.

    Handles the complete trading workflow from finding items
    to selling them after the hold period.
    """

    def __init__(self):
        """Initialize trade logic."""
        self.steam = steam_client
        self.csgotm = csgotm_client
        self.bottm = bottm_parser
        self.db = trades_db

    # ============ Buy Order Management ============

    def get_available_budget(self) -> float:
        """
        Calculate available budget for new orders.

        Returns:
            Available budget in USD
        """
        wallet = self.steam.get_wallet_balance()
        max_orders = settings.calculate_max_orders_value(wallet.balance)
        current_orders = self.db.get_total_orders_value()

        available = max_orders - current_orders
        logger.info(
            f"Budget: ${wallet.balance:.2f} balance, "
            f"${current_orders:.2f} in orders, "
            f"${available:.2f} available"
        )

        return max(0, available)

    def find_items_to_buy(self, max_items: int = 10) -> list[ItemData]:
        """
        Find profitable items to buy.

        Args:
            max_items: Maximum number of items to return

        Returns:
            List of profitable items sorted by expected profit
        """
        # Get items from bottm
        items = self.bottm.get_profitable_items(
            min_profit_pct=settings.min_profit_percent,
            min_price=settings.min_item_price,
            max_price=settings.max_item_price,
            limit=max_items * 2  # Get extra in case some are filtered
        )

        # Filter out items we already have orders for
        active_orders = self.db.get_active_orders()
        ordered_items = {o["item_name"] for o in active_orders}

        # Filter out items on hold
        items_on_hold = self.db.get_items_on_hold()
        held_items = {i["item_name"] for i in items_on_hold}

        filtered = []
        for item in items:
            if item.market_hash_name in ordered_items:
                continue
            if item.market_hash_name in held_items:
                continue
            filtered.append(item)

            if len(filtered) >= max_items:
                break

        logger.info(f"Found {len(filtered)} items to potentially buy")
        return filtered

    def place_buy_orders(self, max_orders: int = 5) -> list[TradeResult]:
        """
        Place buy orders for profitable items.

        Args:
            max_orders: Maximum number of orders to place

        Returns:
            List of TradeResult for each order attempt
        """
        results = []
        available_budget = self.get_available_budget()

        if available_budget <= 0:
            logger.warning("No available budget for new orders")
            return results

        items = self.find_items_to_buy(max_orders)

        for item in items:
            price = item.recommended_buy_order

            # Check if we have budget
            if price > available_budget:
                logger.info(f"Skipping {item.market_hash_name}: price ${price:.2f} > budget ${available_budget:.2f}")
                continue

            # Place order
            order_result = self.steam.create_buy_order(
                market_hash_name=item.market_hash_name,
                price=price,
                quantity=1
            )

            if order_result.success:
                # Record in database
                self.db.add_order(
                    item_name=item.market_hash_name,
                    order_id=order_result.order_id,
                    order_price=price,
                    expected_sell_price=item.csgo_price
                )

                available_budget -= price

                results.append(TradeResult(
                    success=True,
                    message=f"Order placed: {item.market_hash_name} @ ${price:.2f}",
                    item_name=item.market_hash_name,
                    price=price
                ))

                logger.info(f"Order placed: {item.market_hash_name} @ ${price:.2f}")
            else:
                results.append(TradeResult(
                    success=False,
                    message=f"Order failed: {order_result.message}",
                    item_name=item.market_hash_name,
                    price=price
                ))

            time.sleep(3)  # Rate limiting

        return results

    def check_filled_orders(self) -> list[TradeResult]:
        """
        Check for filled orders and record purchases.

        Returns:
            List of TradeResult for filled orders
        """
        results = []
        active_orders = self.db.get_active_orders()

        for order in active_orders:
            is_filled, asset_id = self.steam.check_order_filled(order["order_id"])

            if is_filled:
                # Get current expected sell price
                current_item = self.bottm.get_item_by_name(order["item_name"])
                expected_sell = current_item.csgo_price if current_item else order["expected_sell_price"]

                # Record purchase
                self.db.add_purchased_item(
                    item_name=order["item_name"],
                    purchase_price=order["order_price"],
                    asset_id=asset_id,
                    expected_sell_price=expected_sell,
                    order_id=order["order_id"]
                )

                # Update order status
                self.db.update_order_status(order["order_id"], "filled")

                results.append(TradeResult(
                    success=True,
                    message=f"Order filled: {order['item_name']} @ ${order['order_price']:.2f}",
                    item_name=order["item_name"],
                    price=order["order_price"]
                ))

                logger.info(f"Order filled: {order['item_name']}")

        return results

    def check_and_cancel_stale_orders(self) -> list[TradeResult]:
        """
        Check for orders with significant price changes and cancel them.

        Returns:
            List of TradeResult for cancelled orders
        """
        results = []
        active_orders = self.db.get_active_orders()

        for order in active_orders:
            price_changed, new_price = self.bottm.check_price_changed(
                order["item_name"],
                order["order_price"],
                settings.price_change_threshold
            )

            if price_changed:
                # Cancel the order
                cancelled = self.steam.cancel_buy_order(order["order_id"])

                if cancelled:
                    self.db.cancel_order(order["order_id"])

                    results.append(TradeResult(
                        success=True,
                        message=f"Cancelled: {order['item_name']} (price changed: ${order['order_price']:.2f} -> ${new_price:.2f})",
                        item_name=order["item_name"],
                        price=order["order_price"]
                    ))

                    logger.info(
                        f"Cancelled order for {order['item_name']}: "
                        f"price changed ${order['order_price']:.2f} -> ${new_price:.2f}"
                    )
                else:
                    results.append(TradeResult(
                        success=False,
                        message=f"Failed to cancel: {order['item_name']}",
                        item_name=order["item_name"]
                    ))

        return results

    # ============ Sell Management ============

    def get_items_ready_to_sell(self) -> list[dict]:
        """
        Get items that are ready to sell (past 7-day hold).

        Returns:
            List of items ready for sale
        """
        items = self.db.get_items_ready_to_sell()
        logger.info(f"Found {len(items)} items ready to sell")
        return items

    def sell_ready_items(self) -> list[TradeResult]:
        """
        List items ready for sale on CSGO.TM.

        Returns:
            List of TradeResult for each sale attempt
        """
        results = []
        ready_items = self.get_items_ready_to_sell()

        for item in ready_items:
            # Get current recommended price from bottm
            current_data = self.bottm.get_item_by_name(item["item_name"])

            if current_data and current_data.csgo_price:
                sell_price = current_data.csgo_price
            else:
                # Fallback to expected price from when we bought it
                sell_price = item.get("expected_sell_price")

            if not sell_price:
                logger.warning(f"No price data for {item['item_name']}, skipping")
                continue

            # Find item in Steam inventory to get class_id and instance_id
            inv_item = self.steam.find_item_in_inventory(
                item["item_name"],
                tradable_only=True
            )

            if not inv_item:
                logger.warning(f"Item not found in inventory: {item['item_name']}")
                continue

            # Set price on CSGO.TM (initiates trade request)
            sell_result = self.csgotm.set_price(
                class_id=inv_item.class_id,
                instance_id=inv_item.instance_id,
                price=sell_price
            )

            if sell_result.success:
                # Record listing
                self.db.add_listed_item(
                    item_name=item["item_name"],
                    list_price=sell_price,
                    asset_id=inv_item.asset_id,
                    purchase_price=item["purchase_price"]
                )

                # Update purchased item status
                self.db.update_purchased_item_status(item["id"], "listed")

                results.append(TradeResult(
                    success=True,
                    message=f"Listed for sale: {item['item_name']} @ ${sell_price:.2f}",
                    item_name=item["item_name"],
                    price=sell_price
                ))

                logger.info(f"Listed for sale: {item['item_name']} @ ${sell_price:.2f}")
            else:
                results.append(TradeResult(
                    success=False,
                    message=f"Failed to list: {sell_result.message}",
                    item_name=item["item_name"]
                ))

            time.sleep(2)  # Rate limiting

        return results

    def check_sold_items(self) -> list[TradeResult]:
        """
        Check for sold items on CSGO.TM and record profits.

        Returns:
            List of TradeResult for sold items
        """
        results = []
        listed_items = self.db.get_listed_items()

        # Get sold items from CSGO.TM
        sold_history = self.csgotm.get_sold_items(limit=50)

        for sold in sold_history:
            item_name = sold.get("market_hash_name")
            sale_price = sold.get("received", 0) / 100.0  # Convert from cents

            # Find matching listed item
            matching = None
            for listed in listed_items:
                if listed["item_name"] == item_name:
                    matching = listed
                    break

            if matching:
                # Record sale
                self.db.add_sold_item(
                    item_name=item_name,
                    purchase_price=matching.get("purchase_price", 0),
                    sale_price=sale_price,
                    purchase_date=None  # Would need to track this better
                )

                # Update listed item status
                self.db.update_listed_item_status(matching["id"], "sold")

                profit = settings.calculate_net_profit(
                    matching.get("purchase_price", 0),
                    sale_price
                )

                results.append(TradeResult(
                    success=True,
                    message=f"Sold: {item_name} for ${sale_price:.2f} (profit: ${profit:.2f})",
                    item_name=item_name,
                    price=sale_price
                ))

                logger.info(f"Sold: {item_name} for ${sale_price:.2f} (profit: ${profit:.2f})")

        return results

    # ============ Combined Operations ============

    def run_buy_cycle(self) -> dict:
        """
        Run a complete buy cycle.

        1. Check for filled orders
        2. Cancel stale orders
        3. Place new orders

        Returns:
            Summary of operations
        """
        logger.info("=== Starting Buy Cycle ===")

        # Check filled orders first
        filled = self.check_filled_orders()

        # Cancel stale orders
        cancelled = self.check_and_cancel_stale_orders()

        # Place new orders
        new_orders = self.place_buy_orders()

        summary = {
            "filled_orders": len([r for r in filled if r.success]),
            "cancelled_orders": len([r for r in cancelled if r.success]),
            "new_orders": len([r for r in new_orders if r.success]),
            "failed_orders": len([r for r in new_orders if not r.success]),
        }

        logger.info(f"Buy cycle complete: {summary}")
        return summary

    def run_sell_cycle(self) -> dict:
        """
        Run a complete sell cycle.

        1. Check for sold items
        2. List ready items for sale

        Returns:
            Summary of operations
        """
        logger.info("=== Starting Sell Cycle ===")

        # Check for sold items
        sold = self.check_sold_items()

        # List ready items
        listed = self.sell_ready_items()

        summary = {
            "items_sold": len([r for r in sold if r.success]),
            "items_listed": len([r for r in listed if r.success]),
            "failed_listings": len([r for r in listed if not r.success]),
        }

        logger.info(f"Sell cycle complete: {summary}")
        return summary

    def get_status(self) -> dict:
        """
        Get current trading status.

        Returns:
            Comprehensive status dictionary
        """
        # Get wallet balance
        try:
            wallet = self.steam.get_wallet_balance()
            balance = wallet.balance
        except Exception:
            balance = 0

        # Get database stats
        db_stats = self.db.get_stats()

        # Get bottm stats
        try:
            bottm_stats = self.bottm.get_stats()
        except Exception:
            bottm_stats = {}

        return {
            "wallet_balance": balance,
            "max_orders_value": settings.calculate_max_orders_value(balance),
            **db_stats,
            "bottm_items": bottm_stats.get("total_items", 0),
            "bottm_avg_profit": bottm_stats.get("avg_profit_pct", 0),
        }


# Singleton instance
trade_logic = TradeLogic()
