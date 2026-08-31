"""
Trading bot service - integrates TradingBot with GUI state.
"""

from pathlib import Path
from typing import Optional
import asyncio
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.trading_bot import TradingBot
from flet_gui.state.app_state import AppState
from src.logger import get_logger

logger = get_logger(__name__)


class TradingBotService:
    """Service for managing trading bot in GUI."""

    def __init__(self, state: AppState, db_service=None, account_service=None, page=None):
        """Initialize trading bot service."""
        self.state = state
        self.db_service = db_service
        self.account_service = account_service
        self.page = page  # Flet page for UI updates
        self.bots: dict[str, TradingBot] = {}  # Bot per account
        self.bot_tasks: dict[str, asyncio.Task] = {}

    def start_bot(self) -> bool:
        """
        Prepare bot for starting (validation only).
        Actual initialization happens in run_bot_loop (async).
        """
        if self.state.bot_state.running:
            self.state.add_log("[WARNING] Bot is already running")
            return False

        try:
            # Get enabled accounts
            if not self.account_service or not self.account_service.account_manager:
                self.state.add_log("[ERROR] Account service not available")
                return False

            enabled_accounts = [acc for acc in self.state.accounts if acc.enabled]
            if not enabled_accounts:
                self.state.add_log("[WARNING] No enabled accounts found. Please enable at least one account in Accounts view.")
                return False

            self.state.update_bot_status(True, "Starting...")
            self.state.add_log("[INFO] Bot starting...")

            return True

        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            self.state.add_log(f"[ERROR] Failed to start bot: {str(e)}")
            self.state.update_bot_status(False, "Error")
            return False

    async def _initialize_bots_async(self) -> bool:
        """Initialize bots asynchronously (inside event loop)."""
        try:
            self.state.add_log("[INFO] Initializing trading bots...")

            enabled_accounts = [acc for acc in self.state.accounts if acc.enabled]

            for acc_info in enabled_accounts:
                account = self.account_service.account_manager.get_account(acc_info.name)
                if not account:
                    self.state.add_log(f"[ERROR] Account {acc_info.name} not found")
                    continue

                # ALWAYS reinitialize and login in current event loop
                # This is required because aiohttp sessions are bound to event loops
                self.state.add_log(f"[INFO] Logging in {acc_info.name}...")
                success = await self.account_service.login_account_async(acc_info.name)
                if not success:
                    self.state.add_log(f"[WARNING] Failed to login {acc_info.name}, skipping...")
                    continue

                # Create bot instance
                self.bots[acc_info.name] = TradingBot(account)
                self.state.add_log(f"[INFO] Bot initialized for {acc_info.name}")

            if not self.bots:
                self.state.add_log("[ERROR] No bots could be initialized. Check account login status.")
                return False

            self.state.update_bot_status(True, "Running")
            self.state.add_log(f"[SUCCESS] Trading bot started for {len(self.bots)} account(s)")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize bots: {e}")
            self.state.add_log(f"[ERROR] Failed to initialize bots: {str(e)}")
            self.state.update_bot_status(False, "Error")
            return False

    def stop_bot(self):
        """Stop the trading bot."""
        try:
            if not self.bots:
                self.state.add_log("[WARNING] Bot is not running")
                return

            self.state.add_log("[INFO] Stopping trading bots...")

            # Cancel all bot tasks if running
            for task_name, task in self.bot_tasks.items():
                if task and not task.done():
                    task.cancel()
                    self.state.add_log(f"[INFO] Cancelled task for {task_name}")

            self.bots.clear()
            self.bot_tasks.clear()

            self.state.update_bot_status(False, "Stopped")
            self.state.add_log("[SUCCESS] Trading bots stopped")

        except Exception as e:
            logger.error(f"Failed to stop bot: {e}")
            self.state.add_log(f"[ERROR] Failed to stop bot: {str(e)}")

    async def run_bot_cycle(self):
        """Run the bot trading cycle for all bots."""
        if not self.bots:
            self.state.add_log("[ERROR] Bots not initialized")
            return

        try:
            cycle_num = self.state.bot_state.current_cycle + 1
            self.state.add_log(f"[INFO] Starting bot cycle #{cycle_num}...")

            # Run bot cycle for each bot
            for account_name, bot in self.bots.items():
                try:
                    self.state.add_log(f"[INFO] Running cycle for {account_name}...")
                    await bot.run_cycle()
                    self.state.add_log(f"[SUCCESS] Cycle completed for {account_name}")
                except Exception as e:
                    logger.error(f"Cycle error for {account_name}: {e}")
                    self.state.add_log(f"[ERROR] Cycle failed for {account_name}: {str(e)}")

            # Update state
            self.state.bot_state.current_cycle = cycle_num
            from datetime import datetime
            self.state.bot_state.last_cycle_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.state._notify('bot_state')

            # Refresh data from database
            if self.db_service:
                self.db_service.load_all_data()

            # Update UI after cycle
            if self.page:
                try:
                    self.page.update()
                except Exception as e:
                    logger.debug(f"Page update after cycle: {e}")

            self.state.add_log(f"[SUCCESS] Bot cycle #{cycle_num} completed")

        except Exception as e:
            logger.error(f"Bot cycle error: {e}")
            self.state.add_log(f"[ERROR] Bot cycle failed: {str(e)}")

    async def run_bot_loop(self):
        """Run the bot in a continuous loop."""
        try:
            # Initialize bots INSIDE the async context (important for aiohttp!)
            if not await self._initialize_bots_async():
                self.state.update_bot_status(False, "Init Failed")
                return

            while self.state.bot_state.running:
                try:
                    # Run cycle
                    await self.run_bot_cycle()

                    # Wait for next cycle
                    cycle_interval = self.state.config.get('cycle_interval_minutes', 5) * 60
                    self.state.add_log(f"[INFO] Waiting {cycle_interval}s until next cycle...")
                    await asyncio.sleep(cycle_interval)

                except asyncio.CancelledError:
                    self.state.add_log("[INFO] Bot loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Bot loop error: {e}")
                    self.state.add_log(f"[ERROR] Bot loop error: {str(e)}")
                    # Wait a bit before retrying
                    await asyncio.sleep(30)
        finally:
            # Ensure bot is stopped
            if self.state.bot_state.running:
                self.state.update_bot_status(False, "Stopped")
                self.state.add_log("[INFO] Bot loop ended")

    def get_bot_status(self) -> dict:
        """Get current bot status."""
        return {
            'running': self.state.bot_state.running,
            'current_cycle': self.state.bot_state.current_cycle,
            'last_cycle_time': self.state.bot_state.last_cycle_time,
            'status_text': self.state.bot_state.status_text,
        }
