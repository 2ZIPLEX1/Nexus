"""
Telegram bot for notifications and control.

Sends notifications about trades and provides commands to control the bot.
"""

import asyncio
from datetime import datetime
from typing import Optional

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
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
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self._bot: Optional[Bot] = None
        self._app: Optional[Application] = None
        self._trade_logic = None  # Set later to avoid circular import

    @property
    def is_configured(self) -> bool:
        """Check if Telegram is configured."""
        return bool(self.token and self.chat_id)

    def set_trade_logic(self, trade_logic):
        """Set trade logic reference for status commands."""
        self._trade_logic = trade_logic

    async def send_message(self, text: str, parse_mode: str = "HTML"):
        """
        Send a message to the configured chat.

        Args:
            text: Message text
            parse_mode: Telegram parse mode (HTML, Markdown)
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
                parse_mode=parse_mode
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

    # ============ Notification Methods ============

    def notify_order_placed(self, item_name: str, price: float, expected_profit: float):
        """Notify about new buy order."""
        message = (
            f"📝 <b>New Buy Order</b>\n\n"
            f"Item: <code>{item_name}</code>\n"
            f"Price: <b>${price:.2f}</b>\n"
            f"Expected Profit: <b>{expected_profit:.1f}%</b>"
        )
        self.send_message_sync(message)

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
            "Commands:\n"
            "/status - Trading status\n"
            "/balance - Wallet balance\n"
            "/orders - Active orders\n"
            "/holdings - Items on hold\n"
            "/profit - Profit statistics\n"
            "/help - Show this message",
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
        if self._trade_logic:
            try:
                wallet = self._trade_logic.steam.get_wallet_balance()
                balance = wallet.balance
                currency = wallet.currency_code
            except Exception:
                balance = 0
                currency = "USD"
        else:
            balance = 0
            currency = "USD"

        max_orders = settings.calculate_max_orders_value(balance)
        current_orders = trades_db.get_total_orders_value()

        message = (
            f"💰 <b>Wallet Balance</b>\n\n"
            f"Balance: <b>${balance:.2f} {currency}</b>\n"
            f"Max Orders (x{settings.order_limit_multiplier}): ${max_orders:.2f}\n"
            f"Current Orders: ${current_orders:.2f}\n"
            f"Available: ${max_orders - current_orders:.2f}"
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

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self._cmd_start(update, context)

    # ============ Bot Control ============

    def build_app(self) -> Optional[Application]:
        """Build Telegram application with handlers."""
        if not self.is_configured:
            logger.warning("Telegram not configured")
            return None

        self._app = Application.builder().token(self.token).build()

        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("balance", self._cmd_balance))
        self._app.add_handler(CommandHandler("orders", self._cmd_orders))
        self._app.add_handler(CommandHandler("holdings", self._cmd_holdings))
        self._app.add_handler(CommandHandler("profit", self._cmd_profit))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        return self._app

    async def start_polling(self):
        """Start the bot in polling mode."""
        app = self.build_app()
        if app:
            logger.info("Starting Telegram bot...")
            await app.initialize()
            await app.start()
            await app.updater.start_polling()

    async def stop(self):
        """Stop the bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()


# Singleton instance
telegram_bot = TelegramNotifier()
