"""
Автоматическая покупка предметов на Steam Market.

Функции:
- Создание buy orders на Steam Market
- Проверка статуса заказов
- Отмена заказов
- Управление бюджетом
"""

import time
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime

from src.logger import get_logger
from src.steam_client import SteamClient
from src.database import TradesDatabase
from src.confirmations import ConfirmationHandler

logger = get_logger(__name__)


@dataclass
class BuyOrderStatus:
    """Статус buy order."""
    order_id: str
    item_name: str
    price: float
    quantity: int
    created_at: datetime
    status: str  # 'active', 'filled', 'cancelled'


class AutoBuyer:
    """Автоматическая покупка предметов."""

    def __init__(self, steam_client: SteamClient, db: TradesDatabase, account_name: str,
                 auto_confirm: bool = True, blacklist: List[str] = None, whitelist: List[str] = None):
        """
        Initialize auto buyer.

        Args:
            steam_client: Authenticated Steam client
            db: Database instance
            account_name: Account name for tracking
            auto_confirm: Auto-confirm market listings (default: True)
            blacklist: List of item names to never buy
            whitelist: List of item names to only buy (if set, only these items)
        """
        self.steam_client = steam_client
        self.db = db
        self.account_name = account_name
        self.auto_confirm = auto_confirm
        self.active_orders: Dict[str, BuyOrderStatus] = {}

        # Blacklist/Whitelist
        self.blacklist = set(blacklist or [])
        self.whitelist = set(whitelist or [])

        # Initialize confirmation handler
        self.confirmation_handler = ConfirmationHandler(steam_client) if auto_confirm else None

    def create_buy_order(
        self,
        market_hash_name: str,
        price: float,
        quantity: int = 1,
        check_balance: bool = True
    ) -> Optional[str]:
        """
        Создать buy order на Steam Market.

        Args:
            market_hash_name: Название предмета
            price: Цена в копейках (для RUB: 1000 = 10.00 руб)
            quantity: Количество предметов
            check_balance: Проверять баланс перед покупкой

        Returns:
            Order ID или None если ошибка
        """
        try:
            logger.info(f"Creating buy order: {market_hash_name} @ {price/100:.2f} RUB x{quantity}")

            # Проверка баланса
            if check_balance:
                wallet = self.steam_client.get_wallet_balance()
                if wallet.balance < (price * quantity / 100):
                    logger.error(f"Insufficient balance: {wallet.balance:.2f} < {(price * quantity / 100):.2f}")
                    return None

            # Создаём заказ через Steam API
            # ВАЖНО: Steam API требует цену в копейках (для RUB)
            order_id = self.steam_client.create_buy_order(
                market_hash_name=market_hash_name,
                price_total=int(price),  # В копейках
                quantity=quantity
            )

            if order_id:
                # Сохраняем в БД
                self.db.add_active_order(
                    account_name=self.account_name,
                    item_name=market_hash_name,
                    order_id=order_id,
                    price=price / 100,  # В рублях для БД
                    quantity=quantity
                )

                # Добавляем в активные заказы
                self.active_orders[order_id] = BuyOrderStatus(
                    order_id=order_id,
                    item_name=market_hash_name,
                    price=price / 100,
                    quantity=quantity,
                    created_at=datetime.now(),
                    status='active'
                )

                logger.info(f"✅ Buy order created: {order_id}")
                return order_id
            else:
                logger.error(f"Failed to create buy order for {market_hash_name}")
                return None

        except Exception as e:
            logger.error(f"Error creating buy order: {e}", exc_info=True)
            return None

    def cancel_buy_order(self, order_id: str) -> bool:
        """
        Отменить buy order.

        Args:
            order_id: ID заказа

        Returns:
            True если успешно отменён
        """
        try:
            logger.info(f"Cancelling buy order: {order_id}")

            success = self.steam_client.cancel_buy_order(order_id)

            if success:
                # Обновляем БД
                self.db.update_order_status(order_id, 'cancelled')

                # Обновляем локальный статус
                if order_id in self.active_orders:
                    self.active_orders[order_id].status = 'cancelled'

                logger.info(f"✅ Order cancelled: {order_id}")
                return True
            else:
                logger.error(f"Failed to cancel order: {order_id}")
                return False

        except Exception as e:
            logger.error(f"Error cancelling order: {e}", exc_info=True)
            return False

    def check_order_status(self, order_id: str) -> Optional[str]:
        """
        Проверить статус заказа.

        Args:
            order_id: ID заказа

        Returns:
            Статус: 'active', 'filled', 'cancelled', или None
        """
        try:
            # Получаем список активных заказов
            my_orders = self.steam_client.get_my_market_orders()

            # Ищем наш заказ
            for order in my_orders.get('buy_orders', []):
                if order.get('market_buy_order_id') == order_id:
                    # Заказ активен
                    return 'active'

            # Если не нашли в активных - проверяем историю
            # (заказ мог быть выполнен или отменён)
            history = self.steam_client.get_market_history(count=100)

            for item in history.get('assets', []):
                if item.get('purchaseid') == order_id:
                    # Заказ выполнен
                    return 'filled'

            # Не нашли нигде - скорее всего отменён
            return 'cancelled'

        except Exception as e:
            logger.error(f"Error checking order status: {e}", exc_info=True)
            return None

    def update_all_orders_status(self) -> Dict[str, str]:
        """
        Обновить статус всех активных заказов.

        Returns:
            Dict[order_id, status]
        """
        updated_statuses = {}

        for order_id, order in list(self.active_orders.items()):
            if order.status != 'active':
                continue

            new_status = self.check_order_status(order_id)

            if new_status and new_status != order.status:
                logger.info(f"Order {order_id} status changed: {order.status} → {new_status}")

                # Обновляем статус
                order.status = new_status
                updated_statuses[order_id] = new_status

                # Обновляем в БД
                self.db.update_order_status(order_id, new_status)

                # Если заказ выполнен - добавляем в покупки
                if new_status == 'filled':
                    self.db.add_purchased_item(
                        account_name=self.account_name,
                        item_name=order.item_name,
                        price=order.price,
                        quantity=order.quantity
                    )

        return updated_statuses

    def get_active_orders(self) -> List[BuyOrderStatus]:
        """Получить список активных заказов."""
        return [order for order in self.active_orders.values() if order.status == 'active']

    def get_total_pending_amount(self) -> float:
        """Получить общую сумму активных заказов."""
        return sum(
            order.price * order.quantity
            for order in self.active_orders.values()
            if order.status == 'active'
        )

    def can_afford(self, price: float, quantity: int = 1) -> bool:
        """
        Проверить, хватит ли средств на покупку.

        Args:
            price: Цена за единицу (в рублях)
            quantity: Количество

        Returns:
            True если хватит средств
        """
        wallet = self.steam_client.get_wallet_balance()
        total_cost = price * quantity
        pending_amount = self.get_total_pending_amount()

        available = wallet.balance - pending_amount

        logger.debug(f"Wallet: {wallet.balance:.2f}, Pending: {pending_amount:.2f}, "
                    f"Available: {available:.2f}, Need: {total_cost:.2f}")

        return available >= total_cost

    def auto_buy_from_list(
        self,
        items: List[Dict],
        max_items: int = 10,
        max_price_per_item: float = 1000.0,
        total_budget: float = 5000.0,
        min_profit_pct: float = 15.0,
        prioritize_by: str = 'profit'  # 'profit', 'price', 'roi'
    ) -> Dict[str, any]:
        """
        Автоматически купить предметы из списка.

        Args:
            items: Список предметов из БД
            max_items: Максимальное количество предметов
            max_price_per_item: Макс. цена за предмет
            total_budget: Общий бюджет
            min_profit_pct: Минимальный процент профита
            prioritize_by: Критерий приоритизации ('profit', 'price', 'roi')

        Returns:
            Статистика покупок
        """
        stats = {
            'processed': 0,
            'bought': 0,
            'skipped': 0,
            'blacklisted': 0,
            'errors': 0,
            'total_spent': 0.0
        }

        # Фильтруем по whitelist/blacklist
        filtered_items = []
        for item in items:
            name = item['market_hash_name']

            # Whitelist имеет приоритет
            if self.whitelist and name not in self.whitelist:
                stats['skipped'] += 1
                continue

            # Проверка blacklist
            if name in self.blacklist:
                stats['blacklisted'] += 1
                continue

            filtered_items.append(item)

        # Приоритизация
        if prioritize_by == 'profit':
            filtered_items.sort(key=lambda x: max(x.get('instant_profit_pct', 0), x.get('wait_profit_pct', 0)), reverse=True)
        elif prioritize_by == 'price':
            filtered_items.sort(key=lambda x: x.get('steam_buy_order', 0))
        elif prioritize_by == 'roi':
            filtered_items.sort(key=lambda x: x.get('instant_profit_pct', 0) / max(x.get('steam_buy_order', 1), 1), reverse=True)

        logger.info(f"Filtered {len(filtered_items)}/{len(items)} items (prioritized by {prioritize_by})")

        spent = 0.0
        bought_count = 0

        for item in filtered_items:
            if bought_count >= max_items:
                logger.info(f"Reached max items limit: {max_items}")
                break

            if spent >= total_budget:
                logger.info(f"Reached budget limit: {total_budget:.2f}")
                break

            stats['processed'] += 1

            try:
                market_hash_name = item['market_hash_name']
                steam_buy_order = item.get('steam_buy_order', 0)
                profit_pct = max(
                    item.get('instant_profit_pct', 0),
                    item.get('wait_profit_pct', 0)
                )

                # Проверки
                if steam_buy_order > max_price_per_item:
                    logger.debug(f"Skip {market_hash_name}: price too high ({steam_buy_order:.2f})")
                    stats['skipped'] += 1
                    continue

                if profit_pct < min_profit_pct:
                    logger.debug(f"Skip {market_hash_name}: profit too low ({profit_pct:.1f}%)")
                    stats['skipped'] += 1
                    continue

                if not self.can_afford(steam_buy_order):
                    logger.warning(f"Insufficient funds for {market_hash_name}")
                    stats['skipped'] += 1
                    continue

                # Создаём заказ
                order_id = self.create_buy_order(
                    market_hash_name=market_hash_name,
                    price=int(steam_buy_order * 100),  # В копейках
                    quantity=1
                )

                if order_id:
                    stats['bought'] += 1
                    stats['total_spent'] += steam_buy_order
                    spent += steam_buy_order
                    bought_count += 1

                    logger.info(f"✅ Bought {market_hash_name} @ {steam_buy_order:.2f} RUB (profit: {profit_pct:.1f}%)")

                    # Задержка между покупками
                    time.sleep(5)
                else:
                    stats['errors'] += 1

            except Exception as e:
                logger.error(f"Error buying {item.get('market_hash_name')}: {e}")
                stats['errors'] += 1

        # Автоподтверждение всех покупок
        if self.auto_confirm and stats['bought'] > 0:
            logger.info("Auto-confirming market listings...")
            confirmed = self.confirm_all_purchases()
            stats['confirmed'] = confirmed

        return stats

    def confirm_all_purchases(self) -> int:
        """
        Подтвердить все покупки (market listings).

        Returns:
            Количество подтверждённых покупок
        """
        if not self.confirmation_handler:
            logger.warning("Confirmation handler not initialized")
            return 0

        try:
            # Даём время Steam для создания confirmations
            time.sleep(3)

            confirmed = self.confirmation_handler.confirm_all_market_listings()
            logger.info(f"✅ Confirmed {confirmed} market listings")
            return confirmed

        except Exception as e:
            logger.error(f"Error confirming purchases: {e}")
            return 0
