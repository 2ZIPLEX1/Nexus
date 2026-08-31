"""
Trading Bot - основная логика автоматической торговли.

Workflow:
1. Читает profitable_items из bottm.db
2. Фильтрует предметы (положительный профит, в рамках лимитов)
3. Создает бай-ордера на Steam Market
4. Отслеживает исполненные ордера
5. Добавляет купленные предметы в БД (7-дневный холд)
6. Проверяет предметы после холда
7. Продает на CSGO.TM
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional

from src.logger import get_logger
from src.account_manager import Account
from src.database import trades_db
from src.bottm_parser import bottm_parser
from src.currency_converter import currency_converter
from config import settings

logger = get_logger(__name__)


def _first_number(*values) -> Optional[float]:
    """Return the first value that can be safely used in numeric comparisons."""
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


class TradingBot:
    """
    Бот для автоматической торговли Steam Market → CSGO.TM.
    """

    # Задержка между проверками ордеров (секунды)
    ORDER_CHECK_INTERVAL = 60

    def __init__(self, account: Account):
        """
        Initialize trading bot for an account.

        Args:
            account: Account instance with logged in clients
        """
        self.account = account
        self.name = account.name

        # Загружаем настройки из bot_config.json
        self._load_config()

        logger.info(f"[{self.name}] Trading bot initialized")

    def _load_config(self):
        """Загрузить настройки из bot_config.json"""
        import json
        from pathlib import Path

        config_path = Path("bot_config.json")
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Настройки профита и цен
            self.MIN_PROFIT_PCT = config.get('min_profit_pct', -7.0)
            self.TRADE_MIN_PRICE = config.get('trade_min_price', 1000.0)
            self.TRADE_MAX_PRICE = config.get('trade_max_price', 5000.0)
            self.PROXY_FILE = config.get('proxy_file', 'proxies.txt')
            self.REQUESTS_PER_PROXY = config.get('requests_per_proxy', 50)
            self.ORDER_RATE_LIMIT_COOLDOWN = config.get('order_rate_limit_cooldown', 180)

            logger.info(f"[{self.name}] Config loaded: min_profit={self.MIN_PROFIT_PCT}%, price_range={self.TRADE_MIN_PRICE}-{self.TRADE_MAX_PRICE}")
        else:
            # Значения по умолчанию из bot_config.json
            self.MIN_PROFIT_PCT = -7.0
            self.TRADE_MIN_PRICE = 1000.0
            self.TRADE_MAX_PRICE = 5000.0
            self.PROXY_FILE = 'proxies.txt'
            self.REQUESTS_PER_PROXY = 50
            self.ORDER_RATE_LIMIT_COOLDOWN = 180
            logger.warning(f"[{self.name}] bot_config.json not found, using defaults")

    # ============ Проверка актуальности цен ============

    def _load_proxy_list(self) -> list[str]:
        from pathlib import Path

        proxy_path = Path(self.PROXY_FILE)
        if not proxy_path.exists():
            return []

        return [
            line.strip()
            for line in proxy_path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.strip().startswith('#')
        ]

    @staticmethod
    def _is_rate_limit_error(message: str) -> bool:
        message = (message or '').lower()
        return '429' in message or 'rate limit' in message or 'too many requests' in message

    async def _get_current_steam_buy_price(self, item_name: str) -> Optional[float]:
        proxies = self._load_proxy_list()
        if proxies:
            try:
                from src.bottm.api.steam_market import SteamMarketAPI
                from src.bottm.config import Currency

                api = SteamMarketAPI(
                    currency=Currency.RUB,
                    proxy_list=proxies,
                    requests_per_proxy=self.REQUESTS_PER_PROXY,
                )
                try:
                    buy_orders = await api.get_buy_orders(item_name, max_retries=min(len(proxies), 5))
                    if buy_orders.success and buy_orders.highest_buy_order:
                        return buy_orders.highest_buy_order
                    logger.warning(
                        f"[{self.name}] Steam proxy recheck failed for {item_name}: "
                        f"{buy_orders.error or 'no buy order'}"
                    )
                finally:
                    await api.close()
            except Exception as e:
                logger.warning(f"[{self.name}] Steam proxy recheck error for {item_name}: {e}")

        histogram = await self.account.steam_client.get_market_histogram(item_name)
        if histogram and histogram.get('highest_buy_order'):
            return histogram['highest_buy_order']

        return None

    async def _verify_item_profitability(self, item: dict) -> dict:
        """
        Проверить актуальность профита перед созданием ордера.

        Получает текущие цены с Steam Market и CSGO.TM,
        пересчитывает профит и рекомендует цену для ордера.

        Args:
            item: Item data from database

        Returns:
            Dict with:
            - is_profitable: bool (стоит ли создавать ордер)
            - current_steam_price: float (текущая цена на Steam)
            - current_csgotm_price: float (текущая цена на CSGO.TM)
            - current_profit_pct: float (текущий профит в %)
            - recommended_price: float (рекомендуемая цена для ордера)
            - reason: str (причина, если not profitable)
        """
        item_name = item['name']

        try:
            logger.info(f"[{self.name}] 🔍 Проверка актуальности цен для {item_name}...")

            # Получаем текущие цены на Steam Market
            current_steam_price = await self._get_current_steam_buy_price(item_name)
            if not current_steam_price:
                return {
                    'is_profitable': False,
                    'reason': 'Не удалось получить данные Steam Market'
                }


            # Получаем текущие цены на CSGO.TM
            if not self.account.csgotm_client:
                return {
                    'is_profitable': False,
                    'reason': 'CSGO.TM клиент не инициализирован'
                }

            csgotm_price_data = self.account.csgotm_client.get_item_price(item_name)
            if not csgotm_price_data or not csgotm_price_data.get('min_price'):
                return {
                    'is_profitable': False,
                    'reason': 'Не удалось получить данные CSGO.TM'
                }

            # Используем консервативный подход: минимум между средней и текущей ценой
            # Это аналогично логике сканера для избежания фейкового профита
            min_price = csgotm_price_data['min_price']
            avg_price = csgotm_price_data.get('average_price', min_price)
            current_csgotm_price = min(avg_price, min_price)

            logger.debug(
                f"[{self.name}] CSGO.TM prices: min={min_price:.2f}, avg={avg_price:.2f}, "
                f"using conservative={current_csgotm_price:.2f}"
            )

            # Рассчитываем профит БЕЗ учета комиссии CSGO.TM
            # Профит = (цена продажи - затраты) / затраты * 100%
            if current_steam_price > 0:
                current_profit_pct = ((current_csgotm_price - current_steam_price) / current_steam_price) * 100
            else:
                current_profit_pct = 0

            # Проверка на фейковые предметы
            # Сравниваем текущую цену Steam с рекомендованной из базы
            recommended_price = item.get('recommended_price', current_steam_price)
            if recommended_price > 0:
                price_diff_pct = abs(current_steam_price - recommended_price) / recommended_price * 100
                if price_diff_pct > 20:  # Если разница больше 20%
                    return {
                        'is_profitable': False,
                        'current_steam_price': current_steam_price,
                        'current_csgotm_price': current_csgotm_price,
                        'current_profit_pct': current_profit_pct,
                        'reason': f'Подозрение на фейк: цена отличается на {price_diff_pct:.1f}% (текущая {current_steam_price:.2f} vs рекомендованная {recommended_price:.2f})'
                    }

            # Проверяем минимальный профит
            if current_profit_pct < self.MIN_PROFIT_PCT:
                return {
                    'is_profitable': False,
                    'current_steam_price': current_steam_price,
                    'current_csgotm_price': current_csgotm_price,
                    'current_profit_pct': current_profit_pct,
                    'reason': f'Профит слишком низкий: {current_profit_pct:.1f}% < {self.MIN_PROFIT_PCT}%'
                }

            # Проверяем цену в диапазоне
            if current_steam_price < self.TRADE_MIN_PRICE:
                return {
                    'is_profitable': False,
                    'current_steam_price': current_steam_price,
                    'current_csgotm_price': current_csgotm_price,
                    'current_profit_pct': current_profit_pct,
                    'reason': f'Цена слишком низкая: {current_steam_price:.2f} < {self.TRADE_MIN_PRICE}'
                }

            if current_steam_price > self.TRADE_MAX_PRICE:
                return {
                    'is_profitable': False,
                    'current_steam_price': current_steam_price,
                    'current_csgotm_price': current_csgotm_price,
                    'current_profit_pct': current_profit_pct,
                    'reason': f'Цена слишком высокая: {current_steam_price:.2f} > {self.TRADE_MAX_PRICE}'
                }

            # Все проверки пройдены!
            logger.info(
                f"[{self.name}] ✅ Предмет актуален: Steam {current_steam_price:.2f} → "
                f"CSGO.TM {current_csgotm_price:.2f} conservative (min={min_price:.2f}, avg={avg_price:.2f}) "
                f"→ профит: {current_profit_pct:.1f}%"
            )

            return {
                'is_profitable': True,
                'current_steam_price': current_steam_price,
                'current_csgotm_price': current_csgotm_price,
                'current_profit_pct': current_profit_pct,
                'recommended_price': current_steam_price,
            }

        except Exception as e:
            logger.error(f"[{self.name}] Ошибка проверки актуальности: {e}")
            return {
                'is_profitable': False,
                'reason': f'Ошибка: {e}'
            }

    # ============ Шаг 1: Получение прибыльных предметов ============

    def get_profitable_items(self, limit: Optional[int] = None) -> list[dict]:
        """
        Получить прибыльные предметы из my_trades.db (GUI database).

        Args:
            limit: Максимум предметов (None = без ограничения)

        Returns:
            List of profitable items as dicts
        """
        try:
            from src.database import TradesDatabase

            # Получаем предметы из GUI database (my_trades.db)
            db = TradesDatabase()
            items = db.get_active_profitable_items(min_profit=self.MIN_PROFIT_PCT, limit=limit or 1000)

            if not items:
                logger.warning(f"[{self.name}] No items found in my_trades.db")
                return []

            # Конвертируем в нужный формат для бота
            profitable = []
            for item in items:
                # Items уже отфильтрованы по min_profit в get_active_profitable_items()
                # Проверяем наличие необходимых полей
                steam_buy_order = _first_number(item.get('steam_buy_order'), item.get('recommended_buy_order'))
                csgo_price = _first_number(item.get('csgo_price'))
                profit_pct = _first_number(item.get('recommended_profit_pct'), item.get('profit_pct'))

                if not steam_buy_order or not csgo_price or profit_pct is None:
                    continue

                # Проверяем лимит цены
                recommended_buy = _first_number(item.get('recommended_buy_order'), steam_buy_order)
                if not recommended_buy:
                    continue
                if recommended_buy > self.account.config.max_price_per_item:
                    continue

                # Конвертируем в формат для бота
                item_dict = {
                    'name': item['market_hash_name'],
                    'market_hash_name': item['market_hash_name'],
                    'steam_price': recommended_buy,
                    'csgo_price': csgo_price,
                    'csgotm_price': csgo_price,
                    'profit_pct': profit_pct,
                    'net_profit': csgo_price - recommended_buy,  # Approximate
                    'item_type': item.get('item_type', 'unknown'),
                    'orders_above': item.get('orders_above', 0),
                }
                profitable.append(item_dict)

            # Сортируем по профиту (убывание)
            profitable.sort(
                key=lambda x: x.get('profit_pct') if x.get('profit_pct') is not None else float('-inf'),
                reverse=True
            )

            logger.info(
                f"[{self.name}] Found {len(profitable)} profitable items "
                f"(min profit: {self.MIN_PROFIT_PCT}%)"
            )

            return profitable

        except Exception as e:
            logger.error(f"[{self.name}] Failed to get profitable items: {e}")
            return []

    # ============ Шаг 2: Создание бай-ордеров ============

    async def create_buy_orders(self, max_items: Optional[int] = None) -> dict:
        """
        Создать бай-ордера на прибыльные предметы.

        Args:
            max_items: Максимум предметов для покупки

        Returns:
            Dict with success/failed counts
        """
        logger.info(f"[{self.name}] Creating buy orders...")

        # Получаем Steam ID и identity_secret один раз в начале
        steamid = self.account.steam_client.get_steamid()
        identity_secret = self.account.config.steam_identity_secret

        if not steamid or not identity_secret:
            logger.warning(f"[{self.name}] Steam ID or identity_secret not available, confirmations may fail")

        # Получаем активные ордера из Steam API перед созданием новых
        logger.info(f"[{self.name}] Fetching existing active orders from Steam...")
        steam_active_orders = await self.account.steam_client.get_active_buy_orders()
        steam_active_items = {order['market_hash_name'] for order in steam_active_orders}
        logger.info(f"[{self.name}] Found {len(steam_active_items)} items with active orders in Steam")

        # Синхронизируем найденные ордера в БД (если их там нет)
        synced_count = 0
        for order in steam_active_orders:
            # Проверяем, есть ли этот ордер в БД
            existing = trades_db.get_order_by_id(order['order_id'])
            if not existing:
                # Добавляем ордер в БД для отслеживания
                # Используем правильную сигнатуру метода add_order
                trades_db.add_order(
                    account_name=self.name,
                    item_name=order['market_hash_name'],
                    market_hash_name=order['market_hash_name'],
                    order_id=order['order_id'],
                    order_price=order['price'],
                    quantity=order['quantity'],
                    expected_sell_price=None,  # Неизвестно для существующих ордеров
                )
                synced_count += 1
                logger.info(f"[{self.name}] 📥 Synced order from Steam to DB: {order['market_hash_name']}")

        if synced_count > 0:
            logger.info(f"[{self.name}] Synced {synced_count} orders from Steam to local DB")

        # Получаем баланс через sync метод (уже был получен при определении валюты)
        balance = self.account.get_wallet_balance_sync()
        # Steam позволяет выставлять ордера на сумму в 10 раз больше баланса
        max_order_budget = balance * 10.0
        logger.info(f"[{self.name}] Current balance: {balance:.2f} {self.account.config.currency}")
        logger.info(f"[{self.name}] Max order budget (x10): {max_order_budget:.2f} {self.account.config.currency}")

        if balance < 1.0:
            logger.error(f"[{self.name}] ❌ INSUFFICIENT BALANCE: {balance:.2f} {self.account.config.currency}. Cannot place orders!")
            logger.error(f"[{self.name}] Please add funds to Steam wallet or check if balance detection is working correctly.")
            logger.error(f"[{self.name}] Tip: Click '🔍 Валюта' button in GUI to detect currency and refresh balance.")
            return {'success': 0, 'failed': 0, 'skipped': 0, 'confirmed': 0}

        # Получаем прибыльные предметы
        if max_items is None:
            max_items = self.account.config.max_items

        items = self.get_profitable_items(limit=max_items * 2)  # Берем с запасом

        if not items:
            logger.info(f"[{self.name}] No profitable items to buy")
            return {'success': 0, 'failed': 0, 'skipped': 0, 'confirmed': 0}

        # Создаем ордера
        success_count = 0
        failed_count = 0
        skipped_count = 0
        confirmed_count = 0
        total_spent = 0.0

        for item in items:
            # Проверяем лимиты
            if success_count >= max_items:
                logger.info(f"[{self.name}] Reached max items limit ({max_items})")
                break

            if total_spent >= self.account.config.total_budget:
                logger.info(f"[{self.name}] Reached budget limit ({self.account.config.total_budget})")
                break

            # Проверяем лимит выставления ордеров (Steam позволяет x10 от баланса)
            steam_price_rub = item.get('steam_price', 0)

            # Конвертируем цену из RUB в валюту аккаунта для корректного сравнения с бюджетом
            account_currency = self.account.config.currency
            if account_currency == 'RUB':
                steam_price = steam_price_rub
            else:
                steam_price = currency_converter.convert_from_rub(steam_price_rub, account_currency)

            if total_spent + steam_price > max_order_budget:
                logger.warning(
                    f"[{self.name}] Reached max order budget limit: "
                    f"{total_spent + steam_price:.2f} > {max_order_budget:.2f} {account_currency} ({item['name']})"
                )
                skipped_count += 1
                continue

            # Проверяем цену предмета (фильтр для выставления ордеров) - используем цену в RUB
            if steam_price_rub < self.TRADE_MIN_PRICE:
                logger.debug(f"[{self.name}] Item too cheap: {item['name']} ({steam_price_rub:.2f} < {self.TRADE_MIN_PRICE})")
                skipped_count += 1
                continue

            if steam_price_rub > self.TRADE_MAX_PRICE:
                logger.debug(f"[{self.name}] Item too expensive: {item['name']} ({steam_price_rub:.2f} > {self.TRADE_MAX_PRICE})")
                skipped_count += 1
                continue

            # Проверяем, нет ли уже активного ордера на этот предмет
            # 1. Проверяем Steam API (актуальная информация)
            if item['name'] in steam_active_items:
                logger.info(f"[{self.name}] ⏭️ Active order already exists in Steam: {item['name']}")
                skipped_count += 1
                continue

            # 2. Проверяем локальную БД (на случай если синхронизация отстала)
            existing_order = trades_db.get_order_by_item_name(item['name'])
            if existing_order:
                logger.debug(f"[{self.name}] Order already exists in DB: {item['name']}")
                skipped_count += 1
                continue

            # ВАЖНО: Проверяем актуальность цен перед созданием ордера
            verification = await self._verify_item_profitability(item)

            if not verification['is_profitable']:
                logger.warning(
                    f"[{self.name}] ⚠️ Предмет больше не выгоден: {item['name']} - "
                    f"{verification.get('reason', 'unknown')}"
                )
                skipped_count += 1
                # Задержка перед следующей проверкой (rate limiting)
                await asyncio.sleep(3.0)
                continue

            # Обновляем цену на актуальную
            item['steam_price'] = verification['recommended_price']
            item['recommended_price'] = verification['recommended_price']  # Для телеграм уведомлений
            item['csgotm_price'] = verification['current_csgotm_price']
            item['profit_pct'] = verification['current_profit_pct']
            steam_price_rub = item['steam_price']  # Цена в RUB

            # Конвертируем цену в валюту аккаунта для учета в бюджете
            if account_currency == 'RUB':
                steam_price = steam_price_rub
            else:
                steam_price = currency_converter.convert_from_rub(steam_price_rub, account_currency)

            # Задержка перед созданием ордера (rate limiting)
            logger.debug(f"[{self.name}] Waiting 3s before creating order...")
            await asyncio.sleep(3.0)

            # Задержка перед созданием ордера (rate limiting)
            logger.debug(f"[{self.name}] Waiting 3s before creating order...")
            await asyncio.sleep(3.0)

            # Создаем ордер
            try:
                result = await self._create_buy_order_for_item(item)

                if result['success']:
                    success_count += 1
                    total_spent += steam_price
                    logger.info(
                        f"[{self.name}] ✅ Order created: {item['name']} @ {steam_price_rub:.2f} RUB "
                        f"(profit: {item['profit_pct']:.1f}%)"
                    )

                    # ВАЖНО: aiosteampy автоматически подтверждает ордера если identity_secret передан
                    # Даем время Steam зарегистрировать ордер и создать подтверждение
                    if steamid and identity_secret:
                        logger.info(f"[{self.name}] Waiting for auto-confirmation (aiosteampy handles this automatically)")
                        await asyncio.sleep(5)  # Даем Steam время создать и подтвердить
                        confirmed_count += 1
                        logger.info(f"[{self.name}] ✅ Order should be auto-confirmed by aiosteampy")
                else:
                    failed_count += 1
                    message = result.get('message', 'Unknown error')
                    logger.warning(f"[{self.name}] ❌ Order failed: {item['name']} - {message}")
                    if self._is_rate_limit_error(message):
                        logger.warning(
                            f"[{self.name}] Steam rate limit while creating orders. "
                            f"Cooling down for {self.ORDER_RATE_LIMIT_COOLDOWN}s and stopping this buy cycle."
                        )
                        await asyncio.sleep(self.ORDER_RATE_LIMIT_COOLDOWN)
                        break

            except Exception as e:
                logger.error(f"[{self.name}] Error creating order for {item['name']}: {e}")
                failed_count += 1

            # Задержка между попытками создания ордера (rate limiting)
            # Увеличиваем задержку до 5 секунд чтобы избежать 429 ошибок
            await asyncio.sleep(5.0)

        logger.info(
            f"[{self.name}] Buy orders complete: "
            f"{success_count} success, {failed_count} failed, {skipped_count} skipped, "
            f"{confirmed_count} confirmed"
        )

        return {
            'success': success_count,
            'failed': failed_count,
            'skipped': skipped_count,
            'total_spent': total_spent,
            'confirmed': confirmed_count,
        }

    async def _create_buy_order_for_item(self, item: dict) -> dict:
        """
        Создать бай-ордер для одного предмета.

        Args:
            item: Item data from bottm.db

        Returns:
            Dict with success status and order_id
        """
        market_hash_name = item['name']
        price = item['steam_price']
        expected_sell_price = item.get('csgotm_price', 0)

        try:
            # Создаем ордер через Steam client
            result = await self.account.steam_client.create_buy_order(
                market_hash_name=market_hash_name,
                price=price,
                quantity=1
            )

            if result.success and result.order_id:
                # Добавляем в БД
                trades_db.add_order(
                    account_name=self.name,
                    item_name=market_hash_name,
                    market_hash_name=market_hash_name,
                    order_id=result.order_id,
                    order_price=price,
                    quantity=1,
                    expected_sell_price=expected_sell_price,
                )

                # Отправляем уведомление в Telegram
                try:
                    from src.telegram_bot import telegram_bot
                    telegram_bot.notify_order_placed(
                        item_name=market_hash_name,
                        steam_price=price,
                        csgotm_price=expected_sell_price,
                        recommended_price=item.get('recommended_price', price),
                        profit_pct=item.get('profit_pct', 0),
                        account_name=self.name
                    )
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to send Telegram notification: {e}")

                return {'success': True, 'order_id': result.order_id}
            else:
                return {'success': False, 'message': result.error or 'Unknown error'}

        except Exception as e:
            logger.error(f"[{self.name}] Failed to create order: {e}")
            return {'success': False, 'message': str(e)}

    # ============ Шаг 2.5: Синхронизация статусов ордеров ============

    async def sync_order_statuses(self) -> dict:
        """
        Синхронизировать статусы ордеров с Steam API.

        Получает активные ордера из Steam и сравнивает с БД:
        - Если ордер есть в БД но нет в Steam - помечает как cancelled
        - Если quantity_remaining = 0 - помечает как filled

        Returns:
            Dict with counts: {'cancelled': int, 'still_active': int}
        """
        logger.info(f"[{self.name}] Syncing order statuses with Steam...")

        try:
            # Получаем активные ордера из Steam
            steam_orders = await self.account.steam_client.get_active_buy_orders()
            steam_order_ids = {order['order_id'] for order in steam_orders}

            logger.info(f"[{self.name}] Steam has {len(steam_order_ids)} active orders")

            # Получаем активные ордера из БД
            db_orders = [
                order for order in trades_db.get_active_orders()
                if order['account_name'] == self.name
            ]

            logger.info(f"[{self.name}] Database has {len(db_orders)} active orders")

            # Находим ордера, которых нет в Steam (исполнены или отменены)
            missing_orders = [
                order for order in db_orders
                if str(order['order_id']) not in steam_order_ids
            ]

            cancelled_count = 0
            filled_count = 0

            # Загружаем инвентарь ОДИН раз, если есть ордера для проверки
            # Подсчитываем КОЛИЧЕСТВО каждого предмета в инвентаре
            inventory_counts = {}
            if missing_orders:
                inventory = await self.account.steam_client.get_inventory()
                if inventory:
                    for item in inventory:
                        name = item.market_hash_name
                        inventory_counts[name] = inventory_counts.get(name, 0) + 1

            # Учитываем УЖЕ СУЩЕСТВУЮЩИЕ purchased_items для этого аккаунта
            # Это предотвращает дублирование когда несколько ордеров на один предмет
            existing_purchased = trades_db.get_purchased_items(account_name=self.name)
            matched_counts = {}
            for item in existing_purchased:
                name = item.get('market_hash_name', '')
                if name:
                    matched_counts[name] = matched_counts.get(name, 0) + 1

            # Проверяем каждый пропавший ордер
            for order in missing_orders:
                order_id = str(order['order_id'])
                market_hash_name = order.get('market_hash_name', '')

                # Проверяем, есть ли предмет в инвентаре (= ордер исполнен)
                # И есть ли ещё несопоставленные предметы этого типа
                available_count = inventory_counts.get(market_hash_name, 0)
                matched_count = matched_counts.get(market_hash_name, 0)

                if market_hash_name and available_count > matched_count:
                    logger.info(
                        f"[{self.name}] ✅ Order {order_id} FILLED: {order['item_name']} "
                        f"(inventory: {available_count}, matched: {matched_count + 1})"
                    )
                    trades_db.update_order_status(order_id, 'filled')

                    # Добавляем в purchased_items с 7-дневным холдом
                    trades_db.add_purchased_item(
                        account_name=self.name,
                        item_name=order['item_name'],
                        market_hash_name=market_hash_name,
                        purchase_price=order['order_price'],
                        expected_sell_price=order.get('expected_sell_price'),
                        order_id=order['order_id'],
                    )
                    filled_count += 1
                    # Увеличиваем счётчик сопоставленных предметов
                    matched_counts[market_hash_name] = matched_count + 1
                else:
                    logger.info(
                        f"[{self.name}] ❌ Order {order_id} CANCELLED: {order['item_name']} "
                        f"(inventory: {available_count}, already matched: {matched_count})"
                    )
                    trades_db.update_order_status(order_id, 'cancelled')
                    cancelled_count += 1

            logger.info(
                f"[{self.name}] Sync complete: {filled_count} filled, {cancelled_count} cancelled, "
                f"{len(steam_order_ids)} still active"
            )

            return {
                'filled': filled_count,
                'cancelled': cancelled_count,
                'still_active': len(steam_order_ids)
            }

        except Exception as e:
            logger.error(f"[{self.name}] Error syncing order statuses: {e}")
            import traceback
            traceback.print_exc()
            return {'cancelled': 0, 'still_active': 0}

    # ============ Шаг 3: Проверка исполненных ордеров ============

    async def check_filled_orders(self) -> int:
        """
        Проверить исполненные ордера и добавить предметы в purchased_items.

        Returns:
            Count of newly filled orders
        """
        logger.info(f"[{self.name}] Checking filled orders...")

        # Получаем активные ордера из БД
        active_orders = [
            order for order in trades_db.get_active_orders()
            if order['account_name'] == self.name
        ]

        if not active_orders:
            logger.debug(f"[{self.name}] No active orders to check")
            return 0

        # Загружаем инвентарь ОДИН раз для всех проверок
        inventory = await self.account.steam_client.get_inventory()
        if not inventory:
            logger.debug(f"[{self.name}] Inventory is empty or failed to fetch")
            return 0

        # Подсчитываем КОЛИЧЕСТВО каждого предмета в инвентаре
        inventory_counts = {}
        for item in inventory:
            name = item.market_hash_name
            inventory_counts[name] = inventory_counts.get(name, 0) + 1

        # Учитываем УЖЕ СУЩЕСТВУЮЩИЕ purchased_items для этого аккаунта
        existing_purchased = trades_db.get_purchased_items(account_name=self.name)
        matched_counts = {}
        for item in existing_purchased:
            name = item.get('market_hash_name', '')
            if name:
                matched_counts[name] = matched_counts.get(name, 0) + 1

        filled_count = 0

        for order in active_orders:
            try:
                market_hash_name = order.get('market_hash_name', '')

                # Проверяем есть ли предмет в инвентаре
                # И есть ли ещё несопоставленные предметы этого типа
                available_count = inventory_counts.get(market_hash_name, 0)
                matched_count = matched_counts.get(market_hash_name, 0)

                if market_hash_name and available_count > matched_count:
                    # Отмечаем ордер как исполненный
                    trades_db.update_order_status(order['order_id'], 'filled')

                    # Добавляем в purchased_items
                    trades_db.add_purchased_item(
                        account_name=self.name,
                        item_name=order['item_name'],
                        market_hash_name=market_hash_name,
                        purchase_price=order['order_price'],
                        expected_sell_price=order.get('expected_sell_price'),
                        order_id=order['order_id'],
                    )

                    filled_count += 1
                    # Увеличиваем счётчик сопоставленных предметов
                    matched_counts[market_hash_name] = matched_count + 1
                    logger.info(
                        f"[{self.name}] ✅ Order filled: {order['item_name']} "
                        f"(inventory: {available_count}, matched: {matched_count + 1})"
                    )

            except Exception as e:
                logger.error(f"[{self.name}] Error checking order {order['order_id']}: {e}")

        if filled_count > 0:
            logger.info(f"[{self.name}] {filled_count} orders filled")

        return filled_count

    # ============ Шаг 4: Продажа предметов после холда ============

    async def sell_ready_items(self) -> int:
        """
        Продать предметы, прошедшие 7-дневный холд.

        Returns:
            Count of items listed for sale
        """
        logger.info(f"[{self.name}] Checking items ready to sell...")

        # Получаем предметы, готовые к продаже
        ready_items = [
            item for item in trades_db.get_items_ready_to_sell()
            if item['account_name'] == self.name
        ]

        if not ready_items:
            logger.debug(f"[{self.name}] No items ready to sell")
            return 0

        listed_count = 0

        for item in ready_items:
            try:
                # Получаем актуальную цену на CSGO.TM
                current_price = self._get_csgotm_sell_price(item['item_name'])

                if not current_price or current_price < item['purchase_price']:
                    logger.warning(
                        f"[{self.name}] Skipping {item['item_name']}: "
                        f"price too low ({current_price} < {item['purchase_price']})"
                    )
                    continue

                # Продаем на CSGO.TM
                result = await self._sell_item_on_csgotm(item, current_price)

                if result['success']:
                    # Обновляем статус в БД
                    trades_db.update_purchased_item_status(item['id'], 'listed')

                    # Добавляем в listed_items
                    trades_db.add_listed_item(
                        account_name=self.name,
                        item_name=item['item_name'],
                        market_hash_name=item.get('market_hash_name', item['item_name']),
                        asset_id=item.get('asset_id'),
                        list_price=current_price,
                        purchase_price=item['purchase_price'],
                    )

                    listed_count += 1
                    logger.info(f"[{self.name}] ✅ Listed for sale: {item['item_name']} @ {current_price:.2f}")

                await asyncio.sleep(5)  # Rate limiting

            except Exception as e:
                logger.error(f"[{self.name}] Error selling item {item['item_name']}: {e}")

        if listed_count > 0:
            logger.info(f"[{self.name}] {listed_count} items listed for sale")

        return listed_count

    def _get_csgotm_sell_price(self, item_name: str) -> Optional[float]:
        """
        Получить актуальную цену продажи на CSGO.TM из bottm.db.

        Args:
            item_name: Market hash name

        Returns:
            Price or None
        """
        try:
            item = bottm_parser.get_item_by_name(item_name)
            if item:
                return item.get('csgotm_price')
            return None
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get CSGO.TM price for {item_name}: {e}")
            return None

    async def _sell_item_on_csgotm(self, item: dict, price: float) -> dict:
        """
        Выставить предмет на продажу на CSGO.TM.

        Process:
        1. Find item in Steam inventory
        2. Call CSGO.TM set_price API (creates trade offer from bot)
        3. Item will be listed after accepting trade offer

        Args:
            item: Item data from purchased_items with 'market_hash_name'
            price: Sale price in USD

        Returns:
            Dict with success status and optional item_id
        """
        try:
            market_hash_name = item.get('market_hash_name', item.get('item_name'))

            # Шаг 1: Найти предмет в инвентаре Steam
            inventory = await self.account.steam_client.get_inventory()

            if not inventory:
                logger.warning(f"[{self.name}] Inventory is empty or failed to fetch")
                return {'success': False, 'message': 'Empty inventory'}

            # Ищем предмет
            inventory_item = None
            for inv_item in inventory:
                if inv_item.market_hash_name == market_hash_name:
                    inventory_item = inv_item
                    break

            if not inventory_item:
                logger.warning(
                    f"[{self.name}] Item '{market_hash_name}' not found in inventory"
                )
                return {'success': False, 'message': 'Item not found in inventory'}

            if not inventory_item.tradable:
                logger.warning(
                    f"[{self.name}] Item '{market_hash_name}' is not tradable yet (7-day hold)"
                )
                return {'success': False, 'message': 'Item not tradable (still on hold)'}

            # Шаг 2: Вызвать CSGO.TM set_price API
            logger.info(
                f"[{self.name}] Listing '{market_hash_name}' on CSGO.TM "
                f"at ${price:.2f} (class_id: {inventory_item.class_id})"
            )

            result = self.account.csgotm_client.set_price(
                class_id=inventory_item.class_id,
                instance_id=inventory_item.instance_id,
                price=price
            )

            if result.success:
                logger.info(
                    f"[{self.name}] ✅ Trade offer requested for '{market_hash_name}'. "
                    f"Accept trade to complete listing (item_id: {result.item_id})"
                )
                return {
                    'success': True,
                    'item_id': result.item_id,
                    'message': 'Trade offer created, waiting for acceptance',
                    'asset_id': inventory_item.asset_id
                }
            else:
                logger.error(
                    f"[{self.name}] Failed to list '{market_hash_name}': {result.message}"
                )
                return {'success': False, 'message': result.message}

        except Exception as e:
            logger.error(f"[{self.name}] Error selling item on CSGO.TM: {e}")
            return {'success': False, 'message': str(e)}

    # ============ Background Tasks ============

    async def auto_sync_orders(self, interval: int = 300):
        """
        Автоматическая периодическая синхронизация ордеров в фоне.

        Args:
            interval: Интервал синхронизации в секундах (по умолчанию 5 минут)
        """
        logger.info(f"[{self.name}] Starting auto-sync orders task (interval: {interval}s)")

        while True:
            try:
                await asyncio.sleep(interval)

                # Проверяем, что клиент залогинен
                if not self.account.is_logged_in():
                    logger.debug(f"[{self.name}] Auto-sync: not logged in, skipping")
                    continue

                logger.info(f"[{self.name}] 🔄 Auto-sync: syncing order statuses...")
                sync_results = await self.sync_order_statuses()
                logger.info(
                    f"[{self.name}] Auto-sync complete: "
                    f"{sync_results['cancelled']} cancelled, "
                    f"{sync_results['still_active']} active"
                )

                # Проверяем заполненные ордера
                logger.info(f"[{self.name}] 🔄 Auto-sync: checking filled orders...")
                filled_count = await self.check_filled_orders()
                if filled_count > 0:
                    logger.info(f"[{self.name}] Auto-sync: {filled_count} orders filled!")

            except asyncio.CancelledError:
                logger.info(f"[{self.name}] Auto-sync task cancelled")
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error in auto-sync: {e}")
                # Продолжаем работу несмотря на ошибку

    # ============ Main Loop ============

    async def run_cycle(self) -> dict:
        """
        Выполнить один цикл торговли:
        1. Создать бай-ордера
        2. Проверить исполненные ордера
        3. Продать готовые предметы

        Returns:
            Dict with cycle stats
        """
        logger.info(f"[{self.name}] ===== Running trading cycle =====")

        # Проверяем, что клиенты инициализированы
        if not self.account.is_logged_in():
            logger.error(f"[{self.name}] Steam client not logged in")
            return {'orders_created': 0, 'orders_filled': 0, 'items_listed': 0}

        if not self.account.csgotm_client:
            logger.error(f"[{self.name}] CSGO.TM client not initialized")
            return {'orders_created': 0, 'orders_filled': 0, 'items_listed': 0}

        stats = {
            'orders_created': 0,
            'orders_filled': 0,
            'items_listed': 0,
            'orders_synced': 0,
            'orders_cancelled': 0,
        }

        try:
            # Шаг 0: Синхронизировать статусы ордеров с Steam
            logger.info(f"[{self.name}] Step 0: Syncing order statuses...")
            sync_results = await self.sync_order_statuses()
            stats['orders_synced'] = sync_results['still_active']
            stats['orders_cancelled'] = sync_results['cancelled']

            # Шаг 1: Создать ордера
            logger.info(f"[{self.name}] Step 1: Creating buy orders...")
            order_results = await self.create_buy_orders()
            stats['orders_created'] = order_results['success']

            # Шаг 2: Проверить исполненные ордера (ищем купленные предметы в инвентаре)
            logger.info(f"[{self.name}] Step 2: Checking filled orders...")
            filled_count = await self.check_filled_orders()
            stats['orders_filled'] = filled_count

            # TODO: Шаг 3: Продать готовые предметы (пока отключено)
            # logger.info(f"[{self.name}] Step 3: Selling ready items...")
            # listed_count = await self.sell_ready_items()
            # stats['items_listed'] = listed_count

        except Exception as e:
            logger.error(f"[{self.name}] Error in trading cycle: {e}")

        logger.info(
            f"[{self.name}] Cycle complete: "
            f"{stats['orders_cancelled']} cancelled, "
            f"{stats['orders_synced']} active, "
            f"{stats['orders_created']} created, "
            f"{stats['orders_filled']} filled, "
            f"{stats['items_listed']} listed"
        )

        return stats
