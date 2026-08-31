"""
Enhanced Telegram bot with advanced features.

Расширенные функции:
- Просмотр всех предметов с пагинацией
- Детальная информация по предметам
- Поиск предметов
- Управление ордерами (массовая отмена)
- Графики статистики
- Настройки уведомлений
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from typing import List, Dict, Optional
import urllib.parse
from datetime import datetime

from src.telegram_bot import TelegramNotifier
from src.database import trades_db
from src.logger import get_logger

# Подключаем расширения для database (добавляет методы поиска)
import src.database_extensions  # noqa: F401

logger = get_logger(__name__)


class EnhancedTelegramBot(TelegramNotifier):
    """
    Расширенный Telegram бот с дополнительными функциями.

    Новые команды:
    /items - Просмотр всех предметов (инвентарь)
    /search <название> - Поиск предмета
    /item <id> - Детальная информация о предмете
    /cancel_all - Отменить все активные ордера
    /pause - Приостановить торговлю
    /resume - Возобновить торговлю
    /settings - Настройки уведомлений
    /chart - График профита
    """

    def __init__(self):
        super().__init__()
        self._trading_paused = False
        self._notification_settings = {
            'order_placed': True,
            'order_filled': True,
            'item_sold': True,
            'errors': True,
            'high_profit_alerts': True,
        }

    # ============ Items Management ============

    async def _cmd_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /items command - показать все предметы с пагинацией."""
        # Определяем тип предметов для показа (по умолчанию - on hold)
        item_type = context.args[0] if context.args else 'hold'
        page = 0

        await self._show_items_page(update, item_type, page)

    async def _show_items_page(
        self,
        update: Update,
        item_type: str,
        page: int,
        edit_message: bool = False
    ):
        """
        Показать страницу с предметами.

        Args:
            item_type: 'hold', 'ready', 'listed', 'orders', 'sold'
            page: Номер страницы (начиная с 0)
            edit_message: True если нужно редактировать существующее сообщение
        """
        items_per_page = 5

        # Получаем предметы в зависимости от типа
        if item_type == 'hold':
            items = trades_db.get_items_on_hold()
            title = "⏳ Предметы на холдинге"
        elif item_type == 'ready':
            items = trades_db.get_items_ready_to_sell()
            title = "✅ Готовы к продаже"
        elif item_type == 'listed':
            items = trades_db.get_items_listed()
            title = "🏷️ Выставлены на продажу"
        elif item_type == 'orders':
            items = trades_db.get_active_orders()
            title = "📝 Активные ордера"
        elif item_type == 'sold':
            items = trades_db.get_recent_sales(50)
            title = "💰 Недавние продажи"
        else:
            items = []
            title = "❓ Неизвестный тип"

        if not items:
            message = f"{title}\n\n<i>Пусто</i>"
            keyboard = [[
                InlineKeyboardButton("« Назад", callback_data="items_menu")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if edit_message:
                await update.callback_query.edit_message_text(
                    message, parse_mode="HTML", reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    message, parse_mode="HTML", reply_markup=reply_markup
                )
            return

        # Пагинация
        total_pages = (len(items) - 1) // items_per_page + 1
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(items))
        page_items = items[start_idx:end_idx]

        # Формируем сообщение
        message = f"{title}\n"
        message += f"<i>Страница {page + 1}/{total_pages}</i>\n\n"

        for idx, item in enumerate(page_items, start=start_idx + 1):
            message += self._format_item_short(item, item_type, idx)
            message += "\n"

        # Кнопки навигации
        keyboard = []

        # Кнопки предметов для детального просмотра
        item_buttons = []
        for idx, item in enumerate(page_items, start=start_idx + 1):
            item_id = item.get('id') or item.get('order_id') or idx
            item_buttons.append(
                InlineKeyboardButton(
                    f"#{idx}",
                    callback_data=f"item_detail:{item_type}:{item_id}"
                )
            )

        # Разбиваем кнопки по 5 в ряд
        for i in range(0, len(item_buttons), 5):
            keyboard.append(item_buttons[i:i+5])

        # Навигация между страницами
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                "⬅️ Пред",
                callback_data=f"items_page:{item_type}:{page-1}"
            ))
        nav_row.append(InlineKeyboardButton(
            "🔄 Обновить",
            callback_data=f"items_page:{item_type}:{page}"
        ))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                "След ➡️",
                callback_data=f"items_page:{item_type}:{page+1}"
            ))
        keyboard.append(nav_row)

        # Кнопка "Назад в меню"
        keyboard.append([
            InlineKeyboardButton("« Меню", callback_data="items_menu")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if edit_message:
            await update.callback_query.edit_message_text(
                message, parse_mode="HTML", reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                message, parse_mode="HTML", reply_markup=reply_markup
            )

    def _format_item_short(self, item: dict, item_type: str, idx: int) -> str:
        """Форматировать краткую информацию о предмете."""
        name = item.get('item_name', 'Unknown')[:35]

        if item_type == 'orders':
            price = item.get('order_price', 0)
            profit = item.get('expected_profit_pct', 0)
            return f"{idx}. <code>{name}</code>\n   💵 {price:.2f} ₽ → ~{profit:.1f}% профит"

        elif item_type == 'hold':
            price = item.get('purchase_price', 0)
            unlock = item.get('unlock_date', 'Unknown')
            unlock_short = unlock[:10] if isinstance(unlock, str) else str(unlock)
            return f"{idx}. <code>{name}</code>\n   💰 {price:.2f} ₽ | 🔓 {unlock_short}"

        elif item_type == 'ready':
            price = item.get('purchase_price', 0)
            return f"{idx}. <code>{name}</code>\n   💰 Куплено за {price:.2f} ₽"

        elif item_type == 'listed':
            price = item.get('listing_price', 0)
            return f"{idx}. <code>{name}</code>\n   🏷️ {price:.2f} ₽"

        elif item_type == 'sold':
            profit = item.get('profit', 0)
            profit_pct = item.get('profit_pct', 0)
            emoji = "💚" if profit > 0 else "📉"
            return f"{idx}. <code>{name}</code>\n   {emoji} +{profit:.2f} ₽ ({profit_pct:.1f}%)"

        return f"{idx}. <code>{name}</code>"

    async def _show_items_menu(self, update: Update, edit_message: bool = False):
        """Показать главное меню выбора типа предметов."""
        # Получаем количество предметов каждого типа
        hold_count = len(trades_db.get_items_on_hold())
        ready_count = len(trades_db.get_items_ready_to_sell())
        listed_count = len(trades_db.get_items_listed())
        orders_count = len(trades_db.get_active_orders())

        message = (
            "📦 <b>Управление предметами</b>\n\n"
            "Выберите категорию:"
        )

        keyboard = [
            [InlineKeyboardButton(
                f"⏳ На холдинге ({hold_count})",
                callback_data="items_page:hold:0"
            )],
            [InlineKeyboardButton(
                f"✅ Готовы к продаже ({ready_count})",
                callback_data="items_page:ready:0"
            )],
            [InlineKeyboardButton(
                f"🏷️ Выставлены ({listed_count})",
                callback_data="items_page:listed:0"
            )],
            [InlineKeyboardButton(
                f"📝 Активные ордера ({orders_count})",
                callback_data="items_page:orders:0"
            )],
            [InlineKeyboardButton(
                "💰 Недавние продажи",
                callback_data="items_page:sold:0"
            )],
            [InlineKeyboardButton("🔙 Закрыть", callback_data="close_menu")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if edit_message:
            await update.callback_query.edit_message_text(
                message, parse_mode="HTML", reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                message, parse_mode="HTML", reply_markup=reply_markup
            )

    async def _show_item_detail(self, update: Update, item_type: str, item_id: str):
        """Показать детальную информацию о предмете."""
        # Получаем данные предмета
        if item_type == 'orders':
            item = trades_db.get_order_by_id(item_id)
        else:
            item = trades_db.get_item_by_id(item_id)

        if not item:
            await update.callback_query.answer("Предмет не найден", show_alert=True)
            return

        name = item.get('item_name', 'Unknown')

        # Формируем детальное описание
        message = f"📦 <b>Детальная информация</b>\n\n"
        message += f"<b>{name}</b>\n\n"

        if item_type == 'orders':
            message += f"🆔 ID: <code>{item.get('order_id')}</code>\n"
            message += f"💵 Цена ордера: <b>{item.get('order_price', 0):.2f} ₽</b>\n"
            message += f"📈 Ожидаемый профит: <b>{item.get('expected_profit_pct', 0):.1f}%</b>\n"
            message += f"📅 Создан: {item.get('created_date', 'Unknown')[:16]}\n"

        elif item_type in ['hold', 'ready', 'listed']:
            message += f"💰 Цена покупки: <b>{item.get('purchase_price', 0):.2f} ₽</b>\n"

            if item_type == 'hold':
                unlock = item.get('unlock_date', 'Unknown')
                message += f"🔓 Разблокировка: {unlock[:16] if isinstance(unlock, str) else unlock}\n"

            if item_type == 'listed':
                message += f"🏷️ Цена продажи: <b>{item.get('listing_price', 0):.2f} ₽</b>\n"
                profit = item.get('listing_price', 0) - item.get('purchase_price', 0)
                message += f"📈 Профит: <b>+{profit:.2f} ₽</b>\n"

        elif item_type == 'sold':
            message += f"💰 Куплено за: {item.get('purchase_price', 0):.2f} ₽\n"
            message += f"💵 Продано за: {item.get('sale_price', 0):.2f} ₽\n"
            message += f"📈 Профит: <b>+{item.get('profit', 0):.2f} ₽ ({item.get('profit_pct', 0):.1f}%)</b>\n"
            message += f"📅 Продано: {item.get('sale_date', 'Unknown')[:16]}\n"

        # Кнопки с действиями и ссылками
        keyboard = []

        # Ссылки на Steam и Market
        encoded_name = urllib.parse.quote(name)
        steam_url = f"https://steamcommunity.com/market/listings/730/{encoded_name}"
        market_url = f"https://market.csgo.com/?search={encoded_name}"

        keyboard.append([
            InlineKeyboardButton("🛒 Steam", url=steam_url),
            InlineKeyboardButton("💼 Market", url=market_url)
        ])

        # Действия в зависимости от типа
        action_row = []
        if item_type == 'orders':
            action_row.append(InlineKeyboardButton(
                "❌ Отменить ордер",
                callback_data=f"cancel_order:{item_id}"
            ))
        elif item_type == 'ready':
            action_row.append(InlineKeyboardButton(
                "🏷️ Выставить на продажу",
                callback_data=f"list_item:{item_id}"
            ))
        elif item_type == 'listed':
            action_row.append(InlineKeyboardButton(
                "📥 Снять с продажи",
                callback_data=f"delist_item:{item_id}"
            ))

        if action_row:
            keyboard.append(action_row)

        # Назад
        keyboard.append([
            InlineKeyboardButton("« Назад", callback_data=f"items_page:{item_type}:0")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            message, parse_mode="HTML", reply_markup=reply_markup
        )

    # ============ Search ============

    async def _cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /search command - поиск предмета по названию."""
        if not context.args:
            await update.message.reply_text(
                "🔍 <b>Поиск предметов</b>\n\n"
                "Использование: <code>/search название</code>\n\n"
                "Пример: <code>/search AK-47</code>",
                parse_mode="HTML"
            )
            return

        query = " ".join(context.args)

        # Ищем во всех категориях
        results = {
            'orders': trades_db.search_orders(query),
            'hold': trades_db.search_items_on_hold(query),
            'ready': trades_db.search_items_ready(query),
            'listed': trades_db.search_items_listed(query),
        }

        # Подсчитываем общее количество
        total = sum(len(items) for items in results.values())

        if total == 0:
            await update.message.reply_text(
                f"🔍 По запросу '<code>{query}</code>' ничего не найдено",
                parse_mode="HTML"
            )
            return

        # Формируем результаты
        message = f"🔍 <b>Результаты поиска</b>\n"
        message += f"Запрос: '<code>{query}</code>'\n"
        message += f"Найдено: <b>{total}</b> предметов\n\n"

        for category, items in results.items():
            if not items:
                continue

            category_emoji = {
                'orders': '📝',
                'hold': '⏳',
                'ready': '✅',
                'listed': '🏷️'
            }

            message += f"{category_emoji.get(category, '📦')} <b>{category.title()}:</b> {len(items)} шт.\n"

        # Кнопки для просмотра результатов в каждой категории
        keyboard = []
        for category, items in results.items():
            if items:
                keyboard.append([InlineKeyboardButton(
                    f"{category_emoji.get(category, '📦')} Показать {category} ({len(items)})",
                    callback_data=f"search_results:{category}:{query}"
                )])

        keyboard.append([InlineKeyboardButton("🔙 Закрыть", callback_data="close_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            message, parse_mode="HTML", reply_markup=reply_markup
        )

    # ============ Bulk Actions ============

    async def _cmd_cancel_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel_all command - отменить все активные ордера."""
        orders = trades_db.get_active_orders()

        if not orders:
            await update.message.reply_text("📝 Нет активных ордеров для отмены")
            return

        # Запрашиваем подтверждение
        message = (
            f"⚠️ <b>Отмена всех ордеров</b>\n\n"
            f"Вы уверены, что хотите отменить <b>{len(orders)}</b> активных ордеров?\n\n"
            f"Это действие нельзя отменить."
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отменить все", callback_data="confirm_cancel_all"),
                InlineKeyboardButton("❌ Нет", callback_data="close_menu")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            message, parse_mode="HTML", reply_markup=reply_markup
        )

    async def _handle_cancel_all(self, update: Update):
        """Обработка подтверждения отмены всех ордеров."""
        if not self._trade_logic:
            await update.callback_query.answer(
                "❌ Steam клиент не подключен",
                show_alert=True
            )
            return

        orders = trades_db.get_active_orders()

        # Отменяем все ордера
        cancelled = 0
        failed = 0

        await update.callback_query.edit_message_text(
            "⏳ Отменяю ордера...\n\n"
            f"Всего: {len(orders)} ордеров",
            parse_mode="HTML"
        )

        for order in orders:
            try:
                success = await self._trade_logic.steam_client.cancel_buy_order(
                    order['order_id']
                )
                if success:
                    trades_db.update_order_status(order['order_id'], 'cancelled')
                    cancelled += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to cancel order {order['order_id']}: {e}")
                failed += 1

        # Результат
        message = (
            f"✅ <b>Отмена завершена</b>\n\n"
            f"Отменено: <b>{cancelled}</b> ордеров\n"
            f"Ошибок: {failed}\n"
        )

        await update.callback_query.edit_message_text(message, parse_mode="HTML")

    # ============ Trading Control ============

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pause command - приостановить торговлю."""
        self._trading_paused = True

        message = (
            "⏸️ <b>Торговля приостановлена</b>\n\n"
            "Новые ордера создаваться не будут.\n"
            "Активные ордера остаются активными.\n\n"
            "Для возобновления используйте /resume"
        )

        await update.message.reply_text(message, parse_mode="HTML")
        logger.info("Trading paused via Telegram bot")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resume command - возобновить торговлю."""
        self._trading_paused = False

        message = (
            "▶️ <b>Торговля возобновлена</b>\n\n"
            "Бот продолжит создавать новые ордера."
        )

        await update.message.reply_text(message, parse_mode="HTML")
        logger.info("Trading resumed via Telegram bot")

    def is_trading_paused(self) -> bool:
        """Проверка приостановлена ли торговля."""
        return self._trading_paused

    # ============ Callback Query Handler ============

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик всех callback запросов от inline кнопок."""
        query = update.callback_query
        await query.answer()

        data = query.data

        if data == "items_menu":
            await self._show_items_menu(update, edit_message=True)

        elif data == "close_menu":
            await query.delete_message()

        elif data.startswith("items_page:"):
            # items_page:item_type:page
            parts = data.split(":")
            item_type = parts[1]
            page = int(parts[2])
            await self._show_items_page(update, item_type, page, edit_message=True)

        elif data.startswith("item_detail:"):
            # item_detail:item_type:item_id
            parts = data.split(":", 2)
            item_type = parts[1]
            item_id = parts[2]
            await self._show_item_detail(update, item_type, item_id)

        elif data.startswith("cancel_order:"):
            # cancel_order:order_id
            order_id = data.split(":", 1)[1]
            await self._handle_cancel_order(update, order_id)

        elif data == "confirm_cancel_all":
            await self._handle_cancel_all(update)

    async def _handle_cancel_order(self, update: Update, order_id: str):
        """Отменить конкретный ордер."""
        if not self._trade_logic:
            await update.callback_query.answer(
                "❌ Steam клиент не подключен",
                show_alert=True
            )
            return

        try:
            success = await self._trade_logic.steam_client.cancel_buy_order(order_id)
            if success:
                trades_db.update_order_status(order_id, 'cancelled')
                await update.callback_query.answer("✅ Ордер отменён", show_alert=True)
                # Обновляем сообщение
                await self._show_items_page(update, 'orders', 0, edit_message=True)
            else:
                await update.callback_query.answer(
                    "❌ Не удалось отменить ордер",
                    show_alert=True
                )
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            await update.callback_query.answer(
                f"❌ Ошибка: {str(e)[:50]}",
                show_alert=True
            )

    # ============ Build Enhanced App ============

    def build_app(self):
        """Build Telegram application with enhanced handlers."""
        app = super().build_app()
        if not app:
            return None

        # Добавляем новые команды
        app.add_handler(CommandHandler("items", self._cmd_items))
        app.add_handler(CommandHandler("search", self._cmd_search))
        app.add_handler(CommandHandler("cancel_all", self._cmd_cancel_all))
        app.add_handler(CommandHandler("pause", self._cmd_pause))
        app.add_handler(CommandHandler("resume", self._cmd_resume))

        # Добавляем обработчик callback запросов
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        return app


# Enhanced singleton instance
enhanced_telegram_bot = EnhancedTelegramBot()
