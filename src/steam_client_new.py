"""
Steam client using ValvePython/steam library with HTTP requests.

This implementation replaces steampy with a more reliable approach:
- Uses ValvePython/steam for authentication (supports new Steam API)
- Makes direct HTTP requests to Steam Market API
- Compatible with the same credentials as steampy

Based on the Node.js buyOrders.js implementation.
"""

import json
import time
from base64 import b64decode
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import requests
from steam.webauth import WebAuth
from steam.guard import generate_twofactor_code

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)

# CS2 App ID (same as CS:GO)
CS2_APPID = 730


@dataclass
class WalletInfo:
    """Steam wallet information."""

    balance: float
    currency: int
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
    Steam Market client using ValvePython/steam for authentication
    and direct HTTP requests for market operations.

    Handles:
    - Authentication with Steam Guard (shared_secret for 2FA)
    - Wallet balance checking
    - Buy order placement and management
    - Inventory access
    - Rate limiting
    """

    # Rate limiting
    REQUEST_DELAY = 3.0  # Seconds between requests
    MAX_RETRIES = 3
    RETRY_DELAY = 5.0

    # Steam API endpoints
    BASE_URL = "https://steamcommunity.com"
    MARKET_URL = f"{BASE_URL}/market"

    def __init__(self):
        """Initialize Steam client."""
        self._session: Optional[requests.Session] = None
        self._sessionid: Optional[str] = None
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
            except requests.exceptions.Timeout:
                wait_time = self.RETRY_DELAY * (attempt + 1)
                logger.warning(f"Request timeout, waiting {wait_time}s...")
                time.sleep(wait_time)
            except requests.exceptions.RequestException as e:
                last_error = e
                if "429" in str(e) or "Too Many Requests" in str(e):
                    wait_time = self.RETRY_DELAY * (attempt + 1)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
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
        Login to Steam using ValvePython/steam WebAuth.

        Returns:
            True if login successful
        """
        if self._logged_in and self._session:
            logger.info("Already logged in")
            return True

        try:
            logger.info(f"Logging in as {settings.steam_username}...")

            # Generate 2FA code from shared_secret
            # shared_secret in .env is base64-encoded, so decode it first
            try:
                shared_secret_bytes = b64decode(settings.steam_shared_secret)
                twofactor_code = generate_twofactor_code(shared_secret_bytes)
                logger.info(f"Generated 2FA code: {twofactor_code} (length: {len(twofactor_code)})")
            except Exception as e:
                raise SteamClientError(
                    f"Failed to generate 2FA code. "
                    f"Check that STEAM_SHARED_SECRET is valid base64: {e}"
                )

            # Create WebAuth instance
            wa = WebAuth(settings.steam_username)
            logger.info(f"WebAuth instance created for user: {settings.steam_username}")

            # Attempt login with 2FA
            # Try first without 2FA to get the RSA key and session
            logger.info("Step 1: Initial login attempt...")
            try:
                self._session = wa.login(password=settings.steam_password)
                logger.info("Login successful! Session obtained.")
            except Exception as login_error:
                logger.debug(f"Initial login raised: {type(login_error).__name__}")

                # Import the exception class
                from steam.webauth import TwoFactorCodeRequired

                # If 2FA is required, retry with the code
                if isinstance(login_error, TwoFactorCodeRequired):
                    logger.info(f"2FA required. Retrying with code: {twofactor_code}")
                    try:
                        self._session = wa.login(
                            password=settings.steam_password,
                            twofactor_code=twofactor_code
                        )
                        logger.info("Login with 2FA successful! Session obtained.")
                    except KeyError as key_err:
                        # Handle the 'transfer_parameters' KeyError from Issue #456
                        # https://github.com/ValvePython/steam/issues/456
                        if 'transfer_parameters' in str(key_err):
                            logger.warning(
                                "Encountered 'transfer_parameters' KeyError. "
                                "This is a known issue in steam library, but login was successful."
                            )
                            # The session is already set in wa object, we can use it
                            # even though _finalize_login failed
                            if hasattr(wa, 'session') and wa.session:
                                self._session = wa.session
                                logger.info("Using session from WebAuth object")
                            else:
                                raise SteamClientError(
                                    "Login succeeded but couldn't get session. "
                                    "This is a known issue with steam library. "
                                    "Try updating: pip install --upgrade steam"
                                )
                        else:
                            raise
                    except TwoFactorCodeRequired as e:
                        raise SteamClientError(
                            f"2FA code rejected by Steam. "
                            f"Code used: {twofactor_code}. "
                            f"Please verify your STEAM_SHARED_SECRET is correct."
                        )
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "incorrect login" in error_msg or "invalid" in error_msg:
                            raise SteamClientError("Invalid Steam credentials")
                        elif "too many login failures" in error_msg:
                            raise SteamClientError(
                                "Too many login failures. Wait a few minutes and try again."
                            )
                        else:
                            raise SteamClientError(f"Login with 2FA failed: {e}")
                else:
                    # Not a 2FA error, re-raise
                    error_msg = str(login_error).lower()
                    if "incorrect login" in error_msg or "invalid" in error_msg:
                        raise SteamClientError("Invalid Steam credentials")
                    elif "too many login failures" in error_msg:
                        raise SteamClientError(
                            "Too many login failures. Wait a few minutes and try again."
                        )
                    else:
                        raise SteamClientError(f"Login failed: {login_error}")

            # Get sessionid from cookies
            for cookie in self._session.cookies:
                if cookie.name == 'sessionid':
                    self._sessionid = cookie.value
                    break

            if not self._sessionid:
                raise SteamClientError("Failed to get sessionid from cookies")

            self._logged_in = True
            logger.info("✅ Successfully logged in to Steam!")
            logger.debug(f"SessionID: {self._sessionid[:8]}...")

            return True

        except SteamClientError:
            raise
        except Exception as e:
            logger.error(f"Login failed: {e}")
            logger.debug(f"Login error details: {type(e).__name__}: {e}")
            raise SteamClientError(f"Login failed: {e}")

    def logout(self):
        """Logout from Steam."""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
            self._sessionid = None
            self._logged_in = False
            logger.info("Logged out from Steam")

    def ensure_logged_in(self):
        """Ensure client is logged in."""
        if not self._logged_in or not self._session:
            self.login()

    def _make_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> requests.Response:
        """Make an authenticated HTTP request."""
        self.ensure_logged_in()

        headers = kwargs.pop('headers', {})
        headers.update({
            'Referer': self.MARKET_URL,
            'Origin': self.BASE_URL,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        if method.upper() == 'POST':
            response = self._session.post(url, headers=headers, **kwargs)
        else:
            response = self._session.get(url, headers=headers, **kwargs)

        response.raise_for_status()
        return response

    def get_wallet_balance(self) -> WalletInfo:
        """
        Get current wallet balance.

        Returns:
            WalletInfo with balance and currency
        """
        self.ensure_logged_in()

        try:
            # Get wallet balance from Steam
            url = f"{self.BASE_URL}/steamguard/getjson"
            response = self._retry_on_error(self._make_request, 'GET', url)
            data = response.json()

            # Alternative: fetch from market page
            if not data or 'wallet_balance' not in data:
                url = f"{self.MARKET_URL}/"
                response = self._retry_on_error(self._make_request, 'GET', url)
                # Parse HTML for wallet balance
                # This is a fallback - might need BeautifulSoup
                pass

            balance_cents = int(data.get("wallet_balance", 0))
            balance = balance_cents / 100.0
            currency = data.get("wallet_currency", 1)  # 1 = USD

            return WalletInfo(
                balance=balance,
                currency=currency,
                currency_code="USD"  # Map currency code based on currency int
            )

        except Exception as e:
            logger.error(f"Failed to get wallet balance: {e}")
            raise SteamClientError(f"Failed to get wallet balance: {e}")

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

            url = f"{self.MARKET_URL}/createbuyorder/"

            form_data = {
                'sessionid': self._sessionid,
                'currency': 1,  # USD
                'appid': CS2_APPID,
                'market_hash_name': market_hash_name,
                'price_total': price_cents,
                'quantity': quantity
            }

            headers = {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            }

            response = self._retry_on_error(
                self._make_request,
                'POST',
                url,
                data=form_data,
                headers=headers
            )

            result = response.json()

            # Check for success
            if result.get('success') in [1, True, '1']:
                order_id = str(result.get('buy_orderid', 'unknown'))
                logger.info(f"✅ Buy order created: {order_id}")
                return BuyOrderResult(success=True, order_id=order_id)

            # Handle success:42 (order created but no ID returned)
            elif result.get('success') == 42:
                logger.warning("Steam returned success:42 - verifying order...")
                # Verify order was created by checking active orders
                orders = self.get_buy_orders()
                for order in orders:
                    if order['item_name'] == market_hash_name:
                        logger.info("✅ Order confirmed via getbuyorders")
                        return BuyOrderResult(success=True, message="confirmed-via-list")

                message = "Order may not have been created (success:42)"
                logger.warning(message)
                return BuyOrderResult(success=False, message=message)

            else:
                message = result.get('message', 'Unknown error')
                logger.warning(f"Buy order failed: {message}")
                return BuyOrderResult(success=False, message=message)

        except Exception as e:
            logger.error(f"Failed to create buy order: {e}")
            return BuyOrderResult(success=False, message=str(e))

    def get_buy_orders(self) -> list[dict]:
        """
        Get all active buy orders.

        Returns:
            List of active buy orders
        """
        self.ensure_logged_in()

        try:
            url = f"{self.MARKET_URL}/mylistings/"
            response = self._retry_on_error(self._make_request, 'GET', url)

            # Parse response - might need to parse HTML or JSON
            # This is simplified - actual implementation may differ
            data = response.json() if 'json' in response.headers.get('content-type', '') else {}

            orders = []
            buy_orders = data.get('buy_orders', {})

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

            url = f"{self.MARKET_URL}/cancelbuyorder/"

            form_data = {
                'sessionid': self._sessionid,
                'buy_orderid': order_id
            }

            response = self._retry_on_error(
                self._make_request,
                'POST',
                url,
                data=form_data
            )

            result = response.json()
            success = result.get('success') in [1, True, '1']

            if success:
                logger.info(f"Buy order cancelled: {order_id}")
            else:
                logger.warning(f"Failed to cancel order: {order_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to cancel buy order: {e}")
            return False

    def get_inventory(self) -> list[InventoryItem]:
        """
        Get Steam inventory for CS2.

        Returns:
            List of inventory items
        """
        self.ensure_logged_in()

        try:
            # Get steamid from session
            # This is simplified - you might need to fetch steamid differently
            url = f"{self.BASE_URL}/my/inventory/json/{CS2_APPID}/2"

            response = self._retry_on_error(self._make_request, 'GET', url)
            data = response.json()

            items = []
            assets = data.get('rgInventory', {})
            descriptions = data.get('rgDescriptions', {})

            for asset_id, asset_data in assets.items():
                classid = asset_data.get('classid')
                instanceid = asset_data.get('instanceid')

                desc_key = f"{classid}_{instanceid}"
                desc = descriptions.get(desc_key, {})

                items.append(InventoryItem(
                    asset_id=asset_id,
                    class_id=classid,
                    instance_id=instanceid,
                    market_hash_name=desc.get('market_hash_name', ''),
                    tradable=desc.get('tradable', False),
                    marketable=desc.get('marketable', False),
                    amount=int(asset_data.get('amount', 1)),
                ))

            logger.info(f"Found {len(items)} items in inventory")
            return items

        except Exception as e:
            logger.error(f"Failed to get inventory: {e}")
            return []

    def __enter__(self):
        """Context manager entry."""
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.logout()


# Singleton instance
steam_client = SteamClient()
