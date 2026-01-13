#!/usr/bin/env python3
"""
Steam Trading Bot - Main Entry Point

Automates buying items on Steam Marketplace and selling them on CSGO.TM.

Usage:
    python main.py              # Run bot with Telegram
    python main.py --no-telegram  # Run bot without Telegram
    python main.py --status     # Show current status
    python main.py --test       # Test connections

Environment:
    Copy config/.env.example to .env and fill in your credentials.

For more information, see README.md
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)


def test_connections():
    """Test all connections and configuration."""
    print("Testing connections...\n")

    # Test configuration
    print("1. Configuration:")
    print(f"   Steam Username: {settings.steam_username[:3]}***")
    print(f"   CSGO.TM API Key: {settings.csgotm_api_key[:8]}***")
    print(f"   Telegram: {'Configured' if settings.telegram_bot_token else 'Not configured'}")
    print(f"   Bottm DB: {settings.bottm_db_path}")
    print(f"   Trades DB: {settings.trades_db_path}")
    print()

    # Test bottm database
    print("2. Bottm Database:")
    try:
        from src.bottm_parser import bottm_parser
        stats = bottm_parser.get_stats()
        print(f"   Total items: {stats.get('total_items', 0)}")
        print(f"   Items with prices: {stats.get('items_with_prices', 0)}")
        print(f"   Avg profit: {stats.get('avg_profit_pct', 0):.1f}%")
    except FileNotFoundError:
        print(f"   ERROR: Database not found at {settings.bottm_db_path}")
    except Exception as e:
        print(f"   ERROR: {e}")
    print()

    # Test trades database
    print("3. Trades Database:")
    try:
        from src.database import trades_db
        stats = trades_db.get_stats()
        print(f"   Active orders: {stats.get('active_orders', 0)}")
        print(f"   Items on hold: {stats.get('items_on_hold', 0)}")
        print(f"   Total profit: ${stats.get('total_profit', 0):.2f}")
    except Exception as e:
        print(f"   ERROR: {e}")
    print()

    # Test Steam connection
    print("4. Steam Connection:")
    try:
        from src.steam_client import steam_client
        steam_client.login()
        wallet = steam_client.get_wallet_balance()
        print(f"   Logged in successfully!")
        print(f"   Balance: ${wallet.balance:.2f} {wallet.currency_code}")
        steam_client.logout()
    except Exception as e:
        print(f"   ERROR: {e}")
    print()

    # Test CSGO.TM connection
    print("5. CSGO.TM Connection:")
    try:
        from src.csgotm_client import csgotm_client
        if csgotm_client.ping():
            balance = csgotm_client.get_money()
            print(f"   Connected successfully!")
            print(f"   Balance: {balance:.2f} RUB")
        else:
            print("   ERROR: Ping failed")
    except Exception as e:
        print(f"   ERROR: {e}")
    print()

    print("Test complete!")


def show_status():
    """Show current trading status."""
    print("Trading Bot Status\n" + "=" * 40 + "\n")

    try:
        from src.database import trades_db
        from src.bottm_parser import bottm_parser

        # Trades stats
        stats = trades_db.get_stats()
        print("Trading Statistics:")
        print(f"  Active Orders: {stats.get('active_orders', 0)}")
        print(f"  Orders Value: ${stats.get('total_orders_value', 0):.2f}")
        print(f"  Items on Hold: {stats.get('items_on_hold', 0)}")
        print(f"  Ready to Sell: {stats.get('items_ready_to_sell', 0)}")
        print(f"  Listed for Sale: {stats.get('items_listed', 0)}")
        print()

        # Profit stats
        print("Profit Statistics:")
        print(f"  Total Sales: {stats.get('total_sales', 0)}")
        print(f"  Total Profit: ${stats.get('total_profit', 0):.2f}")
        print(f"  Avg Profit: {stats.get('avg_profit_pct', 0):.1f}%")
        print()

        # Recent sales
        recent = trades_db.get_recent_sales(5)
        if recent:
            print("Recent Sales:")
            for sale in recent:
                print(f"  - {sale['item_name'][:40]}: +${sale['profit']:.2f}")
        print()

        # Bottm stats
        try:
            bottm_stats = bottm_parser.get_stats()
            print("Bottm Database:")
            print(f"  Total Items: {bottm_stats.get('total_items', 0)}")
            print(f"  Avg Profit: {bottm_stats.get('avg_profit_pct', 0):.1f}%")
        except Exception:
            print("Bottm Database: Not available")

    except Exception as e:
        print(f"Error getting status: {e}")


def run_bot(with_telegram: bool = True):
    """Run the trading bot."""
    from src.bot import trading_bot

    if with_telegram:
        asyncio.run(trading_bot.start_with_telegram())
    else:
        trading_bot.start(run_initial_cycles=True)


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Steam Trading Bot - Buy on Steam, Sell on CSGO.TM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  Run bot with Telegram notifications
  python main.py --no-telegram    Run bot without Telegram
  python main.py --test           Test all connections
  python main.py --status         Show current trading status

Configuration:
  Copy config/.env.example to .env and fill in your credentials.
        """
    )

    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Run without Telegram bot"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Test connections and exit"
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and exit"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Set debug logging if requested
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle commands
    if args.test:
        test_connections()
    elif args.status:
        show_status()
    else:
        print("""
╔═══════════════════════════════════════════════════════════╗
║           Steam Trading Bot v1.0.0                        ║
║                                                           ║
║   Buy on Steam Marketplace → Sell on CSGO.TM             ║
╚═══════════════════════════════════════════════════════════╝
        """)
        run_bot(with_telegram=not args.no_telegram)


if __name__ == "__main__":
    main()
