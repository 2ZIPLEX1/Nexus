#!/usr/bin/env python3
"""
Bot Runner - запуск торгового бота для всех аккаунтов.

Usage:
    python bot_runner.py --once          # Один цикл торговли
    python bot_runner.py --loop          # Бесконечный цикл (24/7)
    python bot_runner.py --test          # Тестовый режим (без реальных сделок)
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import get_logger
from src.account_manager import AccountManager
from src.trading_bot import TradingBot
from src.database import trades_db

logger = get_logger(__name__)

# Интервал между циклами (секунды)
CYCLE_INTERVAL = 300  # 5 минут


def run_single_cycle(account_manager: AccountManager, test_mode: bool = False) -> dict:
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
                if not account.login():
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


def run_loop(account_manager: AccountManager, test_mode: bool = False):
    """
    Запустить бота в режиме 24/7 (бесконечный цикл).

    Args:
        account_manager: Account manager instance
        test_mode: If True, don't create real orders
    """
    logger.info("Starting bot in loop mode (24/7)")
    logger.info(f"Cycle interval: {CYCLE_INTERVAL} seconds ({CYCLE_INTERVAL/60:.1f} minutes)")
    logger.info("Press Ctrl+C to stop")

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            logger.info(f"\n\n{'#' * 60}")
            logger.info(f"CYCLE #{cycle_count}")
            logger.info(f"{'#' * 60}\n")

            run_single_cycle(account_manager, test_mode=test_mode)

            logger.info(f"\n💤 Sleeping for {CYCLE_INTERVAL} seconds...")
            time.sleep(CYCLE_INTERVAL)

    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Bot stopped by user (Ctrl+C)")
        logger.info(f"Total cycles completed: {cycle_count}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Trading Bot Runner')
    parser.add_argument('--once', action='store_true', help='Run single cycle and exit')
    parser.add_argument('--loop', action='store_true', help='Run continuous loop (24/7)')
    parser.add_argument('--test', action='store_true', help='Test mode (no real orders)')

    args = parser.parse_args()

    # Check if accounts.json exists
    if not Path('accounts.json').exists():
        logger.error("❌ accounts.json not found!")
        logger.info("Please create accounts.json based on accounts.example.json")
        logger.info("See accounts.example.json for format")
        sys.exit(1)

    # Load accounts
    try:
        account_manager = AccountManager('accounts.json')

        if len(account_manager) == 0:
            logger.error("❌ No accounts loaded!")
            logger.info("Please add accounts to accounts.json")
            sys.exit(1)

        logger.info(f"Loaded {len(account_manager)} account(s)")

        # Login all accounts
        logger.info("\n🔐 Logging in to all accounts...")
        login_results = account_manager.login_all()

        successful_logins = sum(1 for success in login_results.values() if success)

        if successful_logins == 0:
            logger.error("❌ All logins failed!")
            logger.info("\nTroubleshooting:")
            logger.info("1. Make sure steam_cookies_<account>.txt files exist")
            logger.info("2. Or create them by logging in manually in browser:")
            logger.info("   - Open store.steampowered.com")
            logger.info("   - F12 → Application → Cookies")
            logger.info("   - Copy sessionid, steamLoginSecure, steamCountry, timezoneOffset")
            logger.info("   - Save to steam_cookies_<account>.txt")
            sys.exit(1)

        logger.info(f"✅ {successful_logins}/{len(login_results)} accounts logged in")

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
            logger.info("\n▶️  Running single cycle...")
            run_single_cycle(account_manager, test_mode=args.test)
        elif args.loop:
            logger.info("\n▶️  Starting continuous loop...")
            run_loop(account_manager, test_mode=args.test)
        else:
            # Default: single cycle
            logger.info("\n▶️  Running single cycle (use --loop for 24/7 mode)...")
            run_single_cycle(account_manager, test_mode=args.test)

        # Logout
        logger.info("\n👋 Logging out...")
        account_manager.logout_all()

        logger.info("\n✅ Bot finished successfully!")

    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
