"""
Расширения для TradesDatabase для поддержки Telegram бота.

Добавляет методы поиска и фильтрации.
"""

from typing import List, Dict, Optional
from src.database import TradesDatabase


# Monkey-patch методов к существующему классу
def search_orders(self, query: str) -> List[Dict]:
    """
    Поиск активных ордеров по названию предмета.

    Args:
        query: Поисковый запрос

    Returns:
        Список найденных ордеров
    """
    query = query.lower()

    orders = self.get_active_orders()
    return [
        order for order in orders
        if query in order.get('item_name', '').lower()
    ]


def search_items_on_hold(self, query: str) -> List[Dict]:
    """Поиск предметов на холдинге."""
    query = query.lower()

    items = self.get_items_on_hold()
    return [
        item for item in items
        if query in item.get('item_name', '').lower()
    ]


def search_items_ready(self, query: str) -> List[Dict]:
    """Поиск предметов готовых к продаже."""
    query = query.lower()

    items = self.get_items_ready_to_sell()
    return [
        item for item in items
        if query in item.get('item_name', '').lower()
    ]


def search_items_listed(self, query: str) -> List[Dict]:
    """Поиск выставленных предметов."""
    query = query.lower()

    items = self.get_listed_items()
    return [
        item for item in items
        if query in item.get('item_name', '').lower()
    ]


def get_item_by_id(self, item_id: int) -> Optional[Dict]:
    """
    Получить предмет по ID.

    Args:
        item_id: ID предмета в таблице purchased_items

    Returns:
        Словарь с данными предмета или None
    """
    return self.get_purchased_item_by_id(item_id)


def get_items_listed(self) -> List[Dict]:
    """Получить все выставленные предметы (алиас)."""
    return self.get_listed_items()


# Применяем monkey-patch
TradesDatabase.search_orders = search_orders
TradesDatabase.search_items_on_hold = search_items_on_hold
TradesDatabase.search_items_ready = search_items_ready
TradesDatabase.search_items_listed = search_items_listed
TradesDatabase.get_item_by_id = get_item_by_id
TradesDatabase.get_items_listed = get_items_listed
