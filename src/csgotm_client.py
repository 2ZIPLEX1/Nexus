"""
Market.CSGO.COM API client.

Handles selling items and managing listings on market.csgo.com marketplace.
API Documentation: https://market.csgo.com/docs-v2
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class CsgoTmError(Exception):
    """Custom exception for CSGO.TM API errors."""
    pass


class TradeStatus(Enum):
    """Trade request status."""
    PENDING = "pending"
    SENT = "sent"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class SellResult:
    """Result of listing an item for sale."""
    success: bool
    item_id: Optional[str] = None
    message: Optional[str] = None


@dataclass
class TradeRequest:
    """Trade request from CSGO.TM bot."""
    trade_id: str
    bot_id: str
    bot_nick: str
    trade_url: str
    items: list[dict]
    status: TradeStatus


@dataclass
class MarketItem:
    """Item listed on CSGO.TM marketplace."""
    item_id: str
    market_hash_name: str
    price: float
    class_id: str
    instance_id: str


class CsgoTmClient:
    """
    Client for CSGO.TM marketplace API.

    Supports:
    - Listing items for sale
    - Getting trade requests
    - Managing sell listings
    - Checking sold items
    """

    BASE_URL = "https://market.csgo.com/api/v2"
    REQUEST_DELAY = 2.0  # Seconds between requests (increased for stability)
    MAX_RETRIES = 3

    def __init__(self, api_key: Optional[str] = None, session: Optional[requests.Session] = None):
        """Initialize client with API key and optional session (with proxy)."""
        self.api_key = api_key or settings.csgotm_api_key
        self._last_request_time = 0.0

        # Create session with browser-like headers if not provided
        if session:
            self._session = session
            # Add browser headers to existing session
            self._session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://market.csgo.com/',
                'Origin': 'https://market.csgo.com',
                'Connection': 'keep-alive',
            })
        else:
            self._session = requests.Session()
            self._session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://market.csgo.com/',
                'Origin': 'https://market.csgo.com',
                'Connection': 'keep-alive',
            })

    def _rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[dict] = None,
        data: Optional[dict] = None
    ) -> dict:
        """
        Make API request with rate limiting and retries.

        Args:
            endpoint: API endpoint
            method: HTTP method
            params: Query parameters
            data: POST data

        Returns:
            API response as dict
        """
        url = f"{self.BASE_URL}/{endpoint}"

        if params is None:
            params = {}

        # Add API key only if provided (some endpoints work without it)
        if self.api_key:
            params["key"] = self.api_key

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self._rate_limit()

                if method == "GET":
                    response = self._session.get(url, params=params, timeout=60)
                else:
                    response = self._session.post(url, params=params, data=data, timeout=60)

                response.raise_for_status()
                result = response.json()

                if not result.get("success"):
                    error = result.get("error", "Unknown error")
                    logger.debug(f"API request to {endpoint} failed. Full response: {result}")
                    raise CsgoTmError(f"API error: {error}")

                return result

            except requests.exceptions.RequestException as e:
                last_error = e
                # Check if it's a 520 error (Cloudflare issue)
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    logger.warning(f"Request failed (attempt {attempt + 1}): HTTP {status_code} - {e}")
                    if status_code == 520:
                        logger.warning("CSGO.TM returned 520 error (Cloudflare). This may be due to rate limiting or geo-blocking.")
                else:
                    logger.warning(f"Request failed (attempt {attempt + 1}): {e}")

                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff: 3s, 6s, 12s
                    wait_time = 3 * (2 ** attempt)
                    logger.debug(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
            except CsgoTmError:
                raise
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)

        raise CsgoTmError(f"Max retries exceeded: {last_error}")

    # ============ Account Methods ============

    def get_money(self) -> float:
        """Get current balance on CSGO.TM."""
        try:
            result = self._request("get-money")
            # Balance is in kopecks (1/100 of RUB)
            balance = result.get("money", 0) / 100.0
            logger.info(f"CSGO.TM balance: {balance:.2f} RUB")
            return balance
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise

    def ping(self) -> bool:
        """
        Check if API is working and key is valid.

        Note: The /ping endpoint is no longer supported by market.csgo.com API.
        We use /get-money as a health check instead.
        """
        try:
            logger.debug(f"Testing CSGO.TM API connection using get-money endpoint")
            # Use get-money instead of ping (ping endpoint is deprecated/broken)
            result = self._request("get-money")
            success = result.get("success", False)

            if success:
                logger.info("CSGO.TM API connection successful")
                return True
            else:
                logger.warning(f"CSGO.TM API returned success=False. Response: {result}")
                return False
        except CsgoTmError as e:
            logger.error(f"CSGO.TM API connection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"CSGO.TM API connection failed: {type(e).__name__}: {e}")
            logger.debug(f"API key (first 8 chars): {self.api_key[:8] if self.api_key else 'None'}...")
            return False

    def get_profile(self) -> dict:
        """Get account profile info."""
        return self._request("get-profile")

    # ============ Sell Methods ============

    def add_to_sale(
        self,
        item_id: str,
        price: float,
        currency: str = "USD"
    ) -> SellResult:
        """
        List an item for sale on CSGO.TM.

        Note: Item must first be in CSGO.TM inventory (sent via trade).
        For items directly from Steam inventory, use set_price method.

        Args:
            item_id: CSGO.TM item ID
            price: Price in specified currency
            currency: Currency code (USD, RUB, EUR)

        Returns:
            SellResult with success status
        """
        try:
            # Convert price to cents/kopecks
            if currency == "USD":
                price_cents = int(price * 100)
            else:
                price_cents = int(price * 100)

            result = self._request(
                "add-to-sale",
                params={
                    "id": item_id,
                    "price": price_cents,
                    "cur": currency
                }
            )

            logger.info(f"Listed item {item_id} for ${price:.2f}")
            return SellResult(success=True, item_id=item_id)

        except CsgoTmError as e:
            logger.error(f"Failed to list item: {e}")
            return SellResult(success=False, message=str(e))

    def set_price(
        self,
        class_id: str,
        instance_id: str,
        price: float
    ) -> SellResult:
        """
        Set sell price for item from Steam inventory.

        This initiates the process:
        1. CSGO.TM bot sends trade offer
        2. You accept the trade
        3. Item appears on marketplace

        Args:
            class_id: Steam class ID
            instance_id: Steam instance ID
            price: Price in USD

        Returns:
            SellResult with item_id if successful
        """
        try:
            price_cents = int(price * 100)

            result = self._request(
                "set-price",
                params={
                    "classid": class_id,
                    "instanceid": instance_id,
                    "price": price_cents
                }
            )

            item_id = result.get("item_id")
            logger.info(f"Set price for item: ${price:.2f}, waiting for trade")
            return SellResult(success=True, item_id=item_id)

        except CsgoTmError as e:
            logger.error(f"Failed to set price: {e}")
            return SellResult(success=False, message=str(e))

    def remove_from_sale(self, item_id: str) -> bool:
        """Remove item from sale."""
        try:
            self._request("set-price", params={"id": item_id, "price": 0})
            logger.info(f"Removed item {item_id} from sale")
            return True
        except CsgoTmError as e:
            logger.error(f"Failed to remove from sale: {e}")
            return False

    def update_price(self, item_id: str, new_price: float) -> bool:
        """Update price for listed item."""
        try:
            price_cents = int(new_price * 100)
            self._request("set-price", params={"id": item_id, "price": price_cents})
            logger.info(f"Updated price for {item_id}: ${new_price:.2f}")
            return True
        except CsgoTmError as e:
            logger.error(f"Failed to update price: {e}")
            return False

    # ============ Inventory & Listings ============

    def get_my_inventory(self) -> list[MarketItem]:
        """Get items in CSGO.TM inventory (received but not listed)."""
        try:
            result = self._request("my-inventory")
            items = []

            for item in result.get("items", []):
                items.append(MarketItem(
                    item_id=item.get("id"),
                    market_hash_name=item.get("market_hash_name"),
                    price=item.get("price", 0) / 100.0,
                    class_id=item.get("classid"),
                    instance_id=item.get("instanceid"),
                ))

            return items

        except CsgoTmError as e:
            logger.error(f"Failed to get inventory: {e}")
            return []

    def get_items_on_sale(self) -> list[MarketItem]:
        """Get items currently listed for sale."""
        try:
            result = self._request("items")
            items = []

            for item in result.get("items", []):
                items.append(MarketItem(
                    item_id=item.get("item_id"),
                    market_hash_name=item.get("market_hash_name"),
                    price=item.get("price", 0) / 100.0,
                    class_id=item.get("classid"),
                    instance_id=item.get("instanceid"),
                ))

            logger.info(f"Found {len(items)} items on sale")
            return items

        except CsgoTmError as e:
            logger.error(f"Failed to get items on sale: {e}")
            return []

    # ============ Trade Methods ============

    def get_trade_requests(self) -> list[TradeRequest]:
        """Get pending trade requests from CSGO.TM bot."""
        try:
            result = self._request("trade-request-give-p2p-all")
            requests_list = []

            for trade in result.get("trades", []):
                requests_list.append(TradeRequest(
                    trade_id=trade.get("trade_id"),
                    bot_id=trade.get("bot_id"),
                    bot_nick=trade.get("bot_nick"),
                    trade_url=trade.get("trade_url", ""),
                    items=trade.get("items", []),
                    status=TradeStatus.PENDING,
                ))

            return requests_list

        except CsgoTmError as e:
            logger.error(f"Failed to get trade requests: {e}")
            return []

    def get_trade_status(self, trade_id: str) -> Optional[TradeStatus]:
        """Check status of a trade request."""
        try:
            result = self._request("trade-request-give-p2p", params={"id": trade_id})
            status = result.get("status", "unknown")

            status_map = {
                "pending": TradeStatus.PENDING,
                "sent": TradeStatus.SENT,
                "accepted": TradeStatus.ACCEPTED,
                "cancelled": TradeStatus.CANCELLED,
                "timeout": TradeStatus.TIMEOUT,
            }

            return status_map.get(status, TradeStatus.PENDING)

        except CsgoTmError:
            return None

    # ============ Price Methods ============

    def get_item_price(self, market_hash_name: str) -> Optional[dict]:
        """
        Get current prices for an item on CSGO.TM.

        Returns:
            Dict with min_price, average_price, offers_count
        """
        try:
            result = self._request(
                "search-item-by-hash-name-specific",
                params={"hash_name": market_hash_name}
            )

            data = result.get("data", {})

            logger.debug(f"API response for {market_hash_name}: data type={type(data)}")

            # Handle case where API returns list instead of dict
            if isinstance(data, list):
                if len(data) > 0:
                    # When API returns list of items, calculate min price from the list
                    prices = [item.get("price", 0) for item in data if isinstance(item, dict)]
                    if not prices:
                        logger.warning(f"No valid prices in list for {market_hash_name}")
                        return None

                    min_price = min(prices) if prices else 0
                    avg_price = sum(prices) / len(prices) if prices else 0
                    offers_count = len(prices)

                    return {
                        "min_price": min_price / 100.0,
                        "average_price": avg_price / 100.0,
                        "offers_count": offers_count,
                    }
                else:
                    logger.warning(f"Empty data list for {market_hash_name}")
                    return None

            # Handle case where API returns a single dict (legacy format)
            if isinstance(data, dict):
                return {
                    "min_price": data.get("min_price", 0) / 100.0,
                    "average_price": data.get("average_price", 0) / 100.0,
                    "offers_count": data.get("count", 0),
                }

            logger.error(f"Unexpected data type: {type(data)} for {market_hash_name}")
            return None

        except CsgoTmError as e:
            logger.error(f"Failed to get item price for {market_hash_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting item price for {market_hash_name}: {type(e).__name__}: {e}")
            return None

    # ============ History Methods ============

    def get_operation_history(self, limit: int = 100) -> list[dict]:
        """Get recent operations (sales, purchases)."""
        try:
            result = self._request("operation-history", params={"limit": limit})
            return result.get("operations", [])
        except CsgoTmError as e:
            logger.error(f"Failed to get history: {e}")
            return []

    def get_sold_items(self, limit: int = 100) -> list[dict]:
        """Get recently sold items."""
        history = self.get_operation_history(limit)
        return [op for op in history if op.get("type") == "sell"]


# Singleton instance
csgotm_client = CsgoTmClient()
