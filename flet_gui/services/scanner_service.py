"""
Scanner service - integrates AutoScanner with GUI state.
"""

from pathlib import Path
from typing import Optional
import sys
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.auto_scanner import AutoScanner
from flet_gui.state.app_state import AppState
from src.proxy_utils import load_proxy_file
from src.logger import get_logger

logger = get_logger(__name__)


class ScannerService:
    """Service for managing auto-scanner in GUI."""

    def __init__(self, state: AppState, auto_buy_service=None):
        """Initialize scanner service."""
        self.state = state
        self.scanner: Optional[AutoScanner] = None
        self.auto_buy_service = auto_buy_service  # For getting excluded items

    def start_scanner(self) -> bool:
        """Start the auto-scanner."""
        if self.scanner and self.state.scanner_state.running:
            self.state.add_log("[WARNING] Scanner is already running")
            return False

        try:
            self.state.add_log("[INFO] Initializing auto-scanner...")

            # Define scan callback that will be called by AutoScanner
            def scan_callback():
                """Callback for running scans."""
                logger.info("Scanner: Performing automatic scan...")
                self.state.add_log("[INFO] Scanner: Starting automatic scan cycle...")

                try:
                    # Get max items from config
                    max_items = self.state.config.get('auto_scan_new_items', 10)

                    # Run scan synchronously (AutoScanner runs in thread, not async)
                    items = self.run_single_scan(max_items=max_items)

                    # Update profitable items in state
                    if items:
                        # Load from database instead to get full list
                        try:
                            from src.database import TradesDatabase
                            db = TradesDatabase()
                            min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
                            all_items = db.get_active_profitable_items(min_profit=min_profit, limit=100)
                            self.state.profitable_items = all_items
                            self.state._notify('profitable_items')
                        except Exception as e:
                            logger.error(f"Failed to load profitable items: {e}")

                    logger.info(f"Scanner: Automatic scan completed ({len(items)} new items)")

                except Exception as e:
                    logger.error(f"Scanner callback error: {e}", exc_info=True)
                    self.state.add_log(f"[ERROR] Automatic scan failed: {str(e)}")

            # Create scanner instance with callback
            scan_interval = self.state.config.get('scan_interval_minutes', 30)
            self.scanner = AutoScanner(
                scan_callback=scan_callback,
                interval_minutes=scan_interval,
                enabled=True
            )

            # Start the scanner thread
            self.scanner.start()

            self.state.update_scanner_status(True, "Running")
            self.state.add_log("[SUCCESS] Auto-scanner started")

            return True

        except Exception as e:
            logger.error(f"Failed to start scanner: {e}", exc_info=True)
            self.state.add_log(f"[ERROR] Failed to start scanner: {str(e)}")
            self.state.update_scanner_status(False, "Error")
            return False

    def stop_scanner(self):
        """Stop the auto-scanner."""
        try:
            if not self.scanner:
                self.state.add_log("[WARNING] Scanner is not running")
                return

            self.state.add_log("[INFO] Stopping auto-scanner...")

            # Stop the scanner thread
            self.scanner.stop()

            self.scanner = None

            self.state.update_scanner_status(False, "Stopped")
            self.state.add_log("[SUCCESS] Auto-scanner stopped")

        except Exception as e:
            logger.error(f"Failed to stop scanner: {e}", exc_info=True)
            self.state.add_log(f"[ERROR] Failed to stop scanner: {str(e)}")

    async def run_single_scan_async(self, max_items: int = 10) -> list:
        """
        Run a single scan manually for new items (async version).

        Args:
            max_items: Maximum number of new items to scan

        Returns:
            List of profitable items found
        """
        try:
            self.state.add_log(f"[INFO] Starting manual scan for {max_items} new items...")

            # Import here to avoid circular dependencies
            from src.bottm.analysis.scanner import ItemScanner
            from src.database import TradesDatabase
            from src.bottm.config import Currency, FilterSettings

            # Get database
            db = TradesDatabase()

            # Create FilterSettings object from config
            min_profit_value = self.state.config.get('scanner_min_profit', -5.0)
            filters = FilterSettings(
                min_price=self.state.config.get('scanner_min_price', 1000.0),
                max_price=self.state.config.get('scanner_max_price', 10000.0),
                min_sales_7d=self.state.config.get('min_sales_7d', 5),
                min_sales_30d=self.state.config.get('min_volume_30d', 20),
                max_price_deviation=self.state.config.get('max_price_deviation', 15.0),
                min_profit_margin=min_profit_value,
            )

            self.state.add_log(f"[DEBUG] Filter settings: min_profit={min_profit_value}%, min_price={filters.min_price}, max_price={filters.max_price}")

            # Load proxies from file - try config first, then default proxies.txt
            proxy_list = []
            proxy_file = self.state.config.get('proxy_file', '') or 'proxies.txt'
            try:
                from pathlib import Path
                proxy_path = Path(proxy_file)
                if proxy_path.exists():
                    proxy_list, skipped_proxies = load_proxy_file(proxy_path)
                    self.state.add_log(f"[INFO] Loaded {len(proxy_list)} proxies from {proxy_file}")
                    if skipped_proxies:
                        self.state.add_log(f"[WARNING] Skipped {skipped_proxies} invalid proxy entries from {proxy_file}")
                else:
                    self.state.add_log(f"[WARNING] Proxy file not found: {proxy_file}")
            except Exception as e:
                logger.error(f"Failed to load proxies: {e}")
                self.state.add_log(f"[WARNING] Failed to load proxies: {e}")

            # Test proxies before scanning (like in old scanner)
            if proxy_list:
                self.state.add_log(f"[INFO] Testing {len(proxy_list)} proxies...")
                working_proxies = await self._test_proxies(proxy_list)
                proxy_list = working_proxies
                if working_proxies:
                    self.state.add_log(f"[SUCCESS] {len(working_proxies)} working proxies found")
                else:
                    self.state.add_log("[WARNING] No working proxies! Scan may fail")

            # Get first proxy or None
            first_proxy = proxy_list[0] if proxy_list else None

            if not first_proxy:
                self.state.add_log("[WARNING] No proxies configured! Scan may fail due to DNS/network issues")

            # Get requests per proxy from config
            requests_per_proxy = self.state.config.get('requests_per_proxy', 50)

            # USE proxy rotation to avoid hanging when one proxy fails
            self.state.add_log(f"[INFO] Using proxy rotation with {len(proxy_list)} proxies")

            # Log proxy details before creating scanner
            if proxy_list:
                self.state.add_log(f"[DEBUG] Creating ItemScanner with {len(proxy_list)} proxies, requests_per_proxy={requests_per_proxy}")
            else:
                self.state.add_log(f"[DEBUG] Creating ItemScanner with NO PROXY")

            # Get excluded items from auto_buy service
            excluded_items = set()
            if self.auto_buy_service:
                excluded_items = {item.name for item in self.auto_buy_service.items}
                if excluded_items:
                    self.state.add_log(f"[INFO] Excluding {len(excluded_items)} items from auto_buy list")

            # Create scanner WITH proxy rotation
            scanner = ItemScanner(
                database=db,
                currency=Currency.RUB,
                proxy_url=first_proxy,  # Initial proxy
                proxy_list=proxy_list,  # Enable rotation on timeouts/errors
                requests_per_proxy=requests_per_proxy,  # From config
                filters=filters,
                excluded_items=excluded_items,  # Exclude auto_buy items
            )
            self.state.add_log(f"[DEBUG] ItemScanner created successfully")

            try:
                self.state.add_log("[INFO] Loading CSGO.TM market prices...")

                # Add timeout for load_data
                try:
                    await asyncio.wait_for(scanner.load_data(), timeout=60.0)
                    self.state.add_log("[SUCCESS] Market data loaded")
                except asyncio.TimeoutError:
                    self.state.add_log("[ERROR] Timeout loading market data (60s)")
                    return []
                except Exception as e:
                    self.state.add_log(f"[ERROR] Failed to load market data: {e}")
                    return []

                self.state.add_log(f"[INFO] Starting scan of {max_items} items...")

                # Redirect scanner logs to GUI
                import logging
                gui_handler = logging.Handler()
                gui_handler.setLevel(logging.DEBUG)  # Show DEBUG logs

                def emit_to_gui(record):
                    try:
                        msg = record.getMessage()

                        # Skip verbose steam_market logs (nameid, price_history)
                        if record.name == 'src.bottm.api.steam_market':
                            return

                        # Show ALL messages from scanner logger
                        if record.name == 'src.bottm.analysis.scanner':
                            self.state.add_log(f"[{record.levelname}] {msg}")
                        # Show important messages from other loggers
                        elif any(keyword in msg for keyword in [
                            "FOUND", "Error", "Failed", "candidates"
                        ]):
                            self.state.add_log(f"[{record.levelname}] {msg}")
                    except:
                        pass

                gui_handler.emit = emit_to_gui

                # Add handler to scanner, csgo_market, and steam_market loggers
                scanner_logger = logging.getLogger('src.bottm.analysis.scanner')
                csgo_logger = logging.getLogger('src.bottm.api.csgo_market')
                steam_logger = logging.getLogger('src.bottm.api.steam_market')

                # CRITICAL: Set all loggers to DEBUG level
                scanner_logger.setLevel(logging.DEBUG)
                csgo_logger.setLevel(logging.DEBUG)
                steam_logger.setLevel(logging.DEBUG)

                # Ensure propagation
                scanner_logger.propagate = True
                csgo_logger.propagate = True
                steam_logger.propagate = True

                scanner_logger.addHandler(gui_handler)
                csgo_logger.addHandler(gui_handler)
                steam_logger.addHandler(gui_handler)

                self.state.add_log(f"[DEBUG] Added GUI log handlers to scanner loggers")
                self.state.add_log(f"[DEBUG] Scanner logger level: {scanner_logger.level}, effective level: {scanner_logger.getEffectiveLevel()}")

                # Force a test message to verify logging works
                scanner_logger.info("=== SCANNER LOGGER TEST MESSAGE ===")
                self.state.add_log(f"[DEBUG] If you see '=== SCANNER LOGGER TEST MESSAGE ===' above, logging is working")

                try:
                    # Check DB count before scan
                    items_before = db.get_profitable_items_count()
                    self.state.add_log(f"[DEBUG] Database has {items_before} profitable items before scan")

                    # ВАЖНО: Для Scan New ищем max_items НОВЫХ профитных предметов
                    # max_candidates_to_check ограничивает количество проверяемых кандидатов
                    # exclude_existing=True - исключаем предметы, которые уже в БД
                    self.state.add_log(f"[DEBUG] Calling scanner.scan() with max_items={max_items}, max_candidates={500}, exclude_existing=True")
                    profitable_items = await scanner.scan(
                        max_items=max_items,  # Количество НОВЫХ профитных для поиска
                        delay_between_items=2.0,  # Increased delay to avoid rate limiting
                        parallel=1,
                        max_candidates_to_check=500,  # Максимум кандидатов для проверки
                        exclude_existing=True,  # ВАЖНО: Исключить предметы, которые уже в БД
                    )
                    self.state.add_log(f"[DEBUG] scanner.scan() returned {len(profitable_items)} items")

                    # Check DB count after scan
                    items_after = db.get_profitable_items_count()
                    self.state.add_log(f"[DEBUG] Database has {items_after} profitable items after scan (+{items_after - items_before})")

                    # Log item names for debugging
                    if profitable_items:
                        self.state.add_log(f"[DEBUG] First 3 items: {', '.join(item.market_hash_name for item in profitable_items[:3])}")

                finally:
                    scanner_logger.removeHandler(gui_handler)
                    csgo_logger.removeHandler(gui_handler)
                    steam_logger.removeHandler(gui_handler)

                # Update state
                from datetime import datetime
                now = datetime.now()
                self.state.scanner_state.last_scan_time = now.strftime("%Y-%m-%d %H:%M:%S")
                self.state.scanner_state.items_found = len(profitable_items)
                self.state._notify('scanner_state')

                self.state.add_log(f"[SUCCESS] Manual scan completed! Found {len(profitable_items)} profitable items")
                return profitable_items

            finally:
                # Always close scanner to cleanup aiohttp sessions
                try:
                    await scanner.close()
                    # Give aiohttp time to properly cleanup all connections
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Error closing scanner: {e}")

        except Exception as e:
            logger.error(f"Manual scan error: {e}", exc_info=True)
            self.state.add_log(f"[ERROR] Manual scan failed: {str(e)}")
            return []

    def run_single_scan(self, max_items: int = 10) -> list:
        """
        Run a single scan manually for new items (sync wrapper).

        IMPORTANT: This method creates a new event loop and blocks until complete.
        For GUI use, prefer run_single_scan_async() with page.run_task() or asyncio.to_thread().

        Args:
            max_items: Maximum number of new items to scan

        Returns:
            List of profitable items found
        """
        try:
            # Check if we're already in an async context
            try:
                loop = asyncio.get_running_loop()
                # If we're in async context, we can't use run_until_complete
                # Instead, create task and return empty (caller should use async version)
                logger.warning("run_single_scan called from async context - use run_single_scan_async instead")
                self.state.add_log("[WARNING] Use async version for non-blocking scan")
                return []
            except RuntimeError:
                # No running loop, safe to create new one
                pass

            # Run async scan in new event loop (only if not already in async context)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.run_single_scan_async(max_items))
                return result
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        except Exception as e:
            logger.error(f"Manual scan error: {e}", exc_info=True)
            self.state.add_log(f"[ERROR] Manual scan failed: {str(e)}")
            return []

    async def _test_proxies(self, proxies: list[str]) -> list[str]:
        """Test proxies and return only working ones."""
        from src.bottm.api.steam_market import SteamMarketAPI

        working_proxies = []

        for idx, proxy in enumerate(proxies, 1):
            try:
                proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                self.state.add_log(f"[INFO] Testing proxy {idx}/{len(proxies)}: {proxy_display}")

                api = SteamMarketAPI(proxy_url=proxy)
                is_working = await api.check_proxy(proxy, timeout=10, check_steam_api=True)
                await api.close()

                if is_working:
                    working_proxies.append(proxy)
                    self.state.add_log(f"[SUCCESS] Proxy {idx}/{len(proxies)}: {proxy_display} - OK")
                else:
                    self.state.add_log(f"[WARNING] Proxy {idx}/{len(proxies)}: {proxy_display} - FAILED")

            except Exception as e:
                proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                # Текст исключения от aiohttp-socks часто содержит полный URL
                # прокси вместе с user:pass — чистим перед записью в лог.
                from src.logger import redact_text
                self.state.add_log(
                    f"[ERROR] Proxy {idx}/{len(proxies)}: {proxy_display} - {redact_text(str(e))}"
                )

        return working_proxies

    def get_scanner_status(self) -> dict:
        """Get current scanner status."""
        return {
            'running': self.state.scanner_state.running,
            'status_text': self.state.scanner_state.status_text,
            'items_found': self.state.scanner_state.items_found,
            'last_scan_time': self.state.scanner_state.last_scan_time,
            'next_scan_time': self.state.scanner_state.next_scan_time,
        }
