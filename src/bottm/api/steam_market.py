"""
Steam Market API client.

Provides methods to fetch:
- Price overview (lowest_price, median_price, volume)
- Buy orders (highest_buy_order, buy_order_graph)

Supports SOCKS5/HTTP proxy for regions where Steam is blocked.
"""
import re
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import aiohttp
from aiohttp_socks import ProxyConnector

from src.bottm.config import Currency, STEAM_CURRENCY_CODES, config
from src.proxy_utils import normalize_proxy_list, normalize_proxy_url
import src.dns_compat  # noqa: F401  # DNS-фикс (ThreadedResolver) до создания aiohttp-сессий

logger = logging.getLogger(__name__)

# Единый браузерный отпечаток. Chrome-версия в User-Agent и в sec-ch-ua ДОЛЖНА совпадать,
# иначе Steam палит несоответствие. Обновлять обе строки вместе.
CHROME_VERSION = "149"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36"
)
# Client hints (постоянны для сессии, не зависят от типа запроса)
BROWSER_CLIENT_HINTS = {
    "sec-ch-ua": f'"Google Chrome";v="{CHROME_VERSION}", "Chromium";v="{CHROME_VERSION}", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


@dataclass
class PriceOverview:
    """Steam market price overview."""
    success: bool
    lowest_price: Optional[float] = None
    median_price: Optional[float] = None
    volume: Optional[int] = None
    currency: Currency = Currency.RUB


@dataclass
class BuyOrderInfo:
    """Steam market buy order information."""
    success: bool
    error: Optional[str] = None
    highest_buy_order: Optional[float] = None  # In currency units (not cents)
    lowest_sell_order: Optional[float] = None
    buy_order_count: int = 0
    sell_order_count: int = 0
    # Raw order graph: [[price_cents, cumulative_qty, "desc"], ...]
    buy_order_graph: Optional[list] = None

    def count_orders_above_price(self, price: float) -> int:
        """
        Count how many buy orders are at prices ABOVE the given price.

        This tells you how many orders need to fill before yours.
        Steam's graph shows cumulative quantities at each price level.
        """
        if not self.buy_order_graph:
            return 0

        price_cents = int(price * 100)
        orders_above = 0

        # Graph is sorted by price descending (highest first)
        # Each entry: [price_cents, cumulative_qty, description]
        # cumulative_qty is total orders at this price AND ABOVE
        for entry in self.buy_order_graph:
            if len(entry) >= 2:
                level_price = entry[0]  # in cents
                cumulative_qty = entry[1]  # orders at this price and above

                if level_price > price_cents:
                    # This price level is above our target
                    orders_above = cumulative_qty
                else:
                    # We've reached prices at or below our target
                    break

        return orders_above


@dataclass
class PriceHistory:
    """Steam market price history statistics."""
    success: bool
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    avg_price: Optional[float] = None
    median_price: Optional[float] = None
    percentile_20: Optional[float] = None  # 20% of sales were below this price
    percentile_25: Optional[float] = None  # 25% of sales were below this price
    total_sales: int = 0
    days_analyzed: int = 30


def parse_steam_price(price_str: str) -> Optional[float]:
    """
    Parse Steam price string to float.

    Examples:
    - "1 234,56 pуб." -> 1234.56
    - "12,34€" -> 12.34
    - "1,234.56€" -> 1234.56
    """
    if not price_str:
        return None

    # Remove HTML entities and currency symbols
    price_str = price_str.replace("&#8364;", "").replace("€", "")
    price_str = price_str.replace("pуб.", "").replace("руб.", "").replace("₽", "")
    price_str = price_str.replace("$", "").replace("USD", "")
    price_str = price_str.strip()

    # Handle different number formats
    # Russian: "1 234,56" (space as thousand sep, comma as decimal)
    # European: "1.234,56" (dot as thousand sep, comma as decimal)
    # US: "1,234.56" (comma as thousand sep, dot as decimal)

    # Remove spaces
    price_str = price_str.replace(" ", "").replace("\xa0", "")

    # Count dots and commas to determine format
    dots = price_str.count(".")
    commas = price_str.count(",")

    if commas == 1 and dots == 0:
        # "1234,56" -> European/Russian decimal
        price_str = price_str.replace(",", ".")
    elif commas == 1 and dots >= 1:
        # "1.234,56" -> European thousand separator
        price_str = price_str.replace(".", "").replace(",", ".")
    elif dots == 1 and commas >= 1:
        # "1,234.56" -> US format
        price_str = price_str.replace(",", "")
    elif commas > 1:
        # "1,234,567" -> US thousand separators, no decimal
        price_str = price_str.replace(",", "")

    try:
        return float(price_str)
    except ValueError:
        logger.warning(f"Failed to parse price: {price_str}")
        return None


class SteamMarketAPI:
    """Steam Community Market API client."""

    BASE_URL = "https://steamcommunity.com/market"
    APP_ID = 730  # CS:GO/CS2

    def __init__(
        self,
        currency: Currency = Currency.RUB,
        proxy_url: Optional[str] = None,
        proxy_list: Optional[list[str]] = None,
        requests_per_proxy: int = 15,
    ):
        """
        Initialize Steam Market API client.

        Args:
            currency: Currency for prices
            proxy_url: Single proxy URL (e.g., "socks5://host:port" or "socks5://user:pass@host:port")
            proxy_list: List of proxy URLs for rotation
            requests_per_proxy: Rotate proxy after this many requests (default: 15)
        """
        self.currency = currency
        self._session: Optional[aiohttp.ClientSession] = None
        self._item_nameid_cache: dict[str, int] = {}
        self._last_nameid_error: Optional[str] = None

        # Proxy rotation support
        # IMPORTANT: Always create list with at least proxy_url if provided
        logger.info(f"[DEBUG] __init__: proxy_url={proxy_url is not None}, proxy_list={len(proxy_list) if proxy_list else 0}")
        if proxy_list:
            self._proxy_list, skipped_proxies = normalize_proxy_list(proxy_list)
            logger.info(f"[DEBUG] __init__: using proxy_list with {len(self._proxy_list)} valid proxies")
            if skipped_proxies:
                logger.warning(f"Skipped {skipped_proxies} invalid proxy entries")
        elif proxy_url:
            normalized_proxy = normalize_proxy_url(proxy_url)
            self._proxy_list = [normalized_proxy] if normalized_proxy else []
            logger.info(f"[DEBUG] __init__: created proxy_list from proxy_url ({len(self._proxy_list)} proxy)")
            if not normalized_proxy:
                logger.warning("Skipped invalid proxy_url")
        elif config.proxy.enabled and config.proxy.url:
            normalized_proxy = normalize_proxy_url(config.proxy.url)
            self._proxy_list = [normalized_proxy] if normalized_proxy else []
            logger.info(f"[DEBUG] __init__: using config.proxy.url ({len(self._proxy_list)} proxy)")
            if not normalized_proxy:
                logger.warning("Skipped invalid config.proxy.url")
        else:
            self._proxy_list = []
            logger.info(f"[DEBUG] __init__: no proxies configured")

        # If we have proxy_url but empty list, add it
        if proxy_url and not self._proxy_list:
            normalized_proxy = normalize_proxy_url(proxy_url)
            self._proxy_list = [normalized_proxy] if normalized_proxy else []
            logger.info(f"[DEBUG] __init__: fallback - added proxy_url to empty list ({len(self._proxy_list)} proxy)")

        logger.info(f"[DEBUG] __init__: final proxy_list has {len(self._proxy_list)} proxies")
        if self._proxy_list:
            for idx, p in enumerate(self._proxy_list):
                p_display = p.split('@')[-1] if '@' in p else p
                logger.info(f"[DEBUG] __init__: proxy[{idx}] = {p_display}")

        self._current_proxy_idx = 0
        self._requests_count = 0
        self._requests_per_proxy = requests_per_proxy
        logger.info(f"[DEBUG] __init__: requests_per_proxy={requests_per_proxy}")
        self._session_lock = asyncio.Lock()  # Lock for thread-safe session operations
        self._active_requests = 0  # Track active requests to prevent premature rotation
        self._old_sessions = []  # Keep old sessions until they're no longer used

    def _get_current_proxy(self) -> Optional[str]:
        """Get current proxy URL."""
        logger.info(f"[DEBUG] _get_current_proxy called: proxy_list={len(self._proxy_list) if self._proxy_list else 0} items, idx={self._current_proxy_idx}")
        if not self._proxy_list:
            logger.info("[DEBUG] _get_current_proxy returning None (empty list)")
            return None
        proxy = self._proxy_list[self._current_proxy_idx % len(self._proxy_list)]
        proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
        logger.info(f"[DEBUG] _get_current_proxy returning: {proxy_display}")
        return proxy

    def get_current_proxy_info(self) -> str:
        """Get current proxy info for logging (public method)."""
        if not self._proxy_list:
            return "no proxy"
        proxy = self._proxy_list[self._current_proxy_idx % len(self._proxy_list)]
        proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
        return f"[{self._current_proxy_idx + 1}/{len(self._proxy_list)}]: {proxy_display}"

    async def _rotate_proxy(self, reason: str = ""):
        """Switch to next proxy and mark old session for cleanup."""
        if not self._proxy_list:
            logger.warning("Cannot rotate proxy: proxy list is empty")
            return

        if len(self._proxy_list) == 1:
            logger.warning(f"Only 1 proxy available, recreating session with same proxy. Reason: {reason}")
            # Even with 1 proxy, recreate the session to fix connection issues
            async with self._session_lock:
                if self._session and not self._session.closed:
                    self._old_sessions.append(self._session)
                self._session = None
                self._requests_count = 0
            return

        async with self._session_lock:
            old_idx = self._current_proxy_idx

            # Save old session for deferred cleanup (will close when no longer referenced)
            if self._session and not self._session.closed:
                self._old_sessions.append(self._session)
                # Cleanup old sessions list (keep only last 2 to avoid memory leak)
                if len(self._old_sessions) > 2:
                    old = self._old_sessions.pop(0)
                    try:
                        if not old.closed:
                            await old.close()
                    except Exception as e:
                        logger.debug(f"Error closing old session: {e}")

            # Mark for new session creation
            self._session = None

            # Move to next proxy
            self._current_proxy_idx = (self._current_proxy_idx + 1) % len(self._proxy_list)
            self._requests_count = 0

            proxy = self._get_current_proxy()
            proxy_display = proxy.split('@')[-1] if proxy and '@' in proxy else proxy
            reason_msg = f" ({reason})" if reason else ""
            logger.info(f"Rotated from proxy {old_idx + 1} to proxy [{self._current_proxy_idx + 1}/{len(self._proxy_list)}]: {proxy_display}{reason_msg}")

    def _request_complete(self):
        """Mark a request as complete (decrement active request counter)."""
        if self._active_requests > 0:
            self._active_requests -= 1

    async def _handle_rate_limit(self, status_code: int) -> bool:
        """Handle rate limit (429) by rotating proxy. Returns True if rotated."""
        if status_code == 429 and self._proxy_list and len(self._proxy_list) > 1:
            await self._rotate_proxy(reason="429 rate limit")
            return True
        return False

    async def _get_session(self) -> aiohttp.ClientSession:
        logger.info(f"[DEBUG] _get_session called: session={self._session is not None}, closed={self._session.closed if self._session else 'N/A'}")
        async with self._session_lock:
            logger.info("[DEBUG] _get_session: acquired lock")

            # Check if we need to rotate proxy (but only if no active requests)
            if self._proxy_list and self._requests_count >= self._requests_per_proxy and self._active_requests == 0:
                logger.info(f"Auto-rotating proxy (requests: {self._requests_count}/{self._requests_per_proxy})")
                await self._rotate_proxy(reason="request_limit")

            if self._session is None or self._session.closed:
                logger.info("[DEBUG] _get_session: creating new session")
                connector = None
                proxy = self._get_current_proxy()
                logger.info(f"[DEBUG] _get_session: got proxy={proxy is not None}")

                if proxy:
                    logger.info(f"[DEBUG] _get_session: creating ProxyConnector for proxy")
                    try:
                        # ВАЖНО: force_close=True для SOCKS5 прокси
                        # Это создает новое соединение для каждого запроса,
                        # что предотвращает "Connection closed" при переиспользовании
                        connector = ProxyConnector.from_url(
                            proxy,
                            force_close=True,  # Закрывать соединение после каждого запроса (защита от "Connection closed")
                            limit=100,  # Увеличиваем лимит соединений
                        )
                        logger.info(f"[DEBUG] _get_session: ProxyConnector created with force_close=True")
                    except Exception as e:
                        logger.error(f"[DEBUG] _get_session: ProxyConnector creation FAILED: {e}", exc_info=True)
                        raise

                    proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                    logger.info(f"Creating session with proxy [{self._current_proxy_idx + 1}/{len(self._proxy_list)}]: {proxy_display}")
                else:
                    logger.warning("Creating session WITHOUT proxy (no proxies configured)")

                logger.info("[DEBUG] _get_session: creating ClientSession")
                try:
                    self._session = aiohttp.ClientSession(
                        connector=connector,
                        headers={
                            # Полный User-Agent реального Chrome — обрезанный палит бота
                            "User-Agent": BROWSER_USER_AGENT,
                            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                            **BROWSER_CLIENT_HINTS,
                        },
                        # Увеличиваем sock_read до 120 секунд для больших HTML страниц
                        timeout=aiohttp.ClientTimeout(total=180, connect=30, sock_read=120),
                    )
                    logger.info("[DEBUG] _get_session: ClientSession created successfully")
                except Exception as e:
                    logger.error(f"[DEBUG] _get_session: ClientSession creation FAILED: {e}", exc_info=True)
                    raise
            else:
                logger.info("[DEBUG] _get_session: reusing existing session")

            self._requests_count += 1
            self._active_requests += 1
            logger.info(f"[DEBUG] _get_session: returning session (requests_count={self._requests_count}, active_requests={self._active_requests})")
            return self._session

    async def close(self):
        """Close all sessions and wait for proper cleanup."""
        # Close current session
        if self._session and not self._session.closed:
            await self._session.close()

        # Close all old sessions
        for old_session in self._old_sessions:
            try:
                if not old_session.closed:
                    await old_session.close()
            except Exception as e:
                logger.debug(f"Error closing old session: {e}")

        self._old_sessions.clear()

        # Wait for underlying connections to close
        await asyncio.sleep(0.25)

    async def check_proxy(self, proxy_url: str, timeout: float = 10, check_steam_api: bool = True) -> bool:
        """
        Check if proxy is working (basic + Steam API test).

        Args:
            proxy_url: Proxy URL to test
            timeout: Timeout in seconds
            check_steam_api: Also test Steam Market API (checks for 429 errors)

        Returns:
            True if proxy works and NOT rate limited, False otherwise
        """
        try:
            connector = ProxyConnector.from_url(proxy_url)
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as session:
                # Test 1: Basic connectivity
                async with session.get(f"{self.BASE_URL}/") as response:
                    if response.status != 200:
                        logger.debug(f"Proxy failed basic test: status {response.status}")
                        return False

                # Test 2: Steam Market API (check for rate limit)
                if check_steam_api:
                    # Try to get price for a common item
                    test_item = "AK-47 | Redline (Field-Tested)"
                    encoded_name = quote(test_item)
                    api_url = f"{self.BASE_URL}/priceoverview/"
                    params = {
                        'appid': self.APP_ID,
                        'market_hash_name': test_item,
                        'currency': STEAM_CURRENCY_CODES.get(self.currency, 5)
                    }

                    async with session.get(api_url, params=params) as response:
                        if response.status == 429:
                            logger.debug(f"Proxy has rate limit (429)")
                            return False
                        elif response.status != 200:
                            logger.debug(f"Proxy API test failed: status {response.status}")
                            return False

                return True

        except asyncio.TimeoutError:
            logger.debug(f"Proxy timeout")
            return False
        except Exception as e:
            logger.debug(f"Proxy check error: {e}")
            return False

    async def check_all_proxies(self) -> list[str]:
        """
        Check all proxies and return only working ones.

        Returns:
            List of working proxy URLs
        """
        if not self._proxy_list:
            return []

        working = []
        total = len(self._proxy_list)

        for i, proxy in enumerate(self._proxy_list, 1):
            proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
            logger.info(f"Checking proxy [{i}/{total}]: {proxy_display}...")

            if await self.check_proxy(proxy):
                logger.info(f"  OK")
                working.append(proxy)
            else:
                logger.warning(f"  FAILED")

        # Update proxy list to only working ones
        self._proxy_list = working
        logger.info(f"Working proxies: {len(working)}/{total}")

        return working

    async def get_price_overview(self, market_hash_name: str, max_retries: int = 3) -> PriceOverview:
        """
        Get price overview for an item (with automatic proxy rotation on 429).

        Args:
            market_hash_name: Steam market hash name (e.g., "AK-47 | Redline (Field-Tested)")
            max_retries: Maximum number of retries with proxy rotation (default: 3)

        Returns:
            PriceOverview with lowest_price, median_price, volume
        """
        currency_code = STEAM_CURRENCY_CODES[self.currency]

        url = f"{self.BASE_URL}/priceoverview/"
        params = {
            "appid": self.APP_ID,
            "currency": currency_code,
            "market_hash_name": market_hash_name,
        }

        for attempt in range(max_retries):
            session_acquired = False
            try:
                session = await self._get_session()
                session_acquired = True

                # Add timeout to prevent hanging
                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, params=params, timeout=timeout) as response:
                    if response.status == 429:
                        # Rate limit - rotate proxy and retry
                        await self._handle_rate_limit(response.status)
                        logger.warning(f"Rate limit (429) for price_overview, rotating proxy... (attempt {attempt + 1}/{max_retries})")
                        await self._rotate_proxy(reason="rate_limit")

                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)  # Small delay before retry
                            continue
                        else:
                            logger.error(f"Max retries reached for price_overview: {market_hash_name}")
                            return PriceOverview(success=False)

                    elif response.status != 200:
                        await self._handle_rate_limit(response.status)
                        logger.error(f"Steam API error: {response.status}")
                        return PriceOverview(success=False)

                    data = await response.json()

                    if not data.get("success"):
                        return PriceOverview(success=False)

                    return PriceOverview(
                        success=True,
                        lowest_price=parse_steam_price(data.get("lowest_price", "")),
                        median_price=parse_steam_price(data.get("median_price", "")),
                        volume=int(data.get("volume", "0").replace(",", "")) if data.get("volume") else None,
                        currency=self.currency,
                    )
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Timeout getting price overview (15s), rotating proxy... (attempt {attempt + 1})")
                # Rotate proxy on timeout
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="timeout")
                    await asyncio.sleep(2)
                    continue
            except Exception as e:
                logger.error(f"Failed to get price overview (attempt {attempt + 1}): {e}")
                # Rotate proxy on connection errors
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="connection_error")
                    await asyncio.sleep(2)
                    continue
            finally:
                if session_acquired:
                    self._request_complete()

        return PriceOverview(success=False)

    async def _get_item_nameid(self, market_hash_name: str, max_retries: int = 3) -> Optional[int]:
        """
        Get Steam's internal item_nameid by parsing the market listing page.

        This ID is required for the itemordershistogram endpoint.
        """
        if market_hash_name in self._item_nameid_cache:
            return self._item_nameid_cache[market_hash_name]

        self._last_nameid_error = None
        encoded_name = quote(market_hash_name, safe="")
        url = f"{self.BASE_URL}/listings/{self.APP_ID}/{encoded_name}"

        for attempt in range(max_retries):
            session_acquired = False
            try:
                logger.info(f"[nameid] Getting session for {market_hash_name} (attempt {attempt + 1})")
                session = await self._get_session()
                session_acquired = True
                logger.info(f"[nameid] Session acquired, making request")

                async with session.get(url, headers={"Cookie": "bMarketOptOut=1"}) as response:
                    logger.info(f"[nameid] Response received: status {response.status}")
                    if response.status == 429:
                        # Rate limit - rotate proxy and retry
                        await self._handle_rate_limit(response.status)
                        logger.warning(f"Rate limit (429) for nameid, rotating proxy... (attempt {attempt + 1}/{max_retries})")
                        await self._rotate_proxy(reason="rate_limit")

                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        else:
                            logger.error(f"Max retries reached for nameid: {market_hash_name}")
                            return None

                    elif response.status != 200:
                        logger.error(f"Failed to load market page: {response.status}")
                        self._last_nameid_error = f"listing_status_{response.status}"
                        return None

                    logger.info(f"[nameid] Reading HTML response...")
                    try:
                        # Читаем response по чанкам для избежания таймаута
                        # Это может помочь если Steam отправляет большой HTML медленно
                        content = b""
                        chunk_count = 0
                        async for chunk in response.content.iter_chunked(8192):  # 8KB чанки
                            content += chunk
                            chunk_count += 1
                            if chunk_count % 10 == 0:  # Логируем каждые 10 чанков
                                logger.info(f"[nameid] Read {len(content)} bytes so far...")

                        html = content.decode('utf-8', errors='ignore')
                        logger.info(f"[nameid] HTML read successfully ({len(html)} chars, {chunk_count} chunks)")
                    except Exception as e:
                        logger.error(f"[nameid] Failed to read HTML: {type(e).__name__}: {e}")
                        raise

                # Look for ItemActivityTicker.Start( nameid )
                # or Market_LoadOrderSpread( nameid )
                patterns = [
                    r"Market_LoadOrderSpread\(\s*(\d+)\s*\)",
                    r"ItemActivityTicker\.Start\(\s*(\d+)\s*\)",
                ]

                for pattern in patterns:
                    match = re.search(pattern, html)
                    if match:
                        nameid = int(match.group(1))
                        self._item_nameid_cache[market_hash_name] = nameid
                        return nameid

                logger.warning(f"Could not find item_nameid for: {market_hash_name}")
                self._last_nameid_error = self._detect_listing_page_problem(html)
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="nameid_not_found")
                    await asyncio.sleep(2)
                    continue
                return None

            except Exception as e:
                logger.error(f"Failed to get item_nameid (attempt {attempt + 1}): {e}")
                self._last_nameid_error = f"{type(e).__name__}: {str(e)[:80]}"
                # Rotate proxy on connection errors
                if attempt < max_retries - 1:
                    logger.info(f"Rotating proxy due to error, proxy list size: {len(self._proxy_list)}")
                    await self._rotate_proxy(reason=f"connection_error: {type(e).__name__}")
                    await asyncio.sleep(2)
                    continue
            finally:
                if session_acquired:
                    self._request_complete()

        return None

    def _detect_listing_page_problem(self, html: str) -> str:
        """Classify a listing page that does not contain Steam's item_nameid JS."""
        html_lower = html.lower()

        if "g-recaptcha" in html_lower or "captcha" in html_lower:
            return "steam_challenge_or_captcha"
        if "access denied" in html_lower:
            return "steam_access_denied"
        if "not available in your country" in html_lower:
            return "steam_region_blocked"
        if "exit market beta" in html_lower or "select a tab above to see buy order info" in html_lower:
            return "steam_market_beta_group_page"
        if "market_listing_item_name" not in html_lower:
            return f"not_listing_page_html_len_{len(html)}"
        if len(html) < 10000:
            return f"short_listing_html_len_{len(html)}"

        return "listing_missing_nameid_js"

    def _steam_currency_name(self, currency_code: int) -> Optional[str]:
        """Return a short currency name for Steam's numeric currency code."""
        for currency, code in STEAM_CURRENCY_CODES.items():
            if code == currency_code:
                return currency.value

        try:
            from src.currency_rates import CurrencyRatesProvider
            return CurrencyRatesProvider.STEAM_CURRENCIES.get(currency_code)
        except Exception:
            return None

    def _convert_orderbook_price(self, amount: Optional[int], source_currency: Optional[int]) -> Optional[float]:
        """Convert Steam orderbook cents to this client's configured currency units."""
        if amount is None:
            return None

        price = amount / 100
        target_currency_code = STEAM_CURRENCY_CODES[self.currency]

        if not source_currency or source_currency == target_currency_code:
            return price

        source_currency_name = self._steam_currency_name(source_currency)
        if not source_currency_name:
            logger.warning(
                f"Steam orderbook returned unknown currency code {source_currency}; "
                f"using raw price {price:.2f}"
            )
            return price

        try:
            from src.currency_rates import get_currency_provider
            provider = get_currency_provider()

            if self.currency == Currency.RUB:
                return provider.convert_to_rub(price, source_currency_name)

            price_rub = provider.convert_to_rub(price, source_currency_name)
            return provider.convert_rub_to_currency(price_rub, target_currency_code)
        except Exception as e:
            logger.warning(
                f"Failed to convert Steam orderbook currency {source_currency_name} "
                f"to {self.currency.value}: {e}. Using raw price {price:.2f}"
            )
            return price

    def _build_cumulative_graph(self, compact_orders: list, source_currency: Optional[int]) -> list:
        """
        Convert new Steam orderbook compact pairs into the old cumulative graph shape.

        New format: [price_cents, qty_at_price, price_cents, qty_at_price, ...]
        Old format used by count_orders_above_price:
        [price_cents_in_target_currency, cumulative_qty, description]
        """
        graph = []
        cumulative_qty = 0
        target_currency_code = STEAM_CURRENCY_CODES[self.currency]

        for idx in range(0, len(compact_orders) - 1, 2):
            try:
                source_price_cents = int(compact_orders[idx])
                qty_at_price = int(compact_orders[idx + 1])
            except (TypeError, ValueError):
                continue

            cumulative_qty += qty_at_price
            converted_price = self._convert_orderbook_price(source_price_cents, source_currency)
            if converted_price is None:
                continue

            target_price_cents = int(round(converted_price * 100))
            graph.append([
                target_price_cents,
                cumulative_qty,
                f"{converted_price:.2f} {self.currency.value}",
            ])

        if source_currency and source_currency != target_currency_code:
            logger.info(
                f"Converted Steam orderbook graph from currency code {source_currency} "
                f"to {self.currency.value}"
            )

        return graph

    async def _get_buy_orders_from_orderbook(self, market_hash_name: str, max_retries: int = 3) -> BuyOrderInfo:
        """
        Get buy order information from Steam's new Market beta orderbook endpoint.

        Steam's new SSR market no longer exposes Market_LoadOrderSpread/item_nameid
        on listing pages. The beta UI calls /market/orderbook?q=Load instead.
        """
        url = f"{self.BASE_URL}/orderbook"
        params = {
            "q": "Load",
            "qp": json.dumps([self.APP_ID, market_hash_name], ensure_ascii=False, separators=(",", ":")),
        }
        headers = {
            "Accept": "*/*",
            "X-Valve-Request-Type": "queryAction",
            "Referer": f"{self.BASE_URL}/listings/{self.APP_ID}/{quote(market_hash_name, safe='')}",
            # Steam проверяет fetch-контекст: orderbook дергается со страницы листинга (same-origin)
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }

        for attempt in range(max_retries):
            session_acquired = False
            try:
                session = await self._get_session()
                session_acquired = True

                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, params=params, headers=headers, timeout=timeout) as response:
                    if response.status == 429:
                        await self._handle_rate_limit(response.status)
                        logger.warning(
                            f"Rate limit (429) for orderbook, rotating proxy... "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        await self._rotate_proxy(reason="rate_limit")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        return BuyOrderInfo(success=False, error="orderbook_rate_limit")

                    if response.status != 200:
                        logger.error(f"Steam orderbook error: {response.status}")
                        return BuyOrderInfo(success=False, error=f"orderbook_status_{response.status}")

                    data = await response.json()
                    if not data.get("success") or not data.get("data"):
                        return BuyOrderInfo(success=False, error="orderbook_api_false")

                    orderbook = data["data"]
                    source_currency = orderbook.get("eCurrency")
                    target_currency_code = STEAM_CURRENCY_CODES[self.currency]
                    if source_currency and source_currency != target_currency_code:
                        logger.warning(
                            f"Steam orderbook returned currency code {source_currency}, "
                            f"expected {target_currency_code}; converting to {self.currency.value}"
                        )

                    buy_graph = self._build_cumulative_graph(
                        orderbook.get("rgCompactBuyOrders", []),
                        source_currency,
                    )

                    return BuyOrderInfo(
                        success=True,
                        highest_buy_order=self._convert_orderbook_price(orderbook.get("amtMaxBuyOrder"), source_currency),
                        lowest_sell_order=self._convert_orderbook_price(orderbook.get("amtMinSellOrder"), source_currency),
                        buy_order_count=int(orderbook.get("cBuyOrders") or 0),
                        sell_order_count=int(orderbook.get("cSellOrders") or 0),
                        buy_order_graph=buy_graph,
                    )

            except asyncio.TimeoutError:
                logger.error(f"Timeout getting Steam orderbook (15s), rotating proxy... (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="timeout")
                    await asyncio.sleep(2)
                    continue
                return BuyOrderInfo(success=False, error="orderbook_timeout")
            except Exception as e:
                logger.error(f"Failed to get Steam orderbook (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason=f"orderbook_error: {type(e).__name__}")
                    await asyncio.sleep(2)
                    continue
                return BuyOrderInfo(success=False, error=f"orderbook_{type(e).__name__}: {str(e)[:80]}")
            finally:
                if session_acquired:
                    self._request_complete()

        return BuyOrderInfo(success=False, error="orderbook_max_retries")

    async def get_buy_orders(self, market_hash_name: str, max_retries: int = 3) -> BuyOrderInfo:
        """
        Get buy order information for an item (with automatic proxy rotation on 429).

        Args:
            market_hash_name: Steam market hash name
            max_retries: Maximum number of retries with proxy rotation (default: 3)

        Returns:
            BuyOrderInfo with highest_buy_order and other order data
        """
        # Новый SSR-маркет Steam БОЛЬШЕ НЕ отдаёт item_nameid на странице листинга,
        # а её парсинг тяжёлый и жёстко ловит 429. Поэтому ОСНОВНОЙ путь — beta orderbook,
        # а старый nameid + itemordershistogram оставляем только как фоллбэк.
        orderbook_info = await self._get_buy_orders_from_orderbook(market_hash_name, max_retries=max_retries)
        if orderbook_info.success:
            return orderbook_info

        logger.info(
            f"Orderbook failed for {market_hash_name} ({orderbook_info.error}), "
            f"trying legacy nameid+histogram fallback"
        )
        item_nameid = await self._get_item_nameid(market_hash_name)
        if item_nameid is None:
            reason = self._last_nameid_error or "nameid_not_found"
            return BuyOrderInfo(
                success=False,
                error=f"orderbook_failed:{orderbook_info.error};nameid:{reason}"
            )

        currency_code = STEAM_CURRENCY_CODES[self.currency]

        url = f"{self.BASE_URL}/itemordershistogram"
        params = {
            "country": "RU",
            "language": "russian",
            "currency": currency_code,
            "item_nameid": item_nameid,
            "two_factor": 0,
        }

        for attempt in range(max_retries):
            session_acquired = False
            try:
                session = await self._get_session()
                session_acquired = True

                # Add timeout to prevent hanging
                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, params=params, timeout=timeout) as response:
                    if response.status == 429:
                        # Rate limit - rotate proxy and retry
                        await self._handle_rate_limit(response.status)
                        logger.warning(f"Rate limit (429) for buy_orders, rotating proxy... (attempt {attempt + 1}/{max_retries})")
                        await self._rotate_proxy(reason="rate_limit")

                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)  # Small delay before retry
                            continue
                        else:
                            logger.error(f"Max retries reached for buy_orders: {market_hash_name}")
                            return BuyOrderInfo(success=False, error="rate_limit")

                    elif response.status != 200:
                        logger.error(f"Orders histogram error: {response.status}")
                        return BuyOrderInfo(success=False, error=f"histogram_status_{response.status}")

                    data = await response.json()

                    if not data.get("success"):
                        return BuyOrderInfo(success=False, error="histogram_api_false")

                    # highest_buy_order and lowest_sell_order are in cents
                    highest_buy = data.get("highest_buy_order")
                    lowest_sell = data.get("lowest_sell_order")
                    buy_graph = data.get("buy_order_graph", [])

                    return BuyOrderInfo(
                        success=True,
                        highest_buy_order=int(highest_buy) / 100 if highest_buy else None,
                        lowest_sell_order=int(lowest_sell) / 100 if lowest_sell else None,
                        buy_order_count=len(buy_graph),
                        sell_order_count=len(data.get("sell_order_graph", [])),
                        buy_order_graph=buy_graph,
                    )

            except asyncio.TimeoutError:
                logger.error(f"⏱️ Timeout getting buy orders (15s), rotating proxy... (attempt {attempt + 1})")
                # Rotate proxy on timeout
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="timeout")
                    await asyncio.sleep(2)
                    continue
                return BuyOrderInfo(success=False, error="timeout")
            except Exception as e:
                logger.error(f"Failed to get buy orders (attempt {attempt + 1}): {e}")
                # Rotate proxy on connection errors
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="connection_error")
                    await asyncio.sleep(2)
                    continue
                return BuyOrderInfo(success=False, error=f"{type(e).__name__}: {str(e)[:80]}")
            finally:
                if session_acquired:
                    self._request_complete()

        return BuyOrderInfo(success=False, error="max_retries")

    async def get_price_history(self, market_hash_name: str, days: int = 7, max_retries: int = 3) -> PriceHistory:
        """
        Get price history from Steam listing page.

        Parses the var line1=[[date, price, volume], ...] data embedded in the page.
        Note: Prices are returned in USD (Steam's default for history graph).

        Args:
            market_hash_name: Steam market hash name
            days: Number of days of history to analyze (default 7 for recent data)
            max_retries: Maximum number of retries with proxy rotation (default: 3)

        Returns:
            PriceHistory with min, max, avg, median, and percentiles
        """
        from datetime import datetime, timedelta

        encoded_name = quote(market_hash_name, safe="")
        url = f"{self.BASE_URL}/listings/{self.APP_ID}/{encoded_name}"

        for attempt in range(max_retries):
            session_acquired = False
            try:
                session = await self._get_session()
                session_acquired = True

                # Add timeout to prevent hanging (30 seconds for large pages)
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 429:
                        # Rate limit - rotate proxy and retry
                        await self._handle_rate_limit(response.status)
                        logger.warning(f"Rate limit (429) for price_history, rotating proxy... (attempt {attempt + 1}/{max_retries})")
                        await self._rotate_proxy(reason="rate_limit")

                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)  # Small delay before retry
                            continue
                        else:
                            logger.error(f"Max retries reached for price_history: {market_hash_name}")
                            return PriceHistory(success=False)

                    elif response.status != 200:
                        logger.error(f"Failed to load market page for history: {response.status}")
                        return PriceHistory(success=False)

                    # Read response in chunks to avoid timeout
                    logger.info(f"[price_history] Reading HTML response for {market_hash_name}...")
                    try:
                        content = b""
                        chunk_count = 0
                        async for chunk in response.content.iter_chunked(8192):
                            content += chunk
                            chunk_count += 1
                        html = content.decode('utf-8', errors='ignore')
                        logger.info(f"[price_history] HTML read successfully ({len(html)} chars, {chunk_count} chunks)")
                    except Exception as e:
                        logger.error(f"[price_history] Failed to read HTML: {type(e).__name__}: {e}")
                        raise

                # Look for price history data: var line1=[[date, price, volume], ...]
                line1_match = re.search(r'var line1=(\[\[.*?\]\]);', html, re.DOTALL)

                if not line1_match:
                    logger.warning(f"No price history found for: {market_hash_name}")
                    return PriceHistory(success=False)

                data_str = line1_match.group(1)

                # Extract entries with dates: ["MMM DD YYYY HH: +0", price, "volume"]
                entries = re.findall(r'\["([A-Za-z]{3} \d{1,2} \d{4})[^"]*",(\d+\.?\d*),"\d+"', data_str)

                if not entries:
                    logger.warning(f"Could not parse price history for: {market_hash_name}")
                    return PriceHistory(success=False)

                # Filter to last N days
                cutoff_date = datetime.now() - timedelta(days=days)
                recent_prices = []

                for date_str, price_str in entries:
                    try:
                        # Parse date: "Jan 01 2024"
                        entry_date = datetime.strptime(date_str, "%b %d %Y")
                        if entry_date >= cutoff_date:
                            recent_prices.append(float(price_str))
                    except (ValueError, TypeError):
                        continue

                if not recent_prices:
                    # Fallback: use last 50 entries if date parsing failed
                    recent_prices = [float(p) for _, p in entries[-50:]]

                if not recent_prices:
                    return PriceHistory(success=False)

                # Calculate statistics
                sorted_prices = sorted(recent_prices)
                n = len(sorted_prices)

                min_price = sorted_prices[0]
                max_price = sorted_prices[-1]
                avg_price = sum(sorted_prices) / n
                median_price = sorted_prices[n // 2]

                # Percentiles (20th and 25th)
                percentile_20 = sorted_prices[int(n * 0.20)] if n >= 5 else min_price
                percentile_25 = sorted_prices[int(n * 0.25)] if n >= 4 else min_price

                return PriceHistory(
                    success=True,
                    min_price=min_price,
                    max_price=max_price,
                    avg_price=avg_price,
                    median_price=median_price,
                    percentile_20=percentile_20,
                    percentile_25=percentile_25,
                    total_sales=n,
                    days_analyzed=days,
                )

            except asyncio.TimeoutError:
                logger.error(f"⏱️ Timeout getting price history (30s), rotating proxy... (attempt {attempt + 1})")
                # Rotate proxy on timeout
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="timeout")
                    await asyncio.sleep(2)
                    continue
            except Exception as e:
                logger.error(f"Failed to get price history (attempt {attempt + 1}): {e}")
                # Rotate proxy on connection errors
                if attempt < max_retries - 1:
                    await self._rotate_proxy(reason="connection_error")
                    await asyncio.sleep(2)
                    continue
            finally:
                if session_acquired:
                    self._request_complete()

        return PriceHistory(success=False)

    async def get_full_market_info(self, market_hash_name: str) -> dict:
        """
        Get complete market information for an item.

        Returns dict with price_overview and buy_orders.
        """
        # Run both requests concurrently
        price_task = self.get_price_overview(market_hash_name)
        orders_task = self.get_buy_orders(market_hash_name)

        price_overview, buy_orders = await asyncio.gather(price_task, orders_task)

        return {
            "market_hash_name": market_hash_name,
            "price_overview": price_overview,
            "buy_orders": buy_orders,
        }


# Convenience function for testing
async def test_steam_api():
    """Test Steam Market API with a sample item."""
    api = SteamMarketAPI(currency=Currency.RUB)

    test_items = [
        "AK-47 | Redline (Field-Tested)",
        "AWP | Asiimov (Field-Tested)",
    ]

    try:
        for item in test_items:
            print(f"\n{'='*60}")
            print(f"Item: {item}")
            print("="*60)

            info = await api.get_full_market_info(item)

            po = info["price_overview"]
            print(f"\nPrice Overview:")
            print(f"  Lowest price: {po.lowest_price} {po.currency.value}")
            print(f"  Median price: {po.median_price} {po.currency.value}")
            print(f"  Volume (24h): {po.volume}")

            bo = info["buy_orders"]
            print(f"\nBuy Orders:")
            print(f"  Highest buy order: {bo.highest_buy_order} {api.currency.value}")
            print(f"  Lowest sell order: {bo.lowest_sell_order} {api.currency.value}")
            print(f"  Buy order levels: {bo.buy_order_count}")
            print(f"  Sell order levels: {bo.sell_order_count}")

            if po.median_price and bo.highest_buy_order:
                diff = ((po.median_price - bo.highest_buy_order) / po.median_price) * 100
                print(f"\n  Gap (median vs buy order): {diff:.2f}%")

            await asyncio.sleep(1)  # Rate limiting
    finally:
        await api.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_steam_api())
