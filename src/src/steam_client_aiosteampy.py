"""
Асинхронный клиент для Steam на базе aiosteampy.
Замена для старого steam_client.py (steampy/ValvePython).

Основные возможности:
- Асинхронный API (async/await)
- Cookie persistence (быстрая повторная авторизация)
- Статичный user-agent для каждого аккаунта
- Поддержка прокси для каждой сессии
- Совместимость по интерфейсу с SteamClient
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
from urllib.parse import quote

import aiohttp
from aiosteampy import SteamClient as AioSteamClient
from aiosteampy.utils import get_jsonable_cookies, update_session_cookies
from aiosteampy.helpers import restore_from_cookies
from fake_useragent import UserAgent

from src.logger import get_logger

logger = get_logger(__name__)

# Steam CS2 App ID
CS2_APPID = 730


@dataclass
class WalletInfo:
    """Информация о кошельке Steam."""
    balance: float  # Баланс в основной валюте
    currency: int  # Код валюты (5 = RUB, 1 = USD, etc.)
    country: str  # Код страны
    balance_delayed: float = 0.0  # Отложенный баланс

    @property
    def balance_cents(self) -> int:
        """Баланс в центах (для совместимости)."""
        return int(self.balance * 100)


@dataclass
class BuyOrderResult:
    """Результат создания buy order."""
    success: bool
    order_id: Optional[str] = None
    error: Optional[str] = None
    market_hash_name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None


@dataclass
class InventoryItem:
    """Предмет из инвентаря."""
    assetid: str
    classid: str
    instanceid: str
    amount: int
    name: str
    market_hash_name: str
    market_name: str
    icon_url: str
    tradable: bool
    marketable: bool
    tradable_after: Optional[datetime] = None  # Когда предмет станет tradable


class SteamClientAioError(Exception):
    """Базовое исключение для Steam клиента."""
    pass


class SteamClientAio:
    """
    Асинхронный клиент для работы с Steam API через aiosteampy.

    Совместим по интерфейсу с текущим SteamClient для минимизации изменений в коде.
    """

    MARKET_URL = "https://steamcommunity.com/market"
    COMMUNITY_URL = "https://steamcommunity.com"

    def __init__(
        self,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        cookies_file: Optional[str] = None,
        account_name: Optional[str] = None
    ):
        """
        Инициализация клиента.

        Args:
            proxy: URL прокси (socks5://user:pass@host:port)
            user_agent: Статичный user-agent для сессии
            cookies_file: Путь к файлу с cookies
            account_name: Имя аккаунта (для логов)
        """
        self.proxy = proxy
        self.user_agent = user_agent or self._generate_user_agent()
        self.cookies_file = cookies_file or "steam_cookies_aio.json"
        self.account_name = account_name or "unknown"

        # aiosteampy клиент (создается при login)
        self._client: Optional[AioSteamClient] = None

        # Данные авторизации (сохраняются для повторного логина)
        self._credentials: Optional[Dict[str, str]] = None

        # Флаг авторизации
        self._logged_in = False

        logger.info(
            f"[{self.account_name}] SteamClientAio initialized | "
            f"Proxy: {bool(proxy)} | UA: {self.user_agent[:50]}..."
        )

    @staticmethod
    def _generate_user_agent() -> str:
        """Сгенерировать user-agent (Chrome)."""
        return UserAgent().chrome

    async def _save_cookies(self):
        """Сохранить cookies в файл для persistence."""
        if not self._client or not self._client.session:
            return

        try:
            cookies = get_jsonable_cookies(self._client.session)

            # Создаем директорию если нужно
            Path(self.cookies_file).parent.mkdir(parents=True, exist_ok=True)

            # Сохраняем cookies
            with open(self.cookies_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'cookies': cookies,
                    'user_agent': self.user_agent,
                    'saved_at': datetime.now().isoformat()
                }, f, indent=2)

            logger.debug(f"[{self.account_name}] Cookies saved to {self.cookies_file}")
        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to save cookies: {e}")

    async def _load_cookies(self) -> bool:
        """
        Загрузить cookies из файла и восстановить сессию.

        Returns:
            True если cookies загружены успешно
        """
        if not Path(self.cookies_file).exists():
            logger.debug(f"[{self.account_name}] No cookies file found")
            return False

        try:
            with open(self.cookies_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cookies = data.get('cookies', {})
            saved_ua = data.get('user_agent', '')

            # ВАЖНО: User-agent должен совпадать! Иначе cookies не будут работать
            if saved_ua != self.user_agent:
                logger.warning(
                    f"[{self.account_name}] User-agent mismatch! "
                    f"Cookies invalidated (UA changed)"
                )
                return False

            # Клиент должен быть уже создан в login()
            if not self._client:
                logger.error(f"[{self.account_name}] Client not initialized, cannot load cookies")
                return False

            # Восстанавливаем сессию из cookies
            await restore_from_cookies(cookies, self._client)

            logger.info(f"[{self.account_name}] [OK] Cookies loaded successfully")
            return True

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to load cookies: {e}")
            return False

    async def _ensure_client_in_current_loop(self):
        """
        Убедиться что клиент создан в текущем event loop.
        Пересоздать если нужно.
        """
        import asyncio

        if not self._client:
            return  # Клиент не создан, создастся при логине

        try:
            # Проверяем что session привязана к текущему loop
            current_loop = asyncio.get_running_loop()

            if hasattr(self._client, 'session') and self._client.session:
                session_loop = getattr(self._client.session, '_loop', None)

                if session_loop and session_loop != current_loop:
                    logger.info(
                        f"[{self.account_name}] Detected loop change, "
                        f"recreating client for new event loop"
                    )

                    # Закрываем старую session
                    try:
                        await self._client.session.close()
                    except:
                        pass

                    # Пересоздаем клиент если есть credentials
                    if self._credentials:
                        await self._create_client(self._credentials)
                        # Пытаемся загрузить cookies
                        await self._load_cookies()
        except Exception as e:
            logger.debug(f"[{self.account_name}] Error checking event loop: {e}")

    async def _create_client(self, credentials: Dict[str, str]):
        """
        Создать aiosteampy клиент с настройками.

        Args:
            credentials: Словарь с данными авторизации
        """
        # ВАЖНО: steam_id должен быть правильным для работы с токенами!
        # Если steam_id=0, токены не будут работать
        steam_id = credentials.get('steam_id')

        # Конвертируем в int (может прийти как строка из JSON)
        if steam_id:
            steam_id = int(steam_id)
        else:
            steam_id = 0

        if steam_id == 0:
            logger.warning(
                f"[{self.account_name}] No valid steam_id provided! "
                "This may cause authentication issues. Please add steamid to accounts.json"
            )

        # aiosteampy принимает первые 5 параметров позиционно, остальные - как keyword
        self._client = AioSteamClient(
            steam_id,  # Positional: Steam ID64 (REQUIRED for cookie auth!)
            credentials['username'],  # Positional
            credentials['password'],  # Positional
            credentials['shared_secret'],  # Positional
            credentials.get('identity_secret', ''),  # Positional (optional)
            api_key=credentials.get('api_key', '') or None,  # Keyword-only
            proxy=self.proxy,  # Keyword-only: socks5://user:pass@host:port
            user_agent=self.user_agent  # Keyword-only
        )

        logger.info(
            f"[{self.account_name}] SteamClient created | "
            f"Steam ID: {steam_id} | Proxy: {bool(self.proxy)}"
        )

    async def login(
        self,
        username: str,
        password: str,
        shared_secret: str,
        identity_secret: str,
        api_key: str,
        steam_id: Optional[int] = None,
        cookie_file: Optional[str] = None
    ) -> bool:
        """
        Войти в Steam (с cookies или через логин).

        Args:
            username: Steam логин
            password: Steam пароль
            shared_secret: Shared secret для 2FA
            identity_secret: Identity secret для подтверждений
            api_key: Steam Web API key
            steam_id: Steam ID64 (опционально, можно 0 для первого логина)
            cookie_file: Путь к файлу cookies (опционально)

        Returns:
            True если авторизация успешна
        """
        logger.info(f"[{self.account_name}] Logging in to Steam...")

        # Сохраняем credentials для повторного логина
        self._credentials = {
            'username': username,
            'password': password,
            'shared_secret': shared_secret,
            'identity_secret': identity_secret,
            'api_key': api_key,
            'steam_id': steam_id or 0
        }

        # Обновляем путь к cookies если передан
        if cookie_file:
            self.cookies_file = cookie_file

        try:
            # ВАЖНО: Всегда пересоздаем клиент в текущем event loop
            # Это предотвращает "attached to a different loop" ошибки
            if self._client:
                # Закрываем старый клиент
                try:
                    if hasattr(self._client, 'session') and self._client.session:
                        await self._client.session.close()
                except Exception as e:
                    logger.debug(f"[{self.account_name}] Error closing old client: {e}")
                self._client = None

            # Создаем новый клиент с credentials в текущем event loop
            await self._create_client(self._credentials)

            # Пытаемся загрузить cookies
            cookies_loaded = await self._load_cookies()

            if cookies_loaded:
                # Проверяем что сессия жива (простая проверка без prepare)
                try:
                    # Используем is_session_alive() для быстрой проверки сессии
                    # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
                    is_alive = await asyncio.create_task(self._client.is_session_alive())
                    if is_alive:
                        # ВАЖНО: Вызываем prepare() для загрузки wallet info (currency) и других данных
                        prepare_success = False
                        try:
                            await asyncio.create_task(self._client.prepare())
                            logger.info(f"[{self.account_name}] Prepare completed successfully")
                            prepare_success = True
                        except Exception as e:
                            logger.warning(
                                f"[{self.account_name}] Prepare failed: {e}. "
                                "Will attempt full login to ensure proper initialization."
                            )
                            # Не устанавливаем _logged_in, продолжим с полным логином
                            prepare_success = False

                        # Только если prepare успешен, считаем что залогинены
                        if prepare_success:
                            self._logged_in = True
                            logger.info(f"[{self.account_name}] [OK] Logged in via cookies")
                            return True
                        else:
                            # Prepare упал, нужен полный логин
                            logger.info(f"[{self.account_name}] Falling back to full login...")
                    else:
                        logger.warning(f"[{self.account_name}] Session not alive, need fresh login")
                except Exception as e:
                    logger.warning(f"[{self.account_name}] Cookie check failed: {e}")
                    # Cookies не работают, продолжаем с полным логином

            # Cookies не сработали - логинимся через API
            logger.info(f"[{self.account_name}] Logging in via Steam API...")

            # Выполняем логин (aiosteampy автоматически использует shared_secret для 2FA)
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            await asyncio.create_task(self._client.login())

            # ВАЖНО: Вызываем prepare() для загрузки wallet info и других данных
            # Делаем это опциональным, т.к. может требоваться доп. настройка аккаунта
            try:
                await asyncio.create_task(self._client.prepare())
                logger.info(f"[{self.account_name}] Prepare completed successfully")
            except Exception as e:
                logger.warning(
                    f"[{self.account_name}] Prepare failed (non-fatal): {e}. "
                    "Some features may not work until account is properly configured."
                )

            # Сохраняем cookies после успешного логина
            await self._save_cookies()

            self._logged_in = True
            logger.info(f"[{self.account_name}] [OK] Logged in successfully")
            return True

        except Exception as e:
            logger.error(f"[{self.account_name}] Login failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self._logged_in = False
            return False

    async def logout(self):
        """Выйти из Steam и закрыть сессию."""
        if self._client:
            try:
                # Сохраняем cookies перед выходом
                await self._save_cookies()

                # Закрываем aiohttp сессию
                if hasattr(self._client, 'session') and self._client.session:
                    await self._client.session.close()

                logger.info(f"[{self.account_name}] Logged out")
            except Exception as e:
                logger.error(f"[{self.account_name}] Logout error: {e}")
            finally:
                self._logged_in = False

    def is_logged_in(self) -> bool:
        """Проверить статус авторизации."""
        return self._logged_in

    async def get_wallet_balance(self) -> WalletInfo:
        """
        Получить информацию о балансе кошелька.

        Returns:
            WalletInfo с данными о балансе

        Raises:
            SteamClientAioError: Если не авторизован или ошибка API
        """
        if not self._logged_in or not self._client:
            raise SteamClientAioError("Not logged in")

        try:
            # Получаем информацию о кошельке через aiosteampy
            # get_wallet_info() возвращает TypedDict (обычный dict)
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            wallet_data = await asyncio.create_task(self._client.get_wallet_info())

            # Проверяем что данные получены
            if wallet_data is None:
                logger.error(f"[{self.account_name}] get_wallet_info() returned None")
                raise SteamClientAioError("Wallet data is None - not logged in or session expired")

            # Логируем полученные данные для отладки
            logger.debug(f"[{self.account_name}] Wallet data keys: {wallet_data.keys() if isinstance(wallet_data, dict) else 'NOT A DICT'}")

            # Проверяем наличие необходимых ключей
            required_keys = ['wallet_balance', 'wallet_currency', 'wallet_country']
            missing_keys = [key for key in required_keys if key not in wallet_data]
            if missing_keys:
                logger.error(f"[{self.account_name}] Missing wallet data keys: {missing_keys}")
                logger.error(f"[{self.account_name}] Available keys: {list(wallet_data.keys())}")
                raise SteamClientAioError(f"Missing wallet data keys: {missing_keys}")

            # wallet_balance и wallet_delayed_balance возвращаются как строки в центах
            balance = int(wallet_data['wallet_balance']) / 100.0
            balance_delayed = int(wallet_data.get('wallet_delayed_balance', 0)) / 100.0

            return WalletInfo(
                balance=balance,
                currency=wallet_data['wallet_currency'],  # int (currency code)
                country=wallet_data['wallet_country'],     # str (country code)
                balance_delayed=balance_delayed
            )

        except SteamClientAioError:
            raise
        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get wallet balance: {e}")
            import traceback
            logger.error(f"[{self.account_name}] Traceback: {traceback.format_exc()}")
            raise SteamClientAioError(f"Failed to get wallet balance: {e}")

    async def create_buy_order(
        self,
        market_hash_name: str,
        price: float,
        quantity: int = 1,
        currency: int = 5,
        appid: int = CS2_APPID
    ) -> BuyOrderResult:
        """
        Создать buy order на маркете.

        Args:
            market_hash_name: Market hash name предмета
            price: Цена в РУБЛЯХ (всегда RUB, независимо от валюты кошелька)
            quantity: Количество
            currency: Код валюты (ИГНОРИРУЕТСЯ - используется валюта кошелька)
            appid: ID приложения (730 = CS2)

        Returns:
            BuyOrderResult с результатом создания ордера
        """
        if not self._logged_in or not self._client:
            return BuyOrderResult(success=False, error="Not logged in")

        try:
            # ВАЖНО: Получаем валюту кошелька аккаунта
            # Steam НЕ ПОЗВОЛЯЕТ создавать ордера в валюте отличной от валюты кошелька!
            wallet_currency = 5  # Default RUB
            try:
                wallet = await self.get_wallet_balance()
                wallet_currency = wallet.currency
                logger.debug(f"[{self.account_name}] Wallet currency: {wallet_currency}")
            except Exception as e:
                logger.warning(f"[{self.account_name}] Could not get wallet currency, using RUB: {e}")

            # Конвертируем цену из рублей в валюту кошелька если нужно
            price_in_wallet_currency = price
            if wallet_currency != 5:  # Если НЕ RUB
                # Используем актуальные курсы валют (обновляются раз в 24 часа)
                from src.currency_rates import convert_rub_to_currency
                price_in_wallet_currency = convert_rub_to_currency(price, wallet_currency)

                # Устанавливаем минимум 0.01 для любой валюты
                # Steam не принимает ордера меньше 1 цента/копейки
                if price_in_wallet_currency < 0.01:
                    logger.warning(
                        f"[{self.account_name}] Price too low after conversion: {price:.2f} RUB -> "
                        f"{price_in_wallet_currency:.4f} (currency {wallet_currency}), setting minimum 0.01"
                    )
                    price_in_wallet_currency = 0.01
                else:
                    logger.info(
                        f"[{self.account_name}] Converting price: {price:.2f} RUB -> "
                        f"{price_in_wallet_currency:.2f} (currency {wallet_currency})"
                    )

            logger.info(
                f"[{self.account_name}] Creating buy order: {market_hash_name} @ "
                f"{price_in_wallet_currency:.2f} (wallet currency {wallet_currency})"
            )

            # Конвертируем цену в центы, минимум 1 цент
            price_in_cents = max(1, int(price_in_wallet_currency * 100))

            # Создаем App объект для CS:GO/CS2
            from aiosteampy.constants import App
            app = App(appid)

            # Создаем buy order через aiosteampy
            # place_buy_order возвращает buy_order_id (int) если fetch=False
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            order_id = await asyncio.create_task(self._client.place_buy_order(
                obj=market_hash_name,  # market hash name
                app=app,  # App enum
                price=price_in_cents,  # цена в центах
                quantity=quantity,  # количество
                fetch=False  # возвращаем только ID
            ))

            logger.info(
                f"[{self.account_name}] Buy order created successfully: "
                f"order_id={order_id}"
            )

            return BuyOrderResult(
                success=True,
                order_id=order_id,
                market_hash_name=market_hash_name,
                price=price,
                quantity=quantity
            )

        except Exception as e:
            error_msg = str(e)

            # Специальная обработка дублирующегося ордера (DUPLICATE_REQUEST)
            if 'DUPLICATE_REQUEST' in error_msg or 'already have an active buy order' in error_msg:
                logger.warning(f"[{self.account_name}] Order already exists for this item: {market_hash_name}")
                return BuyOrderResult(success=False, error="DUPLICATE_ORDER", market_hash_name=market_hash_name)

            # Специальная обработка rate limiting (429)
            if '429' in error_msg:
                logger.warning(f"[{self.account_name}] Rate limited by Steam (429) - need to slow down requests")
                return BuyOrderResult(success=False, error="Rate limited by Steam (429) - too many requests")

            logger.error(f"[{self.account_name}] Failed to create buy order: {e}; {type(e).__name__}")
            return BuyOrderResult(success=False, error=error_msg)

    async def cancel_buy_order(self, order_id: str) -> bool:
        """
        Отменить buy order.

        Args:
            order_id: ID ордера

        Returns:
            True если ордер отменен успешно
        """
        if not self._logged_in or not self._client:
            return False

        try:
            logger.info(f"[{self.account_name}] Cancelling buy order: {order_id}")

            # Конвертируем order_id в int если нужно
            order_id_int = int(order_id)

            # Отменяем buy order через aiosteampy
            # cancel_buy_order принимает int или BuyOrder объект
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            await asyncio.create_task(self._client.cancel_buy_order(order=order_id_int))

            logger.info(f"[{self.account_name}] Buy order cancelled successfully: {order_id}")
            return True

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to cancel buy order: {e}")
            return False

    async def get_active_buy_orders(self) -> List[Dict[str, Any]]:
        """
        Получить все активные buy ордера.

        Returns:
            Список активных buy ордеров с полями:
            - order_id: ID ордера
            - market_hash_name: Название предмета
            - price: Цена в основной валюте
            - quantity: Количество
            - quantity_remaining: Сколько осталось купить
        """
        if not self._logged_in or not self._client:
            logger.warning(f"[{self.account_name}] Cannot get orders: not logged in")
            return []

        try:
            # Убедимся что клиент в правильном event loop
            await self._ensure_client_in_current_loop()

            logger.info(f"[{self.account_name}] Fetching active buy orders from Steam...")

            # Получаем листинги через aiosteampy
            # get_my_listings возвращает: (active_listings, to_confirm, buy_orders, total_count)
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            active_listings, to_confirm, buy_orders, total_count = await asyncio.create_task(
                self._client.get_my_listings(count=100)  # максимум за запрос
            )

            logger.info(
                f"[{self.account_name}] Found {len(buy_orders)} active buy orders in Steam"
            )

            # Конвертируем BuyOrder объекты в словари
            result = []
            for order in buy_orders:
                # BuyOrder это dataclass с полями: id, item_description, price, quantity, quantity_remaining
                desc = order.item_description if hasattr(order, 'item_description') else None
                market_name = desc.market_hash_name if desc and hasattr(desc, 'market_hash_name') else 'Unknown'
                result.append({
                    'order_id': str(order.id),
                    'market_hash_name': market_name,
                    'price': order.price / 100.0,  # цена в центах -> основная валюта
                    'quantity': order.quantity,
                    'quantity_remaining': order.quantity_remaining,
                })

            return result

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get active buy orders: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def get_market_history(self, count: int = 100) -> Dict[str, Any]:
        """
        Получить историю маркета.

        Args:
            count: Количество записей

        Returns:
            Dict с историей маркета
        """
        if not self._logged_in or not self._client:
            return {'success': False, 'error': 'Not logged in'}

        try:
            logger.info(f"[{self.account_name}] Fetching market history (count={count})")

            # Получаем историю рынка через aiosteampy
            # Возвращает tuple[list[MarketHistoryEvent], total_count]
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            events, total_count = await asyncio.create_task(self._client.get_my_market_history(
                start=0,
                count=min(count, 100)  # Steam не принимает > 100
            ))

            # Конвертируем события в простые словари для совместимости
            history_items = []
            for event in events:
                listing = event.listing
                # Получаем цену (может быть None)
                price = 0.0
                if hasattr(listing, 'price') and listing.price is not None:
                    price = listing.price / 100.0

                # Получаем название предмета
                item_name = ''
                if hasattr(listing, 'item') and listing.item:
                    item_name = getattr(listing.item, 'name', '')

                history_items.append({
                    'time': event.time_event.isoformat(),
                    'type': event.type.name if hasattr(event.type, 'name') else str(event.type),
                    'market_hash_name': item_name,
                    'price': price,
                    'quantity': getattr(listing, 'quantity', 1),
                })

            logger.info(
                f"[{self.account_name}] Market history fetched: "
                f"{len(history_items)}/{total_count} events"
            )

            return {
                'success': True,
                'events': history_items,
                'total_count': total_count
            }

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get market history: {e}")
            return {'success': False, 'error': str(e)}

    async def get_inventory(self, appid: int = CS2_APPID) -> List[InventoryItem]:
        """
        Получить инвентарь.

        Args:
            appid: ID приложения (730 = CS2)

        Returns:
            Список предметов из инвентаря
        """
        if not self._logged_in or not self._client:
            return []

        try:
            # Убедимся что клиент в правильном event loop
            await self._ensure_client_in_current_loop()

            logger.info(f"[{self.account_name}] Fetching inventory (appid={appid})")

            # Создаем AppContext для CS:GO/CS2
            from aiosteampy.constants import AppContext
            app_context = AppContext(appid, 2)  # context_id=2 для основного инвентаря

            # Получаем инвентарь через aiosteampy
            # Возвращает tuple[list[EconItem], total_count, last_assetid]
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            items, total_count, last_assetid = await asyncio.create_task(self._client.get_inventory(
                app_context=app_context,
                count=2000  # максимум за запрос
            ))

            logger.info(
                f"[{self.account_name}] Inventory fetched: {len(items)} items"
            )

            # Конвертируем EconItem в наш InventoryItem
            inventory_items = []
            for item in items:
                # EconItem это dataclass с полями: asset_id, description (ItemDescription), amount, tradable_after
                desc = item.description if item.description else None
                inventory_items.append(
                    InventoryItem(
                        assetid=str(item.asset_id),
                        classid=str(desc.class_id) if desc else '',
                        instanceid=str(desc.instance_id) if desc else '',
                        amount=item.amount,
                        name=desc.name if desc else '',
                        market_hash_name=desc.market_hash_name if desc else '',
                        market_name=desc.market_name if desc else '',
                        icon_url=desc.icon_url if desc else '',
                        tradable=desc.tradable if desc else False,
                        marketable=desc.marketable if desc else False,
                        tradable_after=item.tradable_after  # Реальная дата разблокировки из Steam
                    )
                )

            return inventory_items

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get inventory: {e}")
            return []

    async def fetch_user_inventory(self, steam_id: str, appid: int = CS2_APPID) -> List[InventoryItem]:
        """
        Получить публичный инвентарь пользователя по Steam ID.

        Создает временный клиент для получения публичного инвентаря.
        Работает без авторизации если профиль публичный.

        Args:
            steam_id: Steam ID64 пользователя
            appid: ID приложения (730 = CS2)

        Returns:
            Список предметов из инвентаря
        """
        try:
            logger.info(f"[{self.account_name}] Fetching public inventory for {steam_id} (appid={appid})")

            # Создаем временный клиент в текущем event loop
            from aiosteampy import SteamClient as AioSteamClient
            from aiosteampy.constants import AppContext

            # Создаем клиента с прокси если есть
            temp_client = AioSteamClient(
                proxy=self.proxy,
                user_agent=self.user_agent
            )

            try:
                # Создаем AppContext для CS:GO/CS2
                app_context = AppContext(appid, 2)  # context_id=2 для основного инвентаря

                # Получаем публичный инвентарь
                items, total_count = await temp_client.get_user_inventory(
                    steam_id=int(steam_id),
                    app_context=app_context,
                    count=2000
                )

                logger.info(
                    f"[{self.account_name}] Public inventory fetched: {len(items)} items (total: {total_count})"
                )

                # Конвертируем EconItem в наш InventoryItem
                inventory_items = []
                for item in items:
                    desc = item.description if item.description else None
                    inventory_items.append(
                        InventoryItem(
                            assetid=str(item.asset_id),
                            classid=str(desc.class_id) if desc else '',
                            instanceid=str(desc.instance_id) if desc else '',
                            amount=item.amount,
                            name=desc.name if desc else '',
                            market_hash_name=desc.market_hash_name if desc else '',
                            market_name=desc.market_name if desc else '',
                            icon_url=desc.icon_url if desc else '',
                            tradable=desc.tradable if desc else False,
                            marketable=desc.marketable if desc else False,
                            tradable_after=item.tradable_after  # Реальная дата разблокировки из Steam
                        )
                    )

                return inventory_items

            finally:
                # Закрываем временную сессию
                await temp_client.close()

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to fetch public inventory for {steam_id}: {e}")
            import traceback
            logger.error(f"[{self.account_name}] Traceback: {traceback.format_exc()}")
            return []

    async def get_my_market_orders(self) -> List[Dict[str, Any]]:
        """
        Получить список активных buy orders.

        Returns:
            Список активных buy orders с информацией о цене и количестве
        """
        if not self._logged_in or not self._client:
            return []

        try:
            logger.info(f"[{self.account_name}] Fetching active buy orders")

            # get_my_listings возвращает: (active_listings, to_confirm, buy_orders, total_count)
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            _, _, buy_orders, _ = await asyncio.create_task(self._client.get_my_listings(
                start=0,
                count=100
            ))

            logger.info(f"[{self.account_name}] Found {len(buy_orders)} active buy orders")

            # Конвертируем BuyOrder в простые словари
            orders_list = []
            for order in buy_orders:
                orders_list.append({
                    'type': 'buy',  # Тип ордера
                    'order_id': str(order.id),
                    'market_hash_name': order.item_description.market_hash_name if order.item_description else '',
                    'price': order.price / 100.0,  # Из центов в основную валюту
                    'quantity': order.quantity,
                    'quantity_remaining': order.quantity_remaining,
                })

            return orders_list

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get buy orders: {e}")
            return []

    async def get_market_price(
        self,
        market_hash_name: str,
        appid: int = CS2_APPID
    ) -> Optional[Dict[str, Any]]:
        """
        Получить текущую цену предмета на рынке.

        Args:
            market_hash_name: Market hash name предмета
            appid: ID приложения (730 = CS2)

        Returns:
            Dict с данными о ценах (lowest_price, median_price, volume) или None
        """
        if not self._logged_in or not self._client:
            return None

        try:
            logger.info(f"[{self.account_name}] Fetching price for: {market_hash_name}")

            # Создаем App объект
            from aiosteampy.constants import App
            app = App(appid)

            # Получаем price overview
            # ВАЖНО: Всегда запрашиваем в рублях (currency=5) для совместимости с CSGO.TM
            # Независимо от валюты кошелька аккаунта (EUR, USD и т.д.)
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            price_overview = await asyncio.create_task(self._client.fetch_price_overview(
                obj=market_hash_name,
                app=app,
                params={'currency': 5}  # 5 = RUB
            ))

            # price_overview это TypedDict с полями:
            # success, lowest_price, volume, median_price
            if not price_overview or not price_overview.get('success'):
                logger.warning(f"[{self.account_name}] No price data for {market_hash_name}")
                return None

            # Парсим цены (они приходят как строки с валютой, например "850,50 pуб.")
            lowest_price_str = price_overview.get('lowest_price', '0')
            median_price_str = price_overview.get('median_price', '0')

            # Простой парсинг: берем только цифры и точки/запятые
            import re
            lowest_price = 0.0
            median_price = 0.0

            if lowest_price_str:
                # Извлекаем число из строки типа "850,50 pуб."
                match = re.search(r'([\d\s]+[,.]?\d*)', lowest_price_str.replace(' ', ''))
                if match:
                    price_str = match.group(1).replace(',', '.')
                    lowest_price = float(price_str)

            if median_price_str:
                match = re.search(r'([\d\s]+[,.]?\d*)', median_price_str.replace(' ', ''))
                if match:
                    price_str = match.group(1).replace(',', '.')
                    median_price = float(price_str)

            result = {
                'success': True,
                'lowest_price': lowest_price,
                'median_price': median_price,
                'volume': int(price_overview.get('volume', '0').replace(',', '')),
            }

            logger.info(
                f"[{self.account_name}] Price for {market_hash_name}: "
                f"lowest={lowest_price:.2f}, median={median_price:.2f}, volume={result['volume']}"
            )

            return result

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get market price: {e}")
            return None

    async def get_market_histogram(
        self,
        market_hash_name: str,
        item_nameid: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Получить histogram (buy/sell orders) для предмета через priceoverview API.

        Args:
            market_hash_name: Market hash name предмета
            item_nameid: Item nameid (опционально, не используется)

        Returns:
            Dict с данными о ценах:
            - highest_buy_order: float - максимальная цена покупки
            - lowest_sell_order: float - минимальная цена продажи
            - volume: str - объем торгов
        """
        if not self._logged_in or not self._client:
            return None

        try:
            # Используем Steam Market API для получения текущих цен
            url = "https://steamcommunity.com/market/priceoverview/"
            params = {
                'appid': 730,  # CS:GO
                'market_hash_name': market_hash_name,
                'currency': 5,  # RUB
            }

            # Используем сессию клиента aiosteampy (с прокси и правильными настройками)
            if not self._client or not hasattr(self._client, 'session'):
                logger.error(f"[{self.account_name}] Client session not available")
                return None

            session = self._client.session
            async with session.get(url, params=params) as response:
                logger.info(f"[{self.account_name}] Market API response status: {response.status}")

                if response.status != 200:
                    logger.warning(f"[{self.account_name}] Failed to get market price for {market_hash_name}: HTTP {response.status}")
                    return None

                data = await response.json()
                logger.info(f"[{self.account_name}] Market API response: {data}")

                if not data.get('success'):
                    logger.warning(f"[{self.account_name}] No market data for {market_hash_name}: {data}")
                    return None

                # Парсим цены (формат: "123,45 руб." или "1 234,56 руб.")
                def parse_price(price_str: str) -> float:
                    if not price_str:
                        return 0.0
                    # Убираем валюту и пробелы, заменяем запятую на точку
                    price_str = price_str.replace('руб.', '').replace('₽', '').replace(' ', '').replace(',', '.')
                    try:
                        return float(price_str)
                    except ValueError:
                        logger.warning(f"Failed to parse price string: '{price_str}'")
                        return 0.0

                lowest_price = parse_price(data.get('lowest_price', ''))
                median_price = parse_price(data.get('median_price', ''))

                # Формируем ответ в формате histogram
                result = {
                    'highest_buy_order': lowest_price * 0.95 if lowest_price > 0 else 0.0,  # Примерная цена buy order
                    'lowest_sell_order': lowest_price if lowest_price > 0 else 0.0,
                    'median_price': median_price,
                    'volume': data.get('volume', '0'),
                }

                logger.debug(f"[{self.account_name}] Market data for {market_hash_name}: buy={result['highest_buy_order']:.2f}, sell={result['lowest_sell_order']:.2f}")
                return result

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get market histogram for {market_hash_name}: {e}")
            return None

    def get_steamid(self) -> Optional[str]:
        """
        Получить Steam ID64 текущего аккаунта (синхронный метод).

        Returns:
            Steam ID64 или None
        """
        if not self._logged_in or not self._client:
            return None

        try:
            if not self._client:
                return None

            # Получаем steam_id из клиента
            steam_id = getattr(self._client, 'steam_id', None)
            if steam_id and steam_id != 0:
                return str(steam_id)

            return None

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get steamid: {e}")
            return None

    async def get_access_token(self) -> Optional[str]:
        """
        Получить access token Steam для CSGO.TM ping-new.

        Использует метод /pointssummary/ajaxgetasyncconfig
        который возвращает webapi_token с скоупом "web:community".

        Returns:
            Access token строка или None если не удалось получить
        """
        if not self._logged_in or not self._client:
            logger.warning(f"[{self.account_name}] Cannot get access token: not logged in")
            return None

        try:
            url = "https://steamcommunity.com/pointssummary/ajaxgetasyncconfig"

            # Используем сессию клиента aiosteampy
            if not self._client or not hasattr(self._client, 'session'):
                logger.error(f"[{self.account_name}] Client session not available")
                return None

            session = self._client.session

            # Используем timeout для избежания ошибки "Timeout context manager should be used inside a task"
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=30)

            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    logger.error(
                        f"[{self.account_name}] Failed to get access token: HTTP {response.status}"
                    )
                    return None

                data = await response.json()

                if not data.get('success'):
                    logger.error(
                        f"[{self.account_name}] Access token request failed: {data}"
                    )
                    return None

                token = data.get('data', {}).get('webapi_token')

                if token:
                    logger.info(
                        f"[{self.account_name}] Access token obtained successfully "
                        f"(token length: {len(token)})"
                    )
                    return token
                else:
                    logger.error(
                        f"[{self.account_name}] No webapi_token in response: {data}"
                    )
                    return None

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get access token: {e}")
            import traceback
            logger.debug(f"[{self.account_name}] Traceback: {traceback.format_exc()}")
            return None

    async def accept_trade_offer(self, trade_offer_id: str) -> bool:
        """
        Принять трейд оффер.

        Args:
            trade_offer_id: ID трейд оффера

        Returns:
            True если успешно принят
        """
        if not self._logged_in or not self._client:
            logger.warning(f"[{self.account_name}] Cannot accept trade: not logged in")
            return False

        try:
            logger.info(f"[{self.account_name}] Accepting trade offer: {trade_offer_id}")

            # Используем aiosteampy для принятия трейда
            # accept_trade_offer принимает trade_id
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            await asyncio.create_task(self._client.accept_trade_offer(int(trade_offer_id)))

            logger.info(f"[{self.account_name}] Trade offer {trade_offer_id} accepted")
            return True

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to accept trade offer {trade_offer_id}: {e}")
            return False

    async def get_trade_offers(self, get_sent: bool = False, get_received: bool = True) -> List[Dict[str, Any]]:
        """
        Получить список активных трейд офферов.

        Args:
            get_sent: Включить отправленные офферы
            get_received: Включить полученные офферы

        Returns:
            Список трейд офферов
        """
        if not self._logged_in or not self._client:
            logger.warning(f"[{self.account_name}] Cannot get trade offers: not logged in")
            return []

        try:
            logger.info(f"[{self.account_name}] Fetching trade offers...")

            # Используем aiosteampy
            # get_trade_offers возвращает tuple[list[TradeOffer], list[TradeOffer]]
            # Оборачиваем в create_task чтобы aiohttp timeout работал корректно
            sent_offers, received_offers = await asyncio.create_task(self._client.get_trade_offers(
                sent=get_sent,
                received=get_received,
                active_only=True
            ))

            offers = []

            for offer in received_offers:
                offers.append({
                    'trade_offer_id': str(offer.id),
                    'partner_steam_id': str(offer.partner_id) if hasattr(offer, 'partner_id') else '',
                    'message': getattr(offer, 'message', ''),
                    'state': offer.state.name if hasattr(offer.state, 'name') else str(offer.state),
                    'is_our_offer': False,
                    'items_to_give': len(offer.items_to_give) if hasattr(offer, 'items_to_give') else 0,
                    'items_to_receive': len(offer.items_to_receive) if hasattr(offer, 'items_to_receive') else 0,
                })

            if get_sent:
                for offer in sent_offers:
                    offers.append({
                        'trade_offer_id': str(offer.id),
                        'partner_steam_id': str(offer.partner_id) if hasattr(offer, 'partner_id') else '',
                        'message': getattr(offer, 'message', ''),
                        'state': offer.state.name if hasattr(offer.state, 'name') else str(offer.state),
                        'is_our_offer': True,
                        'items_to_give': len(offer.items_to_give) if hasattr(offer, 'items_to_give') else 0,
                        'items_to_receive': len(offer.items_to_receive) if hasattr(offer, 'items_to_receive') else 0,
                    })

            logger.info(f"[{self.account_name}] Found {len(offers)} active trade offers")
            return offers

        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get trade offers: {e}")
            return []

    async def close(self):
        """Закрыть клиент и сохранить состояние."""
        await self.logout()

    async def __aenter__(self):
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()


# Helper function для создания user-agent для аккаунта
def get_or_create_user_agent(account_name: str, data_dir: str = "data") -> str:
    """
    Получить или создать постоянный user-agent для аккаунта.

    ВАЖНО: User-agent должен быть постоянным!
    При изменении UA cookies сбрасываются.

    Args:
        account_name: Имя аккаунта
        data_dir: Директория для хранения данных

    Returns:
        User-agent string
    """
    ua_dir = Path(data_dir) / "user_agents"
    ua_dir.mkdir(parents=True, exist_ok=True)

    ua_file = ua_dir / f"{account_name}.txt"

    # Если файл существует - читаем из него
    if ua_file.exists():
        ua = ua_file.read_text(encoding='utf-8').strip()
        logger.debug(f"Loaded existing UA for {account_name}")
        return ua

    # Генерируем новый UA
    ua = UserAgent().chrome
    ua_file.write_text(ua, encoding='utf-8')
    logger.info(f"Generated new UA for {account_name}: {ua[:50]}...")

    return ua


# Асинхронная версия для совместимости
async def test_connection():
    """Тест подключения к Steam."""
    async with SteamClientAio(account_name="test") as client:
        success = await client.login(
            username="test",
            password="test",
            shared_secret="test",
            identity_secret="test",
            api_key="test"
        )
        print(f"Login: {success}")


if __name__ == '__main__':
    # Тест
    asyncio.run(test_connection())
