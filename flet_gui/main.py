"""
Main entry point for the Steam Trading Bot Flet GUI.

Run with: python -m flet_gui.main
Run with mock data: python -m flet_gui.main --mock-data
"""

import flet as ft
import sys
import threading
from typing import Callable, Optional

# ВАЖНО: применяет DNS-фикс (aiohttp ThreadedResolver) до создания любых сессий.
# На Windows+aiodns прямое подключение к Steam иначе падает "Could not contact DNS servers".
import src.dns_compat  # noqa: F401

from flet_gui.theme.colors import COLORS
from flet_gui.state.app_state import AppState
from flet_gui.state.events import EventBus, EventType
from flet_gui.components.navigation import create_navigation
from flet_gui.components.header import create_header
from flet_gui.components.status_bar import create_status_bar
from flet_gui.views.dashboard_view import create_dashboard_view
from flet_gui.views.accounts_view import create_accounts_view
from flet_gui.views.orders_view import create_orders_view
from flet_gui.views.inventory_view import create_inventory_view
from flet_gui.views.tm_parser_view import create_tm_parser_view
from flet_gui.views.tm_sales_view import create_tm_sales_view
from flet_gui.views.auto_buy_view import create_auto_buy_view
from flet_gui.views.logs_view import create_logs_view
from flet_gui.views.history_view import create_history_view
from flet_gui.views.settings_view import create_settings_view
from flet_gui.services.mocks import MockServices
from flet_gui.services.database_service import DatabaseService
from flet_gui.services.account_service import AccountService
from flet_gui.services.trading_bot_service import TradingBotService
from flet_gui.services.scanner_service import ScannerService
from flet_gui.services.config_service import ConfigService
from flet_gui.services.statistics_service import StatisticsService
from flet_gui.services.proxy_service import ProxyService
from flet_gui.views.statistics_view import create_statistics_view


class FletApp:
    """
    Main application class for the Steam Trading Bot GUI.

    Handles:
    - Page setup and theming
    - View management and navigation
    - Bot control (start/stop)
    - Data refresh
    """

    def __init__(self, page: ft.Page, use_real_data: bool = False):
        self.page = page
        self.state = AppState()
        self.event_bus = EventBus()
        self.use_real_data = use_real_data

        # Services (only initialized if using real data)
        self.db_service: Optional[DatabaseService] = None
        self.account_service: Optional[AccountService] = None
        self.bot_service: Optional[TradingBotService] = None
        self.scanner_service: Optional[ScannerService] = None
        self.config_service: Optional[ConfigService] = None
        self.statistics_service: Optional[StatisticsService] = None
        self.proxy_service: Optional[ProxyService] = None
        self.sales_service = None  # TM Sales Service
        self.auto_buy_service = None  # Auto Buy Service
        self.telegram_bot = None  # Telegram Bot
        self.telegram_thread: Optional[threading.Thread] = None  # Telegram bot thread

        if use_real_data:
            self.config_service = ConfigService(self.state)
            self.db_service = DatabaseService(self.state)
            self.account_service = AccountService(self.state)
            self.bot_service = TradingBotService(self.state, self.db_service, self.account_service, page=page)
            self.statistics_service = StatisticsService(self.state, self.db_service)
            self.proxy_service = ProxyService(self.state)

            # Initialize Telegram Bot (if configured)
            try:
                from src.telegram_bot import TelegramNotifier
                self.telegram_bot = TelegramNotifier()
                if not self.telegram_bot.is_configured:
                    self.telegram_bot = None
            except Exception as e:
                print(f"Failed to initialize Telegram bot: {e}")
                self.telegram_bot = None

            # Initialize Auto Buy Service (before scanner to provide excluded items)
            from flet_gui.services.auto_buy_service import AutoBuyService
            self.auto_buy_service = AutoBuyService(self.state, self.account_service, self.proxy_service)

            # Initialize Scanner Service (with auto_buy exclusions)
            self.scanner_service = ScannerService(self.state, self.auto_buy_service)

            # Initialize TM Sales Service (with Telegram bot)
            from flet_gui.services.tm_sales_service import TmSalesService
            self.sales_service = TmSalesService(self.state, self.account_service, self.db_service, self.telegram_bot)

            # Link services to Telegram bot for callbacks
            if self.telegram_bot:
                self.telegram_bot.set_sales_service(self.sales_service)

        # View factories
        self.view_factories = {
            0: create_dashboard_view,
            1: create_accounts_view,
            2: create_orders_view,
            3: create_inventory_view,
            4: create_tm_parser_view,
            5: create_tm_sales_view,
            6: create_auto_buy_view,
            7: create_history_view,
            8: create_statistics_view,
            9: create_settings_view,
            10: create_logs_view,
        }
        self.current_view_index = 0

        # Content container ref
        self.content_container = ft.Ref[ft.Container]()

        # Initialize
        self._setup_page()
        self._load_data()
        self._build_ui()

    def _setup_page(self):
        """Configure page settings and theme."""
        self.page.title = "Steamify"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = COLORS["bg_primary"]

        # Window settings
        self.page.window.min_width = 1200
        self.page.window.min_height = 700
        self.page.window.width = 1400
        self.page.window.height = 900

        # Обработчик закрытия приложения
        self.page.on_close = self._on_app_close

        # Иконка приложения
        import os
        import sys
        from pathlib import Path

        # Определяем корневую папку (для PyInstaller используем sys._MEIPASS)
        if getattr(sys, 'frozen', False):
            # Запущено из exe (PyInstaller)
            base_path = Path(sys._MEIPASS)
        else:
            # Запущено из Python
            base_path = Path(__file__).parent.parent

        # Пробуем сначала .ico (для Windows), потом .png
        icon_ico = base_path / "icon.ico"
        icon_png = base_path / "icon.png"

        icon_path = None
        if icon_ico.exists():
            icon_path = str(icon_ico)
        elif icon_png.exists():
            icon_path = str(icon_png)

        if icon_path:
            try:
                # Пробуем оба способа установки иконки
                self.page.window_icon = icon_path
                if hasattr(self.page, 'window') and hasattr(self.page.window, 'icon'):
                    self.page.window.icon = icon_path
                print(f"[INFO] Icon set: {icon_path}")
            except Exception as e:
                print(f"[WARNING] Failed to set icon: {e}")

        # Padding
        self.page.padding = 0
        self.page.spacing = 0

        # Custom theme (simplified for Flet 0.80+)
        self.page.theme = ft.Theme(
            color_scheme_seed=COLORS["accent_purple"],
        )

    def _load_data(self):
        """Load data (mock or real) for the application."""
        if self.use_real_data:
            self._load_real_data()
        else:
            self._load_mock_data()

    def _load_mock_data(self):
        """Load mock data for testing."""
        # Load config even for mock data (but don't load from database)
        if not self.config_service:
            self.config_service = ConfigService(self.state)

        # Load mock data (this will override any database data)
        mock_services = MockServices(self.state)
        mock_services.load_mock_data()

        self.state.add_log("[INFO] Mock data loaded for testing")
        self.state.add_log(f"[DEBUG] Loaded {len(self.state.active_orders)} orders")
        self.state.add_log(f"[DEBUG] Loaded {len(self.state.items_on_hold)} inventory items")
        self.state.add_log(f"[DEBUG] Loaded {len(self.state.profitable_items)} profitable items")

    def _load_real_data(self):
        """Load real data from database and account manager.

        NOTE: This is called during __init__, so it must be sync.
        Heavy DB loading is deferred to async via page.run_task() in _build_ui().
        """
        try:
            self.state.add_log("[INFO] Loading real data...")

            # Config is already loaded in __init__, just log it
            if self.config_service:
                self.state.add_log("[SUCCESS] Configuration loaded")

            # Load database data (sync during startup - fast enough for initial load)
            if self.db_service:
                self.db_service.load_all_data()
                self.state.add_log("[SUCCESS] Database data loaded")

            # Account data is loaded in AccountService.__init__
            if self.account_service:
                self.state.add_log("[SUCCESS] Account data loaded")

            self.state.add_log("[SUCCESS] All data loaded successfully")
        except Exception as e:
            self.state.add_log(f"[ERROR] Failed to load real data: {str(e)}")
            self.state.add_log("[INFO] Falling back to mock data...")
            self._load_mock_data()

    def _build_ui(self):
        """Build the main UI layout."""
        # Initial view (Dashboard) - pass page for reactive updates
        initial_view = self.view_factories[0](page=self.page)

        # Main layout
        self.page.add(
            # Header
            create_header(
                on_start=self._on_start_bot,
                on_stop=self._on_stop_bot,
                on_refresh=self._on_refresh,
                on_sync=self._on_sync_orders,
                page=self.page,
            ),

            # Main content area
            ft.Row(
                [
                    # Navigation rail
                    create_navigation(on_change=self._on_nav_change),

                    # Content area
                    ft.Container(
                        ref=self.content_container,
                        content=initial_view,
                        expand=True,
                        bgcolor=COLORS["bg_primary"],
                    ),
                ],
                expand=True,
                spacing=0,
            ),

            # Status bar
            create_status_bar(),
        )

        # Запускаем Telegram бота в отдельном потоке
        if self.telegram_bot and self.use_real_data:
            self.telegram_thread = threading.Thread(
                target=self._run_telegram_bot_thread,
                daemon=True
            )
            self.telegram_thread.start()

    def _run_telegram_bot_thread(self):
        """Запустить Telegram бота в отдельном потоке."""
        import asyncio
        try:
            # Создаём новый event loop для потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._start_telegram_bot())
        except Exception as e:
            print(f"Failed to run telegram bot thread: {e}")

    async def _start_telegram_bot(self):
        """Запустить Telegram бота и отправить уведомление о запуске."""
        try:
            # Отправляем уведомление о запуске
            from datetime import datetime
            startup_message = (
                "🚀 <b>Steamify Online</b>\n\n"
                f"⏰ Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"✅ Панель управления запущена"
            )
            await self.telegram_bot.send_message(startup_message)

            # Запускаем polling для обработки кнопок
            await self.telegram_bot.start_polling()
        except Exception as e:
            print(f"Failed to start telegram bot: {e}")

    def _on_app_close(self, e):
        """Обработчик закрытия приложения."""
        if self.telegram_bot and self.use_real_data:
            self.page.run_task(self._send_shutdown_notification)

    async def _send_shutdown_notification(self):
        """Отправить уведомление о закрытии приложения в Telegram."""
        try:
            from datetime import datetime
            shutdown_message = (
                "🔴 <b>Steamify Offline</b>\n\n"
                f"⏰ Время остановки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"❌ Панель управления остановлена"
            )
            await self.telegram_bot.send_message(shutdown_message)

            # Останавливаем polling
            await self.telegram_bot.stop()
        except Exception as e:
            print(f"Failed to send shutdown notification: {e}")

    def _on_nav_change(self, index: int):
        """Handle navigation tab change."""
        if index == self.current_view_index:
            return

        self.current_view_index = index

        # Create view
        view_factory = self.view_factories.get(index)
        if view_factory:
            if self.content_container.current:
                # Special handling for views that need services/page
                if index == 0:  # Dashboard view
                    self.content_container.current.content = view_factory(
                        page=self.page
                    )
                elif index == 1:  # Accounts view
                    self.content_container.current.content = view_factory(
                        account_service=self.account_service,
                        page=self.page
                    )
                elif index == 2:  # Orders view
                    self.content_container.current.content = view_factory(
                        page=self.page,
                        account_service=self.account_service,
                        db_service=self.db_service,
                        auto_buy_service=self.auto_buy_service
                    )
                elif index == 3:  # Inventory view
                    self.content_container.current.content = view_factory(
                        page=self.page,
                        db_service=self.db_service,
                        auto_buy_service=self.auto_buy_service
                    )
                elif index == 4:  # TM Parser view
                    self.content_container.current.content = view_factory(
                        scanner_service=self.scanner_service,
                        db_service=self.db_service,
                        account_service=self.account_service,
                        page=self.page
                    )
                elif index == 5:  # TM Sales view
                    self.content_container.current.content = view_factory(
                        sales_service=self.sales_service,
                        account_service=self.account_service,
                        db_service=self.db_service,
                        page=self.page
                    )
                elif index == 6:  # Auto Buy view
                    self.content_container.current.content = view_factory(
                        page=self.page,
                        auto_buy_service=self.auto_buy_service,
                        account_service=self.account_service
                    )
                elif index == 7:  # History view
                    self.content_container.current.content = view_factory(page=self.page)
                elif index == 8:  # Statistics view
                    self.content_container.current.content = view_factory(
                        statistics_service=self.statistics_service,
                        page=self.page
                    )
                elif index == 8:  # Settings view
                    self.content_container.current.content = view_factory(
                        config_service=self.config_service,
                        page=self.page
                    )
                elif index == 9:  # Logs view
                    self.content_container.current.content = view_factory(page=self.page)
                else:
                    self.content_container.current.content = view_factory()
                self.page.update()

        self.event_bus.emit(EventType.TAB_CHANGED, index)

    def _on_start_bot(self):
        """Handle start bot button click."""
        self.event_bus.emit(EventType.BOT_STARTED)

        if self.use_real_data and self.bot_service:
            # Use real trading bot
            if self.bot_service.start_bot():
                self.page.run_task(self.bot_service.run_bot_loop)
        else:
            # Use simulation
            self.state.add_log("[INFO] Starting bot simulation...")
            self.state.update_bot_status(True, "Running")
            self.page.run_task(self._run_bot_simulation)

    def _on_stop_bot(self):
        """Handle stop bot button click."""
        self.event_bus.emit(EventType.BOT_STOPPED)

        if self.use_real_data and self.bot_service:
            # Stop real trading bot
            self.bot_service.stop_bot()
        else:
            # Stop simulation
            self.state.add_log("[INFO] Stopping bot...")
            self.state.update_bot_status(False, "Stopped")

    def _on_sync_orders(self):
        """Handle sync orders button click."""
        if not self.use_real_data or not self.account_service or not self.db_service:
            self.state.add_log("[WARNING] Sync requires real data mode and services")
            return

        self.state.add_log("[INFO] Starting sync with Steam...")
        self.page.run_task(self._sync_orders_async)

    async def _sync_orders_async(self):
        """Async sync orders from Steam."""
        try:
            results = await self.account_service.sync_orders_from_steam(self.db_service)

            # Refresh all data from database (non-blocking)
            await self.db_service.load_all_data_async()

            # Explicitly refresh inventory to recalculate hold_time_remaining
            await self.db_service.refresh_inventory_async()

            # Log results
            self.state.add_log(
                f"[SUCCESS] Sync complete: "
                f"+{results['synced']} new, "
                f"{results['filled']} filled, "
                f"{results['cancelled']} cancelled"
            )

            if results['errors']:
                for err in results['errors']:
                    self.state.add_log(f"[WARNING] {err}")

            # Update UI
            self.page.update()

        except Exception as e:
            self.state.add_log(f"[ERROR] Sync failed: {str(e)}")

    def _on_refresh(self):
        """Handle refresh button click - dispatches to async."""
        self.state.add_log("[INFO] Refreshing data...")
        self.event_bus.emit(EventType.DATA_REFRESH_REQUESTED)

        # Use async refresh to avoid blocking GUI
        self.page.run_task(self._on_refresh_async)

    async def _on_refresh_async(self):
        """Async refresh data from database (non-blocking)."""
        import asyncio

        if self.use_real_data:
            try:
                if self.db_service:
                    # Refresh specific data based on current view
                    if self.current_view_index == 0:  # Dashboard
                        await self.db_service.load_all_data_async()
                    elif self.current_view_index == 2:  # Orders
                        await self.db_service.refresh_orders_async()
                    elif self.current_view_index == 3:  # Inventory
                        await self.db_service.refresh_inventory_async()
                    elif self.current_view_index == 5:  # History
                        await self.db_service.refresh_history_async()
                    else:
                        await self.db_service.load_all_data_async()

                if self.account_service and self.current_view_index == 1:  # Accounts
                    await asyncio.to_thread(self.account_service.load_accounts)

                self.state.add_log("[SUCCESS] Data refreshed from database")
            except Exception as e:
                self.state.add_log(f"[ERROR] Refresh failed: {str(e)}")

        # Reload current view (UI operations are instant, safe in async context)
        if self.content_container.current and self.current_view_index in self.view_factories:
            view_factory = self.view_factories[self.current_view_index]
            # Special handling for views that need services/page
            if self.current_view_index == 0:  # Dashboard view
                self.content_container.current.content = view_factory(page=self.page)
            elif self.current_view_index == 1:  # Accounts view
                self.content_container.current.content = view_factory(
                    account_service=self.account_service,
                    page=self.page
                )
            elif self.current_view_index == 2:  # Orders view
                self.content_container.current.content = view_factory(
                    page=self.page,
                    account_service=self.account_service,
                    db_service=self.db_service,
                    auto_buy_service=self.auto_buy_service
                )
            elif self.current_view_index == 3:  # Inventory view
                self.content_container.current.content = view_factory(
                    page=self.page,
                    db_service=self.db_service
                )
            elif self.current_view_index == 4:  # TM Parser view
                self.content_container.current.content = view_factory(
                    scanner_service=self.scanner_service,
                    db_service=self.db_service,
                    account_service=self.account_service,
                    page=self.page
                )
            elif self.current_view_index == 5:  # TM Sales view
                self.content_container.current.content = view_factory(
                    sales_service=self.sales_service,
                    account_service=self.account_service,
                    db_service=self.db_service,
                    page=self.page
                )
            elif self.current_view_index == 6:  # History view
                self.content_container.current.content = view_factory(page=self.page)
            elif self.current_view_index == 7:  # Statistics view
                self.content_container.current.content = view_factory(
                    statistics_service=self.statistics_service,
                    page=self.page
                )
            elif self.current_view_index == 8:  # Settings view
                self.content_container.current.content = view_factory(
                    config_service=self.config_service,
                    page=self.page
                )
            elif self.current_view_index == 9:  # Logs view
                self.content_container.current.content = view_factory(page=self.page)
            else:
                self.content_container.current.content = view_factory()
            self.page.update()

        if not self.use_real_data:
            self.state.add_log("[SUCCESS] View refreshed")

    async def _run_bot_simulation(self):
        """Run simulated bot cycle for demo."""
        import asyncio
        from flet_gui.services.mocks import simulate_bot_cycle

        while self.state.bot_state.running:
            await simulate_bot_cycle(self.state)
            self.page.update()

            # Wait before next cycle
            cycle_interval = self.state.config.get('cycle_interval_minutes', 1) * 60
            # For demo, use shorter interval
            await asyncio.sleep(min(30, cycle_interval))


def main(page: ft.Page):
    """Main entry point for Flet app."""
    # Real data by default, use --mock-data for testing
    use_real_data = "--mock-data" not in sys.argv
    app = FletApp(page, use_real_data=use_real_data)


if __name__ == "__main__":
    from pathlib import Path
    project_root = Path(__file__).parent.parent
    ft.run(main, assets_dir=str(project_root))
