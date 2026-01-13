"""
Steam client wrapper using steampy library.

Handles authentication, balance checking, buy orders, and inventory management.
"""

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from steampy.client import SteamClient as SteampyClient
from steampy.exceptions import ApiException, InvalidCredentials, TooManyRequests
from steampy.models import Currency, GameOptions

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)

# CS2 game settings (same as CS:GO)
CS2_GAME = GameOptions.CS


@dataclass
class WalletInfo:
    """Steam wallet information."""

    balance: float
    currency: Currency
    currency_code: str

    @property
    def balance_cents(self) -> int:
        """Balance in cents."""
        return int(self.balance * 100)


@dataclass
class BuyOrderResult:
    """Result of placing a buy order."""

    success: bool
    order_id: Optional[str] = None
    message: Optional[str] = None


@dataclass
class InventoryItem:
    """Steam inventory item."""

    asset_id: str
    class_id: str
    instance_id: str
    market_hash_name: str
    tradable: bool
    marketable: bool
    amount: int = 1


class SteamClientError(Exception):
    """Custom exception for Steam client errors."""
    pass


class SteamClient:
    """
    Wrapper for steampy SteamClient with additional functionality.

    Handles:
    - Authentication with Steam Guard (shared_secret + identity_secret)
    - Wallet balance checking
    - Buy order placement and management
    - Inventory access
    - Rate limiting
    """

    # Rate limiting
    REQUEST_DELAY = 3.0  # Seconds between requests
    MAX_RETRIES = 3
    RETRY_DELAY = 5.0

    def __init__(self):
        """Initialize Steam client."""
        self._client: Optional[SteampyClient] = None
        self._last_request_time = 0.0
        self._logged_in = False

    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _retry_on_error(self, func, *args, **kwargs):
        """Retry function on transient errors."""
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            except TooManyRequests:
                wait_time = self.RETRY_DELAY * (attempt + 1)
                logger.warning(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
            except ApiException as e:
                last_error = e
                if "try again" in str(e).lower():
                    time.sleep(self.RETRY_DELAY)
                else:
                    raise
            except Exception as e:
                last_error = e
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)

        raise SteamClientError(f"Max retries exceeded: {last_error}")

    def login(self) -> bool:
        """
        Login to Steam with credentials from settings.

        Returns:
            True if login successful
        """
        if self._logged_in and self._client:
            return True

        try:
            logger.info(f"Logging in as {settings.steam_username}...")

            self._client = SteampyClient(settings.steam_api_key)

            # Try to login with Steam Guard secrets
            # Note: steampy has issues with Steam's new authentication API
            # See: https://github.com/bukson/steampy/issues/377
            try:
                self._client.login(
                    settings.steam_username,
                    settings.steam_password,
                    json.dumps(settings.steam_guard)  # steampy expects JSON string
                )
            except KeyError as e:
                if "refresh_token" in str(e):
                    logger.error(
                        "Steam login failed due to 'refresh_token' error. "
                        "This is a known issue with steampy and Steam's updated authentication API."
                    )
                    logger.error(
                        "Possible solutions:\n"
                        "  1. Try again after a few minutes (Steam may be rate limiting)\n"
                        "  2. Update steampy: pip install --upgrade steampy\n"
                        "  3. Check GitHub for updates: https://github.com/bukson/steampy/issues/377"
                    )
                raise SteamClientError(
                    "Steam authentication failed. Steam may have changed their API. "
                    "See logs for details."
                )

            self._logged_in = True
            logger.info("Successfully logged in to Steam")
            return True

        except InvalidCredentials as e:
            logger.error(f"Invalid Steam credentials: {e}")
            raise SteamClientError("Invalid Steam credentials")
        except SteamClientError:
            raise
        except Exception as e:
            logger.error(f"Login failed: {e}")
            logger.debug(f"Login error details: {type(e).__name__}: {e}")
            raise SteamClientError(f"Login failed: {e}")

    def logout(self):
        """Logout from Steam."""
        if self._client:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None
            self._logged_in = False
            logger.info("Logged out from Steam")

    def ensure_logged_in(self):
        """Ensure client is logged in."""
        if not self._logged_in or not self._client:
            self.login()

    def get_wallet_balance(self) -> WalletInfo:
        """
        Get current wallet balance.

        Returns:
            WalletInfo with balance and currency
        """
        self.ensure_logged_in()

        try:
            wallet = self._retry_on_error(self._client.get_wallet_balance)

            # Parse wallet response
            # steampy returns balance in cents as string
            balance_cents = int(wallet.get("wallet_balance", 0))
            balance = balance_cents / 100.0

            currency_code = wallet.get("wallet_currency", "USD")

            return WalletInfo(
                balance=balance,
                currency=Currency.USD,  # Default, adjust if needed
                currency_code=currency_code
            )

        except Exception as e:
            logger.error(f"Failed to get wallet balance: {e}")
            raise SteamClientError(f"Failed to get wallet balance: {e}")

    def get_my_market_listings(self) -> dict:
        """Get current market listings (sell orders)."""
        self.ensure_logged_in()

        try:
            return self._retry_on_error(self._client.market.get_my_market_listings)
        except Exception as e:
            logger.error(f"Failed to get market listings: {e}")
            return {}

    def get_buy_orders(self) -> list[dict]:
        """
        Get all active buy orders.

        Returns:
            List of active buy orders
        """
        self.ensure_logged_in()

        try:
            listings = self._retry_on_error(self._client.market.get_my_market_listings)
            buy_orders = listings.get("buy_orders", {})

            orders = []
            for order_id, order_data in buy_orders.items():
                orders.append({
                    "order_id": order_id,
                    "item_name": order_data.get("hash_name", ""),
                    "price": int(order_data.get("price", 0)) / 100.0,
                    "quantity": order_data.get("quantity", 1),
                    "quantity_remaining": order_data.get("quantity_remaining", 1),
                })

            return orders

        except Exception as e:
            logger.error(f"Failed to get buy orders: {e}")
            return []

    def create_buy_order(
        self,
        market_hash_name: str,
        price: float,
        quantity: int = 1
    ) -> BuyOrderResult:
        """
        Create a buy order on Steam Market.

        Args:
            market_hash_name: Item's market hash name
            price: Price per item in dollars
            quantity: Number of items to buy

        Returns:
            BuyOrderResult with order ID if successful
        """
        self.ensure_logged_in()

        price_cents = int(price * 100)

        try:
            logger.info(f"Creating buy order: {market_hash_name} @ ${price:.2f} x{quantity}")

            response = self._retry_on_error(
                self._client.market.create_buy_order,
                market_hash_name,
                price_cents,
                quantity,
                CS2_GAME,
                Currency.USD
            )

            if response.get("success") == 1:
                order_id = str(response.get("buy_orderid"))
                logger.info(f"Buy order created: {order_id}")
                return BuyOrderResult(success=True, order_id=order_id)
            else:
                message = response.get("message", "Unknown error")
                logger.warning(f"Buy order failed: {message}")
                return BuyOrderResult(success=False, message=message)

        except Exception as e:
            logger.error(f"Failed to create buy order: {e}")
            return BuyOrderResult(success=False, message=str(e))

    def cancel_buy_order(self, order_id: str) -> bool:
        """
        Cancel a buy order.

        Args:
            order_id: Steam order ID

        Returns:
            True if cancelled successfully
        """
        self.ensure_logged_in()

        try:
            logger.info(f"Cancelling buy order: {order_id}")

            response = self._retry_on_error(
                self._client.market.cancel_buy_order,
                order_id
            )

            success = response.get("success") == 1
            if success:
                logger.info(f"Buy order cancelled: {order_id}")
            else:
                logger.warning(f"Failed to cancel order: {order_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to cancel buy order: {e}")
            return False

    def get_inventory(self, game: GameOptions = CS2_GAME) -> list[InventoryItem]:
        """
        Get Steam inventory for specified game.

        Args:
            game: Game to get inventory for (default: CS2)

        Returns:
            List of inventory items
        """
        self.ensure_logged_in()

        try:
            inventory = self._retry_on_error(
                self._client.get_my_inventory,
                game
            )

            items = []
            for asset_id, item_data in inventory.items():
                items.append(InventoryItem(
                    asset_id=asset_id,
                    class_id=item_data.get("classid", ""),
                    instance_id=item_data.get("instanceid", ""),
                    market_hash_name=item_data.get("market_hash_name", ""),
                    tradable=item_data.get("tradable", False),
                    marketable=item_data.get("marketable", False),
                    amount=int(item_data.get("amount", 1)),
                ))

            logger.info(f"Found {len(items)} items in inventory")
            return items

        except Exception as e:
            logger.error(f"Failed to get inventory: {e}")
            return []

    def find_item_in_inventory(
        self,
        market_hash_name: str,
        tradable_only: bool = True
    ) -> Optional[InventoryItem]:
        """
        Find an item in inventory by market hash name.

        Args:
            market_hash_name: Item's market hash name
            tradable_only: Only return tradable items

        Returns:
            InventoryItem if found, None otherwise
        """
        inventory = self.get_inventory()

        for item in inventory:
            if item.market_hash_name == market_hash_name:
                if tradable_only and not item.tradable:
                    continue
                return item

        return None

    def get_item_price_overview(self, market_hash_name: str) -> Optional[dict]:
        """
        Get price overview for an item from Steam Market.

        Args:
            market_hash_name: Item's market hash name

        Returns:
            Dict with lowest_price, median_price, volume
        """
        self.ensure_logged_in()

        try:
            response = self._retry_on_error(
                self._client.market.fetch_price,
                market_hash_name,
                CS2_GAME,
                Currency.USD
            )

            return {
                "lowest_price": response.get("lowest_price"),
                "median_price": response.get("median_price"),
                "volume": response.get("volume"),
            }

        except Exception as e:
            logger.error(f"Failed to get price overview: {e}")
            return None

    def check_order_filled(self, order_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if a buy order has been filled.

        Args:
            order_id: Steam order ID

        Returns:
            Tuple of (is_filled, asset_id if filled)
        """
        orders = self.get_buy_orders()

        for order in orders:
            if order["order_id"] == order_id:
                # Order still exists, not filled yet
                remaining = order.get("quantity_remaining", 1)
                if remaining == 0:
                    # Order filled but might still be in list
                    return True, None
                return False, None

        # Order not in list - either filled or cancelled
        # Check inventory for newly acquired items
        # This is a simplified check - in production you'd track this better
        return True, None

    def __enter__(self):
        """Context manager entry."""
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.logout()


# Singleton instance
steam_client = SteamClient()
