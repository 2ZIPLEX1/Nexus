"""
Account Manager - управление несколькими аккаунтами Steam/CSGO.TM.

Поддерживает:
- Загрузку конфигурации из accounts.json
- Создание клиентов для каждого аккаунта
- Прокси для каждого аккаунта
- Лимиты и ограничения
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from src.logger import get_logger
# TODO: Миграция - старый клиент закомментирован
# from src.steam_client import SteamClient
from src.steam_client_aiosteampy import SteamClientAio, get_or_create_user_agent
from src.csgotm_client import CsgoTmClient
from src.proxy_manager import ProxyManager

logger = get_logger(__name__)


@dataclass
class ProxyConfig:
    """Конфигурация прокси для аккаунта."""
    enabled: bool = False
    url: str = ''


@dataclass
class AccountConfig:
    """Конфигурация одного аккаунта."""
    name: str
    enabled: bool
    currency: str = 'RUB'  # Валюта Steam (RUB, EUR, USD, ...)

    # Steam credentials
    steam_username: str = ''
    steam_password: str = ''
    steam_api_key: str = ''
    steam_shared_secret: str = ''
    steam_identity_secret: str = ''
    steamid: str = ''  # Steam ID64

    # CSGO.TM credentials
    csgotm_api_key: str = ''

    # Proxy configuration
    proxy: Optional[ProxyConfig] = None

    # Limits
    max_items: int = 10
    max_price_per_item: float = 1000.0
    total_budget: float = 5000.0


class Account:
    """
    Wrapper для одного аккаунта с клиентами Steam и CSGO.TM.
    """

    def __init__(self, config: AccountConfig):
        """
        Initialize account with config.

        Args:
            config: Account configuration
        """
        self.config = config
        self.name = config.name

        # Прокси для логина берётся ТОЛЬКО из accounts.json.
        # Пул proxies.txt — это прокси сканера, подмешивать их сюда нельзя:
        # аккаунт должен ходить в Steam с одного постоянного адреса. Раньше
        # пул подставлялся сюда как fallback, и логин уезжал на случайный
        # сканерный прокси — при мёртвом пуле это роняло вход целиком.
        proxy_to_use = None

        if self.config.proxy and self.config.proxy.enabled and self.config.proxy.url:
            proxy_to_use = self.config.proxy.url
            logger.info(f"[{self.name}] Using account-specific proxy: {proxy_to_use.split('@')[-1]}")
        else:
            logger.info(f"[{self.name}] No proxy configured, using direct connection")

        # Generate or load permanent User-Agent for this account
        # ВАЖНО: User-Agent должен быть постоянным для работы cookies!
        user_agent = get_or_create_user_agent(self.name, data_dir="data")
        logger.info(f"[{self.name}] User-Agent: {user_agent[:50]}...")

        # Create Steam client WITH proxy and User-Agent from the start
        # Each account uses its own proxy and permanent UA to prevent IP/cookie issues
        self.steam_client: Optional[SteamClientAio] = SteamClientAio(
            proxy=proxy_to_use,  # Use proxy for login
            user_agent=user_agent,  # Permanent UA for this account
            cookies_file=f"data/cookies/{self.name}_aio.json",  # Account-specific cookies
            account_name=self.name
        )

        # CSGO.TM client (will be created on login if API key is set)
        self.csgotm_client: Optional[CsgoTmClient] = None

        # Session для прокси
        self._session: Optional[requests.Session] = None

        # Кеш баланса (устанавливается при detect_currency_sync)
        self._last_wallet_balance: Optional[float] = None

        # Флаг первого ручного подтверждения Steam Mobile Guard (для аккаунтов без identity_secret)
        self.first_confirmation_done: bool = False

        logger.info(f"Account initialized: {self.name}")

    def reinitialize_steam_client(self):
        """
        Reinitialize Steam client in the current event loop.

        IMPORTANT: Call this before login_async() if running in a different
        event loop than where the Account was created (e.g., Flet GUI).
        This prevents "attached to a different loop" errors with aiohttp.
        """
        # Determine proxy to use (same logic as __init__): только accounts.json
        proxy_to_use = None
        if self.config.proxy and self.config.proxy.enabled and self.config.proxy.url:
            proxy_to_use = self.config.proxy.url

        # Get existing user agent
        user_agent = get_or_create_user_agent(self.name, data_dir="data")

        # Close old client if exists
        old_client = self.steam_client
        if old_client and old_client._client:
            try:
                # Mark as not logged in to prevent new requests
                old_client._logged_in = False

                # Try to close the session (sync way, non-blocking)
                # The session will be garbage collected eventually
                try:
                    if hasattr(old_client._client, '_connector') and old_client._client._connector:
                        # Force close without waiting
                        old_client._client._connector._closed = True
                except Exception as e:
                    logger.debug(f"[{self.name}] Could not force-close old connector: {e}")

            except Exception as e:
                logger.warning(f"[{self.name}] Error closing old steam client: {e}")

        # Create new client in current event loop
        self.steam_client = SteamClientAio(
            proxy=proxy_to_use,
            user_agent=user_agent,
            cookies_file=f"data/cookies/{self.name}_aio.json",
            account_name=self.name
        )

        logger.info(f"[{self.name}] Steam client reinitialized for current event loop")


    def login(self) -> bool:
        """
        Login to Steam and CSGO.TM.

        NOTE: This is the old synchronous login method.
        Steam client is now created in __init__() and login happens in login_async().

        Returns:
            True if steam client initialized
        """
        logger.info(f"[{self.name}] Initializing (Steam client created in __init__)...")

        try:
            # Steam client is already created in __init__
            # Login will happen in async context via login_async()
            logger.info(f"[{self.name}] Steam client ready (use login_async() to login)")

            # Create CSGO.TM client if API key is set
            if self.config.csgotm_api_key:
                # Закрываем старую сессию если есть
                if hasattr(self, '_session') and self._session:
                    try:
                        self._session.close()
                    except Exception as e:
                        logger.warning(f"[{self.account_name}] Failed to close old session: {e}")

                # Используем helper для создания сессии (избегаем дублирования)
                from src.session_helper import create_session_with_proxy
                proxy_to_use = None
                if self.config.proxy and self.config.proxy.enabled and self.config.proxy.url:
                    proxy_to_use = self.config.proxy.url
                    # Только host:port — в URL прокси есть user:pass, а лог уходит
                    # в файл, в journald и в веб-панель по GET /api/logs.
                    logger.info(f"[{self.account_name}] CSGO.TM will use proxy: {proxy_to_use.split('@')[-1]}")
                else:
                    logger.info(f"[{self.account_name}] CSGO.TM will use direct connection (no proxy)")

                self._session = create_session_with_proxy(proxy_url=proxy_to_use, add_browser_headers=True)

                self.csgotm_client = CsgoTmClient(
                    api_key=self.config.csgotm_api_key,
                    session=self._session
                )

                # Test CSGO.TM connection (non-blocking)
                try:
                    if self.csgotm_client.ping():
                        logger.info(f"[{self.name}] CSGO.TM connected")
                    else:
                        logger.warning(f"[{self.name}] CSGO.TM ping failed, but client is ready")
                except Exception as e:
                    logger.warning(f"[{self.name}] CSGO.TM ping error: {e}, but client is ready")
            else:
                logger.info(f"[{self.name}] No CSGO.TM API key configured")

            return True

        except Exception as e:
            logger.error(f"[{self.name}] Initialization error: {e}")
            return False

    def logout(self):
        """Logout from Steam (sync wrapper)."""
        if self.steam_client:
            # Steam client logout is async, need to run in event loop
            from src.async_helper import run_async_in_gui
            import asyncio

            async def _logout():
                await self.steam_client.logout()

            try:
                run_async_in_gui(_logout())
            except Exception as e:
                logger.warning(f"[{self.name}] Logout error (non-fatal): {e}")

            logger.info(f"[{self.name}] Logged out")

    def get_wallet_balance(self) -> float:
        """
        Get Steam wallet balance (sync version for compatibility).

        NOTE: Это синхронная обертка. Для async кода используйте:
        wallet = await self.steam_client.get_wallet_balance()

        Returns:
            Balance в основной валюте
        """
        return self.get_wallet_balance_sync()

    def get_csgotm_balance(self) -> float:
        """
        Get CSGO.TM balance (backward compatible - returns only money).

        For full info including settlement funds, use get_csgotm_money().
        """
        if not self.csgotm_client:
            return 0.0

        try:
            result = self.csgotm_client.get_money()
            return result.get("money", 0.0)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get CSGO.TM balance: {e}")
            return 0.0

    def get_csgotm_money(self) -> dict:
        """
        Get CSGO.TM balance and settlement funds.

        Returns:
            Dict with keys:
            - money: Current balance
            - money_settlement: Funds in hold
            - currency: Currency code
        """
        if not self.csgotm_client:
            return {"money": 0.0, "money_settlement": 0.0, "currency": "RUB"}

        try:
            return self.csgotm_client.get_money()
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get CSGO.TM money: {e}")
            return {"money": 0.0, "money_settlement": 0.0, "currency": "RUB"}

    def is_logged_in(self) -> bool:
        """Check if logged in to Steam."""
        return self.steam_client is not None and self.steam_client._logged_in

    async def login_async(self) -> bool:
        """
        Async login to Steam using aiosteampy.
        Используется для async контекста (auto_buyer, trading_bot).

        Returns:
            True если логин успешен
        """
        if not self.steam_client:
            logger.error(f"[{self.name}] Steam client not initialized")
            return False

        try:
            success = await self.steam_client.login(
                username=self.config.steam_username,
                password=self.config.steam_password,
                shared_secret=self.config.steam_shared_secret,
                identity_secret=self.config.steam_identity_secret,
                api_key=self.config.steam_api_key,
                steam_id=self.config.steamid
            )

            if success:
                logger.info(f"[{self.name}] ✅ Logged in to Steam (async)")

                # Получаем и сохраняем steamid если его нет
                if not self.config.steamid or self.config.steamid == "0":
                    steamid = self.steam_client.get_steamid()
                    if steamid:
                        self.config.steamid = steamid
                        logger.info(f"[{self.name}] Steam ID obtained: {steamid}")

                # Получаем баланс и кешируем для последующих вызовов
                try:
                    wallet = await self.steam_client.get_wallet_balance()
                    self._last_wallet_balance = wallet.balance
                    logger.debug(f"[{self.name}] Wallet balance cached: {wallet.balance}")
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to get wallet balance after login: {e}")

                # Инициализируем CSGO.TM клиент если есть API ключ
                if self.config.csgotm_api_key and not self.csgotm_client:
                    try:
                        # Используем helper для создания сессии (избегаем дублирования)
                        from src.session_helper import create_session_with_proxy
                        proxy_to_use = None
                        if self.config.proxy and self.config.proxy.enabled and self.config.proxy.url:
                            proxy_to_use = self.config.proxy.url
                            # Только host:port — см. комментарий выше.
                            logger.info(f"[{self.name}] CSGO.TM will use proxy: {proxy_to_use.split('@')[-1]}")
                        else:
                            logger.info(f"[{self.name}] CSGO.TM will use direct connection (no proxy)")

                        self._session = create_session_with_proxy(proxy_url=proxy_to_use, add_browser_headers=True)

                        self.csgotm_client = CsgoTmClient(
                            api_key=self.config.csgotm_api_key,
                            session=self._session
                        )

                        logger.info(f"[{self.name}] CSGO.TM client initialized")
                    except Exception as e:
                        logger.warning(f"[{self.name}] Failed to initialize CSGO.TM client: {e}")
            else:
                logger.error(f"[{self.name}] ❌ Failed to login to Steam")

            return success

        except Exception as e:
            logger.error(f"[{self.name}] Login error: {e}")
            return False

    def login_sync(self) -> bool:
        """
        Синхронная обертка для login_async().
        Используется в GUI для запуска async логина из sync контекста.

        Returns:
            True если логин успешен
        """
        from src.async_helper import run_async_in_gui

        try:
            result = run_async_in_gui(self.login_async())
            return result
        except Exception as e:
            logger.error(f"[{self.name}] Login sync error: {e}")
            return False

    def get_wallet_balance_sync(self) -> float:
        """
        Синхронная обертка для получения баланса.
        Сначала пробует использовать кешированное значение из detect_currency_sync.
        Используется в GUI для запуска async метода из sync контекста.

        Returns:
            Balance в основной валюте или 0.0 если ошибка
        """
        # Сначала пробуем использовать кеш
        if self._last_wallet_balance is not None:
            logger.debug(f"[{self.name}] Using cached wallet balance: {self._last_wallet_balance}")
            return self._last_wallet_balance

        from src.async_helper import run_async_in_gui

        if not self.steam_client:
            logger.warning(f"[{self.name}] Steam client not initialized")
            return 0.0

        try:
            wallet = run_async_in_gui(self.steam_client.get_wallet_balance(), timeout=60.0)
            self._last_wallet_balance = wallet.balance  # Кешируем
            return wallet.balance
        except RuntimeError as e:
            # Ошибка "attached to a different loop" - пытаемся вернуть кеш или 0
            if "different loop" in str(e):
                logger.warning(f"[{self.name}] Event loop mismatch, using cached or 0: {e}")
                return self._last_wallet_balance if self._last_wallet_balance is not None else 0.0
            logger.error(f"[{self.name}] Failed to get wallet balance (sync): {e}")
            return 0.0
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get wallet balance (sync): {e}")
            return 0.0

    def detect_currency_sync(self) -> Optional[str]:
        """
        Синхронная обертка для определения валюты аккаунта.
        Используется в GUI.

        Returns:
            Currency code (e.g., 'RUB', 'USD', 'EUR') or None if failed
        """
        from src.async_helper import run_async_in_gui

        if not self.steam_client or not self.is_logged_in():
            logger.error(f"[{self.name}] Cannot detect currency: not logged in")
            return None

        try:
            # Используем async метод get_wallet_balance
            wallet = run_async_in_gui(self.steam_client.get_wallet_balance(), timeout=60.0)

            # Кешируем баланс для последующего использования
            self._last_wallet_balance = wallet.balance
            logger.debug(f"[{self.name}] Cached balance: {wallet.balance}")

            # Маппинг стран на валюты
            currency_map = {
                'RU': 'RUB',
                'US': 'USD',
                'GB': 'GBP',
                'EU': 'EUR',
                'DE': 'EUR',
                'FR': 'EUR',
                'IT': 'EUR',
                'ES': 'EUR',
                'CN': 'CNY',
                'JP': 'JPY',
                'KR': 'KRW',
                'BR': 'BRL',
                'IN': 'INR',
                'TR': 'TRY',
                'UA': 'UAH',
                'BY': 'BYN',
                'KZ': 'KZT',
                'AR': 'ARS',
                'MX': 'MXN',
                'AU': 'AUD',
                'CA': 'CAD',
            }

            detected = currency_map.get(wallet.country, wallet.country)

            if detected and detected != self.config.currency:
                logger.info(f"[{self.name}] Currency detected: {detected} (was: {self.config.currency})")
                self.config.currency = detected
                return detected

            return self.config.currency

        except Exception as e:
            logger.error(f"[{self.name}] Currency detection failed: {e}")
            return None

    def sync_orders_sync(self) -> dict:
        """
        Синхронная обертка для синхронизации статусов ордеров с Steam.
        Используется в GUI.

        Returns:
            Dict with counts: {'cancelled': int, 'still_active': int}
        """
        from src.async_helper import run_async_in_gui

        if not self.steam_client or not self.is_logged_in():
            logger.error(f"[{self.name}] Cannot sync orders: not logged in")
            return {'cancelled': 0, 'still_active': 0}

        try:
            # Импортируем TradingBot для доступа к методу синхронизации
            from src.trading_bot import TradingBot

            # Создаем временный объект TradingBot
            bot = TradingBot(self)

            # Вызываем async метод через sync обертку
            result = run_async_in_gui(bot.sync_order_statuses(), timeout=60.0)

            logger.info(
                f"[{self.name}] Orders synced: {result['cancelled']} cancelled, "
                f"{result['still_active']} active"
            )

            return result
        except Exception as e:
            logger.error(f"[{self.name}] Failed to sync orders: {e}")
            import traceback
            traceback.print_exc()
            return {'cancelled': 0, 'still_active': 0}

    def detect_currency(self) -> Optional[str]:
        """
        Detect account currency from Steam wallet.

        Returns:
            Currency code (e.g., 'RUB', 'USD', 'EUR') or None if failed
        """
        if not self.steam_client or not self.is_logged_in():
            logger.error(f"[{self.name}] Cannot detect currency: not logged in")
            return None

        try:
            # NOTE: Removed 3-second delay - currency is already detected during prepare() at login
            # No need for additional delay, and proxy bypass is usually not required

            # Temporarily bypass proxy for currency detection to avoid rate limiting
            proxy_session = self.steam_client._session if hasattr(self.steam_client, '_session') else None

            if self.config.proxy and proxy_session:
                # Create clean session without proxy for wallet check
                import requests
                clean_session = requests.Session()

                # Copy essential cookies to new session (without proxy context)
                for cookie in proxy_session.cookies:
                    clean_session.cookies.set_cookie(cookie)

                self.steam_client._session = clean_session
                logger.info(f"[{self.name}] Using direct connection (bypassing proxy) for currency detection")

            wallet_info = self.steam_client.get_wallet_balance()

            # Restore proxy session
            if self.config.proxy and proxy_session:
                self.steam_client._session = proxy_session
                logger.debug(f"[{self.name}] Restored proxy session")

            if wallet_info and wallet_info.currency_code:
                detected_currency = wallet_info.currency_code

                # Проверяем надёжность определения
                is_reliable = wallet_info.balance > 0 or wallet_info.currency != 1

                if not is_reliable:
                    logger.warning(f"[{self.name}] ⚠️ Currency detection unreliable (balance=0, default USD)")
                    logger.info(f"[{self.name}] Detected: {detected_currency}, but keeping current: {self.config.currency}")
                    return self.config.currency  # Возвращаем текущую валюту

                logger.info(f"[{self.name}] 🔍 Detected currency: {detected_currency}")

                # Update config
                if self.config.currency != detected_currency:
                    old_currency = self.config.currency
                    self.config.currency = detected_currency
                    logger.info(f"[{self.name}] ✅ Currency updated: {old_currency} → {detected_currency}")

                return detected_currency
            else:
                logger.error(f"[{self.name}] Failed to get wallet info")
                return None
        except Exception as e:
            logger.error(f"[{self.name}] Error detecting currency: {e}")
            # Ensure proxy session is restored even on error
            if self.config.proxy and proxy_session:
                self.steam_client._session = proxy_session
            return None


def load_proxy_manager_from_file(
    proxy_file: str = 'proxies.txt',
    max_requests: int = 15,
    blacklist_duration: int = 30,
    cooldown: int = 60
) -> Optional[ProxyManager]:
    """
    Load ProxyManager from proxy file.

    Args:
        proxy_file: Path to proxy list file
        max_requests: Max requests per proxy before rotation
        blacklist_duration: Blacklist duration in minutes
        cooldown: Cooldown between proxy uses in seconds

    Returns:
        ProxyManager instance or None if no proxies
    """
    proxy_path = Path(proxy_file)
    if not proxy_path.exists():
        logger.debug(f"Proxy file not found: {proxy_file}")
        return None

    proxies = []
    try:
        with open(proxy_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue

                # Auto-add socks5:// if no protocol specified
                if '://' not in line:
                    line = f'socks5://{line}'

                proxies.append(line)

        if proxies:
            logger.info(f"Loaded {len(proxies)} proxies from {proxy_file}")
            return ProxyManager(
                proxies=proxies,
                max_requests_per_proxy=max_requests,
                blacklist_duration_minutes=blacklist_duration,
                cooldown_seconds=cooldown
            )
        else:
            logger.debug(f"No proxies found in {proxy_file}")
            return None

    except Exception as e:
        logger.error(f"Failed to load proxies: {e}")
        return None


class AccountManager:
    """
    Менеджер для управления несколькими аккаунтами.
    """

    def __init__(self, config_file: str = "accounts.json", proxy_file: str = 'proxies.txt'):
        """
        Initialize account manager.

        Args:
            config_file: Path to accounts configuration file
            proxy_file: Path to proxy list file (optional)
        """
        self.config_file = Path(config_file)
        self.accounts: list[Account] = []

        # Load proxy manager if available
        self.proxy_manager = load_proxy_manager_from_file(proxy_file)

        self._load_accounts()

    def _load_accounts(self):
        """Load accounts from configuration file."""
        if not self.config_file.exists():
            logger.warning(f"Config file not found: {self.config_file}")
            logger.info("Please create accounts.json based on accounts.example.json")
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                accounts_data = json.load(f)

            for acc_data in accounts_data:
                if not acc_data.get('enabled', True):
                    logger.info(f"Account disabled: {acc_data.get('name')}")
                    continue

                # Parse proxy configuration
                proxy_config = None
                if 'proxy' in acc_data:
                    proxy_data = acc_data['proxy']
                    # Support both old (string) and new (dict) format
                    if isinstance(proxy_data, str):
                        # Old format: "socks5://..."
                        proxy_config = ProxyConfig(enabled=True, url=proxy_data)
                    elif isinstance(proxy_data, dict):
                        # New format: {"enabled": true, "url": "..."}
                        proxy_config = ProxyConfig(
                            enabled=proxy_data.get('enabled', False),
                            url=proxy_data.get('url', '')
                        )

                config = AccountConfig(
                    name=acc_data['name'],
                    enabled=acc_data.get('enabled', True),
                    currency=acc_data.get('currency', 'RUB'),
                    steam_username=acc_data['steam']['username'],
                    steam_password=acc_data['steam']['password'],
                    steam_api_key=acc_data['steam']['api_key'],
                    steam_shared_secret=acc_data['steam']['shared_secret'],
                    steam_identity_secret=acc_data['steam']['identity_secret'],
                    steamid=acc_data['steam'].get('steamid', ''),
                    csgotm_api_key=acc_data['csgotm']['api_key'],
                    proxy=proxy_config,
                    max_items=acc_data.get('limits', {}).get('max_items', 10),
                    max_price_per_item=acc_data.get('limits', {}).get('max_price_per_item', 1000.0),
                    total_budget=acc_data.get('limits', {}).get('total_budget', 5000.0),
                )

                account = Account(config)
                self.accounts.append(account)

            logger.info(f"Loaded {len(self.accounts)} account(s)")

        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            raise

    def get_account(self, name: str) -> Optional[Account]:
        """Get account by name."""
        for account in self.accounts:
            if account.name == name:
                return account
        return None

    def get_all_accounts(self) -> list[Account]:
        """Get all accounts."""
        return self.accounts

    def get_enabled_accounts(self) -> list[Account]:
        """Get all enabled accounts."""
        return [acc for acc in self.accounts if acc.config.enabled]

    def login_all(self) -> dict[str, bool]:
        """
        Login to all enabled accounts.

        Returns:
            Dict of account_name: success status
        """
        results = {}

        for account in self.get_enabled_accounts():
            success = account.login()
            results[account.name] = success

        successful = sum(1 for success in results.values() if success)
        logger.info(f"Login complete: {successful}/{len(results)} accounts logged in")

        # Save updated config (e.g., Steam IDs that were auto-detected)
        self.save_config()

        return results

    def logout_all(self):
        """Logout from all accounts."""
        for account in self.accounts:
            account.logout()

    def login_all_sync(self) -> dict[str, bool]:
        """
        Синхронная версия параллельного логина для GUI.
        Логинит все аккаунты параллельно через async.

        Returns:
            Dict[account_name, success]
        """
        from src.async_helper import run_async_in_gui
        import asyncio

        async def _login_all():
            enabled = self.get_enabled_accounts()

            # Логируем начало параллельного логина
            logger.info(f"Starting parallel login for {len(enabled)} accounts...")

            # Создаем задачи с timeout для каждого аккаунта (60 секунд на логин)
            async def login_with_timeout(account):
                try:
                    logger.info(f"[{account.name}] Starting login...")
                    result = await asyncio.wait_for(account.login_async(), timeout=60.0)
                    if result:
                        logger.info(f"[{account.name}] ✅ Login successful")
                    else:
                        logger.warning(f"[{account.name}] ❌ Login failed")
                    return result
                except asyncio.TimeoutError:
                    logger.error(f"[{account.name}] ⏱️ Login timeout (60s)")
                    return False
                except Exception as e:
                    logger.error(f"[{account.name}] ❌ Login error: {e}")
                    return False

            login_tasks = [login_with_timeout(account) for account in enabled]
            results = await asyncio.gather(*login_tasks, return_exceptions=True)

            return {
                account.name: (result is True)
                for account, result in zip(enabled, results)
            }

        try:
            results = run_async_in_gui(_login_all())

            successful = sum(1 for success in results.values() if success)
            logger.info(f"Login complete (sync): {successful}/{len(results)} accounts logged in")

            # Save updated config
            self.save_config()

            return results

        except Exception as e:
            logger.error(f"Login all sync error: {e}")
            return {account.name: False for account in self.get_enabled_accounts()}

    def get_total_balance_sync(self) -> dict:
        """
        Синхронная версия получения общего баланса для GUI.
        Использует async запросы к Steam API.
        ВАЖНО: Конвертирует все балансы в RUB для правильного суммирования.

        Returns:
            Dict with steam_balance and csgotm_balance (оба в RUB)
        """
        from src.async_helper import run_async_in_gui
        from src.currency_converter import currency_converter
        import asyncio

        async def _get_balances():
            total_steam_rub = 0.0
            total_csgotm_rub = 0.0

            for account in self.get_enabled_accounts():
                if account.is_logged_in():
                    account_currency = getattr(account.config, 'currency', 'RUB')

                    # Async получение баланса Steam
                    try:
                        wallet = await account.steam_client.get_wallet_balance()
                        steam_balance = wallet.balance

                        # Конвертируем Steam баланс в RUB
                        if account_currency != 'RUB' and steam_balance > 0:
                            steam_balance_rub = currency_converter.convert_to_rub(steam_balance, account_currency)
                            logger.debug(f"[{account.name}] Steam: {steam_balance:.2f} {account_currency} = {steam_balance_rub:.2f} RUB")
                        else:
                            steam_balance_rub = steam_balance

                        total_steam_rub += steam_balance_rub
                    except Exception as e:
                        logger.error(f"[{account.name}] Failed to get Steam balance: {e}")

                    # CSGO.TM всегда в RUB
                    csgotm_balance = account.get_csgotm_balance()
                    total_csgotm_rub += csgotm_balance

            return {
                'steam_balance': total_steam_rub,
                'csgotm_balance': total_csgotm_rub,
                'total': total_steam_rub + total_csgotm_rub,
            }

        try:
            return run_async_in_gui(_get_balances())
        except Exception as e:
            logger.error(f"Get total balance sync error: {e}")
            return {
                'steam_balance': 0.0,
                'csgotm_balance': 0.0,
                'total': 0.0,
            }

    def get_total_balance(self) -> dict:
        """
        Get total balance across all accounts.

        Returns:
            Dict with steam_balance and csgotm_balance
        """
        steam_total = 0.0
        csgotm_total = 0.0

        for account in self.get_enabled_accounts():
            steam_total += account.get_wallet_balance()
            csgotm_total += account.get_csgotm_balance()

        return {
            'steam_balance': steam_total,
            'csgotm_balance': csgotm_total,
            'total': steam_total + csgotm_total,
        }

    def __len__(self) -> int:
        """Return number of accounts."""
        return len(self.accounts)

    def save_config(self):
        """Save updated account configurations to file with atomic write."""
        import os
        import tempfile
        import shutil

        try:
            # Load current config
            with open(self.config_file, 'r', encoding='utf-8') as f:
                accounts_data = json.load(f)

            # Update all accounts
            for account in self.accounts:
                for acc_data in accounts_data:
                    if acc_data['name'] == account.name:
                        # Ensure 'steam' key exists
                        if 'steam' not in acc_data:
                            acc_data['steam'] = {}

                        # Update Steam ID if changed
                        if account.config.steamid:
                            acc_data['steam']['steamid'] = account.config.steamid

                        # Update currency if changed
                        if account.config.currency:
                            acc_data['currency'] = account.config.currency
                        break

            # Create backup before saving
            config_file_str = str(self.config_file)
            backup_file = config_file_str + '.backup'
            if os.path.exists(config_file_str):
                shutil.copy2(config_file_str, backup_file)

            # Write to temporary file first (atomic write)
            temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(config_file_str), text=True)
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(accounts_data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                # Replace original file atomically
                shutil.move(temp_path, config_file_str)
                logger.debug("Saved accounts configuration")

            except Exception as e:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def __iter__(self):
        """Iterate over accounts."""
        return iter(self.accounts)


# Singleton instance (optional)
# account_manager = AccountManager()
