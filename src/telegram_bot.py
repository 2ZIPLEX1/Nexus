"""
Telegram bot for notifications and control.

Sends notifications about trades and provides commands to control the bot.
"""

import asyncio
import os
import uuid
from datetime import datetime
from typing import Optional

from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import settings
from src.database import trades_db
from src.logger import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """
    Telegram bot for trade notifications and control.

    Commands:
    /start - Start the bot
    /status - Get current trading status
    /balance - Get wallet balance
    /orders - Get active orders
    /holdings - Get items on hold
    /profit - Get profit statistics
    /help - Show help message
    """

    def __init__(self):
        """Initialize Telegram notifier."""
        # telegram_bot_token теперь SecretStr — разворачиваем для python-telegram-bot.
        _token = settings.telegram_bot_token
        self.token = _token.get_secret_value() if _token is not None else None
        self.chat_id = settings.telegram_chat_id
        self._bot: Optional[Bot] = None
        self._app: Optional[Application] = None
        self._trade_logic = None  # Set later to avoid circular import
        self._sales_service = None  # TM Sales Service reference

        # Интерактивные запросы для аккаунтов без maFile (замена консольного input()):
        # ждём Steam Guard код сообщением и подтверждение — нажатием кнопки.
        self._pending_code_request: Optional[dict] = None
        self._pending_confirmations: dict = {}

    @property
    def is_configured(self) -> bool:
        """Check if Telegram is configured."""
        return bool(self.token and self.chat_id)

    def set_trade_logic(self, trade_logic):
        """Set trade logic reference for status commands."""
        self._trade_logic = trade_logic

    def set_sales_service(self, sales_service):
        """Set sales service reference for price update callbacks."""
        self._sales_service = sales_service

    async def send_message(self, text: str, parse_mode: str = "HTML", reply_markup=None):
        """
        Send a message to the configured chat.

        Args:
            text: Message text
            parse_mode: Telegram parse mode (HTML, Markdown)
            reply_markup: Optional inline keyboard
        """
        if not self.is_configured:
            logger.warning("Telegram not configured, skipping notification")
            return

        try:
            if not self._bot:
                self._bot = Bot(token=self.token)

            await self._bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def send_message_sync(self, text: str, parse_mode: str = "HTML"):
        """Synchronous wrapper for send_message."""
        try:
            asyncio.run(self.send_message(text, parse_mode))
        except RuntimeError:
            # Already in async context
            loop = asyncio.get_event_loop()
            loop.create_task(self.send_message(text, parse_mode))

    def _send_message_with_buttons_sync(self, text: str, reply_markup):
        """Synchronous wrapper for send_message with buttons."""
        try:
            asyncio.run(self.send_message(text, "HTML", reply_markup))
        except RuntimeError:
            # Already in async context
            loop = asyncio.get_event_loop()
            loop.create_task(self.send_message(text, "HTML", reply_markup))

    # ============ Notification Methods ============

    def notify_order_placed(
        self,
        item_name: str,
        steam_price: float,
        csgotm_price: float,
        recommended_price: float,
        profit_pct: float,
        account_name: str = None
    ):
        """Notify about new buy order with inline buttons."""
        # Вычисляем профит от рекомендованной цены
        profit_rub = csgotm_price - recommended_price

        # Формируем заголовок с именем аккаунта
        header = f"🟢 <b>Order Placed!</b> [{account_name}]" if account_name else "🟢 <b>Order Placed!</b>"

        message = (
            f"{header}\n\n"
            f"<b>{item_name}</b>\n\n"
            f"💰 Steam: <b>{steam_price:.2f} RUB</b>\n"
            f"💵 Market: <b>{csgotm_price:.2f} RUB</b>\n"
            f"Recommended price: <b>{recommended_price:.2f} RUB</b>\n"
            f"📈 Profit: <b>{profit_rub:+.2f} RUB ({profit_pct:.1f}%)</b>"
        )

        # Создаем кнопки с ссылками
        # Кодируем название предмета для URL
        import urllib.parse
        encoded_name = urllib.parse.quote(item_name)
        steam_url = f"https://steamcommunity.com/market/listings/730/{encoded_name}"
        # CSGO.TM использует search по market_hash_name
        market_url = f"https://market.csgo.com/?search={encoded_name}"

        keyboard = [
            [
                InlineKeyboardButton("🛒 Steam", url=steam_url),
                InlineKeyboardButton("💼 Market", url=market_url)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        self._send_message_with_buttons_sync(message, reply_markup)

    def notify_order_filled(self, item_name: str, price: float, unlock_date: datetime):
        """Notify about filled order."""
        message = (
            f"✅ <b>Order Filled!</b>\n\n"
            f"Item: <code>{item_name}</code>\n"
            f"Price: <b>${price:.2f}</b>\n"
            f"Unlock Date: <b>{unlock_date.strftime('%Y-%m-%d %H:%M')}</b>"
        )
        self.send_message_sync(message)

    def notify_order_cancelled(self, item_name: str, reason: str):
        """Notify about cancelled order."""
        message = (
            f"❌ <b>Order Cancelled</b>\n\n"
            f"Item: <code>{item_name}</code>\n"
            f"Reason: {reason}"
        )
        self.send_message_sync(message)

    def notify_item_listed(self, item_name: str, price: float):
        """Notify about item listed for sale."""
        message = (
            f"🏷️ <b>Item Listed for Sale</b>\n\n"
            f"Item: <code>{item_name}</code>\n"
            f"Price: <b>${price:.2f}</b>"
        )
        self.send_message_sync(message)

    def notify_item_sold(self, item_name: str, sale_price: float, profit: float):
        """Notify about sold item."""
        emoji = "💰" if profit > 0 else "📉"
        message = (
            f"{emoji} <b>Item Sold!</b>\n\n"
            f"Item: <code>{item_name}</code>\n"
            f"Sale Price: <b>${sale_price:.2f}</b>\n"
            f"Profit: <b>${profit:.2f}</b>"
        )
        self.send_message_sync(message)

    def notify_error(self, error_type: str, details: str):
        """Notify about an error."""
        message = (
            f"⚠️ <b>Error: {error_type}</b>\n\n"
            f"<code>{details}</code>"
        )
        self.send_message_sync(message)

    def notify_cycle_complete(self, cycle_type: str, summary: dict):
        """Notify about completed cycle."""
        if cycle_type == "buy":
            message = (
                f"🔄 <b>Buy Cycle Complete</b>\n\n"
                f"Filled Orders: {summary.get('filled_orders', 0)}\n"
                f"Cancelled: {summary.get('cancelled_orders', 0)}\n"
                f"New Orders: {summary.get('new_orders', 0)}\n"
                f"Failed: {summary.get('failed_orders', 0)}"
            )
        else:
            message = (
                f"🔄 <b>Sell Cycle Complete</b>\n\n"
                f"Items Sold: {summary.get('items_sold', 0)}\n"
                f"Items Listed: {summary.get('items_listed', 0)}\n"
                f"Failed: {summary.get('failed_listings', 0)}"
            )
        self.send_message_sync(message)

    # ============ Command Handlers ============

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "🤖 <b>Steam Trading Bot</b>\n\n"
            "I'll notify you about trades and let you control the bot.\n\n"
            "<b>📊 Статус и статистика:</b>\n"
            "/status - Общий статус\n"
            "/balance - Баланс кошелька\n"
            "/profit - Статистика прибыли\n"
            "/stats - Детальная статистика\n"
            "/report - Дневной отчёт\n\n"
            "<b>📦 Инвентарь:</b>\n"
            "/inventory - Предметы на холде\n"
            "/ready - Готовые к продаже\n"
            "/holdings - Все предметы\n\n"
            "<b>📝 Ордера:</b>\n"
            "/orders - Активные ордера\n"
            "/check_orders - Проверить актуальность\n"
            "/cancel [ID] - Отменить ордер\n"
            "/cancel_all - Отменить все ордера\n\n"
            "<b>💰 TM Sales:</b>\n"
            "/prices - Завышенные цены\n"
            "/ignored - Не продаём\n"
            "/unignore [имя] - Вернуть в продажи\n"
            "/update_prices - Обновить до топ-1\n"
            "/sales_stats - Статистика продаж\n\n"
            "<b>⚙️ Настройки:</b>\n"
            "/settings - Текущие настройки\n"
            "/set_profit [%] - Мин. профит\n"
            "/set_min_sales [N] - Мин. продаж\n\n"
            "/help - Показать это меню",
            parse_mode="HTML"
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        if self._trade_logic:
            status = self._trade_logic.get_status()
        else:
            status = trades_db.get_stats()

        message = (
            f"📊 <b>Trading Status</b>\n\n"
            f"💰 Balance: <b>${status.get('wallet_balance', 0):.2f}</b>\n"
            f"📈 Max Orders: <b>${status.get('max_orders_value', 0):.2f}</b>\n\n"
            f"📝 Active Orders: {status.get('active_orders', 0)}\n"
            f"💵 Orders Value: ${status.get('total_orders_value', 0):.2f}\n"
            f"⏳ Items on Hold: {status.get('items_on_hold', 0)}\n"
            f"✅ Ready to Sell: {status.get('items_ready_to_sell', 0)}\n"
            f"🏷️ Listed for Sale: {status.get('items_listed', 0)}\n\n"
            f"💵 Total Sales: {status.get('total_sales', 0)}\n"
            f"💰 Total Profit: ${status.get('total_profit', 0):.2f}"
        )
        await update.message.reply_text(message, parse_mode="HTML")

    async def _cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance command."""
        from src.currency_rates import get_currency_provider
        currency_provider = get_currency_provider()

        # Try to get balances from AppState (most reliable source)
        try:
            from flet_gui.state.app_state import AppState
            state = AppState()

            total_steam_rub = 0
            total_tm_rub = 0
            total_settlement_rub = 0
            account_details = []

            for acc in state.accounts:
                steam_bal = acc.steam_balance or 0
                tm_bal = acc.csgotm_balance or 0
                settlement_bal = acc.csgotm_settlement or 0
                currency = acc.currency or "RUB"

                # Convert Steam balance to RUB
                steam_bal_rub = currency_provider.convert_to_rub(steam_bal, currency)

                # CSGO.TM balances are ALWAYS in RUB
                tm_bal_rub = tm_bal
                settlement_bal_rub = settlement_bal

                total_steam_rub += steam_bal_rub
                total_tm_rub += tm_bal_rub
                total_settlement_rub += settlement_bal_rub

                if steam_bal > 0 or tm_bal > 0 or settlement_bal > 0:
                    account_details.append({
                        'name': acc.username,
                        'steam': steam_bal,
                        'currency': currency,
                        'tm': tm_bal,
                        'settlement': settlement_bal
                    })

            current_orders = trades_db.get_total_orders_value()

            message = "💰 <b>Балансы аккаунтов</b>\n\n"

            if account_details:
                for acc_info in account_details:
                    message += f"<b>{acc_info['name']}</b>:\n"
                    if acc_info['steam'] > 0:
                        message += f"  Steam: {acc_info['steam']:.2f} {acc_info['currency']}\n"
                    if acc_info['tm'] > 0:
                        message += f"  TM: {acc_info['tm']:.2f}₽\n"
                    if acc_info['settlement'] > 0:
                        message += f"  На выводе: {acc_info['settlement']:.2f}₽\n"
                message += "\n"

            message += "<b>Итого (в RUB):</b>\n"
            message += f"  Steam: {total_steam_rub:,.0f}₽\n"
            message += f"  CSGO.TM: {total_tm_rub:,.0f}₽\n"
            message += f"  На выводе: {total_settlement_rub:,.0f}₽\n"
            message += f"  <b>Всего: {total_steam_rub + total_tm_rub + total_settlement_rub:,.0f}₽</b>\n\n"
            message += f"Активных ордеров: {current_orders:.2f}₽"

        except Exception as e:
            logger.error(f"Error getting balances from AppState: {e}")
            # Fallback to old method
            balance = 0
            currency = "USD"
            if self._trade_logic:
                try:
                    wallet = self._trade_logic.steam.get_wallet_balance()
                    balance = wallet.balance
                    currency = wallet.currency_code
                except Exception:
                    pass

            max_orders = settings.calculate_max_orders_value(balance)
            current_orders = trades_db.get_total_orders_value()

            message = (
                f"💰 <b>Wallet Balance</b>\n\n"
                f"Balance: <b>{balance:.2f} {currency}</b>\n"
                f"Max Orders (x{settings.order_limit_multiplier}): {max_orders:.2f}\n"
                f"Current Orders: {current_orders:.2f}\n"
                f"Available: {max_orders - current_orders:.2f}"
            )

        await update.message.reply_text(message, parse_mode="HTML")

    async def _cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /orders command."""
        orders = trades_db.get_active_orders()

        if not orders:
            await update.message.reply_text("📝 No active orders")
            return

        message = f"📝 <b>Active Orders ({len(orders)})</b>\n\n"

        for order in orders[:10]:  # Limit to 10
            message += (
                f"• <code>{order['item_name'][:30]}</code>\n"
                f"  ${order['order_price']:.2f} → "
                f"~{order.get('expected_profit_pct', 0):.1f}% profit\n"
            )

        if len(orders) > 10:
            message += f"\n<i>...and {len(orders) - 10} more</i>"

        await update.message.reply_text(message, parse_mode="HTML")

    async def _cmd_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /holdings command."""
        holdings = trades_db.get_items_on_hold()
        ready = trades_db.get_items_ready_to_sell()

        message = f"⏳ <b>Items on Hold ({len(holdings)})</b>\n\n"

        for item in holdings[:5]:
            unlock = item.get("unlock_date", "Unknown")
            message += (
                f"• <code>{item['item_name'][:30]}</code>\n"
                f"  ${item['purchase_price']:.2f} | Unlocks: {unlock[:10]}\n"
            )

        if ready:
            message += f"\n\n✅ <b>Ready to Sell ({len(ready)})</b>\n"
            for item in ready[:5]:
                message += f"• <code>{item['item_name'][:30]}</code>\n"

        await update.message.reply_text(message, parse_mode="HTML")

    async def _cmd_profit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /profit command."""
        stats = trades_db.get_total_profit()
        recent = trades_db.get_recent_sales(5)

        message = (
            f"💰 <b>Profit Statistics</b>\n\n"
            f"Total Sales: {stats.get('total_sales', 0)}\n"
            f"Total Invested: ${stats.get('total_invested', 0):.2f}\n"
            f"Total Revenue: ${stats.get('total_revenue', 0):.2f}\n"
            f"Total Profit: <b>${stats.get('total_profit', 0):.2f}</b>\n"
            f"Avg Profit: {stats.get('avg_profit_pct', 0):.1f}%\n"
        )

        if recent:
            message += "\n<b>Recent Sales:</b>\n"
            for sale in recent:
                message += (
                    f"• {sale['item_name'][:25]}: "
                    f"+${sale['profit']:.2f}\n"
                )

        await update.message.reply_text(message, parse_mode="HTML")

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command - показать детальную статистику."""
        # Получаем статистику за разные периоды
        today_stats = trades_db.get_stats_for_period('today')
        week_stats = trades_db.get_stats_for_period('week')
        month_stats = trades_db.get_stats_for_period('month')
        all_time_stats = trades_db.get_stats()

        message = (
            f"📊 <b>Детальная Статистика</b>\n\n"
            f"<b>Сегодня:</b>\n"
            f"  Ордера: {today_stats.get('orders_created', 0)} создано, "
            f"{today_stats.get('orders_filled', 0)} исполнено\n"
            f"  Продажи: {today_stats.get('items_sold', 0)} шт, "
            f"профит: {today_stats.get('total_profit', 0):,.0f}₽\n\n"
            f"<b>Неделя:</b>\n"
            f"  Ордера: {week_stats.get('orders_created', 0)} создано, "
            f"{week_stats.get('orders_filled', 0)} исполнено\n"
            f"  Продажи: {week_stats.get('items_sold', 0)} шт, "
            f"профит: {week_stats.get('total_profit', 0):,.0f}₽\n\n"
            f"<b>Месяц:</b>\n"
            f"  Ордера: {month_stats.get('orders_created', 0)} создано, "
            f"{month_stats.get('orders_filled', 0)} исполнено\n"
            f"  Продажи: {month_stats.get('items_sold', 0)} шт, "
            f"профит: {month_stats.get('total_profit', 0):,.0f}₽\n\n"
            f"<b>Всего:</b>\n"
            f"  💰 Общий профит: <b>{all_time_stats.get('total_profit', 0):,.0f}₽</b>\n"
            f"  📈 Средний профит: {all_time_stats.get('avg_profit_pct', 0):.1f}%\n"
            f"  📝 Активных ордеров: {all_time_stats.get('active_orders', 0)}"
        )
        await update.message.reply_text(message, parse_mode="HTML")

    def _get_steam_client(self, account_name: str = ""):
        """
        Steam-клиент для операций с ордерами.

        Раньше команды брали его только из self._trade_logic — это путь GUI.
        В серверном режиме (server_runner/web.api) оркестратор кладёт сюда
        sales_service, а trade_logic остаётся пустым, поэтому /cancel и
        /cancel_all отвечали «Steam клиент не подключен» и ничего не делали.
        """
        svc = self._sales_service
        if svc is not None:
            acc_service = getattr(svc, "account_service", None)
            manager = getattr(acc_service, "account_manager", None) if acc_service else None
            if manager:
                account = manager.get_account(account_name) if account_name else None
                if account is None:
                    # У ордера может не быть account_name — берём любой залогиненный.
                    for candidate in manager.get_all_accounts():
                        if getattr(candidate, "steam_client", None) and candidate.is_logged_in():
                            account = candidate
                            break
                if account is not None and getattr(account, "steam_client", None):
                    return account.steam_client

        if self._trade_logic and getattr(self._trade_logic, "steam_client", None):
            return self._trade_logic.steam_client

        return None

    async def _cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command - отменить ордер по ID."""
        if not context.args:
            # Показываем список активных ордеров с ID
            orders = trades_db.get_active_orders()
            if not orders:
                await update.message.reply_text("📝 Нет активных ордеров")
                return

            message = "📝 <b>Активные ордера</b>\n\n"
            message += "Используйте <code>/cancel ORDER_ID</code> для отмены\n\n"

            for order in orders[:15]:  # Limit to 15
                message += (
                    f"ID: <code>{order['order_id']}</code>\n"
                    f"• {order['item_name'][:35]}\n"
                    f"  ${order['order_price']:.2f}\n\n"
                )

            if len(orders) > 15:
                message += f"<i>...и ещё {len(orders) - 15}</i>"

            await update.message.reply_text(message, parse_mode="HTML")
            return

        # Отменяем указанный ордер
        order_id = context.args[0]

        # Проверяем, существует ли ордер
        order = trades_db.get_order_by_id(order_id)
        if not order:
            await update.message.reply_text(
                f"❌ Ордер {order_id} не найден",
                parse_mode="HTML"
            )
            return

        # Отменяем через Steam API
        steam_client = self._get_steam_client(order.get('account_name', ''))
        if steam_client:
            try:
                success = await steam_client.cancel_buy_order(order_id)
                if success:
                    # Обновляем статус в БД
                    trades_db.update_order_status(order_id, 'cancelled')
                    await update.message.reply_text(
                        f"✅ Ордер отменён\n\n"
                        f"ID: <code>{order_id}</code>\n"
                        f"Предмет: {order['item_name']}\n"
                        f"Цена: ${order['order_price']:.2f}",
                        parse_mode="HTML"
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Не удалось отменить ордер {order_id}",
                        parse_mode="HTML"
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Ошибка при отмене ордера:\n<code>{str(e)}</code>",
                    parse_mode="HTML"
                )
        else:
            await update.message.reply_text(
                "❌ Steam клиент не подключен",
                parse_mode="HTML"
            )

    async def _cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /report command - получить ежедневный отчет."""
        await self.send_daily_report()

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self._cmd_start(update, context)

    # ============ Inventory Commands ============

    async def _cmd_inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /inventory command - показать предметы на холде с ценами."""
        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            # Получаем все предметы на холде
            items = db.get_purchased_items(status='holding')

            if not items:
                await update.message.reply_text("📦 Нет предметов на холде", parse_mode="HTML")
                return

            # Сортируем по дате разблокировки
            items.sort(key=lambda x: x.get('unlock_date', '9999'))

            message = f"📦 <b>Инвентарь на холде ({len(items)} шт)</b>\n\n"

            total_invested = 0
            total_expected = 0

            for idx, item in enumerate(items[:15], 1):
                name = item.get('market_hash_name') or item.get('item_name', 'Unknown')
                buy_price = item.get('purchase_price', 0) or 0
                expected = item.get('expected_sell_price', 0) or 0
                current = item.get('current_csgotm_price', 0) or 0
                unlock = item.get('unlock_date', '')[:10] if item.get('unlock_date') else '?'
                account = item.get('account_name', 'default')

                total_invested += buy_price

                # Вычисляем профит
                sell_price = current if current > 0 else expected
                if sell_price > 0 and buy_price > 0:
                    profit_pct = ((sell_price * 0.9) - buy_price) / buy_price * 100  # -10% комиссия
                    profit_emoji = "📈" if profit_pct >= 0 else "📉"
                    total_expected += sell_price * 0.9
                else:
                    profit_pct = 0
                    profit_emoji = "❓"
                    total_expected += buy_price

                message += f"{idx}. <b>{name[:35]}</b>\n"
                message += f"   💰 {buy_price:.0f}₽ → "
                if current > 0:
                    message += f"🎯 {current:.0f}₽ "
                elif expected > 0:
                    message += f"📊 {expected:.0f}₽ "
                message += f"{profit_emoji} {profit_pct:+.1f}%\n"
                message += f"   📅 {unlock} | 👤 {account}\n\n"

            if len(items) > 15:
                message += f"<i>...и ещё {len(items) - 15} предметов</i>\n\n"

            # Итого
            expected_profit = total_expected - total_invested
            message += f"<b>Итого:</b>\n"
            message += f"💰 Вложено: {total_invested:.0f}₽\n"
            message += f"📊 Ожидаем: {total_expected:.0f}₽\n"
            message += f"📈 Профит: {expected_profit:+.0f}₽"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /inventory command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_ready(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ready command - показать предметы готовые к продаже."""
        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            items = db.get_items_ready_for_sale()

            if not items:
                await update.message.reply_text(
                    "✅ <b>Нет предметов готовых к продаже</b>\n\n"
                    "Все предметы либо на холде, либо уже выставлены.",
                    parse_mode="HTML"
                )
                return

            message = f"✅ <b>Готовы к продаже ({len(items)} шт)</b>\n\n"

            for idx, item in enumerate(items[:20], 1):
                name = item.get('market_hash_name') or item.get('item_name', 'Unknown')
                buy_price = item.get('purchase_price', 0) or 0
                expected = item.get('expected_sell_price', 0) or 0
                current = item.get('current_csgotm_price', 0) or 0
                account = item.get('account_name', 'default')

                sell_price = current if current > 0 else expected
                if sell_price > 0 and buy_price > 0:
                    profit = (sell_price * 0.9) - buy_price
                    profit_pct = profit / buy_price * 100
                    profit_emoji = "💚" if profit >= 0 else "❤️"
                else:
                    profit = 0
                    profit_pct = 0
                    profit_emoji = "❓"

                message += f"{idx}. <b>{name[:30]}</b>\n"
                message += f"   💰 {buy_price:.0f}₽ → {sell_price:.0f}₽ "
                message += f"{profit_emoji} {profit:+.0f}₽ ({profit_pct:+.1f}%)\n"
                message += f"   👤 {account}\n\n"

            if len(items) > 20:
                message += f"<i>...и ещё {len(items) - 20}</i>\n"

            message += "\n💡 Используй TM Sales в GUI для выставления"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /ready command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_check_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /check_orders command - проверить актуальность ордеров."""
        try:
            await update.message.reply_text(
                "⏳ <b>Проверяю ордера...</b>\n\nЭто может занять некоторое время...",
                parse_mode="HTML"
            )

            from src.database import TradesDatabase
            db = TradesDatabase()

            # Получаем активные ордера
            orders = db.get_active_orders()

            if not orders:
                await update.message.reply_text("📝 Нет активных ордеров", parse_mode="HTML")
                return

            # Группируем результаты проверки
            outdated_orders = []  # Ордера с изменившейся ценой
            profitable_orders = []  # Все ещё выгодные
            unprofitable_orders = []  # Стали невыгодными

            for order in orders[:30]:  # Проверяем первые 30
                market_hash_name = order.get('market_hash_name') or order.get('item_name')
                order_price = order.get('order_price', 0)
                expected_profit = order.get('expected_profit_pct', 0)
                order_id = order.get('order_id')
                account = order.get('account_name', 'default')

                # Получаем текущую цену на TM
                current_tm_price = 0
                try:
                    if self._sales_service:
                        acc_state = self._sales_service._account_states.get(account)
                        if acc_state and acc_state.csgotm_client:
                            price_info = acc_state.csgotm_client.get_item_price(market_hash_name)
                            if price_info and price_info.get('min_price'):
                                current_tm_price = price_info['min_price']
                except Exception:
                    pass

                # Вычисляем текущий профит
                if current_tm_price > 0 and order_price > 0:
                    current_profit_pct = ((current_tm_price * 0.9) - order_price) / order_price * 100
                else:
                    current_profit_pct = expected_profit

                order_info = {
                    'order_id': order_id,
                    'name': market_hash_name,
                    'order_price': order_price,
                    'tm_price': current_tm_price,
                    'expected_profit': expected_profit,
                    'current_profit': current_profit_pct,
                    'account': account
                }

                if current_profit_pct < 0:
                    unprofitable_orders.append(order_info)
                elif current_profit_pct < expected_profit - 5:  # Профит упал более чем на 5%
                    outdated_orders.append(order_info)
                else:
                    profitable_orders.append(order_info)

            # Формируем сообщение
            message = f"📝 <b>Проверка ордеров</b>\n\n"
            message += f"Всего активных: {len(orders)}\n"
            message += f"Проверено: {min(30, len(orders))}\n\n"

            # Невыгодные ордера (красные)
            if unprofitable_orders:
                message += f"❌ <b>Невыгодные ({len(unprofitable_orders)}):</b>\n"
                for o in unprofitable_orders[:5]:
                    message += f"• {o['name'][:25]}...\n"
                    message += f"  {o['order_price']:.0f}₽ → {o['tm_price']:.0f}₽ ({o['current_profit']:+.1f}%)\n"
                if len(unprofitable_orders) > 5:
                    message += f"  <i>...и ещё {len(unprofitable_orders) - 5}</i>\n"
                message += "\n"

            # Устаревшие (жёлтые)
            if outdated_orders:
                message += f"⚠️ <b>Профит снизился ({len(outdated_orders)}):</b>\n"
                for o in outdated_orders[:5]:
                    message += f"• {o['name'][:25]}...\n"
                    message += f"  Было {o['expected_profit']:.1f}% → {o['current_profit']:.1f}%\n"
                if len(outdated_orders) > 5:
                    message += f"  <i>...и ещё {len(outdated_orders) - 5}</i>\n"
                message += "\n"

            # Хорошие (зелёные)
            message += f"✅ <b>В порядке: {len(profitable_orders)}</b>\n\n"

            # Кнопки действий
            if unprofitable_orders or outdated_orders:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                # Сохраняем данные для callback
                if not hasattr(self, '_check_orders_data'):
                    self._check_orders_data = {}

                check_id = f"check_{datetime.now().timestamp()}"
                self._check_orders_data[check_id] = {
                    'unprofitable': unprofitable_orders,
                    'outdated': outdated_orders
                }

                keyboard = []
                if unprofitable_orders:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"❌ Отменить невыгодные ({len(unprofitable_orders)})",
                            callback_data=f"cancel_unprofitable:{check_id}"
                        )
                    ])
                if outdated_orders:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"⚠️ Отменить устаревшие ({len(outdated_orders)})",
                            callback_data=f"cancel_outdated:{check_id}"
                        )
                    ])
                if unprofitable_orders or outdated_orders:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🗑 Отменить все проблемные ({len(unprofitable_orders) + len(outdated_orders)})",
                            callback_data=f"cancel_all_bad:{check_id}"
                        )
                    ])
                keyboard.append([
                    InlineKeyboardButton("✅ Оставить как есть", callback_data=f"keep_orders:{check_id}")
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
            else:
                message += "👍 Все ордера актуальны!"
                await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /check_orders command: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_cancel_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel_all command - отменить все ордера."""
        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            orders = db.get_active_orders()

            if not orders:
                await update.message.reply_text("📝 Нет активных ордеров", parse_mode="HTML")
                return

            # Запрашиваем подтверждение
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = [
                [
                    InlineKeyboardButton(f"✅ Да, отменить все ({len(orders)})", callback_data="confirm_cancel_all"),
                    InlineKeyboardButton("❌ Нет", callback_data="abort_cancel_all")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"⚠️ <b>Подтверждение</b>\n\n"
                f"Вы уверены, что хотите отменить <b>все {len(orders)} ордеров</b>?",
                parse_mode="HTML",
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Error in /cancel_all command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    # ============ Settings Commands ============

    async def _cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command - показать текущие настройки."""
        try:
            config = settings.to_dict() if hasattr(settings, 'to_dict') else {}

            message = "⚙️ <b>Текущие настройки</b>\n\n"

            message += "<b>Торговля:</b>\n"
            message += f"• Мин. профит: {config.get('min_profit_percent', settings.min_profit_percent):.1f}%\n"
            message += f"• Макс. цена: {config.get('max_item_price', settings.max_item_price):.2f}$\n"
            message += f"• Мин. цена: {config.get('min_item_price', settings.min_item_price):.2f}$\n"
            message += f"• Мин. продаж/7д: {config.get('min_sales_7d', getattr(settings, 'min_sales_7d', 50))}\n"
            message += f"• Комиссия TM: {settings.csgotm_commission * 100:.1f}%\n\n"

            message += "<b>Сканер:</b>\n"
            message += f"• Задержка: {config.get('scanner_delay', 7.0)}с\n"
            message += f"• Воркеров: {config.get('scanner_workers', 1)}\n"
            message += f"• Макс. предметов: {config.get('scanner_max_items', 10)}\n\n"

            message += "<b>Лимиты:</b>\n"
            message += f"• Множитель ордеров: x{settings.order_limit_multiplier}\n\n"

            message += "💡 <b>Изменить:</b>\n"
            message += "/set_profit [%] - мин. профит\n"
            message += "/set_min_sales [N] - мин. продаж\n"
            message += "/set_max_price [₽] - макс. цена"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /settings command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_set_profit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_profit command - установить минимальный профит."""
        try:
            if not context.args:
                await update.message.reply_text(
                    "💡 <b>Использование:</b>\n"
                    "<code>/set_profit 5</code> - установить мин. профит 5%\n"
                    "<code>/set_profit 10.5</code> - установить мин. профит 10.5%",
                    parse_mode="HTML"
                )
                return

            try:
                new_profit = float(context.args[0].replace(',', '.').replace('%', ''))
            except ValueError:
                await update.message.reply_text("❌ Неверный формат числа", parse_mode="HTML")
                return

            if new_profit < -50 or new_profit > 100:
                await update.message.reply_text("❌ Профит должен быть от -50% до 100%", parse_mode="HTML")
                return

            # Сохраняем в конфиг
            old_value = settings.min_profit_percent
            settings.min_profit_percent = new_profit

            # Также обновляем в AppState если есть
            try:
                from flet_gui.state.app_state import AppState
                state = AppState()
                state.config['min_profit_percent'] = new_profit
                state.config['scanner_min_profit'] = new_profit
            except Exception:
                pass

            await update.message.reply_text(
                f"✅ <b>Мин. профит изменён</b>\n\n"
                f"Было: {old_value:.1f}%\n"
                f"Стало: <b>{new_profit:.1f}%</b>",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in /set_profit command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_set_min_sales(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_min_sales command - установить мин. продаж за 7 дней."""
        try:
            if not context.args:
                await update.message.reply_text(
                    "💡 <b>Использование:</b>\n"
                    "<code>/set_min_sales 50</code> - мин. 50 продаж за 7 дней\n"
                    "<code>/set_min_sales 100</code> - мин. 100 продаж за 7 дней",
                    parse_mode="HTML"
                )
                return

            try:
                new_value = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ Введите целое число", parse_mode="HTML")
                return

            if new_value < 0 or new_value > 10000:
                await update.message.reply_text("❌ Значение должно быть от 0 до 10000", parse_mode="HTML")
                return

            old_value = getattr(settings, 'min_sales_7d', 50)

            # Обновляем в AppState
            try:
                from flet_gui.state.app_state import AppState
                state = AppState()
                state.config['min_sales_7d'] = new_value
            except Exception:
                pass

            await update.message.reply_text(
                f"✅ <b>Мин. продаж изменён</b>\n\n"
                f"Было: {old_value}\n"
                f"Стало: <b>{new_value}</b> продаж/7д",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in /set_min_sales command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_set_max_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_max_price command - установить макс. цену покупки."""
        try:
            if not context.args:
                await update.message.reply_text(
                    "💡 <b>Использование:</b>\n"
                    "<code>/set_max_price 5000</code> - макс. цена 5000₽\n"
                    "<code>/set_max_price 10000</code> - макс. цена 10000₽",
                    parse_mode="HTML"
                )
                return

            try:
                new_value = float(context.args[0].replace(',', '.').replace('₽', ''))
            except ValueError:
                await update.message.reply_text("❌ Неверный формат числа", parse_mode="HTML")
                return

            if new_value < 10 or new_value > 1000000:
                await update.message.reply_text("❌ Цена должна быть от 10₽ до 1,000,000₽", parse_mode="HTML")
                return

            old_value = settings.max_buy_price
            settings.max_buy_price = new_value

            try:
                from flet_gui.state.app_state import AppState
                state = AppState()
                state.config['max_buy_price'] = new_value
            except Exception:
                pass

            await update.message.reply_text(
                f"✅ <b>Макс. цена изменена</b>\n\n"
                f"Было: {old_value:.0f}₽\n"
                f"Стало: <b>{new_value:.0f}₽</b>",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in /set_max_price command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    # ============ TM Sales Commands ============

    async def _cmd_blacklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ignored - показать предметы, убранные из продаж."""
        try:
            from src.database import TradesDatabase
            items = TradesDatabase().get_sale_ignored_items()

            if not items:
                await update.message.reply_text(
                    "🔕 <b>Список пуст</b>\n\n"
                    "Убрать предмет из продаж можно кнопкой «Больше не напоминать» "
                    "в уведомлении о завышенных ценах.",
                    parse_mode="HTML"
                )
                return

            message = f"🔕 <b>Не продаём ({len(items)})</b>\n\n"
            for idx, row in enumerate(items[:30], 1):
                name = row['market_hash_name']
                message += f"{idx}. <code>{name[:55]}</code>\n"
                if row.get('reason'):
                    message += f"   <i>{row['reason'][:60]}</i>\n"

            if len(items) > 30:
                message += f"\n... и ещё {len(items) - 30}\n"

            message += "\n💡 Вернуть в продажи: <code>/unignore ТОЧНОЕ_ИМЯ</code>"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /ignored: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}", parse_mode="HTML")

    async def _cmd_unblacklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /unignore <market_hash_name> - вернуть предмет в продажи."""
        try:
            name = " ".join(context.args).strip() if context.args else ""
            if not name:
                await update.message.reply_text(
                    "Укажите предмет целиком:\n"
                    "<code>/unignore AWP | Exothermic (Battle-Scarred)</code>\n\n"
                    "Список — /ignored",
                    parse_mode="HTML"
                )
                return

            from src.database import TradesDatabase
            if TradesDatabase().unignore_item_for_sale(name):
                await update.message.reply_text(
                    f"✅ <b>Снова продаём</b>\n\n<code>{name[:60]}</code>",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(
                    f"❌ В списке такого нет:\n<code>{name[:60]}</code>\n\n"
                    "Имя должно совпадать точно — сверьтесь со списком /ignored",
                    parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"Error in /unignore: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Ошибка: {e}", parse_mode="HTML")

    async def _cmd_prices(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /prices command - показать завышенные цены."""
        if not self._sales_service:
            await update.message.reply_text("❌ Sales service не запущен", parse_mode="HTML")
            return

        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            message = "💰 <b>Мониторинг цен</b>\n\n"

            # Проверяем для каждого аккаунта
            accounts = self._sales_service._account_states.keys()
            found_any = False

            for account_name in accounts:
                acc_state = self._sales_service._account_states.get(account_name)
                if not acc_state or not acc_state.csgotm_client:
                    continue

                # Получаем выставленные предметы
                our_items = db.get_purchased_items(account_name=account_name)
                listed_items = [item for item in our_items if item.get('status') == 'listed']

                if not listed_items:
                    continue

                tm_items = acc_state.csgotm_client.get_all_items()
                tm_items_dict = {item.get('item_id'): item for item in tm_items if item.get('status') == '1'}

                overpriced = []

                for our_item in listed_items[:20]:  # Проверяем первые 20
                    market_hash_name = our_item.get('market_hash_name')
                    tm_item_id = our_item.get('tm_item_id')

                    if not market_hash_name or not tm_item_id:
                        continue

                    tm_item = tm_items_dict.get(tm_item_id)
                    if not tm_item:
                        continue

                    our_price = float(tm_item.get('price', 0))
                    if our_price <= 0:
                        continue

                    try:
                        market_price_info = acc_state.csgotm_client.get_item_price(market_hash_name)
                        if not market_price_info or 'min_price' not in market_price_info:
                            continue

                        market_min_price = market_price_info['min_price']
                        threshold = 10.0
                        if hasattr(self._sales_service.state, 'config'):
                            threshold = float(self._sales_service.state.config.get('price_check_threshold_percent', 10.0))

                        price_diff_pct = ((our_price - market_min_price) / market_min_price * 100) if market_min_price > 0 else 0

                        if price_diff_pct >= threshold:
                            overpriced.append({
                                'name': market_hash_name,
                                'our_price': our_price,
                                'market_price': market_min_price,
                                'diff': price_diff_pct
                            })

                    except Exception:
                        continue

                if overpriced:
                    found_any = True
                    message += f"<b>{account_name}</b>:\n"
                    for idx, item in enumerate(overpriced[:5], 1):
                        message += f"{idx}. {item['name'][:30]}...\n"
                        message += f"   Наша: {item['our_price']:.0f}₽ | Рынок: {item['market_price']:.0f}₽ (+{item['diff']:.1f}%)\n"

                    if len(overpriced) > 5:
                        message += f"   ...и ещё {len(overpriced) - 5}\n"
                    message += "\n"

            if not found_any:
                message += "✅ Все цены в порядке!"
            else:
                message += "\n💡 Используй /update_prices для обновления"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /prices command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_update_prices(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /update_prices command - обновить цены до топ-1."""
        if not self._sales_service:
            await update.message.reply_text("❌ Sales service не запущен", parse_mode="HTML")
            return

        try:
            await update.message.reply_text("⏳ Обновление цен...", parse_mode="HTML")

            result = await self._sales_service.update_overpriced_items()

            if result['updated'] > 0:
                message = (
                    f"✅ <b>Цены обновлены</b>\n\n"
                    f"Обновлено: {result['updated']}\n"
                    f"Пропущено: {result.get('skipped', 0)}"
                )
            else:
                message = "ℹ️ Нет завышенных цен для обновления"

            if result.get('errors'):
                message += f"\n\n⚠️ Ошибок: {len(result['errors'])}"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /update_prices command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    async def _cmd_sales_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sales_stats command - статистика продаж."""
        try:
            from src.database import TradesDatabase
            db = TradesDatabase()

            message = "📊 <b>Статистика продаж</b>\n\n"

            # Get all purchased items from database
            all_items = db.get_purchased_items()

            # Count by status
            on_hold = [i for i in all_items if i.get('status') == 'holding']
            listed = [i for i in all_items if i.get('status') == 'listed']
            sold = [i for i in all_items if i.get('status') == 'sold']

            # Calculate totals
            total_spent = sum(i.get('buy_price', 0) for i in all_items)
            total_revenue = sum(i.get('sell_price', 0) for i in sold if i.get('sell_price'))
            total_profit = total_revenue - sum(i.get('buy_price', 0) for i in sold)

            message += "<b>По статусу:</b>\n"
            message += f"  • На холде: {len(on_hold)} шт\n"
            message += f"  • Выставлено: {len(listed)} шт\n"
            message += f"  • Продано: {len(sold)} шт\n\n"

            message += "<b>Финансы:</b>\n"
            message += f"  • Потрачено: {total_spent:,.0f}₽\n"
            message += f"  • Выручка: {total_revenue:,.0f}₽\n"
            message += f"  • Профит: {total_profit:,.0f}₽\n\n"

            # If sales_service has runtime stats, add them
            if self._sales_service and hasattr(self._sales_service, '_account_states'):
                accounts = self._sales_service._account_states.keys()
                if accounts:
                    message += "<b>За текущую сессию:</b>\n"
                    session_sold = 0
                    session_revenue = 0

                    for account_name in accounts:
                        acc_state = self._sales_service._account_states.get(account_name)
                        if acc_state and hasattr(acc_state, 'stats'):
                            session_sold += acc_state.stats.items_sold
                            session_revenue += acc_state.stats.total_revenue

                    message += f"  • Продано: {session_sold} шт\n"
                    message += f"  • Выручка: {session_revenue:,.0f}₽"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error in /sales_stats command: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

    # ============ Авторизация отправителя ============

    def _is_authorized(self, update: Update) -> bool:
        """Проверяет, что апдейт пришёл от владельца бота.

        Раньше проверки не было вообще: `chat_id` использовался только как адрес
        ДЛЯ ОТПРАВКИ, а входящие обрабатывались от кого угодно. Любой, кто знает
        юзернейм бота, мог написать ему в личку и отменять ордера, подтверждать
        сделки и — самое опасное — прислать Steam Guard код.

        По умолчанию разрешён только TELEGRAM_CHAT_ID. Дополнительные ID —
        через TELEGRAM_ALLOWED_USER_IDS (через запятую).
        """
        user = update.effective_user
        if user is None:
            return False

        allowed: set[str] = set()
        if self.chat_id:
            allowed.add(str(self.chat_id).strip())
        extra = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
        allowed.update(p.strip() for p in extra.split(",") if p.strip())

        # Пустой allowlist = бот не настроен. Fail-closed: не пускаем никого,
        # иначе «забыл заполнить chat_id» превращается в открытый доступ.
        if not allowed:
            logger.error(
                "Telegram: не задан TELEGRAM_CHAT_ID — входящие команды отклоняются. "
                "Укажите свой chat_id, иначе управление ботом останется недоступным."
            )
            return False

        if str(user.id) in allowed:
            return True

        logger.warning(
            "Telegram: отклонён апдейт от постороннего пользователя id=%s (@%s)",
            user.id, user.username or "?",
        )
        return False

    # ============ Callback Handlers ============

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        callback_data = query.data

        # Кнопки отменяют ордера и подтверждают сделки — только владелец.
        if not self._is_authorized(update):
            try:
                await query.answer("Доступ запрещён", show_alert=True)
            except Exception:
                pass
            return

        try:
            logger.info(f"Received callback query from user {query.from_user.id}")
            logger.info(f"Callback data: {callback_data}")

            # IMPORTANT: Acknowledge immediately before any processing
            try:
                await query.answer()
            except Exception as e:
                logger.warning(f"Failed to acknowledge callback (may be expired): {e}")
                return

            # Ручное подтверждение действия (аккаунты без identity_secret)
            if callback_data.startswith("manual_confirm:"):
                prompt_id = callback_data.split(":", 1)[1]
                fut = self._pending_confirmations.get(prompt_id)
                if fut and not fut.done():
                    fut.set_result(True)
                    try:
                        await query.edit_message_text(
                            "✅ <b>Подтверждено</b>\n\nПродолжаю работу.", parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.debug(f"Failed to edit confirm message: {e}")
                else:
                    try:
                        await query.edit_message_text(
                            "⚠️ <b>Запрос уже неактуален</b>\n\n"
                            "Подтверждение либо получено ранее, либо истекло по таймауту.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                return

            # Price update callbacks
            if callback_data.startswith("update_prices_"):
                logger.info(f"Processing price update callback")
                await self._handle_price_update_callback(query, callback_data)
            # Manual price setting callbacks
            elif callback_data.startswith("set_price:"):
                await self._handle_set_price_callback(query, callback_data)
            elif callback_data.startswith("enter_custom_price:"):
                await self._handle_enter_custom_price(query, callback_data)
            elif callback_data.startswith("skip_item:"):
                await self._handle_skip_item_callback(query, callback_data)
            elif callback_data.startswith("cancel_manual_update:"):
                await self._handle_cancel_manual_update(query, callback_data)
            # Sale-ignore callbacks («Больше не напоминать»)
            elif callback_data.startswith("saleignore_choose:"):
                await self._handle_saleignore_choose(query, callback_data)
            elif callback_data.startswith("saleignore_do:"):
                await self._handle_saleignore_do(query, callback_data)
            # Order check callbacks
            elif callback_data.startswith("cancel_unprofitable:"):
                await self._handle_cancel_orders_callback(query, callback_data, 'unprofitable')
            elif callback_data.startswith("cancel_outdated:"):
                await self._handle_cancel_orders_callback(query, callback_data, 'outdated')
            elif callback_data.startswith("cancel_all_bad:"):
                await self._handle_cancel_orders_callback(query, callback_data, 'all')
            elif callback_data.startswith("keep_orders:"):
                await query.edit_message_text("✅ Ордера оставлены без изменений", parse_mode="HTML")
            # Cancel all confirmation
            elif callback_data == "confirm_cancel_all":
                await self._handle_confirm_cancel_all(query)
            elif callback_data == "abort_cancel_all":
                await query.edit_message_text("❌ Отмена всех ордеров отменена", parse_mode="HTML")
            else:
                logger.warning(f"Unknown callback: {callback_data}")
        except Exception as e:
            logger.error(f"Error in callback handler: {e}", exc_info=True)

    async def _handle_price_update_callback(self, query, callback_data: str):
        """Handle price update button callbacks."""
        if not self._sales_service:
            try:
                await query.edit_message_text(
                    "❌ <b>Ошибка</b>\n\nСервис продаж не запущен",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to edit message: {e}")
            return

        try:
            # Parse callback data: update_prices_{action}:{account_name}
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                logger.error(f"Invalid callback data format: {callback_data}")
                return

            action_part = parts[0]  # update_prices_top1 / update_prices_manual / update_prices_cancel
            account_name = parts[1]

            if action_part == "update_prices_cancel":
                # Отмена - просто закрываем уведомление
                try:
                    await query.edit_message_text(
                        "❌ <b>Отменено</b>\n\nОбновление цен отменено",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"Failed to edit message: {e}")
                return

            elif action_part == "update_prices_top1":
                # Обновить все цены до топ-1
                try:
                    await query.edit_message_text(
                        "⏳ <b>Обновление цен...</b>\n\nОбновляю цены до топ-1, подождите...",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"Failed to edit message (may be expired): {e}")

                # Вызываем метод обновления цен в sales_service
                result = await self._sales_service.update_overpriced_items_to_top1(account_name)

                try:
                    if result.get('updated', 0) > 0:
                        await query.edit_message_text(
                            f"✅ <b>Успешно обновлено</b>\n\n"
                            f"Обновлено предметов: {result['updated']}\n"
                            f"Пропущено: {result.get('skipped', 0)}",
                            parse_mode="HTML"
                        )
                    else:
                        # Показываем причину, иначе непонятно, что именно пошло не так
                        details = f"Пропущено: {result.get('skipped', 0)}\n"
                        errs = result.get('errors') or []
                        if errs:
                            details += "\nПричины:\n" + "\n".join(f"• {e}" for e in errs[:5])
                            if len(errs) > 5:
                                details += f"\n… и ещё {len(errs) - 5}"
                        else:
                            details += "\nПодходящих под обновление лотов не найдено."
                        await query.edit_message_text(
                            "⚠️ <b>Не удалось обновить</b>\n\n"
                            "Не обновлено ни одного предмета\n" + details,
                            parse_mode="HTML"
                        )
                except Exception as e:
                    logger.warning(f"Failed to edit message with result: {e}")

            elif action_part == "update_prices_manual":
                # Ручной ввод цены - показываем диалог для каждого предмета
                items_key = account_name  # account_name теперь содержит items_key
                await self._start_manual_price_update(query, items_key)

        except Exception as e:
            logger.error(f"Error handling price update callback: {e}")
            try:
                await query.edit_message_text(
                    f"❌ <b>Ошибка</b>\n\n{str(e)}",
                    parse_mode="HTML"
                )
            except Exception as edit_error:
                logger.warning(f"Failed to send error message: {edit_error}")

    async def _handle_set_price_callback(self, query, callback_data: str):
        """Обработать установку цены для предмета."""
        try:
            # Формат: set_price:items_key:item_index:price
            parts = callback_data.split(":")
            if len(parts) != 4:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            items_key = parts[1]
            item_index = int(parts[2])
            new_price = float(parts[3])

            state = self._sales_service.state if hasattr(self._sales_service, 'state') else None
            if not state or items_key not in state._pending_price_updates:
                await query.edit_message_text("❌ Данные устарели", parse_mode="HTML")
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            account_name = data['account_name']
            item = items[item_index]

            # Обновляем цену через sales service
            success = await self._sales_service._update_item_price(
                account_name,
                item['tm_item_id'],
                new_price
            )

            if success:
                # Переходим к следующему предмету
                await self._show_item_price_dialog(query, items_key, item_index + 1)
            else:
                await query.edit_message_text(
                    f"❌ <b>Ошибка обновления</b>\n\nНе удалось обновить цену для {item['market_hash_name'][:30]}",
                    parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"Error in set_price callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _handle_enter_custom_price(self, query, callback_data: str):
        """Запросить ввод пользовательской цены."""
        try:
            # Формат: enter_custom_price:items_key:item_index
            parts = callback_data.split(":")
            if len(parts) != 3:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            items_key = parts[1]
            item_index = int(parts[2])

            state = self._sales_service.state if hasattr(self._sales_service, 'state') else None
            if not state or items_key not in state._pending_price_updates:
                await query.edit_message_text("❌ Данные устарели", parse_mode="HTML")
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            item = items[item_index]

            # Сохраняем контекст для обработки текстового ввода
            if not hasattr(state, '_awaiting_price_input'):
                state._awaiting_price_input = {}

            state._awaiting_price_input[query.message.chat_id] = {
                'items_key': items_key,
                'item_index': item_index,
                'item_name': item['market_hash_name']
            }

            # Отправляем инструкцию
            await query.edit_message_text(
                f"✏️ <b>Введите свою цену</b>\n\n"
                f"Предмет: <b>{item['market_hash_name'][:50]}</b>\n\n"
                f"💡 Отправьте число (в рублях) следующим сообщением.\n"
                f"Например: <code>3150</code>\n\n"
                f"Или отправьте /cancel для отмены",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in enter_custom_price callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _handle_saleignore_choose(self, query, callback_data: str):
        """Показать список предметов из уведомления — выбрать, какой убрать из продаж."""
        try:
            # Формат: saleignore_choose:items_key
            parts = callback_data.split(":")
            if len(parts) != 2:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            items_key = parts[1]

            state = self._sales_service.state if self._sales_service else None
            if not state or items_key not in getattr(state, '_pending_price_updates', {}):
                await query.edit_message_text(
                    "❌ <b>Данные устарели</b>\n\nУведомление слишком старое — дождитесь следующего.",
                    parse_mode="HTML"
                )
                return

            items = state._pending_price_updates[items_key]['items']

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            # Telegram режет callback_data после 64 байт, поэтому передаём индекс,
            # а не имя предмета: имена скинов легко перебирают лимит.
            keyboard = []
            for idx, item in enumerate(items[:10]):
                name = item['market_hash_name']
                keyboard.append([
                    InlineKeyboardButton(
                        f"🔕 {name[:45]}",
                        callback_data=f"saleignore_do:{items_key}:{idx}"
                    )
                ])
            keyboard.append([
                InlineKeyboardButton("◀️ Отмена", callback_data=f"update_prices_cancel:none")
            ])

            message = (
                "🔕 <b>Больше не напоминать</b>\n\n"
                "Выберите предмет. Бот перестанет его выставлять на продажу, "
                "менять ему цену и писать о нём.\n\n"
                "Действует на этот вариант скина вместе с износом — "
                "другие износы продолжат продаваться. На покупку не влияет."
            )
            if len(items) > 10:
                message += f"\n\n<i>Показаны первые 10 из {len(items)}.</i>"

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            logger.error(f"Error in saleignore_choose callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _handle_saleignore_do(self, query, callback_data: str):
        """Убрать предмет из продаж: не выставлять, не репрайсить, не напоминать."""
        try:
            # Формат: saleignore_do:items_key:item_index
            parts = callback_data.split(":")
            if len(parts) != 3:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            items_key = parts[1]
            item_index = int(parts[2])

            state = self._sales_service.state if self._sales_service else None
            if not state or items_key not in getattr(state, '_pending_price_updates', {}):
                await query.edit_message_text("❌ <b>Данные устарели</b>", parse_mode="HTML")
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            account_name = data['account_name']

            if item_index >= len(items):
                await query.edit_message_text("❌ Предмет не найден", parse_mode="HTML")
                return

            item = items[item_index]
            market_hash_name = item['market_hash_name']

            from src.database import TradesDatabase
            db = TradesDatabase()

            db.ignore_item_for_sale(
                market_hash_name,
                reason=f"куплен {item.get('purchase_price', 0):.0f}₽, "
                       f"рынок {item.get('market_min_price', 0):.0f}₽",
                added_by=f"telegram/{account_name}"
            )

            # Лот, уже стоящий на CSGO.TM, намеренно не снимаем: вдруг его всё-таки
            # купят по текущей цене. Мы лишь перестаём его трогать и напоминать.
            await query.edit_message_text(
                f"🔕 <b>Убран из продаж</b>\n\n"
                f"<b>{market_hash_name[:50]}</b>\n\n"
                f"Бот больше не будет его выставлять, менять ему цену "
                f"и писать о нём.\n\n"
                f"Текущий лот на CSGO.TM, если он есть, остаётся висеть — "
                f"снимите его вручную, если нужно.\n\n"
                f"Список — /ignored, вернуть в продажи — /unignore",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in saleignore_do callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _handle_skip_item_callback(self, query, callback_data: str):
        """Пропустить предмет и перейти к следующему."""
        try:
            # Формат: skip_item:items_key:item_index
            parts = callback_data.split(":")
            if len(parts) != 3:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            items_key = parts[1]
            item_index = int(parts[2])

            # Переходим к следующему предмету
            await self._show_item_price_dialog(query, items_key, item_index + 1)

        except Exception as e:
            logger.error(f"Error in skip_item callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _handle_cancel_manual_update(self, query, callback_data: str):
        """Отменить процесс ручного обновления цен."""
        try:
            # Формат: cancel_manual_update:items_key
            parts = callback_data.split(":")
            if len(parts) != 2:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            items_key = parts[1]

            state = self._sales_service.state if hasattr(self._sales_service, 'state') else None
            if state and items_key in state._pending_price_updates:
                del state._pending_price_updates[items_key]

            await query.edit_message_text(
                "❌ <b>Отменено</b>\n\nОбновление цен отменено",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in cancel_manual_update callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _start_manual_price_update(self, query, items_key: str):
        """Начать процесс ручного обновления цен - показать первый предмет."""
        if not self._sales_service:
            await query.edit_message_text("❌ <b>Ошибка</b>\n\nСервис продаж не запущен", parse_mode="HTML")
            return

        try:
            # Получаем сохраненные данные
            from flet_gui.state.app_state import AppState
            state = self._sales_service.state if hasattr(self._sales_service, 'state') else None

            if not state or not hasattr(state, '_pending_price_updates') or items_key not in state._pending_price_updates:
                await query.edit_message_text(
                    "❌ <b>Ошибка</b>\n\nДанные устарели, попробуйте еще раз",
                    parse_mode="HTML"
                )
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            account_name = data['account_name']

            if not items:
                await query.edit_message_text("ℹ️ Нет предметов для обновления", parse_mode="HTML")
                return

            # Показываем первый предмет
            await self._show_item_price_dialog(query, items_key, 0)

        except Exception as e:
            logger.error(f"Error starting manual price update: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _show_item_price_dialog(self, query, items_key: str, item_index: int):
        """Показать диалог для установки цены конкретного предмета."""
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from flet_gui.state.app_state import AppState
            state = self._sales_service.state if hasattr(self._sales_service, 'state') else None

            if not state or items_key not in state._pending_price_updates:
                await query.edit_message_text("❌ Данные устарели", parse_mode="HTML")
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            account_name = data['account_name']

            if item_index >= len(items):
                # Все предметы обработаны
                await query.edit_message_text(
                    "✅ <b>Готово!</b>\n\nОбновление цен завершено",
                    parse_mode="HTML"
                )
                # Очищаем данные
                del state._pending_price_updates[items_key]
                return

            item = items[item_index]
            name = item['market_hash_name']
            our_price = item['our_price']
            top1_price = item['market_min_price']
            purchase_price = item.get('purchase_price', 0)

            # Формируем сообщение
            message = f"✏️ <b>Ручное обновление цен</b>\n\n"
            message += f"Предмет {item_index + 1} из {len(items)}\n\n"
            message += f"<b>{name[:50]}</b>\n\n"
            if purchase_price > 0:
                message += f"💰 Купили за: <b>{purchase_price:.0f}₽</b>\n"
            message += f"📊 Текущая цена: <b>{our_price:.0f}₽</b>\n"
            message += f"🎯 Топ-1 на рынке: <b>{top1_price:.0f}₽</b>\n\n"
            message += "Выберите действие:"

            # Кнопки с вариантами цены
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"🎯 Топ-1: {top1_price:.0f}₽",
                        callback_data=f"set_price:{items_key}:{item_index}:{int(top1_price)}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"➖ Топ-1 минус 1₽: {top1_price - 1:.0f}₽",
                        callback_data=f"set_price:{items_key}:{item_index}:{int(top1_price - 1)}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✏️ Ввести свою цену",
                        callback_data=f"enter_custom_price:{items_key}:{item_index}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⏭️ Пропустить",
                        callback_data=f"skip_item:{items_key}:{item_index}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отменить всё",
                        callback_data=f"cancel_manual_update:{items_key}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error showing item price dialog: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    # ---------------- Интерактивные запросы (аккаунты без maFile) -------------
    async def ask_steam_guard_code(self, account_name: str, timeout: int = 600) -> Optional[str]:
        """Спросить Steam Guard код в Telegram и дождаться ответа сообщением.

        Заменяет консольный input() для аккаунтов без shared_secret — на сервере
        консоли нет, поэтому код приходит следующим сообщением в чат.

        Returns:
            Код, либо None если не дождались за timeout.
        """
        if not self.is_configured:
            logger.warning(f"[{account_name}] Telegram не настроен — код запросить негде")
            return None

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_code_request = {"account": account_name, "future": fut}

        await self.send_message(
            f"🔐 <b>Требуется Steam Guard</b>\n\n"
            f"Пожалуйста, введите стим гуард код для <b>{account_name}</b>:\n\n"
            f"<i>Отправьте код следующим сообщением (например: K4XZ9)</i>"
        )

        try:
            code = await asyncio.wait_for(fut, timeout=timeout)
            await self.send_message(f"✅ Код принят, авторизую <b>{account_name}</b>...")
            return code
        except asyncio.TimeoutError:
            logger.error(f"[{account_name}] Не дождались Steam Guard кода за {timeout}с")
            await self.send_message(
                f"⏰ Код для <b>{account_name}</b> так и не пришёл — авторизация отменена."
            )
            return None
        finally:
            self._pending_code_request = None

    async def ask_manual_confirmation(self, account_name: str, action: str = "", timeout: int = 600) -> bool:
        """Попросить подтвердить действие на торговой площадке и дождаться кнопки.

        Для аккаунтов без identity_secret: подтверждение делается вручную в Steam
        Mobile Guard, а кнопка в Telegram сообщает боту, что можно продолжать.
        """
        if not self.is_configured:
            logger.warning(f"[{account_name}] Telegram не настроен — подтверждения не дождёмся")
            return False

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        prompt_id = uuid.uuid4().hex[:8]
        self._pending_confirmations[prompt_id] = fut

        tail = f"\n\n<i>{action}</i>" if action else ""
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Подтверждено", callback_data=f"manual_confirm:{prompt_id}")
        ]])

        await self.send_message(
            f"📱 <b>Требуется подтверждение</b>\n\n"
            f"Аккаунт: <b>{account_name}</b>\n"
            f"Пожалуйста, подтвердите действие на торговой площадке.{tail}",
            reply_markup=keyboard,
        )

        try:
            await asyncio.wait_for(fut, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.error(f"[{account_name}] Не дождались ручного подтверждения за {timeout}с")
            await self.send_message(
                f"⏰ Подтверждение для <b>{account_name}</b> не получено — действие отменено."
            )
            return False
        finally:
            self._pending_confirmations.pop(prompt_id, None)

    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработать текстовое сообщение (Steam Guard код или ввод цены)."""
        if not update.message or not update.message.text:
            return

        # Сюда приходит Steam Guard код — принимать его от постороннего нельзя.
        if not self._is_authorized(update):
            return

        chat_id = update.message.chat_id
        text = update.message.text.strip()

        # Приоритет: ждём ли мы Steam Guard код
        pending = self._pending_code_request
        if pending and not pending["future"].done():
            code = text.replace(" ", "").upper()
            if not (4 <= len(code) <= 8 and code.isalnum()):
                await update.message.reply_text(
                    "❌ Это не похоже на Steam Guard код (5 символов). Попробуйте ещё раз."
                )
                return
            pending["future"].set_result(code)
            return

        # Проверяем, ожидается ли ввод цены от этого пользователя
        state = self._sales_service.state if self._sales_service and hasattr(self._sales_service, 'state') else None

        if not state or not hasattr(state, '_awaiting_price_input') or chat_id not in state._awaiting_price_input:
            # Не ожидаем ввод от этого пользователя - игнорируем
            return

        try:
            input_data = state._awaiting_price_input[chat_id]
            items_key = input_data['items_key']
            item_index = input_data['item_index']
            item_name = input_data['item_name']

            # Парсим введенную цену
            try:
                # Удаляем все нечисловые символы кроме точки и запятой
                price_str = text.replace(',', '.').replace(' ', '').replace('₽', '').replace('руб', '')
                custom_price = float(price_str)

                if custom_price <= 0:
                    await update.message.reply_text(
                        "❌ Цена должна быть больше 0. Попробуйте еще раз или отправьте /cancel",
                        parse_mode="HTML"
                    )
                    return

                if custom_price > 1000000:
                    await update.message.reply_text(
                        "❌ Цена слишком большая (макс 1,000,000₽). Попробуйте еще раз или отправьте /cancel",
                        parse_mode="HTML"
                    )
                    return

            except ValueError:
                await update.message.reply_text(
                    f"❌ Неверный формат цены: <code>{text}</code>\n\n"
                    f"Отправьте число в рублях (например: <code>3150</code>) или /cancel для отмены",
                    parse_mode="HTML"
                )
                return

            # Очищаем состояние ожидания
            del state._awaiting_price_input[chat_id]

            # Получаем данные предметов
            if items_key not in state._pending_price_updates:
                await update.message.reply_text("❌ Данные устарели", parse_mode="HTML")
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            account_name = data['account_name']
            item = items[item_index]

            # Отправляем сообщение о начале обновления
            status_msg = await update.message.reply_text(
                f"⏳ Обновляю цену для <b>{item_name[:40]}</b> на {custom_price:.0f}₽...",
                parse_mode="HTML"
            )

            # Обновляем цену
            success = await self._sales_service._update_item_price(
                account_name,
                item['tm_item_id'],
                custom_price
            )

            if success:
                await status_msg.edit_text(
                    f"✅ <b>Цена обновлена!</b>\n\n"
                    f"{item_name[:40]}\n"
                    f"Новая цена: <b>{custom_price:.0f}₽</b>",
                    parse_mode="HTML"
                )
                # Небольшая задержка перед показом следующего предмета
                import asyncio
                await asyncio.sleep(1)

                # Показываем следующий предмет (создаем "фейковый" query для переиспользования логики)
                # Вместо этого отправляем новое сообщение
                await self._send_next_item_dialog(update.message.chat_id, items_key, item_index + 1)
            else:
                await status_msg.edit_text(
                    f"❌ <b>Ошибка обновления</b>\n\n"
                    f"Не удалось обновить цену для {item_name[:40]}",
                    parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"Error handling text message (price input): {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ <b>Ошибка</b>\n\n{str(e)}",
                parse_mode="HTML"
            )
            # Очищаем состояние при ошибке
            if state and hasattr(state, '_awaiting_price_input') and chat_id in state._awaiting_price_input:
                del state._awaiting_price_input[chat_id]

    async def _send_next_item_dialog(self, chat_id: int, items_key: str, item_index: int):
        """Отправить диалог для следующего предмета."""
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            state = self._sales_service.state if hasattr(self._sales_service, 'state') else None
            if not state or items_key not in state._pending_price_updates:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text="❌ Данные устарели",
                    parse_mode="HTML"
                )
                return

            data = state._pending_price_updates[items_key]
            items = data['items']
            account_name = data['account_name']

            if item_index >= len(items):
                # Все предметы обработаны
                await self._bot.send_message(
                    chat_id=chat_id,
                    text="✅ <b>Готово!</b>\n\nОбновление цен завершено",
                    parse_mode="HTML"
                )
                del state._pending_price_updates[items_key]
                return

            item = items[item_index]
            name = item['market_hash_name']
            our_price = item['our_price']
            top1_price = item['market_min_price']
            purchase_price = item.get('purchase_price', 0)

            # Формируем сообщение
            message = f"✏️ <b>Ручное обновление цен</b>\n\n"
            message += f"Предмет {item_index + 1} из {len(items)}\n\n"
            message += f"<b>{name[:50]}</b>\n\n"
            if purchase_price > 0:
                message += f"💰 Купили за: <b>{purchase_price:.0f}₽</b>\n"
            message += f"📊 Текущая цена: <b>{our_price:.0f}₽</b>\n"
            message += f"🎯 Топ-1 на рынке: <b>{top1_price:.0f}₽</b>\n\n"
            message += "Выберите действие:"

            # Кнопки
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"🎯 Топ-1: {top1_price:.0f}₽",
                        callback_data=f"set_price:{items_key}:{item_index}:{int(top1_price)}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"➖ Топ-1 минус 1₽: {top1_price - 1:.0f}₽",
                        callback_data=f"set_price:{items_key}:{item_index}:{int(top1_price - 1)}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✏️ Ввести свою цену",
                        callback_data=f"enter_custom_price:{items_key}:{item_index}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⏭️ Пропустить",
                        callback_data=f"skip_item:{items_key}:{item_index}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отменить всё",
                        callback_data=f"cancel_manual_update:{items_key}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Error sending next item dialog: {e}", exc_info=True)
            await self._bot.send_message(
                chat_id=chat_id,
                text=f"❌ <b>Ошибка</b>\n\n{str(e)}",
                parse_mode="HTML"
            )

    # ============ Order Management Callbacks ============

    async def _handle_cancel_orders_callback(self, query, callback_data: str, order_type: str):
        """Handle order cancellation callbacks from /check_orders."""
        try:
            # Формат: cancel_unprofitable:check_id / cancel_outdated:check_id / cancel_all_bad:check_id
            parts = callback_data.split(":")
            if len(parts) != 2:
                await query.edit_message_text("❌ Неверный формат данных", parse_mode="HTML")
                return

            check_id = parts[1]

            if not hasattr(self, '_check_orders_data') or check_id not in self._check_orders_data:
                await query.edit_message_text("❌ Данные устарели. Выполните /check_orders заново", parse_mode="HTML")
                return

            data = self._check_orders_data[check_id]
            unprofitable = data.get('unprofitable', [])
            outdated = data.get('outdated', [])

            # Определяем какие ордера отменять
            orders_to_cancel = []
            if order_type == 'unprofitable':
                orders_to_cancel = unprofitable
            elif order_type == 'outdated':
                orders_to_cancel = outdated
            elif order_type == 'all':
                orders_to_cancel = unprofitable + outdated

            if not orders_to_cancel:
                await query.edit_message_text("ℹ️ Нет ордеров для отмены", parse_mode="HTML")
                return

            await query.edit_message_text(
                f"⏳ <b>Отмена ордеров...</b>\n\nОтменяю {len(orders_to_cancel)} ордеров...",
                parse_mode="HTML"
            )

            # Отменяем ордера
            cancelled = 0
            failed = 0

            for order in orders_to_cancel:
                order_id = order.get('order_id')
                account = order.get('account')

                try:
                    # _account_states хранит только csgotm_client; steam_client живёт
                    # в Account из account_manager, поэтому идём через общий хелпер.
                    steam_client = self._get_steam_client(account or "")
                    success = bool(steam_client) and await steam_client.cancel_buy_order(order_id)

                    if success:
                        # Обновляем статус в БД
                        from src.database import TradesDatabase
                        db = TradesDatabase()
                        db.update_order_status(order_id, 'cancelled')
                        cancelled += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"Failed to cancel order {order_id}: {e}")
                    failed += 1

            # Очищаем данные
            del self._check_orders_data[check_id]

            await query.edit_message_text(
                f"✅ <b>Готово!</b>\n\n"
                f"Отменено: {cancelled}\n"
                f"Ошибок: {failed}",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in cancel_orders callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    async def _handle_confirm_cancel_all(self, query):
        """Handle confirm cancel all orders callback."""
        try:
            await query.edit_message_text(
                "⏳ <b>Отмена всех ордеров...</b>\n\nПодождите...",
                parse_mode="HTML"
            )

            from src.database import TradesDatabase
            db = TradesDatabase()
            orders = db.get_active_orders()

            cancelled = 0
            failed = 0

            for order in orders:
                order_id = order.get('order_id')
                account = order.get('account_name', 'default')

                try:
                    steam_client = self._get_steam_client(account or "")
                    success = bool(steam_client) and await steam_client.cancel_buy_order(order_id)

                    if success:
                        db.update_order_status(order_id, 'cancelled')
                        cancelled += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"Failed to cancel order {order_id}: {e}")
                    failed += 1

            await query.edit_message_text(
                f"✅ <b>Все ордера отменены</b>\n\n"
                f"Отменено: {cancelled}\n"
                f"Ошибок: {failed}",
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Error in confirm_cancel_all: {e}", exc_info=True)
            await query.edit_message_text(f"❌ <b>Ошибка</b>\n\n{str(e)}", parse_mode="HTML")

    # ============ Bot Control ============

    def build_app(self) -> Optional[Application]:
        """Build Telegram application with handlers."""
        if not self.is_configured:
            logger.warning("Telegram not configured")
            return None

        self._app = Application.builder().token(self.token).build()

        # --- Шлюз авторизации ---------------------------------------------
        # Группа -1 выполняется раньше всех остальных, а ApplicationHandlerStop
        # обрывает обработку апдейта целиком. Так одним местом закрыты ВСЕ
        # команды (в т.ч. /cancel_all и /set_max_price), кнопки и текстовые
        # сообщения — включая те обработчики, которые добавят позже.
        from telegram.ext import ApplicationHandlerStop, TypeHandler

        async def _auth_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not self._is_authorized(update):
                raise ApplicationHandlerStop

        self._app.add_handler(TypeHandler(Update, _auth_gate), group=-1)

        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("balance", self._cmd_balance))
        self._app.add_handler(CommandHandler("orders", self._cmd_orders))
        self._app.add_handler(CommandHandler("holdings", self._cmd_holdings))
        self._app.add_handler(CommandHandler("profit", self._cmd_profit))
        self._app.add_handler(CommandHandler("stats", self._cmd_stats))
        self._app.add_handler(CommandHandler("cancel", self._cmd_cancel))
        self._app.add_handler(CommandHandler("report", self._cmd_report))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        # Inventory commands
        self._app.add_handler(CommandHandler("inventory", self._cmd_inventory))
        self._app.add_handler(CommandHandler("ready", self._cmd_ready))
        self._app.add_handler(CommandHandler("check_orders", self._cmd_check_orders))
        self._app.add_handler(CommandHandler("cancel_all", self._cmd_cancel_all))

        # Settings commands
        self._app.add_handler(CommandHandler("settings", self._cmd_settings))
        self._app.add_handler(CommandHandler("set_profit", self._cmd_set_profit))
        self._app.add_handler(CommandHandler("set_min_sales", self._cmd_set_min_sales))
        self._app.add_handler(CommandHandler("set_max_price", self._cmd_set_max_price))

        # TM Sales commands
        self._app.add_handler(CommandHandler("ignored", self._cmd_blacklist))
        self._app.add_handler(CommandHandler("unignore", self._cmd_unblacklist))
        self._app.add_handler(CommandHandler("prices", self._cmd_prices))
        self._app.add_handler(CommandHandler("update_prices", self._cmd_update_prices))
        self._app.add_handler(CommandHandler("sales_stats", self._cmd_sales_stats))

        # Add callback query handler for inline button presses
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Add message handler for text input (price input)
        from telegram.ext import MessageHandler, filters
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_text_message
        ))

        return self._app

    async def start_polling(self):
        """Start the bot in polling mode within existing event loop."""
        try:
            app = self.build_app()
            if not app:
                logger.error("Failed to build Telegram app")
                return

            logger.info("Initializing Telegram bot...")
            await app.initialize()

            logger.info("Starting Telegram bot...")
            await app.start()

            logger.info("Starting polling...")
            # Явно указываем типы обновлений, включая callback_query
            await app.updater.start_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
            )

            logger.info("Telegram bot polling started successfully")
            logger.info("Bot is ready to receive messages and button presses")

            # Держим бота активным (этот await никогда не завершится)
            import asyncio
            await asyncio.Event().wait()

        except Exception as e:
            logger.error(f"Failed to start Telegram bot polling: {e}", exc_info=True)

    async def stop(self):
        """Stop the bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    # ============ Monitoring & Alerts ============

    def notify_high_profit_item(self, item_name: str, profit_pct: float, steam_price: float, csgo_price: float):
        """Уведомление о найденном предмете с высоким профитом."""
        message = (
            f"🎯 <b>Найден выгодный предмет!</b>\n\n"
            f"📦 <b>{item_name}</b>\n"
            f"💰 Steam: {steam_price:.2f} ₽\n"
            f"💎 CSGO.TM: {csgo_price:.2f} ₽\n"
            f"📈 Профит: <b>+{profit_pct:.1f}%</b>"
        )
        self.send_message_sync(message)

    def notify_order_filled(self, item_name: str, price: float, profit_pct: float):
        """Уведомление о заполненном ордере с высоким профитом."""
        emoji = "💚" if profit_pct >= 15 else "💰" if profit_pct >= 10 else "✅"
        message = (
            f"{emoji} <b>Ордер исполнен!</b>\n\n"
            f"📦 {item_name}\n"
            f"💸 Куплено за: {price:.2f} ₽\n"
            f"📈 Ожидаемый профит: <b>+{profit_pct:.1f}%</b>"
        )
        self.send_message_sync(message)

    def notify_error(self, error_type: str, details: str, severity: str = "warning"):
        """Уведомление об ошибке."""
        emoji_map = {
            "critical": "🔴",
            "error": "⚠️",
            "warning": "🟡"
        }
        emoji = emoji_map.get(severity, "⚠️")

        message = (
            f"{emoji} <b>Проблема: {error_type}</b>\n\n"
            f"Детали: {details}\n"
            f"Время: {datetime.now().strftime('%H:%M:%S')}"
        )
        self.send_message_sync(message)

    def notify_api_error(self, api_name: str, error_msg: str):
        """Уведомление об ошибке API."""
        self.notify_error(
            error_type=f"Ошибка {api_name} API",
            details=error_msg,
            severity="warning"
        )

    def notify_proxy_issues(self, failed_proxies: int, total_proxies: int):
        """Уведомление о проблемах с прокси."""
        if failed_proxies >= total_proxies * 0.5:  # >50% failed
            self.notify_error(
                error_type="Критические проблемы с прокси",
                details=f"Не работают {failed_proxies}/{total_proxies} прокси",
                severity="critical"
            )
        elif failed_proxies > 0:
            self.notify_error(
                error_type="Проблемы с прокси",
                details=f"Не работают {failed_proxies}/{total_proxies} прокси",
                severity="warning"
            )

    def notify_account_login_failed(self, account_name: str, reason: str):
        """Уведомление о неудачной попытке логина."""
        self.notify_error(
            error_type=f"Не удалось войти в аккаунт {account_name}",
            details=reason,
            severity="error"
        )

    async def send_daily_report(self):
        """Отправить ежедневный отчет."""
        try:
            # Получаем статистику за сегодня
            today_stats = trades_db.get_stats_for_period('today')
            yesterday_stats = trades_db.get_stats_for_period('yesterday')

            # Получаем общую статистику
            all_stats = trades_db.get_stats()

            # Формируем отчет
            message = (
                f"📊 <b>Ежедневный отчет</b>\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"

                f"<b>Сегодня:</b>\n"
                f"  📦 Ордеров создано: {today_stats.get('orders_created', 0)}\n"
                f"  ✅ Исполнено: {today_stats.get('orders_filled', 0)}\n"
                f"  💰 Куплено предметов: {today_stats.get('items_purchased', 0)}\n"
                f"  💎 Продано предметов: {today_stats.get('items_sold', 0)}\n"
                f"  📈 Прибыль: <b>{today_stats.get('total_profit', 0):.2f} ₽</b>\n\n"

                f"<b>Вчера:</b>\n"
                f"  📈 Прибыль: {yesterday_stats.get('total_profit', 0):.2f} ₽\n"
                f"  💎 Продано: {yesterday_stats.get('items_sold', 0)} шт.\n\n"

                f"<b>Всего за все время:</b>\n"
                f"  💰 Общая прибыль: <b>{all_stats.get('total_profit', 0):.2f} ₽</b>\n"
                f"  🔄 Сделок: {all_stats.get('total_trades', 0)}\n"
                f"  📊 Средний профит: {all_stats.get('avg_profit', 0):.2f} ₽\n\n"

                f"🤖 <i>Автоматический отчет от Steam Trading Bot</i>"
            )

            await self.send_message(message)
            logger.info("Daily report sent successfully")

        except Exception as e:
            logger.error(f"Failed to send daily report: {e}")

    def start_daily_reports(self, hour: int = 20, minute: int = 0):
        """
        Запустить автоматическую отправку ежедневных отчетов.

        Args:
            hour: Час отправки (0-23)
            minute: Минута отправки (0-59)
        """
        import asyncio
        from datetime import datetime, timedelta

        async def daily_report_task():
            """Фоновая задача для ежедневных отчетов."""
            while True:
                try:
                    # Вычисляем время до следующего отчета
                    now = datetime.now()
                    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                    # Если время уже прошло, отправляем завтра
                    if target <= now:
                        target += timedelta(days=1)

                    wait_seconds = (target - now).total_seconds()
                    logger.info(f"Next daily report scheduled at {target.strftime('%Y-%m-%d %H:%M')}")

                    # Ждем до следующего времени отправки
                    await asyncio.sleep(wait_seconds)

                    # Отправляем отчет
                    await self.send_daily_report()

                    # Ждем 60 секунд, чтобы не отправить дважды
                    await asyncio.sleep(60)

                except asyncio.CancelledError:
                    logger.info("Daily report task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in daily report task: {e}")
                    await asyncio.sleep(3600)  # Ждем час при ошибке

        # Запускаем задачу в фоне
        asyncio.create_task(daily_report_task())
        logger.info(f"Daily reports scheduled for {hour:02d}:{minute:02d}")


# Singleton instance
telegram_bot = TelegramNotifier()
