#!/usr/bin/env python3
"""
Bot Runner - запуск торгового бота для всех аккаунтов.

Usage:
    python bot_runner.py --once          # Один цикл торговли
    python bot_runner.py --loop          # Бесконечный цикл (24/7)
    python bot_runner.py --test          # Тестовый режим (без реальных сделок)
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import get_logger
from src.account_manager import AccountManager
from src.trading_bot import TradingBot
from src.database import trades_db

logger = get_logger(__name__)

# Интервал между циклами (секунды)
CYCLE_INTERVAL = 300  # 5 минут


async def run_single_cycle(account_manager: AccountManager, test_mode: bool = False) -> dict:
    """
    Выполнить один цикл торговли для всех аккаунтов.

    Args:
        account_manager: Account manager instance
        test_mode: If True, don't create real orders

    Returns:
        Dict with combined stats
    """
    logger.info("=" * 60)
    logger.info("Starting trading cycle for all accounts")
    logger.info("=" * 60)

    total_stats = {
        'orders_created': 0,
        'orders_filled': 0,
        'items_listed': 0,
        'accounts_processed': 0,
    }

    for account in account_manager.get_enabled_accounts():
        try:
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Processing account: {account.name}")
            logger.info(f"{'=' * 40}")

            # Login if not logged in
            if not account.is_logged_in():
                logger.info(f"[{account.name}] Logging in...")
                if not await account.login_async():
                    logger.error(f"[{account.name}] Login failed, skipping")
                    continue

            # Get wallet balance
            balance = account.get_wallet_balance()
            logger.info(f"[{account.name}] Wallet balance: {balance:.2f}")

            if balance < 1.0:
                logger.warning(f"[{account.name}] Insufficient balance, skipping")
                continue

            # Create trading bot
            bot = TradingBot(account)

            # Run cycle
            if test_mode:
                logger.info(f"[{account.name}] TEST MODE - reading profitable items only")
                items = bot.get_profitable_items(limit=5)
                logger.info(f"[{account.name}] Would create {len(items)} orders")
                stats = {'orders_created': 0, 'orders_filled': 0, 'items_listed': 0}
            else:
                stats = bot.run_cycle()

            # Update total stats
            total_stats['orders_created'] += stats['orders_created']
            total_stats['orders_filled'] += stats['orders_filled']
            total_stats['items_listed'] += stats['items_listed']
            total_stats['accounts_processed'] += 1

            logger.info(f"[{account.name}] Cycle complete")

        except Exception as e:
            logger.error(f"[{account.name}] Error in cycle: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    logger.info("\n" + "=" * 60)
    logger.info("Cycle complete for all accounts")
    logger.info(f"Accounts processed: {total_stats['accounts_processed']}")
    logger.info(f"Orders created: {total_stats['orders_created']}")
    logger.info(f"Orders filled: {total_stats['orders_filled']}")
    logger.info(f"Items listed: {total_stats['items_listed']}")
    logger.info("=" * 60)

    return total_stats


async def run_loop(account_manager: AccountManager, test_mode: bool = False):
    """
    Запустить бота в режиме 24/7 (бесконечный цикл).

    Args:
        account_manager: Account manager instance
        test_mode: If True, don't create real orders
    """
    logger.info("Starting bot in loop mode (24/7)")
    logger.info(f"Cycle interval: {CYCLE_INTERVAL} seconds ({CYCLE_INTERVAL/60:.1f} minutes)")
    logger.info("Press Ctrl+C to stop")

    # Запускаем фоновые задачи автосинхронизации для каждого аккаунта
    auto_sync_tasks = []
    for account in account_manager.get_enabled_accounts():
        if account.is_logged_in():
            bot = TradingBot(account)
            task = asyncio.create_task(bot.auto_sync_orders(interval=300))  # 5 минут
            auto_sync_tasks.append(task)
            logger.info(f"[{account.name}] Started auto-sync background task")

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            logger.info(f"\n\n{'#' * 60}")
            logger.info(f"CYCLE #{cycle_count}")
            logger.info(f"{'#' * 60}\n")

            await run_single_cycle(account_manager, test_mode=test_mode)

            logger.info(f"\nSleeping for {CYCLE_INTERVAL} seconds...")
            await asyncio.sleep(CYCLE_INTERVAL)

    except KeyboardInterrupt:
        logger.info("\n\nBot stopped by user (Ctrl+C)")
        logger.info(f"Total cycles completed: {cycle_count}")

        # Отменяем фоновые задачи
        logger.info("Cancelling auto-sync tasks...")
        for task in auto_sync_tasks:
            task.cancel()
        await asyncio.gather(*auto_sync_tasks, return_exceptions=True)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Trading Bot Runner')
    parser.add_argument('--once', action='store_true', help='Run single cycle and exit')
    parser.add_argument('--loop', action='store_true', help='Run continuous loop (24/7)')
    parser.add_argument('--test', action='store_true', help='Test mode (no real orders)')

    args = parser.parse_args()

    # Check if accounts.json exists
    if not Path('accounts.json').exists():
        logger.error("[ERROR] accounts.json not found!")
        logger.info("Please create accounts.json based on accounts.example.json")
        logger.info("See accounts.example.json for format")
        sys.exit(1)

    # Load accounts
    try:
        account_manager = AccountManager('accounts.json')

        if len(account_manager) == 0:
            logger.error("[ERROR] No accounts loaded!")
            logger.info("Please add accounts to accounts.json")
            sys.exit(1)

        logger.info(f"Loaded {len(account_manager)} account(s)")

        # Login all accounts (async version)
        logger.info("\n[LOGIN] Logging in to all accounts...")
        enabled_accounts = account_manager.get_enabled_accounts()

        # Login accounts in parallel
        login_tasks = [account.login_async() for account in enabled_accounts]
        login_results = await asyncio.gather(*login_tasks, return_exceptions=True)

        # Count successful logins
        successful_logins = sum(1 for result in login_results if result is True)

        if successful_logins == 0:
            logger.error("[ERROR] All logins failed!")
            logger.info("\nTroubleshooting:")
            logger.info("1. Check your credentials in accounts.json")
            logger.info("2. Make sure Steam Guard (2FA) is properly configured")
            logger.info("3. Check proxy settings if using proxies")
            sys.exit(1)

        logger.info(f"[OK] {successful_logins}/{len(enabled_accounts)} accounts logged in")

        # Show balances
        logger.info("\n💰 Account balances:")
        for account in account_manager.get_enabled_accounts():
            if account.is_logged_in():
                steam_balance = account.get_wallet_balance()
                csgotm_balance = account.get_csgotm_balance()
                logger.info(f"  [{account.name}] Steam: {steam_balance:.2f} | CSGO.TM: {csgotm_balance:.2f}")

        # Show database stats
        logger.info("\n📊 Database stats:")
        db_stats = trades_db.get_stats()
        logger.info(f"  Active orders: {db_stats['active_orders']}")
        logger.info(f"  Items on hold: {db_stats['items_on_hold']}")
        logger.info(f"  Items ready to sell: {db_stats['items_ready_to_sell']}")
        logger.info(f"  Items listed: {db_stats['items_listed']}")
        logger.info(f"  Total profit: ${db_stats['total_profit']:.2f}")

        # Determine mode
        if args.once:
            logger.info("\nRunning single cycle...")
            await run_single_cycle(account_manager, test_mode=args.test)
        elif args.loop:
            logger.info("\nStarting continuous loop...")
            await run_loop(account_manager, test_mode=args.test)
        else:
            # Default: single cycle
            logger.info("\nRunning single cycle (use --loop for 24/7 mode)...")
            await run_single_cycle(account_manager, test_mode=args.test)

        # Logout (TODO: make logout_all async if needed)
        logger.info("\n[LOGOUT] Logging out...")
        account_manager.logout_all()

        logger.info("\n[OK] Bot finished successfully!")

    except Exception as e:
        logger.error(f"\n[ERROR] Fatal error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    # Set event loop policy for Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
