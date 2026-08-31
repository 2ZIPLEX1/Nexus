"""
Scanner process - runs as separate subprocess to avoid event loop conflicts.

This module runs the TM Parser scanner in a separate process, avoiding
async event loop conflicts with the main GUI.
"""
import asyncio
import logging
import sys
import json
import os
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.bottm.config import Currency, FilterSettings
from src.bottm.analysis.scanner import ItemScanner
from src.database import TradesDatabase
from src.proxy_utils import load_proxy_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class ScannerProcess:
    """Scanner process runner."""

    def __init__(self, config_file: str = "scanner_config.json", stop_file: str = "scanner_stop.flag"):
        """
        Initialize scanner process.

        Args:
            config_file: JSON file with scanner configuration
            stop_file: Flag file that signals process to stop
        """
        self.config_file = Path(config_file)
        self.stop_file = Path(stop_file)
        self.config = {}
        self.scanner: Optional[ItemScanner] = None

    def load_config(self) -> bool:
        """Load scanner configuration from JSON file."""
        try:
            if not self.config_file.exists():
                logger.error(f"Config file not found: {self.config_file}")
                return False

            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)

            logger.info(f"Loaded config: {self.config}")
            return True

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False

    def should_stop(self) -> bool:
        """Check if stop signal received."""
        return self.stop_file.exists()

    def load_proxies(self, proxy_file: str) -> list[str]:
        """Load proxies from file."""
        proxy_path = Path(proxy_file)
        if not proxy_path.exists():
            logger.warning(f"Proxy file not found: {proxy_file}")
            return []

        try:
            proxies, skipped = load_proxy_file(proxy_path)

            logger.info(f"Loaded {len(proxies)} proxies from {proxy_file}")
            if skipped:
                logger.warning(f"Skipped {skipped} invalid proxy entries from {proxy_file}")
            return proxies

        except Exception as e:
            logger.error(f"Failed to load proxies: {e}")
            return []

    async def test_proxies(self, proxies: list[str]) -> list[str]:
        """Test proxies and return working ones."""
        from src.bottm.api.steam_market import SteamMarketAPI

        if not proxies:
            return []

        logger.info(f"Testing {len(proxies)} proxies...")
        working_proxies = []

        for idx, proxy in enumerate(proxies, 1):
            try:
                api = SteamMarketAPI(proxy_url=proxy)
                is_working = await api.check_proxy(proxy, timeout=10)
                await api.close()

                if is_working:
                    working_proxies.append(proxy)
                    proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                    logger.info(f"✅ Proxy {idx}/{len(proxies)}: {proxy_display} - working")
                else:
                    proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                    logger.info(f"❌ Proxy {idx}/{len(proxies)}: {proxy_display} - not working")

            except Exception as e:
                proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                logger.error(f"❌ Proxy {idx}/{len(proxies)}: {proxy_display} - error: {e}")

        logger.info(f"Working proxies: {len(working_proxies)}/{len(proxies)}")
        return working_proxies

    async def run_scanner(self):
        """Run the scanner with loaded configuration."""
        try:
            # Сначала попробуем загрузить общие настройки из bot_config.json
            bot_config = {}
            bot_config_path = Path("bot_config.json")
            if bot_config_path.exists():
                with open(bot_config_path, 'r', encoding='utf-8') as f:
                    bot_config = json.load(f)
                logger.info("Loaded shared settings from bot_config.json")

            # Extract config (приоритет у scanner_config.json, fallback на bot_config.json)
            min_price = float(self.config.get('min_price', bot_config.get('scanner_min_price', 1000)))
            max_price = float(self.config.get('max_price', bot_config.get('scanner_max_price', 10000)))
            min_profit = float(self.config.get('min_profit', bot_config.get('scanner_min_profit', -5.0)))
            min_sales_7d = int(self.config.get('min_sales_7d', bot_config.get('min_sales_7d', 50)))
            proxy_file = self.config.get('proxy_file', bot_config.get('proxy_file', 'proxies.txt'))
            requests_per_proxy = int(self.config.get('requests_per_proxy', bot_config.get('requests_per_proxy', 50)))
            max_items = int(self.config.get('max_items', bot_config.get('scanner_max_items', 10)))
            delay = float(self.config.get('delay', bot_config.get('scanner_delay', 7.0)))
            workers = int(self.config.get('workers', bot_config.get('scanner_workers', 1)))

            logger.info(f"Scanner settings: price {min_price}-{max_price}, min profit {min_profit}%")
            logger.info(f"Max items: {max_items}, delay: {delay}s, workers: {workers}")

            # Load and test proxies
            proxies = self.load_proxies(proxy_file)

            if proxies:
                proxies = await self.test_proxies(proxies)

                if not proxies:
                    logger.warning("No working proxies found. Continuing without proxies.")
            else:
                logger.info("No proxies configured. Working without proxies (may be rate limited).")

            # Create filter settings
            filters = FilterSettings(
                min_price=min_price,
                max_price=max_price,
                min_sales_7d=min_sales_7d,
                min_profit_margin=min_profit,
            )

            # Create database connection
            db = TradesDatabase()

            # Increase requests_per_proxy to avoid rotation
            scan_requests_per_proxy = max(max_items * 10, requests_per_proxy)

            # Use first proxy for CSGO Market API (doesn't rotate, blocked by Russian hosting)
            first_proxy = proxies[0] if proxies else None

            # Create scanner
            self.scanner = ItemScanner(
                database=db,
                currency=Currency.RUB,
                proxy_url=first_proxy,  # Single proxy for CSGO Market API
                proxy_list=proxies if proxies else None,  # List for Steam Market API (rotates)
                requests_per_proxy=scan_requests_per_proxy,
                filters=filters,
            )

            logger.info("Loading market data from CSGO.TM and Steam Market...")
            await self.scanner.load_data()

            logger.info("Data loaded! Starting scan...")

            # Check stop signal before scan
            if self.should_stop():
                logger.info("Stop signal received before scan")
                await self.scanner.close()
                return

            # Run scan
            parallel = min(workers, max_items)
            logger.info(f"Parallel workers: {parallel}")

            profitable_items = await self.scanner.scan(
                max_items=max_items,
                delay_between_items=delay,
                parallel=parallel,
            )

            # Close scanner
            await self.scanner.close()

            logger.info(f"✅ Scan complete! Found {len(profitable_items)} profitable items")

        except Exception as e:
            logger.error(f"Scanner error: {e}", exc_info=True)
            if self.scanner:
                await self.scanner.close()
            raise

    async def run(self):
        """Main run method."""
        try:
            # Load configuration
            if not self.load_config():
                logger.error("Failed to load config, exiting")
                return

            # Run scanner
            await self.run_scanner()

            logger.info("Scanner process completed successfully")

        except Exception as e:
            logger.error(f"Scanner process failed: {e}", exc_info=True)
            sys.exit(1)


def main():
    """Entry point for scanner process."""
    try:
        # Create scanner process
        process = ScannerProcess()

        # Run in async event loop
        asyncio.run(process.run())

        sys.exit(0)

    except KeyboardInterrupt:
        logger.info("Scanner interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
