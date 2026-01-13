"""
Main bot orchestrator.

Coordinates all trading operations:
- Scheduled buy/sell cycles
- Auto-confirmations
- Telegram notifications
- Error handling and recovery
"""

import asyncio
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from src.confirmations import ConfirmationHandler
from src.database import trades_db
from src.logger import get_logger
from src.steam_client import steam_client, SteamClientError
from src.telegram_bot import telegram_bot
from src.trade_logic import trade_logic

logger = get_logger(__name__)


class TradingBot:
    """
    Main trading bot orchestrator.

    Manages:
    - Steam authentication
    - Scheduled trading cycles
    - Auto-confirmations
    - Telegram notifications
    - Graceful shutdown
    """

    def __init__(self):
        """Initialize the trading bot."""
        self.scheduler: Optional[BackgroundScheduler] = None
        self.confirmation_handler: Optional[ConfirmationHandler] = None
        self.running = False
        self._confirm_thread: Optional[threading.Thread] = None

        # Connect components
        telegram_bot.set_trade_logic(trade_logic)

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def handle_shutdown(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

    def _login(self) -> bool:
        """Login to Steam."""
        try:
            logger.info("Logging in to Steam...")
            steam_client.login()

            # Create confirmation handler
            self.confirmation_handler = ConfirmationHandler(steam_client)

            # Verify login by checking balance
            wallet = steam_client.get_wallet_balance()
            logger.info(f"Logged in successfully. Balance: ${wallet.balance:.2f}")

            telegram_bot.send_message_sync(
                f"🟢 <b>Bot Started</b>\n\n"
                f"Balance: <b>${wallet.balance:.2f}</b>"
            )

            return True

        except SteamClientError as e:
            logger.error(f"Steam login failed: {e}")
            telegram_bot.notify_error("Steam Login Failed", str(e))
            return False

    def _run_buy_cycle(self):
        """Execute buy cycle with error handling."""
        logger.info("Running buy cycle...")
        try:
            summary = trade_logic.run_buy_cycle()
            telegram_bot.notify_cycle_complete("buy", summary)
        except Exception as e:
            logger.error(f"Buy cycle error: {e}")
            telegram_bot.notify_error("Buy Cycle Error", str(e))

    def _run_sell_cycle(self):
        """Execute sell cycle with error handling."""
        logger.info("Running sell cycle...")
        try:
            summary = trade_logic.run_sell_cycle()
            telegram_bot.notify_cycle_complete("sell", summary)
        except Exception as e:
            logger.error(f"Sell cycle error: {e}")
            telegram_bot.notify_error("Sell Cycle Error", str(e))

    def _run_confirmation_cycle(self):
        """Check and confirm pending confirmations."""
        if self.confirmation_handler:
            try:
                results = self.confirmation_handler.confirm_all()
                if sum(results.values()) > 0:
                    logger.info(f"Confirmations: {results}")
            except Exception as e:
                logger.error(f"Confirmation error: {e}")

    def _confirmation_loop(self):
        """Background thread for continuous confirmation checking."""
        logger.info("Starting confirmation loop...")
        while self.running:
            try:
                self._run_confirmation_cycle()
            except Exception as e:
                logger.error(f"Confirmation loop error: {e}")

            time.sleep(30)  # Check every 30 seconds

    def _setup_scheduler(self):
        """Setup APScheduler for periodic tasks."""
        self.scheduler = BackgroundScheduler()

        # Buy cycle - every N hours
        buy_interval = settings.buy_check_interval_hours
        self.scheduler.add_job(
            self._run_buy_cycle,
            trigger=IntervalTrigger(hours=buy_interval),
            id="buy_cycle",
            name="Buy Cycle",
            replace_existing=True,
            max_instances=1,
        )

        # Sell cycle - every N hours
        sell_interval = settings.sell_check_interval_hours
        self.scheduler.add_job(
            self._run_sell_cycle,
            trigger=IntervalTrigger(hours=sell_interval),
            id="sell_cycle",
            name="Sell Cycle",
            replace_existing=True,
            max_instances=1,
        )

        logger.info(
            f"Scheduler configured: buy every {buy_interval}h, "
            f"sell every {sell_interval}h"
        )

    def start(self, run_initial_cycles: bool = True):
        """
        Start the trading bot.

        Args:
            run_initial_cycles: Whether to run cycles immediately on start
        """
        logger.info("=" * 50)
        logger.info("Starting Steam Trading Bot")
        logger.info("=" * 50)

        self._setup_signal_handlers()

        # Login to Steam
        if not self._login():
            logger.error("Failed to login, exiting...")
            return

        self.running = True

        # Setup and start scheduler
        self._setup_scheduler()
        self.scheduler.start()

        # Start confirmation thread
        self._confirm_thread = threading.Thread(
            target=self._confirmation_loop,
            daemon=True
        )
        self._confirm_thread.start()

        # Run initial cycles if requested
        if run_initial_cycles:
            logger.info("Running initial cycles...")
            self._run_buy_cycle()
            time.sleep(5)
            self._run_sell_cycle()

        logger.info("Bot is running. Press Ctrl+C to stop.")

        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    async def start_with_telegram(self):
        """Start bot with Telegram polling (async mode)."""
        logger.info("=" * 50)
        logger.info("Starting Steam Trading Bot with Telegram")
        logger.info("=" * 50)

        self._setup_signal_handlers()

        # Login to Steam
        if not self._login():
            logger.error("Failed to login, exiting...")
            return

        self.running = True

        # Setup and start scheduler
        self._setup_scheduler()
        self.scheduler.start()

        # Start confirmation thread
        self._confirm_thread = threading.Thread(
            target=self._confirmation_loop,
            daemon=True
        )
        self._confirm_thread.start()

        # Run initial cycles
        logger.info("Running initial cycles...")
        self._run_buy_cycle()
        await asyncio.sleep(5)
        self._run_sell_cycle()

        # Start Telegram bot
        if telegram_bot.is_configured:
            await telegram_bot.start_polling()

            # Keep running
            while self.running:
                await asyncio.sleep(1)

            await telegram_bot.stop()
        else:
            logger.warning("Telegram not configured, running without it")
            while self.running:
                await asyncio.sleep(1)

    def stop(self):
        """Stop the trading bot gracefully."""
        logger.info("Stopping bot...")
        self.running = False

        # Stop scheduler
        if self.scheduler:
            self.scheduler.shutdown(wait=False)

        # Logout from Steam
        try:
            steam_client.logout()
        except Exception:
            pass

        telegram_bot.send_message_sync("🔴 <b>Bot Stopped</b>")

        logger.info("Bot stopped.")

    def get_status(self) -> dict:
        """Get current bot status."""
        status = trade_logic.get_status()

        # Add scheduler info
        if self.scheduler:
            jobs = []
            for job in self.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time),
                })
            status["scheduled_jobs"] = jobs

        status["running"] = self.running

        return status

    def run_manual_buy_cycle(self):
        """Manually trigger a buy cycle."""
        if not self.running:
            logger.warning("Bot is not running")
            return

        logger.info("Manual buy cycle triggered")
        self._run_buy_cycle()

    def run_manual_sell_cycle(self):
        """Manually trigger a sell cycle."""
        if not self.running:
            logger.warning("Bot is not running")
            return

        logger.info("Manual sell cycle triggered")
        self._run_sell_cycle()


# Global bot instance
trading_bot = TradingBot()


def main():
    """Main entry point."""
    trading_bot.start(run_initial_cycles=True)


def main_async():
    """Async entry point with Telegram."""
    asyncio.run(trading_bot.start_with_telegram())


if __name__ == "__main__":
    main()
