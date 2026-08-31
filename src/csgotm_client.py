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
    MAX_RETRIES = 5  # Increased for 5xx error handling

    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        """
        Initialize client with API key and optional session (with proxy).

        Args:
            api_key: CSGO.TM API key (required)
            session: Optional requests session with proxy support
        """
        self.api_key = api_key
        self._last_request_time = 0.0

        # Логируем информацию о ключе для диагностики
        if api_key:
            # Для диагностики хватает первых 4 символов и длины: раньше в лог
            # уходило 12 символов из 31, а лог виден через веб-панель.
            logger.info(f"CSGO.TM client initialized with API key: {api_key[:4]}… (length: {len(api_key)})")
        else:
            logger.warning("CSGO.TM client initialized WITHOUT API key!")

        # Create session with browser-like headers if not provided
        if session:
            self._session = session
            # Add browser headers to existing session (используем helper для избежания дублирования)
            from src.session_helper import get_browser_headers
            csgo_tm_headers = get_browser_headers()
            csgo_tm_headers.update({
                'Referer': 'https://market.csgo.com/',
                'Origin': 'https://market.csgo.com',
            })
            self._session.headers.update(csgo_tm_headers)
        else:
            # Создаем новую сессию через helper (избегаем дублирования)
            from src.session_helper import create_session_with_proxy
            self._session = create_session_with_proxy(proxy_url=None, add_browser_headers=True)
            self._session.headers.update({
                'Referer': 'https://market.csgo.com/',
                'Origin': 'https://market.csgo.com',
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
        data: Optional[dict] = None,
        json_data: Optional[dict] = None
    ) -> dict:
        """
        Make API request with rate limiting and retries.

        Args:
            endpoint: API endpoint
            method: HTTP method
            params: Query parameters
            data: POST form data
            json_data: POST JSON data

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
                    # Use json parameter if json_data provided, otherwise use data for form-data
                    if json_data is not None:
                        response = self._session.post(url, params=params, json=json_data, timeout=60)
                    else:
                        response = self._session.post(url, params=params, data=data, timeout=60)

                response.raise_for_status()
                result = response.json()

                # Некоторые эндпоинты (например, bid-ask) не возвращают поле "success"
                # Для них проверяем наличие данных напрямую
                if endpoint in ["bid-ask"]:
                    # Проверяем что есть данные bid или ask
                    if "bid" in result or "ask" in result:
                        return result
                    # Если данных нет, это ошибка
                    error = result.get("error") or result.get("message") or "No data returned"
                    raise CsgoTmError(f"API error: {error}")

                if not result.get("success"):
                    # Check for error in different fields
                    error = result.get("error") or result.get("message") or result.get("error_message")
                    # Пустая строка тоже считается как "нет ошибки" - используем Unknown error
                    if not error or error == "":
                        error = "Unknown error"

                    # Ожидаемые/некритичные ошибки логируем как debug
                    expected_errors = ["nothing", "Bad KEY", "item_on_sale", "item_not_in_inventory", "Unknown error"]
                    if error in expected_errors:
                        logger.debug(f"API request to {endpoint}: {error}")
                    else:
                        logger.warning(f"API request to {endpoint} failed. Error: {error}")
                        logger.warning(f"Full API response: {result}")

                    raise CsgoTmError(f"API error: {error}")

                return result

            except requests.exceptions.RequestException as e:
                last_error = e
                # Check if it's a retriable error (5xx server errors)
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    logger.warning(f"Request failed (attempt {attempt + 1}): HTTP {status_code} - {e}")

                    # 5xx errors are server-side issues, always retry
                    if 500 <= status_code < 600:
                        if status_code == 520:
                            logger.warning("CSGO.TM returned 520 error (Cloudflare). This may be due to rate limiting or geo-blocking.")
                        else:
                            logger.warning(f"CSGO.TM server error ({status_code}). Retrying...")
                else:
                    logger.warning(f"Request failed (attempt {attempt + 1}): {e}")

                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff: 3s, 6s, 12s
                    wait_time = 3 * (2 ** attempt)
                    logger.info(f"Waiting {wait_time}s before retry...")
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

    def get_money(self) -> dict:
        """
        Get current balance and settlement funds on CSGO.TM.

        Returns:
            Dict with keys:
            - money: Current balance (in original currency units)
            - money_settlement: Funds in hold (in original currency units)
            - currency: Currency code (RUB, EUR, USD, etc.)
        """
        try:
            result = self._request("get-money")
            # API возвращает значения УЖЕ в основной валюте (рублях), а НЕ в копейках
            money = result.get("money", 0)
            money_settlement = result.get("money_settlement", 0)
            api_currency = result.get("currency", "RUB")

            # DEBUG: Логируем RAW значения из API
            logger.info(f"CSGO.TM API raw response: money={money}, settlement={money_settlement}, currency={api_currency}")

            # ВАЖНО: CSGO.TM всегда работает в рублях, независимо от валюты Steam аккаунта
            # API возвращает currency = валюта Steam аккаунта, но балансы всегда в RUB
            currency = "RUB"

            logger.info(f"CSGO.TM balance: {money:.2f} {currency}, settlement: {money_settlement:.2f} {currency} (API returned currency: {api_currency})")

            return {
                "money": money,
                "money_settlement": money_settlement,
                "currency": currency
            }
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
            error_msg = str(e)
            # Ожидаемые ошибки логируем как debug
            if "item_not_in_inventory" in error_msg or "item_on_sale" in error_msg:
                logger.debug(f"Cannot list item {item_id}: {error_msg}")
            else:
                logger.error(f"Failed to list item {item_id}: {error_msg}")
            return SellResult(success=False, message=error_msg)

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
            self._request("set-price", params={"item_id": item_id, "price": 0})
            logger.info(f"Removed item {item_id} from sale")
            return True
        except CsgoTmError as e:
            logger.error(f"Failed to remove from sale: {e}")
            return False

    def update_price(self, item_id: str, new_price: float, currency: str = "RUB") -> bool:
        """Update price for listed item."""
        try:
            price_cents = int(new_price * 100)
            result = self._request("set-price", params={
                "item_id": item_id,
                "price": price_cents,
                "cur": currency
            })
            # Раньше возвращали True всегда, если не было исключения — из-за этого отказ API
            # («success»: false) выглядел как успешное обновление цены.
            ok = bool((result or {}).get("success", False))
            if ok:
                logger.info(f"Updated price for {item_id}: {new_price:.2f} {currency}")
            else:
                logger.warning(
                    f"Price update rejected for {item_id} ({new_price:.2f} {currency}): {result}"
                )
            return ok
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

    def get_all_items(self) -> list[dict]:
        """
        Получить все предметы (детальная информация со статусами).

        Returns:
            List of items with full details:
            - item_id: ID предмета в системе CSGO.TM
            - assetid: ID предмета в инвентаре
            - market_hash_name: Название предмета
            - price: Цена (в рублях/долларах/евро)
            - currency: Валюта (RUB, USD, EUR)
            - status: Статус предмета:
                * 1 = выставлен на продажу
                * 2 = продан, нужно передать боту
                * 3 = ожидание передачи купленного предмета
                * 4 = можно забрать купленный предмет
            - position: Позиция в очереди продажи
            - source: Источник (STEAM или ALFASKIN)
            - left: Время на передачу предмета (для статуса 2)
            - settlement: Время до финального статуса после успешного трейда
        """
        try:
            result = self._request("items")
            # ВАЖНО: при пустом инвентаре CSGO.TM отдаёт {"items": null}, а не {"items": []}.
            # result.get("items", []) вернул бы None (ключ есть → дефолт не применяется),
            # и итерация ниже падала бы с 'NoneType' object is not iterable, роняя вызывающий код.
            items = (result or {}).get("items") or []

            # Сохраняем оригинальные цены (API возвращает в рублях)
            for item in items:
                price_raw = item.get("price", 0)
                # Сохраняем оригинальную цену
                item["price_raw"] = price_raw
                # Оставляем price как есть (уже в рублях)
                item["price"] = price_raw

            logger.info(f"Found {len(items)} items (all statuses)")
            return items

        except CsgoTmError as e:
            logger.error(f"Failed to get all items: {e}")
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
            Dict with min_price (top-1), average_price, offers_count
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
                    # When API returns list of items, get prices and find minimum (top-1)
                    prices = [item.get("price", 0) for item in data if isinstance(item, dict) and item.get("price")]
                    if not prices:
                        logger.warning(f"No valid prices in list for {market_hash_name}")
                        return None

                    # Sort to get actual top-1 (minimum price)
                    prices.sort()
                    min_price = prices[0] if prices else 0
                    avg_price = sum(prices) / len(prices) if prices else 0
                    offers_count = len(prices)

                    result = {
                        "min_price": min_price / 100.0,
                        "average_price": avg_price / 100.0,
                        "offers_count": offers_count,
                    }

                    logger.debug(f"get_item_price({market_hash_name}): top-1={result['min_price']:.0f} RUB, offers={offers_count}")
                    return result
                else:
                    logger.warning(f"Empty data list for {market_hash_name}")
                    return None

            # Handle case where API returns a single dict (legacy format)
            if isinstance(data, dict):
                # For dict format, ensure we have actual minimum price
                # If it has 'price' field (single item), use that as min_price
                if "price" in data:
                    return {
                        "min_price": data.get("price", 0) / 100.0,
                        "average_price": data.get("price", 0) / 100.0,
                        "offers_count": 1,
                    }
                else:
                    # If it has min_price field, use that
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

    def get_history(self, date: str = None, date_end: int = None) -> list[dict]:
        """
        Get history of purchases and sales.

        Args:
            date: Date in DD-MM-YYYY format or UNIX timestamp
            date_end: End date as UNIX timestamp

        Returns:
            List of history items with event='buy' or event='sell'
        """
        try:
            import time
            params = {}

            # Если дата не указана, берём последние 7 дней
            if not date:
                date = int(time.time()) - 7 * 24 * 60 * 60  # 7 дней назад
            params["date"] = date

            if date_end:
                params["date_end"] = date_end

            result = self._request("history", params=params)
            return result.get("data", [])
        except CsgoTmError as e:
            logger.debug(f"Failed to get history: {e}")
            return []

    def get_sold_items(self, days: int = 7) -> list[dict]:
        """
        Get recently sold items.

        Args:
            days: Number of days to look back (default 7)

        Returns:
            List of sold items with fields: item_id, market_hash_name, received, time, etc.
        """
        import time
        date = int(time.time()) - days * 24 * 60 * 60
        history = self.get_history(date=date)
        # Фильтруем только продажи (event='sell')
        return [item for item in history if item.get("event") == "sell"]

    # ============ Sales Management Methods ============

    def go_offline(self) -> bool:
        """
        Остановить продажи (уйти в оффлайн).

        Returns:
            True если успешно
        """
        try:
            result = self._request("go-offline")
            logger.info("CSGO.TM sales stopped (offline)")
            return result.get("success", False)
        except CsgoTmError as e:
            logger.error(f"Failed to go offline: {e}")
            return False

    def ping_online(self, access_token: str, proxy: Optional[str] = None) -> dict:
        """
        Включить продажи (необходимо отправлять раз в 3 минуты).

        Args:
            access_token: Steam access token (JWT)
            proxy: Опциональный прокси для запросов

        Returns:
            Dict с результатом:
            - success: bool
            - error: Optional[str]
        """
        try:
            # Build JSON data with access_token
            json_data = {
                "access_token": access_token
            }
            if proxy:
                json_data["proxy"] = proxy

            # v=2 parameter must be in URL params, not POST data
            params = {"v": "2"}

            logger.debug(f"Sending ping-new POST request with access_token (first 50 chars): {access_token[:50]}...")
            logger.debug(f"Ping-new request params: {params}")

            # Use POST request with v=2 in params and JSON data in body
            result = self._request("ping-new", method="POST", params=params, json_data=json_data)

            # Log the full response for debugging
            logger.info(f"CSGO.TM ping-new response: {result}")
            logger.info("CSGO.TM ping successful - sales online")
            return {"success": True}

        except CsgoTmError as e:
            error_msg = str(e)
            logger.error(f"Failed to ping online: {error_msg}")

            # Специальная обработка ошибок токена
            if "invalid_access_token" in error_msg.lower() or "bad token" in error_msg.lower():
                return {"success": False, "error": "invalid_access_token"}

            return {"success": False, "error": error_msg}

    def test_sell_status(self) -> dict:
        """
        Проверить возможность продажи.

        Returns:
            Dict со статусом:
            - user_token: Установлена ли трейд ссылка
            - trade_check: Пройдена ли проверка трейд офферов
            - site_online: Находитесь ли вы в онлайне (ping)
            - site_notmpban: Нет ли бана за не передачу вещей
            - steam_web_api_key: Установлен ли API ключ Steam
        """
        try:
            result = self._request("test")
            status = result.get("status", {})
            logger.info(f"CSGO.TM sell status: {status}")
            return status
        except CsgoTmError as e:
            logger.error(f"Failed to get sell status: {e}")
            return {}

    def update_inventory(self, lang: str = "ru") -> bool:
        """
        Обновить инвентарь на CSGO.TM.

        Args:
            lang: Язык инвентаря (ru, en)

        Returns:
            True если успешно
        """
        try:
            result = self._request("update-inventory", params={"lang": lang})
            logger.info(f"CSGO.TM inventory update requested (lang={lang})")
            return result.get("success", False)
        except CsgoTmError as e:
            logger.error(f"Failed to update inventory: {e}")
            return False

    def inventory_status(self) -> Optional[dict]:
        """
        Получить состояние кеша инвентаря Steam.

        Returns:
            Dict со статусом:
            - is_updating: bool - идет ли обновление кеша
            - last_time_update: int - время последнего обновления (timestamp)
            - last_time_success_update: int - время последнего успешного обновления
            - items: int - количество предметов в кеше
        """
        try:
            result = self._request("inventory-status")
            status = {
                "is_updating": result.get("is_updating", False),
                "last_time_update": result.get("last_time_update", 0),
                "last_time_success_update": result.get("last_time_success_update", 0),
                "items": result.get("items", 0),
            }
            logger.debug(f"CSGO.TM inventory status: {status}")
            return status
        except CsgoTmError as e:
            logger.error(f"Failed to get inventory status: {e}")
            return None

    def get_sellable_inventory(self, lang: str = "ru") -> list[dict]:
        """Предметы, доступные к выставлению ПРЯМО СЕЙЧАС (эндпоинт my-inventory).

        По документации: «Getting Steam inventory, only those items that you have not
        yet put up for sale». То есть возвращаются только НЕ выставленные предметы,
        которые реально в Steam-инвентаре. Поле tradable=1 означает, что предмет не на
        трейд-холде. Поле `id` — актуальный assetid для add-to-sale, market_price —
        рекомендованная цена.

        Это надёжный источник «что можно продать», в отличие от unlock_date в нашей БД.
        """
        try:
            result = self._request("my-inventory", params={"lang": lang})
            items = (result or {}).get("items") or []
            logger.info(f"my-inventory: {len(items)} предметов доступно к выставлению")
            return items
        except CsgoTmError as e:
            logger.error(f"Failed to get my-inventory: {e}")
            return []

    def find_inventory_asset_ids(self, market_hash_name: str) -> list[str]:
        """Найти актуальные assetid предмета в кэше инвентаря маркета по имени.

        Нужно потому, что assetid в Steam МЕНЯЕТСЯ при каждом перемещении предмета
        (трейд, возврат с продажи). Сохранённый в БД id быстро протухает, и add-to-sale
        отвечает item_not_recieved, хотя предмет в инвентаре есть — просто под другим id.

        Поле `id` из my-inventory — это и есть assetid для add-to-sale (по их документации).
        """
        try:
            result = self._request("my-inventory", params={"lang": "ru"})
            items = (result or {}).get("items") or []
            found = [
                str(i.get("id"))
                for i in items
                if i.get("id")
                and i.get("market_hash_name") == market_hash_name
                and i.get("tradable", 1)
            ]
            logger.debug(f"find_inventory_asset_ids({market_hash_name}): {found}")
            return found
        except CsgoTmError as e:
            logger.error(f"Failed to read my-inventory for {market_hash_name}: {e}")
            return []

    def add_to_sale_by_steam_id(
        self,
        steam_item_id: str,
        price: float,
        currency: str = "RUB"
    ) -> SellResult:
        """
        Выставить предмет на продажу по Steam ID.

        Args:
            steam_item_id: ID предмета в Steam (assetid)
            price: Цена в указанной валюте
            currency: Валюта (RUB, USD, EUR)

        Returns:
            SellResult с item_id если успешно
        """
        try:
            # Конвертируем цену в копейки/центы
            # 1 RUB = 100, 1 USD = 1000, 1 EUR = 1000
            if currency == "RUB":
                price_cents = int(price * 100)
            else:
                price_cents = int(price * 1000)

            result = self._request(
                "add-to-sale",
                params={
                    "id": steam_item_id,
                    "price": price_cents,
                    "cur": currency
                }
            )

            item_id = result.get("item_id")
            logger.info(f"Listed item {steam_item_id} for {price:.2f} {currency} (item_id: {item_id})")
            return SellResult(success=True, item_id=str(item_id) if item_id else None)

        except CsgoTmError as e:
            error_msg = str(e)
            # Ожидаемые ошибки логируем как debug
            if "item_not_in_inventory" in error_msg or "item_on_sale" in error_msg:
                logger.debug(f"Cannot list item {steam_item_id}: {error_msg}")
            else:
                logger.error(f"Failed to list item {steam_item_id}: {error_msg}")
            return SellResult(success=False, message=error_msg)

    def set_price_by_item_id(
        self,
        item_id: str,
        price: float,
        currency: str = "RUB"
    ) -> bool:
        """
        Установить новую цену для выставленного предмета.

        Args:
            item_id: ID предмета в системе CSGO.TM
            price: Новая цена (0 = снять с продажи)
            currency: Валюта (RUB, USD, EUR)

        Returns:
            True если успешно
        """
        try:
            # Конвертируем цену
            if currency == "RUB":
                price_cents = int(price * 100)
            else:
                price_cents = int(price * 1000)

            result = self._request(
                "set-price",
                params={
                    "item_id": item_id,
                    "price": price_cents,
                    "cur": currency
                }
            )

            if price == 0:
                logger.info(f"Removed item {item_id} from sale")
            else:
                logger.info(f"Updated price for item {item_id}: {price:.2f} {currency}")

            return result.get("success", False)

        except CsgoTmError as e:
            logger.error(f"Failed to set price for {item_id}: {e}")
            return False

    def get_trades_to_give(self) -> list[dict]:
        """
        Получить данные для создания p2p-офферов покупателям (проданные предметы).

        ВАЖНО: эндпоинт возвращает ключ "offers" (а не "trades" — из-за этого раньше
        всегда получалось 0). Каждый оффер содержит данные для создания трейда на Steam:
            - partner: steamid32 покупателя
            - token: токен его трейд-ссылки
            - tradeoffermessage: сообщение с hash (без него маркет не свяжет трейд)
            - hash: идентификатор сделки
            - items: [{appid, contextid, assetid, amount, price}]
        """
        try:
            result = self._request("trade-request-give-p2p-all")
            offers = (result or {}).get("offers") or []
            logger.info(f"Found {len(offers)} p2p offers to give")
            return offers
        except CsgoTmError as e:
            error_msg = str(e)
            # "nothing" - это нормально, просто нечего передавать
            if "nothing" in error_msg.lower():
                logger.debug("No p2p offers to give (API returned 'nothing')")
                return []
            logger.error(f"Failed to get trades to give: {e}")
            return []

    def trade_ready(self, trade_offer_id: str | int) -> bool:
        """
        Зарегистрировать у маркета созданный нами на Steam трейд-оффер.

        Без этого шага маркет не свяжет отправленный оффер со сделкой.
        """
        try:
            result = self._request("trade-ready", params={"tradeoffer": str(trade_offer_id)})
            ok = bool((result or {}).get("success", False))
            if ok:
                logger.info(f"Trade offer {trade_offer_id} registered on market")
            else:
                logger.warning(f"Market rejected trade-ready for {trade_offer_id}: {result}")
            return ok
        except CsgoTmError as e:
            logger.error(f"Failed to register trade offer {trade_offer_id}: {e}")
            return False

    def get_items_to_give(self) -> list[dict]:
        """
        Получить список предметов на отдачу (для P2P).

        Returns:
            List of items waiting to be traded
        """
        try:
            result = self._request("get-items-to-give")
            items = result.get("items", [])
            logger.info(f"Found {len(items)} items to give")
            return items
        except CsgoTmError as e:
            logger.error(f"Failed to get items to give: {e}")
            return []

    def get_sold_items_pending_trade(self) -> list[dict]:
        """
        Получить предметы со статусом 2 (проданы, нужно передать боту).

        Returns:
            List of sold items waiting to be traded to bot
        """
        try:
            all_items = self.get_all_items()
            # Фильтруем только статус 2
            sold_items = [item for item in all_items if item.get("status") == "2"]
            logger.info(f"Found {len(sold_items)} sold items pending trade (status=2)")
            return sold_items
        except Exception as e:
            logger.error(f"Failed to get sold items pending trade: {e}")
            return []

    def get_bid_ask(self, market_hash_name: str, phase: str = None) -> Optional[dict]:
        """
        Получить стакан заявок (bid-ask) для предмета.

        Args:
            market_hash_name: Название предмета на рынке
            phase: Фаза предмета (для ножей Doppler): phase1, phase2, phase3, phase4, sapphire, ruby, blackpearl

        Returns:
            Dict с bid и ask заявками:
            - bid: список заявок на покупку [{price, total}, ...]
            - ask: список предметов на продаже [{price, total}, ...]
            - currency: валюта
        """
        try:
            params = {"hash_name": market_hash_name}
            if phase:
                params["phase"] = phase

            result = self._request("bid-ask", params=params)

            # Парсим цены из строк в float
            bid_list = []
            for bid_item in result.get("bid", []):
                try:
                    bid_list.append({
                        "price": float(bid_item.get("price", 0)),
                        "total": int(bid_item.get("total", 0))
                    })
                except (ValueError, TypeError):
                    pass

            ask_list = []
            for ask_item in result.get("ask", []):
                try:
                    ask_list.append({
                        "price": float(ask_item.get("price", 0)),
                        "total": int(ask_item.get("total", 0))
                    })
                except (ValueError, TypeError):
                    pass

            return {
                "bid": bid_list,
                "ask": ask_list,
                "currency": result.get("currency", "RUB")
            }
        except CsgoTmError as e:
            logger.debug(f"Failed to get bid-ask for {market_hash_name}: {e}")
            return None


# Singleton instance removed - each account creates its own client
# csgotm_client = CsgoTmClient()
