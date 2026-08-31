"""
CSGO.TM Sales Service - управление автоматическими продажами.

Функционал:
- Ping онлайн каждые 3 минуты (поддержание статуса продавца)
- Выставление предметов на продажу после окончания холда
- Автоматическое подтверждение трейдов при продаже
- Обновление инвентаря на CSGO.TM
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any, Callable

from src.logger import get_logger
from src.csgotm_client import CsgoTmClient
from flet_gui.state.app_state import AppState

logger = get_logger(__name__)


class SalesStatus(Enum):
    """Статус сервиса продаж."""
    STOPPED = "stopped"
    STARTING = "starting"
    ONLINE = "online"
    ERROR = "error"
    OFFLINE = "offline"


@dataclass
class SalesStats:
    """Статистика продаж."""
    items_listed: int = 0
    items_sold: int = 0
    trades_confirmed: int = 0
    total_revenue: float = 0.0
    last_ping_time: Optional[datetime] = None
    last_error: Optional[str] = None


@dataclass
class AccountSalesState:
    """Состояние продаж для одного аккаунта."""
    account_name: str
    status: SalesStatus = SalesStatus.STOPPED
    access_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    stats: SalesStats = field(default_factory=SalesStats)
    csgotm_client: Optional[CsgoTmClient] = None
    sell_status: Dict[str, bool] = field(default_factory=dict)


class TmSalesService:
    """
    Сервис для управления продажами на CSGO.TM.

    Основные функции:
    1. Ping-онлайн каждые 3 минуты для поддержания статуса продавца
    2. Автоматическое выставление предметов после холда
    3. Подтверждение трейдов при продаже
    """

    PING_INTERVAL = 180  # 3 минуты в секундах
    TOKEN_REFRESH_INTERVAL = 23 * 60 * 60  # Обновлять токен каждые 23 часа (срок жизни 24ч)
    HOLD_CHECK_INTERVAL = 300  # Проверять холд каждые 5 минут
    TRADE_CHECK_INTERVAL = 60  # Проверять трейды каждую минуту
    SOLD_CHECK_INTERVAL = 120  # Проверять продажи каждые 2 минуты
    CANCELLED_TRADE_CHECK_INTERVAL = 180  # Проверять отменённые трейды каждые 3 минуты
    PRICE_CHECK_INTERVAL = 600  # Проверять актуальность цен каждые 10 минут
    MAX_LIST_MISSES = 3  # После стольких промахов подряд считаем предмет оттрейженным (traded_away)
    INVENTORY_SETTLE_SEC = 15  # Пауза после обновления кэша инвентаря TM (док: 10-20 сек)
    INVENTORY_UPDATE_MAX_WAIT = 180  # Инвентарь на 400-800 предметов не успевал за 60с

    # Ошибки add-to-sale, которые лечатся обновлением кэша инвентаря (не финальные).
    # Формулировки — из документации market.csgo.com (item_not_recieved — их опечатка).
    RETRYABLE_LIST_ERRORS = (
        "item_not_in_inventory",
        "item_not_recieved",
        "inventory_not_loaded",
        "no_description_found",
    )

    def __init__(self, state: AppState, account_service=None, db_service=None, telegram_bot=None):
        """
        Инициализация сервиса.

        Args:
            state: Глобальное состояние приложения
            account_service: Сервис аккаунтов (для доступа к Steam клиентам)
            db_service: Сервис БД (для работы с инвентарем)
            telegram_bot: Telegram бот для уведомлений (опционально)
        """
        self.state = state
        self.account_service = account_service
        self.db_service = db_service
        self.telegram_bot = telegram_bot

        # Состояние для каждого аккаунта
        self._account_states: Dict[str, AccountSalesState] = {}

        # Флаги работы
        self._running = False
        self._ping_task: Optional[asyncio.Task] = None
        self._hold_check_task: Optional[asyncio.Task] = None
        self._trade_check_task: Optional[asyncio.Task] = None
        self._sold_check_task: Optional[asyncio.Task] = None
        self._cancelled_trade_check_task: Optional[asyncio.Task] = None
        self._price_check_task: Optional[asyncio.Task] = None

        # Отслеживание проданных предметов (чтобы не дублировать записи)
        self._processed_sales: set = set()

        # Отслеживание проданных предметов для проверки статуса трейда через 10 минут
        # Формат: {(account_name, item_id): {'sold_time': timestamp, 'tm_item_id': str, 'market_hash_name': str}}
        self._pending_trade_checks: Dict[tuple, dict] = {}

        # Счётчик промахов при листинге: сколько раз подряд holding-предмет не нашёлся
        # в Steam-инвентаре. После _MAX_LIST_MISSES помечаем его 'traded_away' (уже оттрейжен),
        # чтобы он выпал из очереди готовых к продаже и не спамил warning'ами каждый цикл.
        # Формат: {db_item_id: count}. Сбрасывается при успешном нахождении предмета.
        self._list_miss_counts: Dict[int, int] = {}

        # Дедуп p2p-офферов: {deal_hash: {'offer_id': int|None, 'registered': bool}}.
        # Чтобы не слать один и тот же оффер повторно (Steam 500 бывает ложным → дубль).
        self._sent_p2p_offers: Dict[str, dict] = {}

        # Callback для обновления UI
        self._on_status_change: Optional[Callable[[str, SalesStatus], None]] = None

    def set_status_callback(self, callback: Callable[[str, SalesStatus], None]):
        """Установить callback для обновления статуса в UI."""
        self._on_status_change = callback

    def _notify_status_change(self, account_name: str, status: SalesStatus):
        """Уведомить UI об изменении статуса."""
        if self._on_status_change:
            try:
                self._on_status_change(account_name, status)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")

    async def start(self, account_names: Optional[List[str]] = None):
        """
        Запустить сервис продаж.

        Args:
            account_names: Список аккаунтов для запуска (None = все enabled)
        """
        if self._running:
            logger.warning("TM Sales Service already running")
            self.state.add_log("[WARNING] TM Sales Service already running, ignoring start request")
            return

        self._running = True
        self.state.add_log("[INFO] TM Sales Service starting...")

        # Очищаем старые обработанные продажи (старше 30 дней)
        try:
            from src.database import TradesDatabase
            db = TradesDatabase()
            db.cleanup_old_processed_sales(days=30)
        except Exception as e:
            logger.warning(f"Failed to cleanup old processed sales: {e}")

        # Инициализируем состояния для аккаунтов
        accounts = account_names or self._get_enabled_accounts()
        self.state.add_log(f"[DEBUG] Found {len(accounts)} accounts to start: {accounts}")

        if not accounts:
            self.state.add_log("[WARNING] No enabled accounts found!")
            self._running = False
            return

        for acc_name in accounts:
            self.state.add_log(f"[DEBUG] Initializing account: {acc_name}")
            await self._init_account_state(acc_name)

        # Запускаем фоновые задачи
        self.state.add_log("[DEBUG] Starting background tasks...")
        self._ping_task = asyncio.create_task(self._ping_loop())
        self._hold_check_task = asyncio.create_task(self._hold_check_loop())
        self._trade_check_task = asyncio.create_task(self._trade_check_loop())
        self._sold_check_task = asyncio.create_task(self._sold_check_loop())
        self._cancelled_trade_check_task = asyncio.create_task(self._cancelled_trade_check_loop())
        self._price_check_task = asyncio.create_task(self._price_check_loop())

        self.state.add_log(f"[SUCCESS] TM Sales Service started for {len(accounts)} accounts")

    async def stop(self):
        """Остановить сервис продаж."""
        if not self._running:
            return

        self._running = False
        self.state.add_log("[INFO] TM Sales Service stopping...")

        # Отменяем фоновые задачи
        for task in [self._ping_task, self._hold_check_task, self._trade_check_task, self._sold_check_task, self._cancelled_trade_check_task, self._price_check_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Уходим в оффлайн на всех аккаунтах
        for acc_name, acc_state in self._account_states.items():
            if acc_state.csgotm_client:
                try:
                    acc_state.csgotm_client.go_offline()
                    acc_state.status = SalesStatus.OFFLINE
                    self._notify_status_change(acc_name, SalesStatus.OFFLINE)
                except Exception as e:
                    logger.error(f"[{acc_name}] Failed to go offline: {e}")

        self._account_states.clear()
        self.state.add_log("[SUCCESS] TM Sales Service stopped")

    def _get_enabled_accounts(self) -> List[str]:
        """Получить список включенных аккаунтов."""
        return [acc.name for acc in self.state.accounts if acc.enabled]

    async def _init_account_state(self, account_name: str):
        """Инициализировать состояние для аккаунта."""
        try:
            self.state.add_log(f"[DEBUG] [{account_name}] Looking up account in account_service...")

            # Получаем аккаунт из account_service
            account = None
            if self.account_service and self.account_service.account_manager:
                account = self.account_service.account_manager.get_account(account_name)
                self.state.add_log(f"[DEBUG] [{account_name}] Account found: {account is not None}")
            else:
                self.state.add_log(f"[ERROR] [{account_name}] account_service or account_manager is None!")
                return

            if not account:
                logger.error(f"[{account_name}] Account not found")
                self.state.add_log(f"[ERROR] [{account_name}] Account not found in account_manager")
                return

            # Реинициализируем клиент ТОЛЬКО если аккаунт ещё не залогинен.
            #
            # Раньше это делалось безусловно «для текущего event loop». В headless/API-режиме
            # логин и продажи живут в ОДНОМ loop, а reinitialize_steam_client() сбрасывает
            # _logged_in и пересоздаёт клиент — то есть убивает уже рабочую сессию.
            # Дальше is_logged_in() давал False → лишний авто-релогин → Steam отвечал
            # error 8 (лимит попыток входа) и аккаунт оставался без сессии.
            #
            # Смену event loop (кейс Flet GUI) безопасно обрабатывает сам клиент в
            # _ensure_client_in_current_loop(): он пересоздаёт сессию и подтягивает куки.
            if not account.is_logged_in():
                self.state.add_log(f"[INFO] [{account_name}] Reinitializing Steam client...")
                try:
                    account.reinitialize_steam_client()
                except Exception as e:
                    self.state.add_log(f"[ERROR] [{account_name}] Failed to reinitialize Steam client: {e}")
                    return

            # Проверяем что аккаунт залогинен
            is_logged_in = account.is_logged_in()
            self.state.add_log(f"[DEBUG] [{account_name}] is_logged_in: {is_logged_in}")

            if not is_logged_in:
                self.state.add_log(f"[WARNING] [{account_name}] Account not logged in! Please login first via Accounts tab.")
                # Попробуем залогинить
                self.state.add_log(f"[INFO] [{account_name}] Attempting auto-login...")
                try:
                    success = await account.login_async()
                    if success:
                        self.state.add_log(f"[SUCCESS] [{account_name}] Auto-login successful")
                    else:
                        self.state.add_log(f"[ERROR] [{account_name}] Auto-login failed - please login manually")
                        return
                except Exception as e:
                    self.state.add_log(f"[ERROR] [{account_name}] Auto-login error: {e}")
                    return

            # Получаем CSGO.TM клиент
            csgotm_client = account.csgotm_client
            has_api_key = bool(account.config.csgotm_api_key) if account.config else False
            self.state.add_log(f"[DEBUG] [{account_name}] CSGO.TM client: {csgotm_client is not None}, has API key: {has_api_key}")

            if not csgotm_client:
                logger.error(f"[{account_name}] CSGO.TM client not initialized")
                self.state.add_log(f"[ERROR] [{account_name}] CSGO.TM client not initialized - check TM API key in accounts.json")
                return

            # Создаем состояние
            acc_state = AccountSalesState(
                account_name=account_name,
                status=SalesStatus.STARTING,
                csgotm_client=csgotm_client,
            )
            self._account_states[account_name] = acc_state
            self._notify_status_change(account_name, SalesStatus.STARTING)
            self.state.add_log(f"[DEBUG] [{account_name}] Account state created, getting access token...")

            # Получаем access token
            await self._refresh_access_token(account_name)

            # Проверяем статус продаж
            self.state.add_log(f"[DEBUG] [{account_name}] Checking sell status on CSGO.TM...")
            await self._check_sell_status(account_name)

            self.state.add_log(f"[SUCCESS] [{account_name}] Initialization complete")

        except Exception as e:
            logger.error(f"[{account_name}] Failed to init sales state: {e}")
            self.state.add_log(f"[ERROR] [{account_name}] Failed to init: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if account_name in self._account_states:
                self._account_states[account_name].status = SalesStatus.ERROR
                self._account_states[account_name].stats.last_error = str(e)
                self._notify_status_change(account_name, SalesStatus.ERROR)

    async def _refresh_access_token(self, account_name: str):
        """Обновить access token для аккаунта."""
        acc_state = self._account_states.get(account_name)
        if not acc_state:
            self.state.add_log(f"[ERROR] [{account_name}] No account state for token refresh")
            return

        try:
            self.state.add_log(f"[DEBUG] [{account_name}] Getting Steam client for access token...")

            # Получаем Steam клиент
            account = None
            if self.account_service and self.account_service.account_manager:
                account = self.account_service.account_manager.get_account(account_name)

            if not account:
                raise Exception("Account not found in account_manager")

            # Проверяем, что Steam клиент инициализирован и работает
            if not account.steam_client or not account.is_logged_in():
                self.state.add_log(f"[WARNING] [{account_name}] Steam client issue (exists: {account.steam_client is not None}, logged in: {account.is_logged_in()})")
                self.state.add_log(f"[INFO] [{account_name}] Reinitializing Steam client...")
                account.reinitialize_steam_client()

                # Проверяем, залогинен ли аккаунт
                if not account.is_logged_in():
                    self.state.add_log(f"[INFO] [{account_name}] Not logged in, attempting login...")
                    success = await account.login_async()
                    if not success:
                        raise Exception("Failed to login to Steam")
                    self.state.add_log(f"[SUCCESS] [{account_name}] Logged in successfully")

            if not account.steam_client:
                raise Exception(f"Steam client not available after reinitialization")

            self.state.add_log(f"[DEBUG] [{account_name}] Calling get_access_token()...")

            # Получаем access token
            token = await account.steam_client.get_access_token()

            # Пусто = почти всегда протухшая сессия. is_logged_in() при этом врёт:
            # флаг стоит с момента старта, а куки давно недействительны. Без этой
            # ветки бот бесконечно ловил invalid_access_token, продажи стояли,
            # и починить это можно было только перезапуском службы.
            if not token:
                alive = False
                try:
                    alive = await account.steam_client.is_session_alive()
                except Exception as e:
                    logger.warning(f"[{account_name}] Session check failed: {e}")

                if not alive:
                    self.state.add_log(
                        f"[WARNING] [{account_name}] Сессия Steam протухла — перелогиниваюсь"
                    )
                    account.reinitialize_steam_client()
                    if await account.login_async():
                        self.state.add_log(f"[SUCCESS] [{account_name}] Перелогин выполнен")
                        token = await account.steam_client.get_access_token()
                    else:
                        raise Exception("перелогин не удался")

            if token:
                acc_state.access_token = token
                acc_state.token_expires_at = datetime.now() + timedelta(hours=23)
                logger.info(f"[{account_name}] Access token refreshed")
                self.state.add_log(f"[SUCCESS] [{account_name}] Access token obtained (length: {len(token)})")
            else:
                raise Exception("get_access_token() returned None")

        except Exception as e:
            logger.error(f"[{account_name}] Failed to refresh access token: {e}")
            import traceback
            logger.error(traceback.format_exc())
            acc_state.stats.last_error = f"Token error: {e}"
            self.state.add_log(f"[ERROR] [{account_name}] Failed to get access token: {e}")

    async def _check_sell_status(self, account_name: str):
        """Проверить статус возможности продаж."""
        acc_state = self._account_states.get(account_name)
        if not acc_state or not acc_state.csgotm_client:
            return

        try:
            status = acc_state.csgotm_client.test_sell_status()
            acc_state.sell_status = status

            # Логируем статус
            issues = []
            if not status.get('user_token'):
                issues.append("trade link not set")
            if not status.get('trade_check'):
                issues.append("trade check failed")
            if not status.get('steam_web_api_key'):
                issues.append("Steam API key not set")
            if status.get('site_notmpban') is False:
                issues.append("TEMP BAN for not giving items!")

            if issues:
                self.state.add_log(f"[WARNING] [{account_name}] Sell issues: {', '.join(issues)}")
            else:
                self.state.add_log(f"[SUCCESS] [{account_name}] Sell status OK")

        except Exception as e:
            logger.error(f"[{account_name}] Failed to check sell status: {e}")

    async def _ping_loop(self):
        """Цикл ping-онлайн (каждые 3 минуты)."""
        self.state.add_log("[DEBUG] Ping loop started")
        first_run = True

        while self._running:
            try:
                accounts = list(self._account_states.items())
                if first_run:
                    self.state.add_log(f"[DEBUG] Ping loop: {len(accounts)} accounts to ping")
                    first_run = False

                for acc_name, acc_state in accounts:
                    await self._do_ping(acc_name)

                # Ждем следующего цикла
                await asyncio.sleep(self.PING_INTERVAL)

            except asyncio.CancelledError:
                self.state.add_log("[DEBUG] Ping loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in ping loop: {e}")
                self.state.add_log(f"[ERROR] Ping loop error: {e}")
                await asyncio.sleep(30)

    async def _do_ping(self, account_name: str):
        """Выполнить ping для аккаунта."""
        acc_state = self._account_states.get(account_name)
        if not acc_state:
            self.state.add_log(f"[ERROR] [{account_name}] No account state for ping")
            return

        if not acc_state.csgotm_client:
            self.state.add_log(f"[ERROR] [{account_name}] No CSGO.TM client for ping")
            return

        try:
            # Проверяем, нужно ли обновить токен
            if (acc_state.token_expires_at and
                datetime.now() >= acc_state.token_expires_at - timedelta(hours=1)):
                self.state.add_log(f"[DEBUG] [{account_name}] Token expiring soon, refreshing...")
                await self._refresh_access_token(account_name)

            if not acc_state.access_token:
                logger.warning(f"[{account_name}] No access token for ping")
                self.state.add_log(f"[WARNING] [{account_name}] No access token, cannot ping")
                return

            # Выполняем ping
            self.state.add_log(f"[DEBUG] [{account_name}] Sending ping to CSGO.TM...")
            result = acc_state.csgotm_client.ping_online(acc_state.access_token)
            self.state.add_log(f"[DEBUG] [{account_name}] Ping result: {result}")

            if result.get('success'):
                acc_state.status = SalesStatus.ONLINE
                acc_state.stats.last_ping_time = datetime.now()
                acc_state.stats.last_error = None
                self._notify_status_change(account_name, SalesStatus.ONLINE)
                self.state.add_log(f"[SUCCESS] [{account_name}] Ping OK - now ONLINE")
            else:
                error = result.get('error', 'unknown')

                # Если "too early for ping" - это не ошибка, просто информация
                if 'too early' in error.lower():
                    self.state.add_log(f"[INFO] [{account_name}] Пинг слишком рано, следующая попытка через 3 минуты")
                    # Не меняем статус, оставляем как есть
                    return

                # Если токен невалидный или истёк - обновляем
                if error == 'invalid_access_token' or 'token expired' in error.lower():
                    self.state.add_log(f"[WARNING] [{account_name}] Access token expired/invalid, refreshing...")
                    await self._refresh_access_token(account_name)
                    # Пробуем еще раз
                    if acc_state.access_token:
                        self.state.add_log(f"[DEBUG] [{account_name}] Retrying ping with new token...")
                        result = acc_state.csgotm_client.ping_online(acc_state.access_token)
                        if result.get('success'):
                            acc_state.status = SalesStatus.ONLINE
                            acc_state.stats.last_ping_time = datetime.now()
                            self._notify_status_change(account_name, SalesStatus.ONLINE)
                            self.state.add_log(f"[SUCCESS] [{account_name}] Ping OK after token refresh")
                            return

                acc_state.status = SalesStatus.ERROR
                acc_state.stats.last_error = error
                self._notify_status_change(account_name, SalesStatus.ERROR)
                self.state.add_log(f"[ERROR] [{account_name}] Ping failed: {error}")

        except Exception as e:
            logger.error(f"[{account_name}] Ping error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.state.add_log(f"[ERROR] [{account_name}] Ping exception: {e}")
            acc_state.status = SalesStatus.ERROR
            acc_state.stats.last_error = str(e)
            self._notify_status_change(account_name, SalesStatus.ERROR)

    async def _hold_check_loop(self):
        """Цикл проверки холда (каждые 5 минут)."""
        while self._running:
            try:
                await self._check_and_list_items()
                await asyncio.sleep(self.HOLD_CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in hold check loop: {e}")
                await asyncio.sleep(60)

    async def _check_and_list_items(self):
        """Проверить холд и выставить предметы на продажу."""
        if not self.db_service:
            logger.debug("Hold check skipped: no db_service")
            return

        try:
            from src.database import TradesDatabase
            from collections import deque
            db = TradesDatabase()

            # ИСТОЧНИК ПРАВДЫ — my-inventory маркета, а НЕ unlock_date из БД.
            # my-inventory отдаёт только предметы, которые (а) реально в Steam-инвентаре,
            # (б) tradable=1 (не на холде), (в) ещё НЕ выставлены. Это ровно то, что можно
            # выставить прямо сейчас, причём со свежим assetid. unlock_date в БД бывает
            # ошибочным (видели tradable-предмет с unlock в будущем), поэтому на него
            # больше не опираемся. Заодно это «расстекляет» ложно-listed (они снова
            # появляются в my-inventory) и убирает тяжёлый запрос всего Steam-инвентаря.
            for account_name, acc_state in list(self._account_states.items()):
                if not acc_state or acc_state.status != SalesStatus.ONLINE or not acc_state.csgotm_client:
                    continue

                sellable = acc_state.csgotm_client.get_sellable_inventory()  # [{id, market_hash_name, ...}]
                if not sellable:
                    logger.debug(f"[{account_name}] my-inventory пуст — нечего выставлять")
                    continue

                # name → очередь свежих assetid (несколько копий одного скина)
                ids_by_name: Dict[str, deque] = {}
                for inv in sellable:
                    name = inv.get('market_hash_name')
                    if name and inv.get('id') and inv.get('tradable', 1):
                        ids_by_name.setdefault(name, deque()).append(str(inv.get('id')))

                # Наши предметы (что и по какой цене продаём). Берём holding И listed:
                # 'listed', попавший в my-inventory, — это застрявший (по факту не на
                # маркете), его надо выставить заново.
                our_items = [
                    it for it in db.get_purchased_items(account_name=account_name)
                    if it.get('status') in ('holding', 'listed')
                    and it.get('expected_sell_price')
                ]

                to_list = []
                for it in our_items:
                    name = it.get('market_hash_name')
                    q = ids_by_name.get(name)
                    if q:
                        it = dict(it)
                        it['steam_id'] = q.popleft()  # свежий id, отмечаем как занятый
                        to_list.append(it)

                if not to_list:
                    logger.debug(f"[{account_name}] нет совпадений my-inventory ↔ БД")
                    continue

                logger.info(f"[{account_name}] К выставлению: {len(to_list)} шт (из my-inventory)")
                self.state.add_log(f"[INFO] [{account_name}] К выставлению: {len(to_list)} предметов")

                for it in to_list:
                    # steam_id уже свежий из my-inventory → _list_item_for_sale не будет
                    # тянуть Steam-инвентарь и обновлять кэш.
                    await self._list_item_for_sale(it, skip_inventory_update=True)
                    await asyncio.sleep(2)  # rate limiting

        except Exception as e:
            logger.error(f"Error checking items for sale: {e}", exc_info=True)

    async def _list_item_for_sale(self, item: dict, skip_inventory_update: bool = False):
        """Выставить предмет на продажу."""
        account_name = item.get('account_name', '')
        acc_state = self._account_states.get(account_name)

        if not acc_state or acc_state.status != SalesStatus.ONLINE:
            logger.warning(f"[{account_name}] Not online, cannot list item")
            return

        if not acc_state.csgotm_client:
            return

        try:
            # Получаем данные предмета
            steam_id = item.get('steam_id') or item.get('assetid') or item.get('asset_id')
            expected_price = item.get('expected_sell_price', 0)
            market_hash_name = item.get('market_hash_name', '')
            item_id = item.get('id')

            # Предмет убран из продаж вручную — не выставляем. Иначе он вернулся бы
            # на витрину следующим же циклом, и уведомления пошли бы заново.
            if market_hash_name:
                try:
                    from src.database import TradesDatabase
                    if TradesDatabase().is_sale_ignored(market_hash_name):
                        self.state.add_log(
                            f"[INFO] [{account_name}] Убран из продаж, не выставляю: {market_hash_name[:40]}"
                        )
                        return
                except Exception as e:
                    logger.warning(f"[{account_name}] Sale-ignore check failed: {e}")

            if not expected_price:
                logger.warning(f"[{account_name}] Cannot list item - missing expected_sell_price: {market_hash_name}")
                return

            # Если нет asset_id, пробуем найти предмет в Steam инвентаре
            if not steam_id and market_hash_name:
                self.state.add_log(f"[INFO] [{account_name}] Searching for '{market_hash_name}' in Steam inventory...")

                # Получаем Steam клиент
                account = None
                if self.account_service and self.account_service.account_manager:
                    account = self.account_service.account_manager.get_account(account_name)

                if account and account.steam_client:
                    try:
                        # Получаем инвентарь CS2 (appid=730)
                        inventory = await account.steam_client.get_inventory(730)

                        # Ищем предмет по market_hash_name
                        # Инвентарь возвращает объекты InventoryItem, а не словари
                        for inv_item in inventory:
                            # Используем атрибуты объекта напрямую
                            if hasattr(inv_item, 'market_hash_name') and inv_item.market_hash_name == market_hash_name:
                                steam_id = inv_item.assetid if hasattr(inv_item, 'assetid') else None
                                if steam_id:
                                    self.state.add_log(f"[SUCCESS] [{account_name}] Found asset_id: {steam_id}")
                                    # Обновляем в БД
                                    if self.db_service and item_id:
                                        from src.database import TradesDatabase
                                        db = TradesDatabase()
                                        db.update_purchased_item_asset_id(item_id, str(steam_id))
                                        self.state.add_log(f"[INFO] [{account_name}] Updated asset_id in database")
                                    break
                    except Exception as e:
                        logger.error(f"[{account_name}] Failed to get Steam inventory: {e}")

            if not steam_id:
                # Предмет не найден в Steam-инвентаре. Одиночный промах бывает ложным
                # (ещё на холде у Steam / частичная подгрузка / рассинхрон имени), поэтому
                # считаем промахи подряд и только после MAX_LIST_MISSES помечаем 'traded_away'.
                misses = self._list_miss_counts.get(item_id, 0) + 1 if item_id else 0
                if item_id:
                    self._list_miss_counts[item_id] = misses

                if item_id and misses >= self.MAX_LIST_MISSES:
                    if self.db_service and item_id:
                        try:
                            from src.database import TradesDatabase
                            TradesDatabase().update_purchased_item_status(item_id, "traded_away")
                        except Exception as e:
                            logger.error(f"[{account_name}] Failed to mark item traded_away: {e}")
                    self._list_miss_counts.pop(item_id, None)
                    logger.warning(
                        f"[{account_name}] Item '{market_hash_name}' not in inventory after "
                        f"{misses} attempts - marking as traded_away"
                    )
                    self.state.add_log(
                        f"[WARNING] [{account_name}] '{market_hash_name}' не найден в инвентаре "
                        f"{misses} раз(а) подряд — помечен как оттрейженный, снят с продажи."
                    )
                else:
                    logger.warning(f"[{account_name}] Cannot list item - missing asset_id/steam_id: {market_hash_name}")
                    self.state.add_log(
                        f"[WARNING] [{account_name}] Cannot list '{market_hash_name}' - item not found in Steam inventory. "
                        f"Item may still be on hold or already traded away. (промах {misses}/{self.MAX_LIST_MISSES})"
                    )
                return

            # Предмет найден в инвентаре — сбрасываем счётчик промахов.
            if item_id:
                self._list_miss_counts.pop(item_id, None)

            # Обновляем инвентарь на CSGO.TM только если это не было сделано ранее
            if not skip_inventory_update:
                self.state.add_log(f"[INFO] [{account_name}] Requesting inventory update on CSGO.TM...")
                acc_state.csgotm_client.update_inventory()

                # Ждем завершения обновления
                update_success = await self._wait_for_inventory_update(account_name, max_wait_time=self.INVENTORY_UPDATE_MAX_WAIT)
                if not update_success:
                    self.state.add_log(
                        f"[WARNING] [{account_name}] Inventory update timeout, attempting to list anyway..."
                    )

            # Проверяем актуальную цену на маркете и выставляем топ-1
            final_price = expected_price
            if market_hash_name:
                try:
                    current_market_price = acc_state.csgotm_client.get_item_price(market_hash_name)
                    if current_market_price and 'min_price' in current_market_price:
                        market_min_price = current_market_price['min_price']

                        # ВСЕГДА выставляем топ-1 (минимальная цена - 1 рубль)
                        # Но проверяем, что это не слишком низкая цена
                        if market_min_price > expected_price * 0.8:  # Не ниже 80% от expected
                            final_price = market_min_price - 1
                            price_diff = ((final_price - expected_price) / expected_price * 100) if expected_price > 0 else 0

                            if final_price > expected_price:
                                self.state.add_log(
                                    f"[SUCCESS] [{account_name}] Extra profit! Market: {market_min_price:.0f}₽ > Expected: {expected_price:.0f}₽ "
                                    f"(+{price_diff:.1f}%), listing at {final_price:.0f}₽"
                                )
                            else:
                                self.state.add_log(
                                    f"[INFO] [{account_name}] Market price: {market_min_price:.0f}₽, listing at {final_price:.0f}₽ (top-1)"
                                )
                        else:
                            # Рыночная цена слишком низкая - используем expected
                            self.state.add_log(
                                f"[WARNING] [{account_name}] Market price ({market_min_price:.0f}₽) too low (< 80% of {expected_price:.0f}₽), "
                                f"using expected price instead"
                            )
                except Exception as e:
                    logger.warning(f"[{account_name}] Failed to get market price, using expected price: {e}")
                    self.state.add_log(f"[WARNING] [{account_name}] Could not check market price, using expected price")

            # Выставляем на продажу
            result = acc_state.csgotm_client.add_to_sale_by_steam_id(
                steam_item_id=str(steam_id),
                price=final_price,
                currency="RUB"
            )

            # Группа ошибок TM, которые лечатся обновлением кэша инвентаря, а НЕ являются
            # финальными (по их же документации к add-to-sale):
            #   inventory_not_loaded  - need to update inventory
            #   item_not_recieved     - need to update inventory  (опечатка в их API)
            #   item_not_in_inventory - update it first ... wait 10-20 seconds
            #   no_description_found  - Steam не отдал описание, повторить позже
            # Типичный кейс: предмет пришёл в Steam уже после пакетного обновления кэша.
            err = (result.message or "").lower()
            if not result.success and any(code in err for code in self.RETRYABLE_LIST_ERRORS):
                # ГЛАВНАЯ причина этих ошибок — протухший asset_id в БД, а НЕ «холодный» кэш.
                # assetid в Steam меняется при каждом перемещении предмета, поэтому
                # сохранённый при покупке id может указывать в никуда, хотя сам предмет
                # в инвентаре есть. Спрашиваем у маркета актуальный id по имени.
                fresh_ids = [
                    i for i in acc_state.csgotm_client.find_inventory_asset_ids(market_hash_name)
                    if i != str(steam_id)
                ]

                if fresh_ids:
                    new_id = fresh_ids[0]
                    self.state.add_log(
                        f"[INFO] [{account_name}] {market_hash_name[:30]}: asset_id устарел "
                        f"({steam_id} → {new_id}), выставляю с актуальным"
                    )
                    result = acc_state.csgotm_client.add_to_sale_by_steam_id(
                        steam_item_id=new_id,
                        price=final_price,
                        currency="RUB"
                    )
                    if result.success:
                        steam_id = new_id
                        # Чиним id в БД, чтобы в следующий раз не спотыкаться
                        if self.db_service and item_id:
                            try:
                                from src.database import TradesDatabase
                                TradesDatabase().update_purchased_item_asset_id(item_id, new_id)
                            except Exception as e:
                                logger.debug(f"[{account_name}] Не удалось обновить asset_id: {e}")
                else:
                    # Предмета нет в кэше маркета вовсе — возможно, кэш ещё не подтянулся
                    self.state.add_log(
                        f"[INFO] [{account_name}] {market_hash_name[:30]} нет в кэше маркета "
                        f"({err.strip()}) — обновляю инвентарь и повторяю"
                    )
                    acc_state.csgotm_client.update_inventory()
                    await self._wait_for_inventory_update(
                        account_name, max_wait_time=self.INVENTORY_UPDATE_MAX_WAIT
                    )
                    result = acc_state.csgotm_client.add_to_sale_by_steam_id(
                        steam_item_id=str(steam_id),
                        price=final_price,
                        currency="RUB"
                    )

            if result.success:
                acc_state.stats.items_listed += 1
                self.state.add_log(
                    f"[SUCCESS] [{account_name}] Listed: {market_hash_name[:30]} @ {final_price:.0f} RUB"
                )

                # Обновляем статус в БД
                if item_id:
                    from src.database import TradesDatabase
                    db = TradesDatabase()
                    db.update_item_sale_status(
                        item_id=item_id,
                        status='listed',
                        tm_item_id=result.item_id
                    )
                    self.state.add_log(f"[INFO] [{account_name}] Updated item status to 'listed' in database")
            else:
                # Если предмет уже выставлен - это не ошибка, обновляем статус
                if "item_on_sale" in result.message.lower():
                    self.state.add_log(
                        f"[INFO] [{account_name}] Item already on sale: {market_hash_name[:30]}"
                    )
                    # Обновляем статус в БД как выставленный
                    if item_id:
                        from src.database import TradesDatabase
                        db = TradesDatabase()
                        db.update_item_sale_status(
                            item_id=item_id,
                            status='listed',
                            tm_item_id=None  # ID неизвестен, но предмет выставлен
                        )
                        self.state.add_log(f"[INFO] [{account_name}] Updated item status to 'listed' in database")
                elif "item_not_in_inventory" in result.message.lower():
                    # Предмет не в инвентаре - возможно уже продан или на холде
                    self.state.add_log(
                        f"[WARNING] [{account_name}] Item not in CSGO.TM inventory: {market_hash_name[:30]} (may be sold or on trade hold)"
                    )
                else:
                    self.state.add_log(
                        f"[ERROR] [{account_name}] Failed to list {market_hash_name[:30]}: {result.message}"
                    )

        except Exception as e:
            logger.error(f"Error listing item for sale: {e}")

    async def _trade_check_loop(self):
        """Цикл проверки и подтверждения трейдов (каждую минуту)."""
        while self._running:
            try:
                for acc_name in list(self._account_states.keys()):
                    await self._check_and_confirm_trades(acc_name)

                await asyncio.sleep(self.TRADE_CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trade check loop: {e}")
                await asyncio.sleep(30)

    async def _check_and_confirm_trades(self, account_name: str):
        """Проверить и подтвердить трейды для аккаунта."""
        acc_state = self._account_states.get(account_name)
        if not acc_state or acc_state.status != SalesStatus.ONLINE:
            return

        if not acc_state.csgotm_client:
            return

        try:
            # Получаем трейды на отдачу
            trades = acc_state.csgotm_client.get_trades_to_give()

            if not trades:
                return

            self.state.add_log(f"[INFO] [{account_name}] Found {len(trades)} trades to confirm")

            # Получаем Steam клиент для подтверждения
            account = None
            if self.account_service and self.account_service.account_manager:
                account = self.account_service.account_manager.get_account(account_name)

            if not account or not account.steam_client:
                logger.warning(f"[{account_name}] Steam client not available for trade confirmation")
                return

            # p2p: маркет отдаёт ДАННЫЕ для создания оффера, а не готовый оффер на приём.
            # Порядок по документации: создать оффер покупателю → подтвердить (maFile)
            # → зарегистрировать у маркета через trade-ready.
            #
            # ДЕДУП: маркет возвращает одну и ту же сделку каждые 60с, пока она не
            # зарегистрирована. При этом Steam на /tradeoffer/new/send может ответить 500,
            # ФАКТИЧЕСКИ создав оффер — если повторить, уйдёт ВТОРОЙ оффер тому же человеку
            # на тот же скин (наблюдалось). Поэтому отправляем оффер ровно ОДИН раз на сделку
            # (по hash), а при неуспехе не повторяем отправку — только логируем для ручной сверки.
            for offer in trades:
                partner = offer.get('partner')
                token = offer.get('token')
                message = offer.get('tradeoffermessage', '')
                items = offer.get('items') or []
                deal_hash = offer.get('hash') or (
                    f"{partner}:" + "|".join(str(i.get('assetid')) for i in items)
                )

                if not partner or not token or not items:
                    self.state.add_log(
                        f"[WARNING] [{account_name}] Пропущен p2p-оффер: не хватает данных "
                        f"(partner={bool(partner)}, token={bool(token)}, items={len(items)})"
                    )
                    continue

                prev = self._sent_p2p_offers.get(deal_hash)
                if prev is not None:
                    # Эту сделку уже обрабатывали в текущей сессии.
                    # Если оффер ушёл, но trade-ready не прошёл — повторяем ТОЛЬКО регистрацию.
                    if prev.get('offer_id') and not prev.get('registered'):
                        if acc_state.csgotm_client.trade_ready(prev['offer_id']):
                            prev['registered'] = True
                            acc_state.stats.trades_confirmed += 1
                            self.state.add_log(
                                f"[SUCCESS] [{account_name}] p2p-оффер {prev['offer_id']} "
                                "зарегистрирован на маркете (повторный trade-ready)"
                            )
                    continue

                # Помечаем ДО отправки: даже если Steam вернёт 500, оффер мог создаться —
                # повторная отправка означала бы дубликат.
                self._sent_p2p_offers[deal_hash] = {'offer_id': None, 'registered': False}

                offer_id = await account.steam_client.send_p2p_offer(
                    partner=partner,
                    token=token,
                    message=message,
                    items=items,
                )

                if not offer_id:
                    self.state.add_log(
                        f"[ERROR] [{account_name}] Не удалось создать p2p-оффер для {partner} "
                        "(повтор не делаем во избежание дубля — проверьте сделку вручную)"
                    )
                    await asyncio.sleep(2)
                    continue

                self._sent_p2p_offers[deal_hash]['offer_id'] = offer_id

                # Без trade-ready маркет не свяжет отправленный оффер со сделкой
                if acc_state.csgotm_client.trade_ready(offer_id):
                    self._sent_p2p_offers[deal_hash]['registered'] = True
                    acc_state.stats.trades_confirmed += 1
                    self.state.add_log(
                        f"[SUCCESS] [{account_name}] p2p-оффер {offer_id} отправлен, "
                        "подтверждён и зарегистрирован на маркете"
                    )
                else:
                    self.state.add_log(
                        f"[WARNING] [{account_name}] Оффер {offer_id} отправлен, "
                        "но маркет не принял trade-ready (повторим регистрацию в след. цикле)"
                    )

                await asyncio.sleep(2)  # Rate limiting

        except Exception as e:
            logger.error(f"[{account_name}] Error checking trades: {e}")

    async def _sold_check_loop(self):
        """Цикл проверки проданных предметов (каждые 2 минуты)."""
        while self._running:
            try:
                for acc_name in list(self._account_states.keys()):
                    await self._check_sold_items(acc_name)

                await asyncio.sleep(self.SOLD_CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in sold check loop: {e}")
                await asyncio.sleep(30)

    async def _check_sold_items(self, account_name: str):
        """Проверить и записать проданные предметы для аккаунта."""
        acc_state = self._account_states.get(account_name)
        if not acc_state or acc_state.status != SalesStatus.ONLINE:
            return

        if not acc_state.csgotm_client:
            return

        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            # Сначала проверяем отменённые трейды
            # Если предмет был продан (status='sold'), но снова появился со status=1 (на продаже),
            # значит трейд отменился и нужно откатить продажу
            our_items = db.get_purchased_items(account_name=account_name)
            sold_items_by_name = {
                item.get("market_hash_name"): item
                for item in our_items
                if item.get("status") == "sold"
            }

            if sold_items_by_name:
                # Получаем предметы на продаже с TM
                tm_items = acc_state.csgotm_client.get_all_items()

                for tm_item in tm_items:
                    status = str(tm_item.get("status", ""))
                    if status == "1":  # Предмет на продаже
                        item_name = tm_item.get("market_hash_name", "")
                        tm_item_id = tm_item.get("item_id", "")

                        # Проверяем - был ли этот предмет записан как проданный
                        if item_name in sold_items_by_name:
                            sold_item = sold_items_by_name[item_name]
                            db_item_id = sold_item.get("id")

                            # Трейд был отменён! Откатываем продажу
                            self.state.add_log(
                                f"[WARNING] [{account_name}] Trade cancelled detected: {item_name[:40]} "
                                f"(item back on sale, status=1)"
                            )

                            # Возвращаем статус обратно на 'listed'
                            db.update_purchased_item_status(db_item_id, 'listed')

                            # Обновляем tm_item_id на случай если он изменился
                            if hasattr(db, 'update_purchased_item_tm_id'):
                                db.update_purchased_item_tm_id(db_item_id, tm_item_id)

                            # Удаляем из sold_items
                            db.delete_sold_item_by_name(account_name, item_name)

                            # Убираем из обработанных продаж чтобы можно было снова продать
                            # Удаляем записи по tm_item_id (более надежно чем по имени)
                            sale_key_tm = f"{account_name}_tm_{tm_item_id}"
                            db.remove_processed_sale(sale_key_tm)

                            # Убираем из очереди проверки отменённых трейдов
                            check_keys_to_remove = [(acc, item_id) for (acc, item_id) in self._pending_trade_checks.keys()
                                                   if acc == account_name and item_id == db_item_id]
                            for key in check_keys_to_remove:
                                if key in self._pending_trade_checks:
                                    del self._pending_trade_checks[key]

                            # Обновляем статистику
                            if acc_state.stats.items_sold > 0:
                                acc_state.stats.items_sold -= 1

                            self.state.add_log(
                                f"[INFO] [{account_name}] Sale cancelled for {item_name[:40]}, "
                                f"item returned to listings"
                            )

            # Получаем список НАШИХ предметов со статусом 'listed'
            # Обновляем список после проверки отменённых трейдов
            our_items = db.get_purchased_items(account_name=account_name)
            our_listed_items_by_id = {
                item.get("id"): item
                for item in our_items
                if item.get("status") == "listed"
            }

            if not our_listed_items_by_id:
                return  # Нет наших выставленных предметов - нечего проверять

            # Отслеживаем обработанные item_id из TM чтобы не дублировать в Способе 2
            processed_tm_item_ids = set()

            # Способ 1: Проверяем статусы предметов на CSGO.TM
            # status=2 или status=7 означает что предмет продан и ожидает передачи
            tm_items = acc_state.csgotm_client.get_all_items()
            for tm_item in tm_items:
                status = str(tm_item.get("status", ""))
                if status in ["2", "7"]:  # Продано, ожидает передачи
                    item_name = tm_item.get("market_hash_name", "")
                    sale_price = float(tm_item.get("price", 0))
                    tm_asset_id = tm_item.get("assetid", "")
                    tm_item_id = tm_item.get("item_id", "")

                    # Уникальный ключ для проверки дублей (по item_id из TM)
                    sale_key = f"{account_name}_tm_{tm_item_id}"
                    if db.is_sale_processed(sale_key):
                        processed_tm_item_ids.add(tm_item_id)
                        continue

                    # Ищем наш предмет по asset_id (более точное сопоставление)
                    purchased_item = None
                    for our_item in our_listed_items_by_id.values():
                        # Сначала пробуем по asset_id
                        if tm_asset_id and our_item.get("asset_id") == tm_asset_id:
                            purchased_item = our_item
                            break

                    # Если не нашли по asset_id, ищем по имени
                    if not purchased_item:
                        for our_item in our_listed_items_by_id.values():
                            if our_item.get("market_hash_name") == item_name:
                                purchased_item = our_item
                                break

                    if not purchased_item:
                        continue

                    our_item_id = purchased_item.get("id")
                    check_key = (account_name, our_item_id)

                    # По документации TM: settlement > 0 → трейд УСПЕШЕН, покупатель уже
                    # получил предмет (идёт лишь финальный отсчёт). Это единственный
                    # надёжный признак реальной продажи. Сам по себе статус 2/7 значит
                    # «продан, ОЖИДАЕТ ПЕРЕДАЧИ» — трейд ещё может быть отменён/протухнуть.
                    try:
                        settlement = float(tm_item.get("settlement") or 0)
                    except (TypeError, ValueError):
                        settlement = 0

                    if settlement > 0:
                        purchase_price = float(purchased_item.get("purchase_price", 0))
                        profit = sale_price - purchase_price
                        profit_pct = (profit / purchase_price * 100) if purchase_price > 0 else 0

                        db.add_sold_item(
                            account_name=account_name,
                            item_name=item_name,
                            purchase_price=purchase_price,
                            sale_price=sale_price,
                            platform='csgotm'
                        )
                        db.update_purchased_item_status(our_item_id, "sold")

                        if our_item_id in our_listed_items_by_id:
                            del our_listed_items_by_id[our_item_id]

                        acc_state.stats.items_sold += 1
                        acc_state.stats.total_revenue += sale_price

                        self.state.add_log(
                            f"[SOLD] [{account_name}] {item_name[:40]} | "
                            f"Price: {sale_price:.2f}₽ | Profit: {profit:.2f}₽ ({profit_pct:.1f}%)"
                        )
                        db.mark_sale_as_processed(sale_key, account_name, item_name)
                        processed_tm_item_ids.add(tm_item_id)
                        self._pending_trade_checks.pop(check_key, None)
                        continue

                    # Продан, но ещё НЕ передан — продажу не фиксируем, только ждём.
                    if check_key not in self._pending_trade_checks:
                        import time
                        self._pending_trade_checks[check_key] = {
                            'sold_time': time.time(),
                            'tm_item_id': tm_item_id,
                            'market_hash_name': item_name,
                            'db_item_id': our_item_id,
                            'sale_price': sale_price,
                        }
                        self.state.add_log(
                            f"[INFO] [{account_name}] {item_name[:40]} куплен на TM за {sale_price:.2f}₽ — "
                            "ожидает передачи. Продажа будет записана после трейда."
                        )
                        logger.info(
                            f"[{account_name}] Awaiting transfer: {item_name[:40]} ({sale_price:.2f}₽)"
                        )


            # Если больше нет наших предметов - выходим
            if not our_listed_items_by_id:
                return

            # Способ 2: Проверяем историю продаж (для уже переданных предметов)
            # Используется только для предметов, которые не были найдены через статусы
            sold_items = acc_state.csgotm_client.get_sold_items(days=7)

            if not sold_items:
                return

            for sale in sold_items:
                # Уникальный ID операции - используем item_id + time
                item_id = sale.get("item_id", "")
                sale_time = sale.get("time", "")
                operation_id = f"{item_id}_{sale_time}"

                if not item_id:
                    continue

                # Пропускаем если этот item_id уже обработан в Способе 1
                if item_id in processed_tm_item_ids:
                    continue

                # Проверяем не обработали ли уже
                sale_key = f"{account_name}_{operation_id}"
                if db.is_sale_processed(sale_key):
                    continue

                # Получаем данные о продаже
                item_name = sale.get("market_hash_name", "Unknown")

                # ВАЖНО: Проверяем что это НАШ предмет (есть в базе со статусом 'listed')
                purchased_item = None
                for our_item in our_listed_items_by_id.values():
                    if our_item.get("market_hash_name") == item_name:
                        purchased_item = our_item
                        break

                if not purchased_item:
                    # Это не наш предмет - пропускаем, но помечаем чтобы не проверять снова
                    db.mark_sale_as_processed(sale_key, account_name, item_name)
                    continue

                sale_price = float(sale.get("received", 0))
                # API history возвращает в копейках, конвертируем в рубли
                if sale_price > 10000:  # Скорее всего копейки
                    sale_price = sale_price / 100
                purchase_price = float(purchased_item.get("purchase_price", 0))

                # Записываем продажу
                if sale_price > 0:
                    profit = sale_price - purchase_price
                    profit_pct = (profit / purchase_price * 100) if purchase_price > 0 else 0

                    db.add_sold_item(
                        account_name=account_name,
                        item_name=item_name,
                        purchase_price=purchase_price,
                        sale_price=sale_price,
                        platform='csgotm'
                    )

                    # Обновляем статус в purchased_items
                    db.update_purchased_item_status(purchased_item["id"], "sold")

                    # Удаляем из словаря по ID
                    our_item_id = purchased_item.get("id")
                    if our_item_id in our_listed_items_by_id:
                        del our_listed_items_by_id[our_item_id]

                    # Обновляем статистику
                    acc_state.stats.items_sold += 1
                    acc_state.stats.total_revenue += sale_price

                    # Логируем продажу
                    self.state.add_log(
                        f"[SOLD] [{account_name}] {item_name[:40]} | "
                        f"Price: {sale_price:.2f}₽ | Profit: {profit:.2f}₽ ({profit_pct:.1f}%)"
                    )

                    # Добавляем в очередь на проверку статуса трейда через 10 минут
                    import time
                    check_key = (account_name, our_item_id)
                    self._pending_trade_checks[check_key] = {
                        'sold_time': time.time(),
                        'tm_item_id': item_id,
                        'market_hash_name': item_name,
                        'db_item_id': our_item_id
                    }
                    logger.debug(f"[{account_name}] Added item to trade check queue: {item_name[:30]}")

                # Помечаем как обработанное
                db.mark_sale_as_processed(sale_key, account_name, item_name)

        except Exception as e:
            logger.error(f"[{account_name}] Error checking sold items: {e}")

    async def _cancelled_trade_check_loop(self):
        """Цикл проверки отменённых трейдов (каждые 3 минуты)."""
        while self._running:
            try:
                await self._check_cancelled_trades()
                await asyncio.sleep(self.CANCELLED_TRADE_CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cancelled trade check loop: {e}")
                await asyncio.sleep(60)

    async def _check_cancelled_trades(self):
        """Проверить статус трейдов проданных предметов через 10+ минут."""
        import time
        current_time = time.time()
        CHECK_DELAY = 600  # 10 минут в секундах

        items_to_remove = []

        for check_key, check_data in list(self._pending_trade_checks.items()):
            account_name, db_item_id = check_key
            sold_time = check_data['sold_time']
            tm_item_id = check_data['tm_item_id']
            market_hash_name = check_data['market_hash_name']

            # Проверяем только если прошло больше 10 минут
            if current_time - sold_time < CHECK_DELAY:
                continue

            # Проверяем статус трейда
            acc_state = self._account_states.get(account_name)
            if not acc_state or not acc_state.csgotm_client:
                continue

            try:
                # Получаем историю за последние 2 часа
                date_start = int(sold_time - 3600)  # За час до продажи
                date_end = int(current_time)

                history = acc_state.csgotm_client.get_history(date=date_start, date_end=date_end)

                # Ищем нашу продажу в истории
                sale_found = False
                trade_cancelled = False
                trade_successful = False

                for entry in history:
                    if entry.get('event') != 'sell':
                        continue

                    if entry.get('item_id') != tm_item_id:
                        continue

                    sale_found = True
                    stage = str(entry.get('stage', ''))
                    settlement = int(entry.get('settlement', 0))

                    # TRADE_STAGE_TIMED_OUT = 5 - трейд отменён/истёк
                    if stage == '5':
                        trade_cancelled = True
                        self.state.add_log(
                            f"[WARNING] [{account_name}] Trade cancelled for {market_hash_name[:40]} (stage=5)"
                        )
                        break

                    # settlement > 0 означает что трейд успешный
                    if settlement > 0:
                        trade_successful = True
                        self.state.add_log(
                            f"[SUCCESS] [{account_name}] Trade successful for {market_hash_name[:40]} (settlement={settlement})"
                        )
                        break

                # Обрабатываем результат
                if trade_cancelled:
                    # Трейд отменён - нужно выставить предмет обратно
                    from src.database import TradesDatabase
                    db = TradesDatabase()

                    # Получаем данные предмета для повторного выставления
                    with db._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT id, market_hash_name, expected_sell_price, asset_id, account_name
                            FROM purchased_items
                            WHERE id = ?
                        """, (db_item_id,))
                        item_data = cursor.fetchone()

                    # Обновляем статус обратно на 'holding' (временно)
                    db.update_purchased_item_status(db_item_id, 'holding')

                    # Удаляем из sold_items (отменяем продажу)
                    db.delete_sold_item_by_name(account_name, market_hash_name)

                    # Обновляем статистику
                    if acc_state.stats.items_sold > 0:
                        acc_state.stats.items_sold -= 1

                    self.state.add_log(
                        f"[WARNING] [{account_name}] Trade cancelled for {market_hash_name[:40]}, re-listing..."
                    )

                    # Сразу выставляем предмет обратно на продажу
                    if item_data:
                        item_dict = {
                            'id': item_data[0],
                            'market_hash_name': item_data[1],
                            'expected_sell_price': item_data[2],
                            'asset_id': item_data[3],
                            'account_name': item_data[4]
                        }
                        # Выставляем асинхронно
                        try:
                            await self._list_item_for_sale(item_dict, skip_inventory_update=False)
                        except Exception as e:
                            logger.error(f"[{account_name}] Failed to relist after trade cancel: {e}")
                            self.state.add_log(f"[ERROR] [{account_name}] Failed to relist {market_hash_name[:40]}: {e}")

                    # Удаляем из очереди
                    items_to_remove.append(check_key)

                elif trade_successful or not sale_found:
                    # Трейд успешен или запись не найдена (уже финализирована) - удаляем из очереди
                    items_to_remove.append(check_key)

                # Если прошло больше 2 часов и статус всё ещё не определён - удаляем из очереди
                if current_time - sold_time > 7200:  # 2 часа
                    logger.debug(f"[{account_name}] Trade check timeout for {market_hash_name[:30]}, removing from queue")
                    items_to_remove.append(check_key)

            except Exception as e:
                logger.error(f"[{account_name}] Error checking trade status for {market_hash_name[:30]}: {e}")
                # Если ошибка и прошло много времени - удаляем из очереди
                if current_time - sold_time > 7200:
                    items_to_remove.append(check_key)

        # Удаляем обработанные записи
        for key in items_to_remove:
            if key in self._pending_trade_checks:
                del self._pending_trade_checks[key]

        if items_to_remove:
            logger.debug(f"Removed {len(items_to_remove)} items from trade check queue")

    async def _price_check_loop(self):
        """Цикл проверки актуальности цен выставленных предметов (каждые 10 минут)."""
        while self._running:
            try:
                for acc_name in list(self._account_states.keys()):
                    await self._check_listed_prices(acc_name)

                await asyncio.sleep(self.PRICE_CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in price check loop: {e}")
                await asyncio.sleep(60)

    async def _check_listed_prices(self, account_name: str):
        """Проверить актуальность цен выставленных предметов."""
        acc_state = self._account_states.get(account_name)
        if not acc_state or acc_state.status != SalesStatus.ONLINE:
            return

        if not acc_state.csgotm_client:
            return

        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            # Получаем наши выставленные предметы
            our_items = db.get_purchased_items(account_name=account_name)
            listed_items = [item for item in our_items if item.get('status') == 'listed']

            if not listed_items:
                logger.debug(f"[{account_name}] No listed items to check prices")
                return

            logger.info(f"[{account_name}] Checking prices for {len(listed_items)} listed items")

            # Получаем все выставленные предметы с TM для получения текущих цен
            tm_items = acc_state.csgotm_client.get_all_items()
            tm_items_dict = {item.get('item_id'): item for item in tm_items if item.get('status') == '1'}

            overpriced_items = []

            # Предметы, убранные из продаж кнопкой «Больше не напоминать».
            # Читаем один раз на проверку: это «висяки», по которым уведомление
            # приходило бы каждый цикл и ничего бы не меняло.
            try:
                from src.database import TradesDatabase
                sale_ignored = {
                    row['market_hash_name'] for row in TradesDatabase().get_sale_ignored_items()
                }
            except Exception as e:
                logger.warning(f"[{account_name}] Failed to load sale-ignore list: {e}")
                sale_ignored = set()

            for our_item in listed_items:
                market_hash_name = our_item.get('market_hash_name')
                tm_item_id = our_item.get('tm_item_id')  # ID предмета в CSGO.TM
                db_item_id = our_item.get('id')

                if not market_hash_name or not tm_item_id:
                    continue

                if market_hash_name in sale_ignored:
                    logger.debug(f"[{account_name}] Sale ignored, skipping: {market_hash_name}")
                    continue

                # Получаем текущую цену нашего лота
                tm_item = tm_items_dict.get(tm_item_id)
                if not tm_item:
                    continue

                our_price = float(tm_item.get('price', 0))
                if our_price <= 0:
                    continue

                # Получаем актуальную минимальную цену на рынке
                try:
                    market_price_info = acc_state.csgotm_client.get_item_price(market_hash_name)
                    if not market_price_info or 'min_price' not in market_price_info:
                        continue

                    market_min_price = market_price_info['min_price']

                    # Порог для уведомления из настроек (по умолчанию 10%)
                    threshold = 10.0
                    if hasattr(self.state, 'config'):
                        threshold = float(self.state.config.get('price_check_threshold_percent', 10.0))

                    price_diff_pct = ((our_price - market_min_price) / market_min_price * 100) if market_min_price > 0 else 0

                    if price_diff_pct >= threshold:  # Наша цена превышает порог
                        # Получаем цену покупки из БД (order_price или purchase_price)
                        purchase_price = our_item.get('order_price') or our_item.get('purchase_price') or 0

                        overpriced_items.append({
                            'market_hash_name': market_hash_name,
                            'our_price': our_price,
                            'market_min_price': market_min_price,
                            'price_diff_pct': price_diff_pct,
                            'tm_item_id': tm_item_id,
                            'db_item_id': db_item_id,
                            'purchase_price': purchase_price  # Цена покупки на Steam
                        })

                        # diff показываем как отклонение рынка относительно НАШЕЙ цены
                        # (минус = мы дороже топ-1) — тот же знак, что и в Telegram-уведомлении.
                        market_vs_our = ((market_min_price - our_price) / our_price * 100) if our_price > 0 else 0
                        logger.info(
                            f"[{account_name}] Overpriced: {market_hash_name[:40]} "
                            f"(our: {our_price:.0f}₽, top-1: {market_min_price:.0f}₽, diff: {market_vs_our:+.1f}%)"
                        )

                except Exception as e:
                    logger.debug(f"[{account_name}] Failed to check price for {market_hash_name[:30]}: {e}")
                    continue

                await asyncio.sleep(0.5)  # Rate limiting между проверками

            # Если есть завышенные цены - проверяем режим работы
            if overpriced_items:
                logger.info(f"[{account_name}] Found {len(overpriced_items)} overpriced items")
                self.state.add_log(f"[INFO] [{account_name}] Found {len(overpriced_items)} overpriced items")

                # Проверяем настройку автоматического обновления
                auto_update = False
                if hasattr(self.state, 'config'):
                    auto_update = self.state.config.get('auto_update_prices', False)

                if auto_update:
                    # Автоматический режим - обновляем цены без уведомлений
                    self.state.add_log(
                        f"[INFO] [{account_name}] Auto-updating {len(overpriced_items)} overpriced items"
                    )
                    await self._auto_update_prices(account_name, overpriced_items)
                else:
                    # Ручной режим - отправляем уведомление в Telegram
                    self.state.add_log(f"[INFO] [{account_name}] Sending Telegram notification for {len(overpriced_items)} items")
                    await self._send_overpriced_notification(account_name, overpriced_items)
            else:
                logger.debug(f"[{account_name}] All prices are good")

        except Exception as e:
            logger.error(f"[{account_name}] Error checking listed prices: {e}")

    async def _auto_update_prices(self, account_name: str, items: list):
        """Автоматически обновить цены завышенных предметов."""
        acc_state = self._account_states.get(account_name)
        if not acc_state or not acc_state.csgotm_client:
            return

        updated_count = 0
        for item in items:
            try:
                tm_item_id = item['tm_item_id']
                market_min_price = item['market_min_price']
                market_hash_name = item['market_hash_name']

                # Новая цена = рыночная - 1 рубль (топ-1)
                new_price = market_min_price - 1

                # Обновляем цену через API
                success = acc_state.csgotm_client.update_price(tm_item_id, new_price)

                if success:
                    updated_count += 1
                    self.state.add_log(
                        f"[SUCCESS] [{account_name}] Auto-updated: {market_hash_name[:35]} "
                        f"{item['our_price']:.0f}₽ → {new_price:.0f}₽"
                    )

                await asyncio.sleep(1)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to auto-update price for {item['market_hash_name']}: {e}")

        self.state.add_log(f"[INFO] [{account_name}] Auto-update complete: {updated_count}/{len(items)} items updated")

    async def _send_overpriced_notification(self, account_name: str, items: list):
        """Отправить уведомление о завышенных ценах в Telegram с интерактивными кнопками."""
        try:
            # Формируем сообщение
            message = f"⚠️ <b>Завышенные цены на {account_name}</b>\n\n"
            message += f"Найдено предметов с завышенной ценой: {len(items)}\n\n"

            for idx, item in enumerate(items[:5], 1):  # Показываем только первые 5
                name = item['market_hash_name'][:35]
                our_price = item['our_price']
                market_price = item['market_min_price']  # Это уже топ-1
                purchase_price = item.get('purchase_price', 0)

                # Отклонение рынка относительно НАШЕЙ цены: минус = мы дороже рынка (топ-1 ниже нас).
                # Раньше показывали (our-market)/market как "+885%" рядом с "Рынок", что читалось
                # как отклонение рынка и вводило в заблуждение — теперь знак корректный.
                market_vs_our = ((market_price - our_price) / our_price * 100) if our_price > 0 else 0

                message += f"{idx}. {name}\n"
                if purchase_price > 0:
                    # Показываем цену покупки если есть
                    message += f"   💰 Купили: {purchase_price:.0f}₽\n"
                message += f"   Наша: {our_price:.0f}₽ | Рынок: {market_price:.0f}₽ ({market_vs_our:+.1f}%)\n"
                message += f"   Топ-1: {market_price:.0f}₽\n\n"

            if len(items) > 5:
                message += f"... и ещё {len(items) - 5} предметов\n\n"

            message += "💡 Выберите действие:"

            # Отправляем уведомление
            self.state.add_log(f"[INFO] [{account_name}] Sending overpriced items notification ({len(items)} items)")

            # Пытаемся найти Telegram бот
            if hasattr(self, 'telegram_bot') and self.telegram_bot:
                # Создаем кнопки для Telegram
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                    # Сериализуем список предметов в JSON для передачи через callback_data
                    import json
                    # Сохраняем items в состоянии для последующего использования
                    # Используем короткий ID вместо полной сериализации
                    import hashlib
                    import time
                    items_key = hashlib.md5(f"{account_name}:{time.time()}".encode()).hexdigest()[:8]
                    if not hasattr(self.state, '_pending_price_updates'):
                        self.state._pending_price_updates = {}
                    self.state._pending_price_updates[items_key] = {
                        'items': items,
                        'account_name': account_name
                    }

                    keyboard = [
                        [
                            InlineKeyboardButton(
                                f"✅ Выставить топ-1 ({len(items)} предметов)",
                                callback_data=f"update_prices_top1:{account_name}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "✏️ Ввести цену вручную",
                                callback_data=f"update_prices_manual:{items_key}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🔕 Больше не напоминать",
                                callback_data=f"saleignore_choose:{items_key}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "❌ Отмена",
                                callback_data=f"update_prices_cancel:{account_name}"
                            )
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await self.telegram_bot.send_message(message, reply_markup=reply_markup)
                except ImportError:
                    # Если не установлен python-telegram-bot, отправляем без кнопок
                    message += "\n\n• Используйте /update_prices для обновления цен"
                    await self.telegram_bot.send_message(message)
            else:
                # Если бот не настроен, просто логируем
                self.state.add_log(f"[WARNING] [{account_name}] Telegram bot not configured, skipping notification")
                logger.warning(f"Telegram notification skipped: {len(items)} overpriced items found")

        except Exception as e:
            logger.error(f"Failed to send overpriced notification: {e}")

    async def update_overpriced_items(self, account_name: str = None) -> dict:
        """
        Автоматически обновить цены завышенных предметов до топ-1.

        Args:
            account_name: Имя аккаунта (None = все аккаунты)

        Returns:
            dict: {'updated': int, 'skipped': int, 'errors': list}
        """
        results = {'updated': 0, 'skipped': 0, 'errors': []}

        accounts_to_process = []
        if account_name:
            if account_name in self._account_states:
                accounts_to_process = [account_name]
        else:
            accounts_to_process = list(self._account_states.keys())

        if not accounts_to_process:
            msg = f"аккаунт '{account_name}' не найден среди активных ({list(self._account_states.keys())})"
            results['errors'].append(msg)
            logger.warning(f"update_overpriced_items: {msg}")

        for acc_name in accounts_to_process:
            acc_state = self._account_states.get(acc_name)
            if not acc_state or acc_state.status != SalesStatus.ONLINE:
                st = acc_state.status.name if acc_state and hasattr(acc_state.status, 'name') else 'NO_STATE'
                results['errors'].append(f"{acc_name}: не в онлайне (status={st})")
                logger.warning(f"[{acc_name}] update prices skipped: status={st}")
                continue

            if not acc_state.csgotm_client:
                results['errors'].append(f"{acc_name}: нет CSGO.TM клиента")
                continue

            try:
                from src.database import TradesDatabase
                db = TradesDatabase()

                # Получаем наши выставленные предметы
                our_items = db.get_purchased_items(account_name=acc_name)
                listed_items = [item for item in our_items if item.get('status') == 'listed']

                if not listed_items:
                    continue

                # Получаем все выставленные предметы с TM
                tm_items = acc_state.csgotm_client.get_all_items()
                tm_items_dict = {item.get('item_id'): item for item in tm_items if item.get('status') == '1'}

                logger.info(
                    f"[{acc_name}] update prices: {len(listed_items)} listed в БД, "
                    f"{len(tm_items_dict)} активных лотов на TM"
                )

                for our_item in listed_items:
                    market_hash_name = our_item.get('market_hash_name')
                    tm_item_id = our_item.get('tm_item_id')

                    if not market_hash_name or not tm_item_id:
                        # tm_item_id бывает NULL, если предмет был выставлен вне бота
                        # (в _list_item_for_sale он пишется как None при "already on sale").
                        results['skipped'] += 1
                        logger.info(
                            f"[{acc_name}] skip {str(market_hash_name)[:35]}: нет tm_item_id в БД"
                        )
                        continue

                    tm_item = tm_items_dict.get(tm_item_id)
                    if not tm_item:
                        results['skipped'] += 1
                        logger.info(
                            f"[{acc_name}] skip {market_hash_name[:35]}: лот {tm_item_id} "
                            "не найден среди активных на TM (status!=1)"
                        )
                        continue

                    our_price = float(tm_item.get('price', 0))
                    if our_price <= 0:
                        results['skipped'] += 1
                        continue

                    # Получаем актуальную минимальную цену
                    try:
                        market_price_info = acc_state.csgotm_client.get_item_price(market_hash_name)
                        if not market_price_info or 'min_price' not in market_price_info:
                            results['skipped'] += 1
                            logger.info(
                                f"[{acc_name}] skip {market_hash_name[:35]}: не получена цена рынка"
                            )
                            continue

                        market_min_price = market_price_info['min_price']
                        price_diff_pct = ((our_price - market_min_price) / market_min_price * 100) if market_min_price > 0 else 0

                        # Обновляем только если цена завышена на 10%+
                        if price_diff_pct >= 10:
                            # Новая цена = рыночная - 1 рубль (топ-1)
                            new_price = market_min_price - 1

                            # Обновляем цену через API
                            success = acc_state.csgotm_client.update_price(tm_item_id, new_price)

                            if success:
                                results['updated'] += 1
                                self.state.add_log(
                                    f"[SUCCESS] [{acc_name}] Price updated: {market_hash_name[:35]} "
                                    f"{our_price:.0f}₽ → {new_price:.0f}₽"
                                )
                            else:
                                results['skipped'] += 1
                                self.state.add_log(
                                    f"[WARNING] [{acc_name}] Failed to update price for {market_hash_name[:35]}"
                                )

                        await asyncio.sleep(1)  # Rate limiting

                    except Exception as e:
                        results['errors'].append(f"{acc_name}/{market_hash_name[:20]}: {str(e)}")
                        logger.error(f"Failed to update price for {market_hash_name}: {e}")

            except Exception as e:
                results['errors'].append(f"{acc_name}: {str(e)}")
                logger.error(f"Error updating prices for {acc_name}: {e}")

        self.state.add_log(
            f"[INFO] Price update complete: {results['updated']} updated, "
            f"{results['skipped']} skipped, {len(results['errors'])} errors"
        )

        return results

    async def update_overpriced_items_to_top1(self, account_name: str) -> dict:
        """
        Обновить завышенные цены до топ-1 (алиас для update_overpriced_items).

        Args:
            account_name: Имя аккаунта

        Returns:
            dict: {'updated': int, 'skipped': int, 'errors': list}
        """
        return await self.update_overpriced_items(account_name)

    async def _update_item_price(self, account_name: str, tm_item_id: str, new_price: float) -> bool:
        """
        Обновить цену конкретного предмета.

        Args:
            account_name: Имя аккаунта
            tm_item_id: ID предмета в CSGO.TM
            new_price: Новая цена в рублях

        Returns:
            bool: True если успешно
        """
        acc_state = self._account_states.get(account_name)
        if not acc_state or not acc_state.csgotm_client:
            logger.error(f"[{account_name}] CSGO.TM client not available")
            return False

        try:
            # Обновляем цену через CSGO.TM API
            success = acc_state.csgotm_client.update_price(tm_item_id, new_price)

            if success:
                logger.info(f"[{account_name}] Updated price for item {tm_item_id}: {new_price:.0f}₽")
                self.state.add_log(f"[INFO] [{account_name}] Price updated: {new_price:.0f}₽")
            else:
                logger.error(f"[{account_name}] Failed to update price for item {tm_item_id}")

            return success

        except Exception as e:
            logger.error(f"[{account_name}] Error updating price for item {tm_item_id}: {e}")
            return False

    # ============ Public API ============

    def get_status(self, account_name: str) -> SalesStatus:
        """Получить статус продаж для аккаунта."""
        acc_state = self._account_states.get(account_name)
        return acc_state.status if acc_state else SalesStatus.STOPPED

    def get_stats(self, account_name: str) -> Optional[SalesStats]:
        """Получить статистику продаж для аккаунта."""
        acc_state = self._account_states.get(account_name)
        return acc_state.stats if acc_state else None

    def get_sell_status(self, account_name: str) -> Dict[str, bool]:
        """Получить статус возможности продаж для аккаунта."""
        acc_state = self._account_states.get(account_name)
        return acc_state.sell_status if acc_state else {}

    def is_running(self) -> bool:
        """Проверить, запущен ли сервис."""
        return self._running

    def get_all_statuses(self) -> Dict[str, SalesStatus]:
        """Получить статусы всех аккаунтов."""
        return {name: state.status for name, state in self._account_states.items()}

    async def manual_ping(self, account_name: str):
        """Ручной ping для аккаунта."""
        if account_name not in self._account_states:
            await self._init_account_state(account_name)

        await self._do_ping(account_name)

    async def manual_list_item(self, account_name: str, steam_id: str, price: float):
        """Вручную выставить предмет на продажу."""
        acc_state = self._account_states.get(account_name)
        if not acc_state or not acc_state.csgotm_client:
            self.state.add_log(f"[ERROR] [{account_name}] Not initialized")
            return False

        result = acc_state.csgotm_client.add_to_sale_by_steam_id(
            steam_item_id=steam_id,
            price=price,
            currency="RUB"
        )

        if result.success:
            acc_state.stats.items_listed += 1
            self.state.add_log(f"[SUCCESS] [{account_name}] Listed item @ {price:.0f} RUB")
            return True
        else:
            self.state.add_log(f"[ERROR] [{account_name}] Failed: {result.message}")
            return False

    async def _wait_for_inventory_update(self, account_name: str, max_wait_time: int = 60) -> bool:
        """
        Ждать завершения обновления инвентаря на CSGO.TM.

        Args:
            account_name: Имя аккаунта
            max_wait_time: Максимальное время ожидания в секундах

        Returns:
            True если обновление завершено успешно
        """
        acc_state = self._account_states.get(account_name)
        if not acc_state or not acc_state.csgotm_client:
            return False

        wait_interval = 5  # Проверяем каждые 5 секунд
        waited = 0

        # Флаг is_updating у маркета залипает: наблюдали True больше 10 минут подряд,
        # хотя last_time_success_update уже обновился (и мы сами его держим, дёргая
        # update-inventory на каждой попытке). Поэтому основной критерий готовности —
        # СДВИГ last_time_success_update относительно момента запроса, а не флаг.
        baseline = 0
        try:
            st0 = acc_state.csgotm_client.inventory_status() or {}
            baseline = int(st0.get("last_time_success_update", 0) or 0)
        except Exception:
            pass

        while waited < max_wait_time:
            await asyncio.sleep(wait_interval)
            waited += wait_interval

            # Проверяем статус обновления
            status = acc_state.csgotm_client.inventory_status()
            fresh = False
            if status:
                try:
                    fresh = int(status.get("last_time_success_update", 0) or 0) > baseline
                except Exception:
                    fresh = False
            if status and (fresh or not status.get("is_updating", False)):
                items_count = status.get("items", 0)
                # Документация TM: после обновления инвентаря нужно подождать 10-20 сек,
                # иначе add-to-sale отвечает item_not_in_inventory — флаг is_updating
                # снимается раньше, чем предмет реально появляется в кэше.
                await asyncio.sleep(self.INVENTORY_SETTLE_SEC)
                self.state.add_log(
                    f"[SUCCESS] [{account_name}] Inventory updated ({items_count} items in cache)"
                )
                return True

            self.state.add_log(
                f"[INFO] [{account_name}] Inventory update in progress... ({waited}s/{max_wait_time}s)"
            )

        self.state.add_log(
            f"[WARNING] [{account_name}] Inventory update timeout after {max_wait_time}s"
        )
        return False

    async def update_inventory(self, account_name: str, wait_for_completion: bool = False):
        """
        Обновить инвентарь на CSGO.TM.

        Args:
            account_name: Имя аккаунта
            wait_for_completion: Ждать ли завершения обновления
        """
        self.state.add_log(f"[DEBUG] [{account_name}] update_inventory called")

        acc_state = self._account_states.get(account_name)
        if not acc_state:
            self.state.add_log(f"[WARNING] [{account_name}] No account state - initializing...")
            # Попробуем инициализировать
            if self.account_service and self.account_service.account_manager:
                account = self.account_service.account_manager.get_account(account_name)
                if account and account.csgotm_client:
                    success = account.csgotm_client.update_inventory()
                    if success:
                        self.state.add_log(f"[SUCCESS] [{account_name}] Inventory update requested (direct)")
                    else:
                        self.state.add_log(f"[ERROR] [{account_name}] Failed to update inventory (direct)")
                    return success

            self.state.add_log(f"[ERROR] [{account_name}] Cannot update inventory - no client")
            return False

        if not acc_state.csgotm_client:
            self.state.add_log(f"[ERROR] [{account_name}] No CSGO.TM client")
            return False

        success = acc_state.csgotm_client.update_inventory()
        if success:
            self.state.add_log(f"[SUCCESS] [{account_name}] Inventory update requested")

            # Если нужно ждать завершения
            if wait_for_completion:
                await self._wait_for_inventory_update(account_name)
        else:
            self.state.add_log(f"[ERROR] [{account_name}] Failed to update inventory")

        return success
