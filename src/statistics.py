"""
Модуль для сбора и анализа статистики торговли.

Функции:
- Статистика покупок/продаж
- Расчёт ROI и профита
- Экспорт данных в CSV/Excel
"""

import csv
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

from src.logger import get_logger
from src.database import TradesDatabase

logger = get_logger(__name__)


class TradingStatistics:
    """Статистика торговли."""

    def __init__(self, db: TradesDatabase):
        """
        Initialize statistics module.

        Args:
            db: Database instance
        """
        self.db = db

    def get_summary(self, days: int = 30) -> Dict:
        """
        Получить сводную статистику.

        Args:
            days: Количество дней для анализа

        Returns:
            Dict со статистикой
        """
        try:
            # Получаем статистику из БД
            stats = self.db.get_stats()
            profit_data = self.db.get_total_profit()
            recent_sales = self.db.get_recent_sales(limit=1000)

            # Активные предметы - используем count для точного количества
            active_profitable_count = self.db.get_profitable_items_count()
            active_orders = self.db.get_active_orders()

            # Подсчёт общей статистики
            items_purchased = self.db.get_purchased_items_count()
            items_sold = self.db.get_sold_items_count()

            total_profit = profit_data.get('total_profit', 0.0)
            total_revenue = profit_data.get('total_revenue', 0.0)
            total_cost = profit_data.get('total_cost', 0.0)

            # ROI
            roi = (total_profit / total_cost * 100) if total_cost > 0 else 0

            # Средний профит на сделку
            avg_profit_per_trade = total_profit / items_sold if items_sold > 0 else 0

            return {
                'period_days': days,
                'items_purchased': items_purchased,
                'items_sold': items_sold,
                'total_spent': round(total_cost, 2),
                'total_earned': round(total_revenue, 2),
                'total_profit': round(total_profit, 2),
                'roi_percent': round(roi, 2),
                'avg_profit_per_trade': round(avg_profit_per_trade, 2),
                'active_profitable_items': active_profitable_count,
                'active_orders': len(active_orders)
            }

        except Exception as e:
            logger.error(f"Error calculating summary: {e}", exc_info=True)
            return {
                'period_days': days,
                'items_purchased': 0,
                'items_sold': 0,
                'total_spent': 0.0,
                'total_earned': 0.0,
                'total_profit': 0.0,
                'roi_percent': 0.0,
                'avg_profit_per_trade': 0.0,
                'active_profitable_items': 0,
                'active_orders': 0
            }

    def get_daily_stats(self, days: int = 7) -> List[Dict]:
        """
        Получить статистику по дням.

        Args:
            days: Количество дней

        Returns:
            List[Dict] с данными по каждому дню
        """
        try:
            results = []
            recent_sales = self.db.get_recent_sales(limit=1000)

            for i in range(days):
                date = datetime.now() - timedelta(days=i)
                date_str = date.strftime('%Y-%m-%d')

                # Фильтруем продажи за этот день
                day_sold = [
                    s for s in recent_sales
                    if s.get('sold_at') and datetime.fromisoformat(s['sold_at']).date() == date.date()
                ]

                earned = sum(s.get('sale_price', 0) for s in day_sold)
                profit = sum(s.get('profit', 0) for s in day_sold)

                results.append({
                    'date': date_str,
                    'purchased': 0,  # Не отслеживаем по дням
                    'sold': len(day_sold),
                    'spent': 0.0,
                    'earned': round(earned, 2),
                    'profit': round(profit, 2)
                })

            return results

        except Exception as e:
            logger.error(f"Error calculating daily stats: {e}", exc_info=True)
            return []

    def get_top_items(self, limit: int = 10, by: str = 'profit') -> List[Dict]:
        """
        Получить топ предметов.

        Args:
            limit: Количество предметов
            by: Критерий сортировки ('profit', 'trades', 'roi')

        Returns:
            List[Dict] с предметами
        """
        try:
            sold = self.db.get_recent_sales(limit=1000)

            # Группируем по предметам
            item_stats = {}

            for sale in sold:
                item_name = sale['item_name']

                if item_name not in item_stats:
                    item_stats[item_name] = {
                        'item_name': item_name,
                        'trades': 0,
                        'total_profit': 0,
                        'avg_profit': 0,
                        'roi': 0
                    }

                profit = sale.get('profit', 0)
                item_stats[item_name]['trades'] += 1
                item_stats[item_name]['total_profit'] += profit

            # Рассчитываем средние значения
            for stats in item_stats.values():
                if stats['trades'] > 0:
                    stats['avg_profit'] = stats['total_profit'] / stats['trades']

            # Сортируем
            if by == 'profit':
                sorted_items = sorted(
                    item_stats.values(),
                    key=lambda x: x['total_profit'],
                    reverse=True
                )
            elif by == 'trades':
                sorted_items = sorted(
                    item_stats.values(),
                    key=lambda x: x['trades'],
                    reverse=True
                )
            else:  # roi
                sorted_items = sorted(
                    item_stats.values(),
                    key=lambda x: x['roi'],
                    reverse=True
                )

            return sorted_items[:limit]

        except Exception as e:
            logger.error(f"Error getting top items: {e}", exc_info=True)
            return []

    def export_to_csv(
        self,
        output_file: str,
        data_type: str = 'all',
        days: int = 30
    ) -> bool:
        """
        Экспортировать данные в CSV.

        Args:
            output_file: Путь к файлу
            data_type: Тип данных ('purchased', 'sold', 'profitable', 'all')
            days: Количество дней для экспорта

        Returns:
            True если успешно
        """
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            cutoff_date = datetime.now() - timedelta(days=days)

            if data_type in ['purchased', 'all']:
                self._export_purchased_to_csv(output_path, cutoff_date)

            if data_type in ['sold', 'all']:
                self._export_sold_to_csv(output_path, cutoff_date)

            if data_type in ['profitable', 'all']:
                self._export_profitable_to_csv(output_path)

            logger.info(f"Data exported to {output_file}")
            return True

        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}", exc_info=True)
            return False

    def _export_purchased_to_csv(self, base_path: Path, cutoff_date: datetime):
        """Экспорт покупок в CSV."""
        # Используем get_items_ready_to_sell и get_items_on_hold
        ready = self.db.get_items_ready_to_sell()
        on_hold = self.db.get_items_on_hold()
        all_purchased = ready + on_hold

        output_file = base_path.parent / f"{base_path.stem}_purchased.csv"

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'account_name', 'item_name', 'price', 'quantity',
                'purchase_date', 'unlock_date', 'status'
            ])
            writer.writeheader()

            for item in all_purchased:
                writer.writerow({
                    'account_name': item.get('account_name', 'N/A'),
                    'item_name': item.get('item_name', 'N/A'),
                    'price': item.get('price', 0),
                    'quantity': item.get('quantity', 1),
                    'purchase_date': item.get('purchased_at', 'N/A'),
                    'unlock_date': item.get('unlock_date', 'N/A'),
                    'status': item.get('status', 'N/A')
                })

        logger.info(f"Exported {len(all_purchased)} purchased items to {output_file}")

    def _export_sold_to_csv(self, base_path: Path, cutoff_date: datetime):
        """Экспорт продаж в CSV."""
        sold = self.db.get_recent_sales(limit=10000)

        output_file = base_path.parent / f"{base_path.stem}_sold.csv"

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'account_name', 'item_name', 'purchase_price', 'sale_price',
                'profit', 'profit_pct', 'sold_at', 'platform'
            ])
            writer.writeheader()

            for sale in sold:
                writer.writerow({
                    'account_name': sale.get('account_name', 'N/A'),
                    'item_name': sale.get('item_name', 'N/A'),
                    'purchase_price': sale.get('price', 0),
                    'sale_price': sale.get('sale_price', 0),
                    'profit': sale.get('profit', 0),
                    'profit_pct': sale.get('profit_pct', 0),
                    'sold_at': sale.get('sold_at', 'N/A'),
                    'platform': sale.get('platform', 'N/A')
                })

        logger.info(f"Exported {len(sold)} sold items to {output_file}")

    def _export_profitable_to_csv(self, base_path: Path):
        """Экспорт выгодных предметов в CSV."""
        profitable = self.db.get_active_profitable_items(limit=10000)

        output_file = base_path.parent / f"{base_path.stem}_profitable.csv"

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'market_hash_name', 'item_type', 'steam_buy_order', 'steam_lowest_sell',
                'recommended_buy_order', 'csgo_price', 'csgo_buy_order',
                'instant_profit_pct', 'wait_profit_pct',
                'recommended_instant_pct', 'recommended_wait_pct',
                'orders_above', 'found_at', 'updated_at'
            ])
            writer.writeheader()

            # Записываем построчно, извлекая только нужные поля
            for item in profitable:
                writer.writerow({
                    'market_hash_name': item.get('market_hash_name', ''),
                    'item_type': item.get('item_type', ''),
                    'steam_buy_order': item.get('steam_buy_order', 0),
                    'steam_lowest_sell': item.get('steam_lowest_sell', 0),
                    'recommended_buy_order': item.get('recommended_buy_order', 0),
                    'csgo_price': item.get('csgo_price', 0),
                    'csgo_buy_order': item.get('csgo_buy_order', 0),
                    'instant_profit_pct': item.get('instant_profit_pct', 0),
                    'wait_profit_pct': item.get('wait_profit_pct', 0),
                    'recommended_instant_pct': item.get('recommended_instant_pct', 0),
                    'recommended_wait_pct': item.get('recommended_wait_pct', 0),
                    'orders_above': item.get('orders_above', 0),
                    'found_at': item.get('found_at', ''),
                    'updated_at': item.get('updated_at', '')
                })

        logger.info(f"Exported {len(profitable)} profitable items to {output_file}")

    def generate_report(self, days: int = 30) -> str:
        """
        Генерировать текстовый отчёт.

        Args:
            days: Количество дней для анализа

        Returns:
            Отчёт в текстовом формате
        """
        summary = self.get_summary(days)

        report = f"""
╔════════════════════════════════════════════════════════════╗
║          ОТЧЁТ О ТОРГОВЛЕ (за {days} дней)                      ║
╠════════════════════════════════════════════════════════════╣
║                                                             ║
║  Покупки:        {summary.get('items_purchased', 0):>4} шт                             ║
║  Продажи:        {summary.get('items_sold', 0):>4} шт                             ║
║                                                             ║
║  Потрачено:      {summary.get('total_spent', 0):>10.2f} ₽                      ║
║  Получено:       {summary.get('total_earned', 0):>10.2f} ₽                      ║
║  Профит:         {summary.get('total_profit', 0):>10.2f} ₽                      ║
║                                                             ║
║  ROI:            {summary.get('roi_percent', 0):>7.2f} %                        ║
║  Ср. профит:     {summary.get('avg_profit_per_trade', 0):>10.2f} ₽/сделка             ║
║                                                             ║
║  Активных:       {summary.get('active_profitable_items', 0):>4} предмета                    ║
║                                                             ║
╚════════════════════════════════════════════════════════════╝
        """

        return report.strip()
