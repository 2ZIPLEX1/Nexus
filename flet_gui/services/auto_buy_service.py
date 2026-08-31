"""
Сервис автопокупки предметов для поддержания минимального количества в инвентаре.
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

from flet_gui.state.app_state import AppState

logger = logging.getLogger(__name__)


class AutoBuyItem:
    """Предмет для автопокупки."""
    def __init__(self, url: str, name: str, is_charm: bool = False):
        self.url = url
        self.name = name
        self.is_charm = is_charm  # Брелок или скин
        self.current_count = 0
        self.target_count = 25 if is_charm else 10
        self.pending_orders = 0


class AutoBuyService:
    """Сервис автопокупки предметов."""

    CHECK_INTERVAL = 300  # Проверка каждые 5 минут

    def __init__(self, state: AppState, account_service=None, proxy_service=None):
        self.state = state
        self.account_service = account_service
        self.proxy_service = proxy_service
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        self.items: List[AutoBuyItem] = []
        self.selected_account_name: Optional[str] = None  # Выбранный аккаунт для покупок
        self._load_items()

    def _load_items(self):
        """Загрузить список предметов из skins.txt."""
        skins_file = Path("skins.txt")
        if not skins_file.exists():
            logger.warning("skins.txt not found")
            return

        try:
            with open(skins_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Формат: URL название
                    parts = line.split(' ', 1)
                    if len(parts) < 2:
                        continue

                    url = parts[0]
                    name = parts[1]

                    # Определяем брелок по названию
                    is_charm = 'Charm |' in name

                    item = AutoBuyItem(url, name, is_charm)
                    self.items.append(item)

            logger.info(f"Loaded {len(self.items)} items for auto-buy")

            # Подсчитываем скины и брелки
            charms_count = sum(1 for item in self.items if item.is_charm)
            skins_count = len(self.items) - charms_count
            logger.info(f"Skins: {skins_count}, Charms: {charms_count}")

        except Exception as e:
            logger.error(f"Failed to load skins.txt: {e}")

    def is_auto_buy_item(self, item_name: str) -> bool:
        """Проверить, является ли предмет предметом автопокупки."""
        return any(item.name == item_name for item in self.items)

    async def start(self):
        """Запустить сервис."""
        if self._running:
            logger.warning("AutoBuy service already running")
            return

        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info("AutoBuy service started")
        self.state.add_log("[INFO] AutoBuy service started")

    async def stop(self):
        """Остановить сервис."""
        if not self._running:
            return

        self._running = False

        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass

        logger.info("AutoBuy service stopped")
        self.state.add_log("[INFO] AutoBuy service stopped")

    def is_running(self) -> bool:
        """Проверить, запущен ли сервис."""
        return self._running

    async def _check_loop(self):
        """Цикл проверки инвентаря и создания ордеров."""
        while self._running:
            try:
                await self._check_inventory()
                await asyncio.sleep(self.CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto-buy check loop: {e}")
                self.state.add_log(f"[ERROR] AutoBuy check error: {e}")
                await asyncio.sleep(60)

    async def _check_inventory(self):
        """Проверить инвентарь и создать ордера при необходимости."""
        if not self.account_service or not self.account_service.account_manager:
            logger.warning("Account service not available")
            return

        # Получаем все аккаунты
        accounts = self.account_service.account_manager.accounts
        if not accounts:
            return

        # Подсчитываем предметы во всех инвентарях
        for item in self.items:
            item.current_count = 0
            item.pending_orders = 0  # Сбрасываем pending_orders перед синхронизацией

        # Собираем все активные ордера со всех аккаунтов для синхронизации pending_orders
        all_orders = {}
        for account in accounts:
            if not account.is_logged_in():
                continue

            try:
                existing_orders = await self._get_existing_orders(account)
                # Объединяем ордера со всех аккаунтов
                for item_name, quantity in existing_orders.items():
                    all_orders[item_name] = all_orders.get(item_name, 0) + quantity
            except Exception as e:
                logger.error(f"Failed to get orders for {account.name}: {e}")

        # Синхронизируем pending_orders с реальными ордерами
        for item in self.items:
            item.pending_orders = all_orders.get(item.name, 0)
            if item.pending_orders > 0:
                logger.info(f"Synced pending_orders for {item.name}: {item.pending_orders}")

        for account in accounts:
            # Проверяем что аккаунт залогинен
            if not account.is_logged_in():
                logger.info(f"Account {account.name} is not logged in, skipping")
                continue

            try:
                # Получаем инвентарь залогиненного аккаунта
                logger.info(f"Checking inventory for account: {account.name}")
                inventory = await self._get_inventory(account)
                logger.info(f"Got {len(inventory)} items from {account.name}")

                # Подсчитываем предметы
                for item in self.items:
                    count = sum(1 for inv_item in inventory if inv_item.get('market_hash_name') == item.name)
                    if count > 0:
                        logger.info(f"Found {count} of {item.name} in {account.name}")
                    item.current_count += count

            except Exception as e:
                logger.error(f"Failed to get inventory for {account.name}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        # Логируем только общую статистику при мониторинге
        items_to_buy = []
        for item in self.items:
            needed = item.target_count - item.current_count - item.pending_orders
            if needed > 0:
                items_to_buy.append((item, needed))

        if items_to_buy:
            total_needed = sum(count for _, count in items_to_buy)
            logger.info(f"Monitoring: {total_needed} items needed across {len(items_to_buy)} types")

    async def _get_inventory(self, account) -> List[Dict]:
        """Получить инвентарь аккаунта через активный Steam клиент."""
        if not account.steam_client:
            logger.warning(f"Steam client not available for {account.name}")
            return []

        # Проверяем что аккаунт залогинен
        if not account.is_logged_in():
            logger.warning(f"Account {account.name} is not logged in")
            return []

        try:
            from src.async_helper import get_async_runner

            # Получаем AsyncRunner который используется для логина
            runner = get_async_runner()

            # Выполняем get_inventory в том же event loop где был создан клиент
            inventory_items = runner.run_async(
                account.steam_client.get_inventory(appid=730),
                timeout=60.0
            )

            # Конвертируем InventoryItem в dict
            inventory_dicts = []
            for item in inventory_items:
                inventory_dicts.append({
                    'assetid': item.assetid,
                    'classid': item.classid,
                    'instanceid': item.instanceid,
                    'amount': item.amount,
                    'name': item.name,
                    'market_hash_name': item.market_hash_name,
                    'market_name': item.market_name,
                    'icon_url': item.icon_url,
                    'tradable': item.tradable,
                    'marketable': item.marketable,
                })

            logger.info(f"Fetched {len(inventory_dicts)} items from {account.name} inventory")
            return inventory_dicts

        except Exception as e:
            logger.error(f"Failed to get inventory for {account.name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def _get_item_price(self, steam_market_api, item_name: str) -> Optional[float]:
        """Получить lowest sell order цену предмета через Steam Market API (для быстрой покупки)."""
        try:
            # Получаем информацию о buy/sell orders через Steam Market API
            buy_order_info = await steam_market_api.get_buy_orders(item_name)

            if not buy_order_info.success:
                logger.warning(f"Failed to get orders info for {item_name}")
                return None

            # Используем lowest_sell_order для быстрой покупки
            if buy_order_info.lowest_sell_order and buy_order_info.lowest_sell_order > 0:
                logger.info(f"Price for {item_name}: {buy_order_info.lowest_sell_order:.2f} RUB (lowest sell order)")
                return buy_order_info.lowest_sell_order

            # Fallback на highest_buy_order если нет sell orders
            if buy_order_info.highest_buy_order and buy_order_info.highest_buy_order > 0:
                logger.info(f"Price for {item_name}: {buy_order_info.highest_buy_order:.2f} RUB (highest buy order, no sell orders)")
                return buy_order_info.highest_buy_order

            logger.warning(f"No orders found for {item_name}")
            return None

        except Exception as e:
            logger.error(f"Failed to get price for {item_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def _get_existing_orders(self, account) -> dict:
        """Получить существующие ордера аккаунта. Возвращает dict {item_name: quantity}."""
        existing_orders = {}
        try:
            from src.async_helper import get_async_runner
            runner = get_async_runner()

            # Получаем все активные ордера
            my_orders = runner.run_async(
                account.steam_client.get_my_market_orders(),
                timeout=30.0
            )

            # Подсчитываем количество по каждому предмету
            for order in my_orders:
                if order.get('type') == 'buy':
                    item_name = order.get('market_hash_name', '')
                    # Используем quantity_remaining (оставшееся кол-во), а не quantity (изначальное)
                    quantity_remaining = order.get('quantity_remaining', order.get('quantity', 1))
                    if item_name:
                        existing_orders[item_name] = existing_orders.get(item_name, 0) + quantity_remaining

            logger.info(f"Found {len(existing_orders)} items with existing buy orders")

        except Exception as e:
            logger.error(f"Failed to get existing orders: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return existing_orders

    async def _create_orders(self, items_to_buy: List[tuple]):
        """
        Создать ордера на покупку недостающих предметов.

        Args:
            items_to_buy: List of (AutoBuyItem, count) tuples
        """
        if not self.account_service or not self.account_service.account_manager:
            logger.error("Account service not available")
            self.state.add_log("[ERROR] Account service not available")
            return

        # Получаем выбранный или первый залогиненный аккаунт
        accounts = self.account_service.account_manager.accounts
        account = None

        # Если выбран конкретный аккаунт, используем его
        if self.selected_account_name:
            for acc in accounts:
                if acc.name == self.selected_account_name and acc.is_logged_in():
                    account = acc
                    logger.info(f"Using selected account: {self.selected_account_name}")
                    break

            if not account:
                # Выбранный аккаунт не залогинен
                self.state.add_log(f"[ERROR] Selected account '{self.selected_account_name}' is not logged in")
                return
        else:
            # Если не выбран - берем первый залогиненный
            for acc in accounts:
                if acc.is_logged_in():
                    account = acc
                    logger.info(f"Using first logged in account: {acc.name}")
                    break

            if not account:
                self.state.add_log("[ERROR] No logged in account found")
                return

        # Получаем Steam client для создания ордеров
        if not account.steam_client:
            self.state.add_log("[ERROR] Steam client not available")
            return

        # Получаем существующие ордера чтобы не создавать дубликаты
        self.state.add_log("[INFO] Checking existing orders...")
        existing_orders = await self._get_existing_orders(account)

        # Создаем SteamMarketAPI для получения цен
        from src.bottm.api.steam_market import SteamMarketAPI
        from src.bottm.config import Currency

        # ВАЖНО: Всегда получаем цены в RUB, т.к. код рассчитан на рубли
        # Конвертация в валюту кошелька происходит в create_buy_order
        currency = Currency.RUB

        # Используем пул прокси из proxies.txt для ротации и избежания rate limit
        proxy_list = None
        if self.proxy_service and self.proxy_service.proxy_manager:
            # Получаем credentials из прокси аккаунта
            proxy_credentials = None
            if account.config.proxy and account.config.proxy.enabled and account.config.proxy.url:
                # Извлекаем username:password из URL аккаунта
                account_proxy = account.config.proxy.url
                if '@' in account_proxy:
                    # Формат: socks5://user:pass@host:port
                    protocol_and_auth = account_proxy.split('@')[0]
                    if '://' in protocol_and_auth:
                        auth_part = protocol_and_auth.split('://')[1]
                        if ':' in auth_part:
                            proxy_credentials = auth_part  # user:pass

            # Добавляем credentials ко всем прокси из proxies.txt
            original_proxies = self.proxy_service.proxy_manager.proxies
            proxy_list = []

            for proxy_url in original_proxies:
                if proxy_credentials and '@' not in proxy_url:
                    # Добавляем credentials к прокси без авторизации
                    # socks5://host:port -> socks5://user:pass@host:port
                    if '://' in proxy_url:
                        protocol, rest = proxy_url.split('://', 1)
                        proxy_with_auth = f"{protocol}://{proxy_credentials}@{rest}"
                        proxy_list.append(proxy_with_auth)
                    else:
                        proxy_list.append(proxy_url)
                else:
                    proxy_list.append(proxy_url)

            logger.info(f"Using {len(proxy_list)} proxies from proxies.txt with auth for Steam Market API")
        else:
            # Fallback на прокси аккаунта
            if account.config.proxy and account.config.proxy.enabled and account.config.proxy.url:
                proxy_list = [account.config.proxy.url]
                logger.info(f"Using account proxy for Steam Market API")

        steam_market_api = SteamMarketAPI(
            currency=currency,
            proxy_list=proxy_list,
            requests_per_proxy=15  # Ротация каждые 15 запросов
        )

        total_created = 0
        total_failed = 0
        total_skipped = 0
        processed = 0
        total_items = len(items_to_buy)

        # Получаем баланс и лимит для проверки
        from src.async_helper import get_async_runner
        runner = get_async_runner()
        try:
            wallet_info = runner.run_async(
                account.steam_client.get_wallet_balance(),
                timeout=10.0
            )
            balance = wallet_info.balance  # Уже в рублях/евро (деление на 100 в get_wallet_balance)
            wallet_currency = wallet_info.currency  # Код валюты (3 = EUR, 5 = RUB, 1 = USD)
            order_limit = balance * 10
            logger.info(f"Wallet balance: {balance:.2f} (currency {wallet_currency}), order limit: {order_limit:.2f}")

            # Получаем текущую сумму ордеров
            my_orders = runner.run_async(
                account.steam_client.get_my_market_orders(),
                timeout=30.0
            )
            current_orders_sum = 0
            for order in my_orders:
                if order.get('type') == 'buy':
                    price = order.get('price', 0)  # Уже в рублях/евро (деление на 100 в get_my_market_orders)
                    quantity = order.get('quantity_remaining', order.get('quantity', 1))
                    current_orders_sum += (price * quantity)

            logger.info(f"Current orders sum: {current_orders_sum:.2f}, available: {order_limit - current_orders_sum:.2f}")
            self.state.add_log(f"[INFO] Current orders: {current_orders_sum:.2f}/{order_limit:.2f}, available: {order_limit - current_orders_sum:.2f}")

        except Exception as e:
            logger.error(f"Failed to get wallet info: {e}")
            # Продолжаем без проверки лимита
            order_limit = None
            current_orders_sum = 0
            wallet_currency = 5  # Fallback на RUB

        # Настраиваем callback для ручного подтверждения (аккаунты без identity_secret)
        no_identity_secret = not account.config.steam_identity_secret
        if no_identity_secret:
            from src.manual_confirmation import ManualConfirmationWaiter
            from flet_gui.state.events import EventBus, EventType

            def _on_waiting(account_name, confirmation_id):
                self.state.add_log(
                    f"[WAITING] [{account_name}] Подтвердите buy order в Steam Guard на телефоне, "
                    f"затем нажмите кнопку 'Подтвердил ✓' в интерфейсе"
                )
                EventBus().emit(EventType.CONFIRMATION_REQUIRED, {
                    "account_name": account_name,
                })

            def _on_confirmed(account_name):
                self.state.add_log(f"[OK] [{account_name}] Подтверждение получено! Продолжаем выставление ордеров...")
                EventBus().emit(EventType.CONFIRMATION_COMPLETED, {
                    "account_name": account_name,
                })

            waiter = ManualConfirmationWaiter(
                steam_client=account.steam_client,
                account_name=account.name,
                on_waiting=_on_waiting,
                on_confirmed=_on_confirmed,
            )
            account.steam_client.set_confirmation_callback(waiter.wait_for_confirmation)
            self.state.add_log(
                f"[INFO] Аккаунт без identity_secret — первый ордер потребует подтверждения на телефоне. "
                f"Нажмите 'Подтвердил ✓' в баннере после подтверждения."
            )

        for item, count in items_to_buy:
            processed += 1
            try:
                logger.info(f"Processing item {processed}/{total_items}: {item.name}, need {count}")
                self.state.add_log(f"[INFO] Processing {processed}/{total_items}: {item.name}")

                # Проверяем существующие ордера на этот предмет
                existing_count = existing_orders.get(item.name, 0)
                if existing_count > 0:
                    # Уменьшаем количество на уже существующие ордера
                    adjusted_count = max(0, count - existing_count)
                    if adjusted_count == 0:
                        self.state.add_log(f"[INFO] Skipping {item.name}: already have {existing_count} orders")
                        total_skipped += count
                        continue
                    elif adjusted_count < count:
                        self.state.add_log(f"[INFO] {item.name}: need {count}, have {existing_count} orders, creating {adjusted_count} more")
                        count = adjusted_count

                # Получаем lowest sell order цену через Steam Market API (для быстрой покупки)
                logger.info(f"Getting price for {item.name}...")
                self.state.add_log(f"[INFO] Getting price for {item.name}...")

                # Retry логика для получения цены (может быть rate limit)
                price = None
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        price = await self._get_item_price(steam_market_api, item.name)
                        if price:
                            break
                        # Если цена не получена, подождем и попробуем снова
                        if attempt < max_retries - 1:
                            logger.warning(f"No price returned for {item.name}, retry {attempt + 1}/{max_retries}")
                            await asyncio.sleep(5)
                    except Exception as price_error:
                        logger.error(f"Exception while getting price for {item.name} (attempt {attempt + 1}): {price_error}")
                        if attempt < max_retries - 1:
                            self.state.add_log(f"[WARNING] Error getting price for {item.name}, retrying in 5 seconds...")
                            await asyncio.sleep(5)
                        else:
                            self.state.add_log(f"[ERROR] Failed to get price for {item.name} after {max_retries} attempts: {str(price_error)}")
                            total_failed += count

                if not price:
                    self.state.add_log(f"[ERROR] Could not get price for {item.name}, skipping")
                    total_failed += count
                    continue

                # Создаем buy order по lowest sell order цене (для моментальной покупки)
                buy_price = price  # В RUB
                order_total_rub = buy_price * count

                # Конвертируем в валюту кошелька для проверки лимита
                from src.currency_rates import convert_rub_to_currency
                order_total = convert_rub_to_currency(order_total_rub, wallet_currency)

                # Проверяем лимит ордеров
                if order_limit is not None:
                    available = order_limit - current_orders_sum
                    if order_total > available:
                        self.state.add_log(
                            f"[WARNING] Order limit reached! Need {order_total:.2f}, available {available:.2f}. Stopping."
                        )
                        logger.warning(f"Order limit reached. Stopping order creation.")
                        break

                self.state.add_log(
                    f"[INFO] Creating buy order: {item.name} x{count} @ {buy_price:.2f} RUB (instant buy, total: {order_total:.2f})"
                )

                # Создаем ордер через steam_client используя AsyncRunner
                # (нужно для совместимости с Flet event loop)
                from src.async_helper import get_async_runner
                runner = get_async_runner()

                try:
                    result = runner.run_async(
                        account.steam_client.create_buy_order(
                            market_hash_name=item.name,
                            price=buy_price,
                            quantity=count,
                            currency=5,  # RUB
                            appid=730
                        ),
                        timeout=30.0
                    )

                    if result.success:
                        self.state.add_log(
                            f"[SUCCESS] Order created: {item.name} x{count} @ {buy_price:.2f} RUB (ID: {result.order_id})"
                        )
                        # pending_orders синхронизируется из реальных ордеров в _check_inventory()
                        total_created += count
                        # Обновляем текущую сумму ордеров
                        if order_limit is not None:
                            current_orders_sum += order_total
                    else:
                        self.state.add_log(
                            f"[ERROR] Failed to create order for {item.name}: {result.error}"
                        )
                        total_failed += count

                except Exception as order_error:
                    logger.error(f"Exception while creating order for {item.name}: {order_error}")
                    self.state.add_log(f"[ERROR] Exception creating order for {item.name}: {str(order_error)}")
                    total_failed += count

                # Пауза между ордерами чтобы не спамить API
                # Увеличиваем паузу после каждых 5 ордеров
                if total_created > 0 and total_created % 5 == 0:
                    logger.info(f"Created {total_created} orders, taking a longer break to avoid rate limit")
                    self.state.add_log(f"[INFO] Taking a break after {total_created} orders to avoid rate limit...")
                    await asyncio.sleep(10)  # Длинная пауза после каждых 5 ордеров
                else:
                    await asyncio.sleep(3)  # Обычная пауза между ордерами

            except Exception as e:
                logger.error(f"Failed to create order for {item.name}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.state.add_log(f"[ERROR] Failed to create order for {item.name}: {e}")
                total_failed += count

        # Итоговое сообщение
        skipped_msg = f", {total_skipped} skipped (already have orders)" if total_skipped > 0 else ""
        not_processed = total_items - processed
        not_processed_msg = f", {not_processed} not processed (limit reached)" if not_processed > 0 else ""

        self.state.add_log(
            f"[INFO] Order creation complete: {total_created} created, {total_failed} failed{skipped_msg}{not_processed_msg}"
        )

        # Показываем актуальную сумму ордеров если доступна
        if order_limit is not None:
            self.state.add_log(
                f"[INFO] Current orders sum: {current_orders_sum:.2f}/{order_limit:.2f} (available: {order_limit - current_orders_sum:.2f})"
            )

        # Закрываем SteamMarketAPI сессию
        await steam_market_api.close()

    def set_selected_account(self, account_name: Optional[str]):
        """Установить выбранный аккаунт для покупок. None = auto mode."""
        self.selected_account_name = account_name
        if account_name:
            logger.info(f"AutoBuy: Selected account set to {account_name}")
        else:
            logger.info(f"AutoBuy: Auto mode enabled (will use first logged in account)")

    def get_selected_account(self) -> Optional[str]:
        """Получить имя выбранного аккаунта."""
        return self.selected_account_name

    def get_available_accounts(self) -> List[str]:
        """Получить список доступных аккаунтов."""
        if not self.account_service or not self.account_service.account_manager:
            return []
        return [acc.name for acc in self.account_service.account_manager.accounts if acc.config.enabled]

    def get_stats(self) -> Dict:
        """Получить статистику по предметам."""
        stats = {
            'total_items': len(self.items),
            'skins': [],
            'charms': [],
        }

        for item in self.items:
            item_info = {
                'name': item.name,
                'current': item.current_count,
                'target': item.target_count,
                'pending': item.pending_orders,
                'needed': max(0, item.target_count - item.current_count - item.pending_orders),
            }

            if item.is_charm:
                stats['charms'].append(item_info)
            else:
                stats['skins'].append(item_info)

        return stats
