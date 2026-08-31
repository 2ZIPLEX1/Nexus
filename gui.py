"""
GUI для Steam Trading Bot на CustomTkinter.

Функции:
- Dashboard с статистикой и графиками
- Управление аккаунтами
- Просмотр активных ордеров
- Логи в реальном времени
- Start/Stop бота
"""

import customtkinter as ctk
import threading
import time
import subprocess
import os
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
import json
import sys
from urllib.parse import quote

from src.logger import get_logger
from src.account_manager import AccountManager
from src.trading_bot import TradingBot
from src.database import trades_db
from src.currency_converter import currency_converter
from src.auto_scanner import AutoScanner
from src.proxy_manager import ProxyManager
from src.statistics import TradingStatistics

logger = get_logger(__name__)

# Настройки темы
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Современная цветовая палитра
COLORS = {
    "bg_primary": "#1a1a1a",      # Основной фон
    "bg_secondary": "#242424",    # Вторичный фон
    "bg_tertiary": "#2d2d2d",     # Третичный фон (карточки)
    "accent_green": "#10b981",    # Зеленый акцент (успех)
    "accent_red": "#ef4444",      # Красный акцент (ошибка)
    "accent_blue": "#3b82f6",     # Синий акцент (инфо)
    "accent_yellow": "#f59e0b",   # Желтый акцент (предупреждение)
    "accent_purple": "#8b5cf6",   # Фиолетовый акцент
    "text_primary": "#ffffff",    # Основной текст
    "text_secondary": "#9ca3af",  # Вторичный текст
    "border": "#3f3f46",          # Границы
}


class TradingBotGUI(ctk.CTk):
    """Главное окно GUI приложения."""

    def __init__(self):
        super().__init__()

        # Настройки окна
        self.title("Steam Trading Bot")
        self.geometry("1200x800")
        self.minsize(1000, 600)

        # Состояние бота
        self.bot_running = False
        self.bot_thread: Optional[threading.Thread] = None
        self.account_manager: Optional[AccountManager] = None

        # Scanner process
        self.scanner_process: Optional[subprocess.Popen] = None
        self.scanner_running = False
        self.scanner_monitor_thread: Optional[threading.Thread] = None

        # Словарь для хранения ссылок на balance labels аккаунтов
        self.account_balance_labels = {}

        # Состояние сортировки для TM Parser
        self.sort_by_profit = False  # False = по умолчанию (по дате), True = по профиту

        # Новые модули
        self.auto_scanner: Optional[AutoScanner] = None
        self.proxy_manager: Optional[ProxyManager] = None
        self.statistics: Optional[TradingStatistics] = None

        # AsyncRunner для работы с async Steam API
        from src.async_helper import get_async_runner
        self.async_runner = get_async_runner()
        logger.info("AsyncRunner initialized for GUI")

        # Настройки бота (загружаются из bot_config.json)
        self.bot_config = {
            'min_profit_pct': 5.0,
            'cycle_interval_minutes': 5,
            'bottm_db_path': 'data/main.db',
            'auto_refresh': True,
            'debug_mode': False,
            # Trading настройки (выставление ордеров)
            'trade_min_price': 100,
            'trade_max_price': 5000,
            # TM Parser настройки
            'scanner_min_price': 1000,
            'scanner_max_price': 10000,
            'scanner_min_profit': -5.0,
            'csgo_commission': 7.0,
            'min_sales_7d': 50,
            'proxy_file': 'proxies.txt',
            'requests_per_proxy': 50,  # Increased to avoid rotation during scan
            'scanner_max_items': 10,  # Reduced to avoid rate limits
            'scanner_delay': 7.0,  # Increased delay to avoid 429 errors
            'scanner_workers': 1,  # Reduced workers to avoid overwhelming proxies
            # Auto Scanner настройки
            'auto_scan_enabled': False,
            'auto_scan_interval': 30,  # минуты - интервал поиска новых
            'auto_scan_new_items': 10,  # количество новых предметов за раз
            'auto_rescan_interval': 60,  # минуты - интервал проверки актуальности
            # Proxy Manager настройки
            'proxy_max_requests': 15,
            'proxy_cooldown': 60,  # секунды
            'proxy_blacklist_duration': 30,  # минуты
        }

        # Создаем интерфейс
        self._create_ui()

        # Загружаем аккаунты и настройки
        self._load_accounts()
        self._load_bot_config()

        # Загружаем предметы из БД сразу при запуске
        self._refresh_profitable_items()

        # Обработка закрытия окна
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _create_ui(self):
        """Создать интерфейс."""
        # Верхняя панель с кнопками управления
        self._create_header()

        # Табы
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Создаем вкладки
        self.tab_dashboard = self.tabview.add("📊 Dashboard")
        self.tab_accounts = self.tabview.add("👤 Аккаунты")
        self.tab_orders = self.tabview.add("📋 Ордера")
        self.tab_inventory = self.tabview.add("📦 Инвентарь")
        self.tab_tm_parser = self.tabview.add("🔍 TM Parser")
        self.tab_history = self.tabview.add("📜 История")
        self.tab_settings = self.tabview.add("⚙️ Настройки")
        self.tab_logs = self.tabview.add("📝 Логи")

        # Наполняем вкладки
        self._create_dashboard_tab()
        self._create_accounts_tab()
        self._create_orders_tab()
        self._create_inventory_tab()
        self._create_tm_parser_tab()
        self._create_history_tab()
        self._create_settings_tab()
        self._create_logs_tab()

        # Статус бар внизу
        self._create_statusbar()

    def _create_header(self):
        """Создать верхнюю панель."""
        header_frame = ctk.CTkFrame(
            self,
            height=80,
            fg_color=COLORS["bg_secondary"],
            corner_radius=15
        )
        header_frame.pack(fill="x", padx=10, pady=10)

        # Левая часть - заголовок и статус
        left_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_frame.pack(side="left", padx=20, pady=15)

        # Заголовок
        title_label = ctk.CTkLabel(
            left_frame,
            text="🤖 Steam Trading Bot",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        title_label.pack(anchor="w")

        # Статус и время работы
        self.status_label = ctk.CTkLabel(
            left_frame,
            text="⏸️ Бот остановлен",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        self.status_label.pack(anchor="w", pady=(5, 0))

        # Кнопки управления
        btn_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        btn_frame.pack(side="right", padx=20)

        self.btn_start = ctk.CTkButton(
            btn_frame,
            text="▶️ Старт",
            command=self._start_bot,
            fg_color=COLORS["accent_green"],
            hover_color="#059669",
            width=130,
            height=45,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(
            btn_frame,
            text="⏸️ Стоп",
            command=self._stop_bot,
            fg_color=COLORS["accent_red"],
            hover_color="#dc2626",
            width=130,
            height=45,
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled"
        )
        self.btn_stop.pack(side="left", padx=5)

        self.btn_refresh = ctk.CTkButton(
            btn_frame,
            text="🔄 Обновить",
            command=self._refresh_data,
            fg_color=COLORS["accent_blue"],
            hover_color="#2563eb",
            width=130,
            height=45,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.btn_refresh.pack(side="left", padx=5)

    def _create_dashboard_tab(self):
        """Создать вкладку Dashboard с 3 панелями."""
        # Top panel - 40% высоты (статистика с выбором аккаунта)
        top_panel = ctk.CTkFrame(
            self.tab_dashboard,
            corner_radius=10,
            fg_color="#2B2D35",
            border_width=1,
            border_color="#3A3D45"
        )
        top_panel.pack(fill="both", expand=False, padx=10, pady=10)

        # Account selector в top panel
        account_selector_frame = ctk.CTkFrame(top_panel, fg_color="transparent")
        account_selector_frame.pack(fill="x", padx=20, pady=(15, 10))

        ctk.CTkLabel(
            account_selector_frame,
            text="Показать метрики для:",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=(0, 10))

        # Получаем список аккаунтов
        account_names = ["Все аккаунты"]
        if self.account_manager and len(self.account_manager.accounts) > 0:
            account_names.extend([acc.name for acc in self.account_manager.accounts])

        self.account_selector = ctk.CTkComboBox(
            account_selector_frame,
            values=account_names,
            command=self._on_account_selected,
            width=200,
            corner_radius=8
        )
        self.account_selector.set("Все аккаунты")
        self.account_selector.pack(side="left")

        # Карточки статистики в top panel
        stats_cards_frame = ctk.CTkFrame(top_panel, fg_color="transparent")
        stats_cards_frame.pack(fill="x", padx=15, pady=(10, 15))

        self.stats_cards = {}
        stats_data = [
            ("💰 Баланс Steam", "0.00 RUB", "balance_steam"),
            ("💎 Баланс CSGO.TM", "0.00 RUB", "balance_csgotm"),
            ("📋 Активных ордеров", "0", "active_orders"),
            ("📦 На холде", "0", "on_hold"),
            ("💵 Прибыль", "$0.00", "profit"),
            ("✅ Продано", "0", "sold_items"),
        ]

        for i, (title, value, key) in enumerate(stats_data):
            card = self._create_stat_card(stats_cards_frame, title, value, key)
            card.grid(row=i//3, column=i%3, padx=10, pady=10, sticky="ew")
            self.stats_cards[key] = card

        stats_cards_frame.grid_columnconfigure(0, weight=1)
        stats_cards_frame.grid_columnconfigure(1, weight=1)
        stats_cards_frame.grid_columnconfigure(2, weight=1)

        # Bottom container - 60% высоты
        bottom_container = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        bottom_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Configure grid weights (50/50 split)
        bottom_container.grid_columnconfigure(0, weight=1)
        bottom_container.grid_columnconfigure(1, weight=1)
        bottom_container.grid_rowconfigure(0, weight=1)

        # Left panel - Последние сделки
        bottom_left = ctk.CTkFrame(
            bottom_container,
            corner_radius=10,
            fg_color="#2B2D35",
            border_width=1,
            border_color="#3A3D45"
        )
        bottom_left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._create_recent_trades_table(bottom_left)

        # Right panel - Активные ордера
        bottom_right = ctk.CTkFrame(
            bottom_container,
            corner_radius=10,
            fg_color="#2B2D35",
            border_width=1,
            border_color="#3A3D45"
        )
        bottom_right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._create_active_orders_table(bottom_right)

    def _create_stat_card(self, parent, title: str, value: str, key: str):
        """
        Создать карточку со статистикой (улучшенный дизайн).

        Args:
            parent: Родительский контейнер
            title: Заголовок карточки
            value: Значение
            key: Ключ для идентификации карточки
        """
        card_frame = ctk.CTkFrame(
            parent,
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["bg_tertiary"]
        )

        title_label = ctk.CTkLabel(
            card_frame,
            text=title,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        )
        title_label.pack(padx=15, pady=(15, 5), anchor="w")

        value_label = ctk.CTkLabel(
            card_frame,
            text=value,
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        value_label.pack(padx=15, pady=(0, 15), anchor="w")

        # Сохраняем ссылку на label для обновления
        card_frame.value_label = value_label

        return card_frame

    def _on_account_selected(self, account_name: str):
        """Callback при выборе аккаунта из dropdown."""
        self._update_dashboard_stats(account_name)
        self._refresh_recent_trades()
        self._refresh_active_orders_table()

    def _format_price_with_conversion(self, price_rub: float, show_conversion: bool = True) -> str:
        """
        Форматирует цену с конвертацией в валюту аккаунта.

        Args:
            price_rub: Цена в рублях
            show_conversion: Показывать ли конвертацию

        Returns:
            Строка: "1000.00 ₽" или "1000.00 ₽ (~10.50 EUR)"
        """
        if not show_conversion or price_rub == 0:
            return f"{price_rub:.2f} ₽"

        # Получить валюту первого активного аккаунта
        account_currency = 'RUB'
        if self.account_manager and len(self.account_manager.accounts) > 0:
            account = self.account_manager.accounts[0]
            account_currency = getattr(account.config, 'currency', 'RUB')

        # Если аккаунт в RUB - не показывать конвертацию
        if account_currency == 'RUB':
            return f"{price_rub:.2f} ₽"

        # Конвертировать через currency_rates
        try:
            from src.currency_rates import convert_rub_to_currency

            # Получить код валюты Steam (EUR = 3, USD = 1, RUB = 5)
            currency_codes = {'EUR': 3, 'USD': 1, 'RUB': 5}
            currency_code = currency_codes.get(account_currency, 5)

            converted = convert_rub_to_currency(price_rub, currency_code)
            return f"{price_rub:.2f} ₽ (~{converted:.2f} {account_currency})"
        except Exception as e:
            logger.warning(f"Failed to convert currency: {e}")
            return f"{price_rub:.2f} ₽"

    def _create_recent_trades_table(self, parent_frame):
        """Создать таблицу последних сделок."""
        # Header
        header_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header_frame,
            text="📈 Последние сделки",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")

        # Scrollable container
        self.trades_scrollable = ctk.CTkScrollableFrame(
            parent_frame,
            fg_color="transparent"
        )
        self.trades_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Заголовок таблицы
        header = ctk.CTkFrame(self.trades_scrollable, fg_color=COLORS["bg_tertiary"], corner_radius=6)
        header.pack(fill="x", pady=(0, 5))

        headers = ["Дата", "Предмет", "Покупка", "Продажа", "Профит"]
        widths = [140, 0, 90, 90, 90]  # 0 = expand для предмета

        header_container = ctk.CTkFrame(header, fg_color="transparent")
        header_container.pack(fill="x", padx=10, pady=6)

        for i, (text, width) in enumerate(zip(headers, widths)):
            if width == 0:
                # Расширяемая колонка для названия предмета
                label = ctk.CTkLabel(
                    header_container,
                    text=text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    anchor="w"
                )
                label.pack(side="left", fill="x", expand=True, padx=5)
            else:
                label = ctk.CTkLabel(
                    header_container,
                    text=text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    width=width,
                    anchor="e" if i >= 2 else "w"
                )
                label.pack(side="left", padx=5)

    def _create_active_orders_table(self, parent_frame):
        """Создать таблицу активных ордеров."""
        # Header
        header_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header_frame,
            text="📋 Активные ордера",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")

        # Scrollable container
        self.orders_scrollable = ctk.CTkScrollableFrame(
            parent_frame,
            fg_color="transparent"
        )
        self.orders_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Заголовок таблицы
        header = ctk.CTkFrame(self.orders_scrollable, fg_color=COLORS["bg_tertiary"], corner_radius=6)
        header.pack(fill="x", pady=(0, 5))

        headers = ["Аккаунт", "Предмет", "Цена", "Создан"]
        widths = [120, 0, 90, 140]  # 0 = expand для предмета

        header_container = ctk.CTkFrame(header, fg_color="transparent")
        header_container.pack(fill="x", padx=10, pady=6)

        for i, (text, width) in enumerate(zip(headers, widths)):
            if width == 0:
                # Расширяемая колонка для названия предмета
                label = ctk.CTkLabel(
                    header_container,
                    text=text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    anchor="w"
                )
                label.pack(side="left", fill="x", expand=True, padx=5)
            else:
                label = ctk.CTkLabel(
                    header_container,
                    text=text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    width=width,
                    anchor="e" if i >= 2 else "w"
                )
                label.pack(side="left", padx=5)

    def _refresh_recent_trades(self):
        """Обновить таблицу последних сделок."""
        if not hasattr(self, 'trades_scrollable'):
            return

        # Очистить старые строки (кроме заголовка)
        for widget in self.trades_scrollable.winfo_children()[1:]:
            widget.destroy()

        try:
            # Получить данные из БД
            recent_trades = trades_db.get_recent_sales(limit=10)

            # Фильтр по аккаунту если выбран конкретный
            selected_account = self.account_selector.get() if hasattr(self, 'account_selector') else "Все аккаунты"
            if selected_account != "Все аккаунты":
                recent_trades = [t for t in recent_trades if t.get('account_name') == selected_account]

            for trade in recent_trades:
                row_frame = ctk.CTkFrame(self.trades_scrollable, fg_color=COLORS["bg_tertiary"], corner_radius=4)
                row_frame.pack(fill="x", pady=2)

                row_container = ctk.CTkFrame(row_frame, fg_color="transparent")
                row_container.pack(fill="x", padx=10, pady=6)

                # Данные строки
                date = trade.get('sale_date', 'N/A')
                if date and len(date) > 16:
                    date = date[:16]  # Обрезаем до "YYYY-MM-DD HH:MM"
                elif date and len(date) > 10:
                    date = date[:10]  # Только дата
                item = trade.get('item_name', 'N/A')
                # Обрезаем длинные названия
                if len(item) > 50:
                    item = item[:47] + "..."
                buy_price = trade.get('purchase_price', 0) or 0
                sell_price = trade.get('sale_price', 0) or 0
                profit = sell_price - buy_price

                # Цвет профита
                profit_color = COLORS["accent_green"] if profit >= 0 else COLORS["accent_red"]

                # Дата
                ctk.CTkLabel(
                    row_container,
                    text=str(date),
                    width=140,
                    anchor="w",
                    font=ctk.CTkFont(size=10)
                ).pack(side="left", padx=5)

                # Предмет (расширяемая колонка)
                item_label = ctk.CTkLabel(
                    row_container,
                    text=str(item),
                    anchor="w",
                    font=ctk.CTkFont(size=10)
                )
                item_label.pack(side="left", fill="x", expand=True, padx=5)

                # Покупка
                ctk.CTkLabel(
                    row_container,
                    text=f"{buy_price:.0f}",
                    width=90,
                    anchor="e",
                    font=ctk.CTkFont(size=10)
                ).pack(side="left", padx=5)

                # Продажа
                ctk.CTkLabel(
                    row_container,
                    text=f"{sell_price:.0f}",
                    width=90,
                    anchor="e",
                    font=ctk.CTkFont(size=10)
                ).pack(side="left", padx=5)

                # Профит
                ctk.CTkLabel(
                    row_container,
                    text=f"{profit:+.0f}",
                    text_color=profit_color,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    width=90,
                    anchor="e"
                ).pack(side="left", padx=5)

        except Exception as e:
            logger.error(f"Error refreshing recent trades: {e}", exc_info=True)

    def _refresh_active_orders_table(self):
        """Обновить таблицу активных ордеров."""
        if not hasattr(self, 'orders_scrollable'):
            return

        # Очистить все
        for widget in self.orders_scrollable.winfo_children():
            widget.destroy()

        try:
            # Получить данные из БД
            active_orders = trades_db.get_all_active_orders()

            # Фильтр по аккаунту если выбран конкретный
            selected_account = self.account_selector.get() if hasattr(self, 'account_selector') else "Все аккаунты"
            if selected_account != "Все аккаунты":
                active_orders = [o for o in active_orders if o.get('account_name') == selected_account]

            # Обновляем счетчик активных ордеров в dashboard
            if hasattr(self, 'stats_cards') and 'active_orders' in self.stats_cards:
                if selected_account == "Все аккаунты":
                    total_count = trades_db.get_active_orders_count()
                else:
                    total_count = len([o for o in trades_db.get_all_active_orders() if o.get('account_name') == selected_account])
                self.stats_cards['active_orders'].value_label.configure(text=str(total_count))

            if not active_orders:
                ctk.CTkLabel(
                    self.orders_scrollable,
                    text="Нет активных ордеров",
                    font=ctk.CTkFont(size=14)
                ).pack(pady=20)
                return

            # Фиксированные ширины колонок
            col_widths = [130, 550, 120, 180]

            # Создаем заголовок
            header = ctk.CTkFrame(self.orders_scrollable, fg_color=COLORS["bg_secondary"])
            header.pack(fill="x", pady=(0, 5))

            headers = [
                ("Аккаунт", col_widths[0]),
                ("Предмет", col_widths[1]),
                ("Цена ₽", col_widths[2]),
                ("Дата создания", col_widths[3])
            ]
            for text, width in headers:
                ctk.CTkLabel(
                    header,
                    text=text,
                    width=width,
                    anchor="w",
                    font=ctk.CTkFont(size=13, weight="bold")
                ).pack(side="left", padx=8, pady=8)

            # Показать все ордера (без лимита 10)
            for order in active_orders:
                row_frame = ctk.CTkFrame(self.orders_scrollable, fg_color=COLORS["bg_tertiary"], corner_radius=4)
                row_frame.pack(fill="x", pady=2)

                # Данные строки
                account = order.get('account_name', 'N/A')
                item = order.get('item_name', 'N/A')
                # Обрезаем длинные названия
                if len(item) > 73:
                    item = item[:70] + "..."
                price = order.get('order_price', 0) or 0
                date = order.get('created_at', 'N/A')
                if date and len(date) > 16:
                    date = date[:16]

                # Аккаунт
                ctk.CTkLabel(
                    row_frame,
                    text=str(account),
                    width=col_widths[0],
                    anchor="w",
                    font=ctk.CTkFont(size=12)
                ).pack(side="left", padx=8, pady=6)

                # Предмет
                ctk.CTkLabel(
                    row_frame,
                    text=str(item),
                    width=col_widths[1],
                    anchor="w",
                    font=ctk.CTkFont(size=12),
                    text_color="#3498db"
                ).pack(side="left", padx=8, pady=6)

                # Цена
                ctk.CTkLabel(
                    row_frame,
                    text=f"{price:.2f}",
                    width=col_widths[2],
                    anchor="w",
                    font=ctk.CTkFont(size=12)
                ).pack(side="left", padx=8, pady=6)

                # Дата создания
                ctk.CTkLabel(
                    row_frame,
                    text=str(date),
                    width=col_widths[3],
                    anchor="w",
                    font=ctk.CTkFont(size=12)
                ).pack(side="left", padx=8, pady=6)

        except Exception as e:
            logger.error(f"Error refreshing active orders: {e}", exc_info=True)

    def _sync_orders_from_steam(self):
        """Синхронизировать ордера и инвентарь со Steam без запуска торгового цикла."""
        from src.async_helper import run_async_in_gui

        async def _sync():
            results = {'synced': 0, 'filled': 0, 'cancelled': 0, 'errors': []}

            if not self.account_manager:
                return results

            for account in self.account_manager.get_enabled_accounts():
                if not account.is_logged_in():
                    results['errors'].append(f"{account.name}: не авторизован")
                    continue

                try:
                    self._log(f"🔄 [{account.name}] Синхронизация ордеров со Steam...")

                    # Получаем активные ордера из Steam
                    steam_orders = await account.steam_client.get_active_buy_orders()
                    steam_order_ids = {order['order_id'] for order in steam_orders}

                    self._log(f"[{account.name}] Найдено {len(steam_orders)} активных ордеров в Steam")

                    # Синхронизируем новые ордера в БД
                    for order in steam_orders:
                        existing = trades_db.get_order_by_id(order['order_id'])
                        if not existing:
                            trades_db.add_order(
                                account_name=account.name,
                                item_name=order['market_hash_name'],
                                market_hash_name=order['market_hash_name'],
                                order_id=order['order_id'],
                                order_price=order['price'],
                                quantity=order['quantity'],
                                expected_sell_price=None,
                            )
                            results['synced'] += 1
                            self._log(f"[{account.name}] 📥 Добавлен ордер: {order['market_hash_name']}")

                    # Проверяем ордера из БД - исполнены или отменены
                    db_orders = [o for o in trades_db.get_active_orders() if o['account_name'] == account.name]

                    # Ордера, которых нет в Steam
                    missing_orders = [
                        o for o in db_orders
                        if str(o['order_id']) not in steam_order_ids
                    ]

                    # Загружаем инвентарь ОДИН раз если есть пропавшие ордера
                    inventory_counts = {}
                    if missing_orders:
                        inventory = await account.steam_client.get_inventory()
                        if inventory:
                            for item in inventory:
                                name = item.market_hash_name
                                inventory_counts[name] = inventory_counts.get(name, 0) + 1

                    # Учитываем УЖЕ СУЩЕСТВУЮЩИЕ purchased_items для этого аккаунта
                    existing_purchased = trades_db.get_purchased_items(account_name=account.name)
                    matched_counts = {}
                    for item in existing_purchased:
                        name = item.get('market_hash_name', '')
                        if name:
                            matched_counts[name] = matched_counts.get(name, 0) + 1

                    for order in missing_orders:
                        order_id = str(order['order_id'])
                        market_hash_name = order.get('market_hash_name', '')

                        available_count = inventory_counts.get(market_hash_name, 0)
                        matched_count = matched_counts.get(market_hash_name, 0)

                        if market_hash_name and available_count > matched_count:
                            trades_db.update_order_status(order_id, 'filled')
                            # Добавляем в purchased_items
                            trades_db.add_purchased_item(
                                account_name=account.name,
                                item_name=order['item_name'],
                                market_hash_name=market_hash_name,
                                purchase_price=order['order_price'],
                                expected_sell_price=order.get('expected_sell_price'),
                                order_id=order_id,
                            )
                            results['filled'] += 1
                            matched_counts[market_hash_name] = matched_count + 1
                            self._log(f"[{account.name}] ✅ Исполнен: {order['item_name']}")
                        else:
                            trades_db.update_order_status(order_id, 'cancelled')
                            results['cancelled'] += 1
                            self._log(f"[{account.name}] ❌ Отменён: {order['item_name']}")

                except Exception as e:
                    results['errors'].append(f"{account.name}: {str(e)}")
                    self._log(f"[{account.name}] ⚠️ Ошибка: {e}")

            return results

        try:
            self._log("🔄 Запуск синхронизации со Steam...")
            results = run_async_in_gui(_sync(), timeout=60)

            # Обновляем таблицы
            self._refresh_active_orders_table()
            self._refresh_inventory_list()

            self._log(
                f"✅ Синхронизация завершена: "
                f"+{results['synced']} новых, "
                f"{results['filled']} исполнено, "
                f"{results['cancelled']} отменено"
            )

            if results['errors']:
                for err in results['errors']:
                    self._log(f"⚠️ {err}")

        except Exception as e:
            self._log(f"❌ Ошибка синхронизации: {e}")
            logger.error(f"Sync error: {e}", exc_info=True)

    def _create_accounts_tab(self):
        """Создать вкладку с аккаунтами."""
        # Верхняя панель
        header = ctk.CTkFrame(self.tab_accounts)
        header.pack(fill="x", padx=10, pady=10)

        label = ctk.CTkLabel(
            header,
            text="👤 Управление аккаунтами",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        label.pack(side="left", padx=10)

        # Кнопка "Определить валюту для всех"
        btn_detect_all = ctk.CTkButton(
            header,
            text="🔍 Определить валюту (все)",
            command=self._detect_all_currencies,
            width=200,
            fg_color=COLORS["accent_purple"],
            hover_color="#7c3aed"
        )
        btn_detect_all.pack(side="right", padx=5)

        btn_add = ctk.CTkButton(
            header,
            text="➕ Добавить",
            command=self._add_account,
            width=100
        )
        btn_add.pack(side="right", padx=5)

        # Список аккаунтов
        self.accounts_scrollable = ctk.CTkScrollableFrame(self.tab_accounts)
        self.accounts_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _create_orders_tab(self):
        """Создать вкладку с ордерами."""
        # Заголовок с кнопками
        header_frame = ctk.CTkFrame(self.tab_orders)
        header_frame.pack(fill="x", padx=10, pady=10)

        label = ctk.CTkLabel(
            header_frame,
            text="📋 Активные ордера",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        label.pack(side="left", padx=10)

        # Кнопка синхронизации ордеров со Steam
        sync_orders_btn = ctk.CTkButton(
            header_frame,
            text="🔄 Синхронизировать со Steam",
            command=self._sync_orders_from_steam,
            width=200,
            height=35,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS['accent_blue'],
            hover_color="#2563eb"
        )
        sync_orders_btn.pack(side="right", padx=5)

        # Таблица ордеров
        self.orders_scrollable = ctk.CTkScrollableFrame(self.tab_orders)
        self.orders_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _create_inventory_tab(self):
        """Создать вкладку с инвентарем."""
        # Заголовок с фильтрами
        header_frame = ctk.CTkFrame(self.tab_inventory)
        header_frame.pack(fill="x", padx=10, pady=10)

        label = ctk.CTkLabel(
            header_frame,
            text="📦 Предметы на холде",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        label.pack(side="left", padx=10)

        # Кнопка обновления цен
        refresh_prices_btn = ctk.CTkButton(
            header_frame,
            text="🔄 Обновить цены",
            command=self._refresh_item_prices,
            width=150,
            height=35,
            font=ctk.CTkFont(size=13)
        )
        refresh_prices_btn.pack(side="right", padx=5)

        # Фильтр по аккаунту
        filter_frame = ctk.CTkFrame(self.tab_inventory)
        filter_frame.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(
            filter_frame,
            text="Фильтр по аккаунту:",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=10)

        # Получаем список аккаунтов
        account_names = ["Все аккаунты"]
        try:
            from src.account_manager import account_manager
            if hasattr(account_manager, 'accounts'):
                account_names.extend([acc.name for acc in account_manager.accounts.values()])
        except Exception:
            pass

        self.inventory_account_filter = ctk.CTkComboBox(
            filter_frame,
            values=account_names,
            command=lambda _: self._refresh_inventory_list(),
            width=200,
            font=ctk.CTkFont(size=13)
        )
        self.inventory_account_filter.pack(side="left", padx=5)
        self.inventory_account_filter.set("Все аккаунты")

        # Таблица предметов
        self.inventory_scrollable = ctk.CTkScrollableFrame(self.tab_inventory)
        self.inventory_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _create_tm_parser_tab(self):
        """Создать вкладку TM Parser с выгодными предметами."""
        # Заголовок с информацией
        header = ctk.CTkFrame(self.tab_tm_parser)
        header.pack(fill="x", padx=10, pady=10)

        label = ctk.CTkLabel(
            header,
            text="🔍 Выгодные предметы (TM Parser)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        label.pack(side="left", padx=10)

        # Кнопка запуска сканирования
        self.scan_btn = ctk.CTkButton(
            header,
            text="🔄 Запустить сканирование",
            command=self._start_scanner,
            width=200,
            height=38,
            font=ctk.CTkFont(size=13)
        )
        self.scan_btn.pack(side="right", padx=5)

        # Кнопка пересканирования всех
        self.rescan_all_btn = ctk.CTkButton(
            header,
            text="🔁 Пересканировать все",
            command=self._rescan_all_items,
            width=180,
            height=38,
            fg_color=COLORS["accent_yellow"],
            hover_color="#d97706",
            font=ctk.CTkFont(size=13)
        )
        self.rescan_all_btn.pack(side="right", padx=5)

        # Кнопка поиска новых
        self.scan_new_btn = ctk.CTkButton(
            header,
            text="⭐ Искать новые",
            command=self._scan_new_items,
            width=150,
            height=38,
            fg_color=COLORS["accent_green"],
            hover_color="#059669",
            font=ctk.CTkFont(size=13)
        )
        self.scan_new_btn.pack(side="right", padx=5)

        # Статус сканирования
        self.scanner_status_label = ctk.CTkLabel(
            header,
            text="Статус: не запущено",
            text_color="gray",
            font=ctk.CTkFont(size=13)
        )
        self.scanner_status_label.pack(side="right", padx=10)

        # Вторая строка с фильтром
        filter_frame = ctk.CTkFrame(self.tab_tm_parser)
        filter_frame.pack(fill="x", padx=10, pady=(0, 10))

        # Чекбокс для включения/выключения фильтра
        self.profit_filter_enabled_var = ctk.BooleanVar(value=False)
        profit_filter_checkbox = ctk.CTkCheckBox(
            filter_frame,
            text="Фильтр по профиту:",
            variable=self.profit_filter_enabled_var,
            command=self._on_profit_filter_toggle,
            font=ctk.CTkFont(size=13)
        )
        profit_filter_checkbox.pack(side="left", padx=(10, 5))

        self.parser_min_profit_entry = ctk.CTkEntry(
            filter_frame,
            width=100,
            height=35,
            placeholder_text="-5.0",
            font=ctk.CTkFont(size=13),
            state="disabled"  # По умолчанию выключен
        )
        self.parser_min_profit_entry.pack(side="left", padx=5)
        self.parser_min_profit_entry.insert(0, str(self.bot_config.get('scanner_min_profit', -5.0)))

        apply_filter_btn = ctk.CTkButton(
            filter_frame,
            text="Применить фильтр",
            command=self._apply_profit_filter,
            width=150,
            height=35,
            fg_color=COLORS["accent_blue"],
            hover_color="#2563eb",
            font=ctk.CTkFont(size=13)
        )
        apply_filter_btn.pack(side="left", padx=5)

        items_count_label = ctk.CTkLabel(
            filter_frame,
            text="",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        )
        items_count_label.pack(side="left", padx=10)
        self.parser_items_count_label = items_count_label

        # Кнопка Auto Scanner
        self.auto_scan_toggle_btn = ctk.CTkButton(
            filter_frame,
            text="⏰ Auto Scan: OFF",
            command=self._toggle_auto_scan,
            width=160,
            height=35,
            fg_color=COLORS["text_secondary"],
            hover_color="#6b7280",
            font=ctk.CTkFont(size=13)
        )
        self.auto_scan_toggle_btn.pack(side="right", padx=5)

        # Кнопка Statistics
        stats_btn = ctk.CTkButton(
            filter_frame,
            text="📊 Статистика",
            command=self._show_statistics_window,
            width=130,
            height=35,
            fg_color=COLORS["accent_purple"],
            hover_color="#7c3aed",
            font=ctk.CTkFont(size=13)
        )
        stats_btn.pack(side="right", padx=5)

        # Кнопка Export
        export_btn = ctk.CTkButton(
            filter_frame,
            text="📤 Экспорт",
            command=self._export_data,
            width=110,
            height=35,
            fg_color=COLORS["accent_yellow"],
            hover_color="#d97706",
            font=ctk.CTkFont(size=13)
        )
        export_btn.pack(side="right", padx=5)

        # Таблица выгодных предметов
        self.parser_scrollable = ctk.CTkScrollableFrame(self.tab_tm_parser)
        self.parser_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _create_history_tab(self):
        """Создать вкладку истории операций."""
        # Заголовок
        header_frame = ctk.CTkFrame(self.tab_history)
        header_frame.pack(fill="x", padx=10, pady=10)

        header = ctk.CTkLabel(
            header_frame,
            text="История операций",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        header.pack(side="left", padx=10)

        # Кнопка обновления
        refresh_btn = ctk.CTkButton(
            header_frame,
            text="Обновить",
            command=self._refresh_history,
            width=120,
            height=32
        )
        refresh_btn.pack(side="right", padx=5)

        # Фильтры
        filter_frame = ctk.CTkFrame(self.tab_history)
        filter_frame.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(filter_frame, text="Тип:", font=ctk.CTkFont(size=13)).pack(side="left", padx=10)

        self.history_type_var = ctk.StringVar(value="all")
        type_options = ctk.CTkOptionMenu(
            filter_frame,
            values=["all", "purchased", "sold", "orders"],
            variable=self.history_type_var,
            width=120,
            command=lambda _: self._refresh_history()
        )
        type_options.pack(side="left", padx=5)

        ctk.CTkLabel(filter_frame, text="Период:", font=ctk.CTkFont(size=13)).pack(side="left", padx=10)

        self.history_days_var = ctk.StringVar(value="7")
        days_options = ctk.CTkOptionMenu(
            filter_frame,
            values=["7", "14", "30", "60", "90", "365"],
            variable=self.history_days_var,
            width=100,
            command=lambda _: self._refresh_history()
        )
        days_options.pack(side="left", padx=5)

        ctk.CTkLabel(filter_frame, text="дней", font=ctk.CTkFont(size=13)).pack(side="left")

        # Таблица истории
        self.history_scrollable = ctk.CTkScrollableFrame(self.tab_history)
        self.history_scrollable.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Загружаем историю
        self._refresh_history()

    def _refresh_history(self):
        """Обновить историю операций."""
        # Очищаем
        for widget in self.history_scrollable.winfo_children():
            widget.destroy()

        history_type = self.history_type_var.get()
        days = int(self.history_days_var.get())

        try:
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=days)

            items = []

            if history_type in ["all", "purchased"]:
                # Купленные предметы
                ready = trades_db.get_items_ready_to_sell()
                on_hold = trades_db.get_items_on_hold()
                for item in ready + on_hold:
                    items.append({
                        'type': 'purchased',
                        'date': item.get('purchased_at', ''),
                        'item_name': item.get('item_name', 'N/A'),
                        'price': item.get('price', 0),
                        'status': item.get('status', 'N/A')
                    })

            if history_type in ["all", "sold"]:
                # Проданные предметы
                sold = trades_db.get_recent_sales(limit=1000)
                for item in sold:
                    items.append({
                        'type': 'sold',
                        'date': item.get('sold_at', ''),
                        'item_name': item.get('item_name', 'N/A'),
                        'price': item.get('sale_price', 0),
                        'profit': item.get('profit', 0),
                        'status': 'sold'
                    })

            if history_type in ["all", "orders"]:
                # Активные ордера
                orders = trades_db.get_active_orders()
                for order in orders:
                    items.append({
                        'type': 'order',
                        'date': order.get('created_at', ''),
                        'item_name': order.get('item_name', 'N/A'),
                        'price': order.get('order_price', 0),  # Исправлено: order_price вместо price
                        'status': order.get('status', 'N/A')
                    })

            # Сортируем по дате
            items.sort(key=lambda x: x['date'], reverse=True)

            # Отображаем
            if not items:
                no_data_label = ctk.CTkLabel(
                    self.history_scrollable,
                    text="Нет данных для отображения",
                    font=ctk.CTkFont(size=14),
                    text_color="gray"
                )
                no_data_label.pack(pady=50)
            else:
                # Заголовок таблицы
                header_frame = ctk.CTkFrame(self.history_scrollable)
                header_frame.pack(fill="x", padx=5, pady=5)

                ctk.CTkLabel(header_frame, text="Дата", width=150, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
                ctk.CTkLabel(header_frame, text="Тип", width=100, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
                ctk.CTkLabel(header_frame, text="Предмет", width=300, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
                ctk.CTkLabel(header_frame, text="Цена", width=100, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
                ctk.CTkLabel(header_frame, text="Статус/Профит", width=150, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

                # Строки данных
                for item in items[:100]:  # Первые 100
                    row_frame = ctk.CTkFrame(self.history_scrollable)
                    row_frame.pack(fill="x", padx=5, pady=2)

                    # Цвет и текст по типу
                    if item['type'] == 'purchased':
                        fg_color = COLORS["accent_blue"]
                        type_text = "Куплено"
                    elif item['type'] == 'sold':
                        fg_color = COLORS["accent_green"]
                        type_text = "Продано"
                    else:
                        fg_color = COLORS["text_secondary"]
                        type_text = "Ордер"

                    date_str = item['date'][:16] if item['date'] else 'N/A'
                    ctk.CTkLabel(row_frame, text=date_str, width=150).pack(side="left", padx=5)
                    ctk.CTkLabel(row_frame, text=type_text, width=100, fg_color=fg_color).pack(side="left", padx=5)
                    ctk.CTkLabel(row_frame, text=item['item_name'][:40], width=300).pack(side="left", padx=5)
                    ctk.CTkLabel(row_frame, text=f"{item['price']:.2f} ₽", width=100).pack(side="left", padx=5)

                    status_text = item['status']
                    if item['type'] == 'sold' and 'profit' in item:
                        status_text = f"+{item['profit']:.2f} ₽"

                    ctk.CTkLabel(row_frame, text=status_text, width=150).pack(side="left", padx=5)

                total_label = ctk.CTkLabel(
                    self.history_scrollable,
                    text=f"Показано: {min(len(items), 100)}/{len(items)}",
                    font=ctk.CTkFont(size=12),
                    text_color="gray"
                )
                total_label.pack(pady=10)

        except Exception as e:
            logger.error(f"Error refreshing history: {e}", exc_info=True)
            error_label = ctk.CTkLabel(
                self.history_scrollable,
                text=f"Ошибка загрузки истории: {e}",
                font=ctk.CTkFont(size=14),
                text_color="red"
            )
            error_label.pack(pady=50)

    def _create_settings_section(self, parent, title: str, icon: str = ""):
        """
        Создать секцию настроек с красивым оформлением.

        Args:
            parent: Родительский контейнер
            title: Заголовок секции
            icon: Emoji иконка

        Returns:
            CTkFrame для добавления настроек
        """
        # Контейнер секции
        section_frame = ctk.CTkFrame(
            parent,
            corner_radius=12,
            border_width=1,
            border_color="#3A3D45",
            fg_color="#2B2D35"
        )
        section_frame.pack(fill="x", padx=10, pady=10)

        # Заголовок секции
        header_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))

        # Цветной индикатор слева
        indicator = ctk.CTkFrame(
            header_frame,
            fg_color="#3498DB",
            width=4,
            height=24,
            corner_radius=2
        )
        indicator.pack(side="left", padx=(0, 10))

        # Заголовок
        ctk.CTkLabel(
            header_frame,
            text=f"{icon} {title}",
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(side="left")

        # Контейнер для полей
        content_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        content_frame.pack(fill="x", padx=15, pady=(0, 15))

        return content_frame

    def _create_setting_field(self, parent, label: str, entry_var: str, placeholder: str = "", description: str = ""):
        """
        Создать поле настройки с улучшенным стилем.

        Args:
            parent: Родительский frame
            label: Название настройки
            entry_var: Имя переменной для Entry (self.{entry_var})
            placeholder: Placeholder текст
            description: Описание (серый текст)
        """
        field_frame = ctk.CTkFrame(parent, fg_color="transparent")
        field_frame.pack(fill="x", pady=8)

        # Label
        label_widget = ctk.CTkLabel(
            field_frame,
            text=label,
            width=220,
            anchor="w",
            font=ctk.CTkFont(size=13)
        )
        label_widget.pack(side="left", padx=(0, 15))

        # Entry с улучшенным стилем
        entry = ctk.CTkEntry(
            field_frame,
            width=120,
            height=35,
            placeholder_text=placeholder,
            corner_radius=8,
            border_width=1,
            border_color="#3A3D45"
        )
        entry.pack(side="left", padx=(0, 15))

        # Сохранить в self
        setattr(self, entry_var, entry)

        # Description
        if description:
            desc_label = ctk.CTkLabel(
                field_frame,
                text=description,
                text_color="#808080",
                font=ctk.CTkFont(size=11)
            )
            desc_label.pack(side="left")

    def _create_settings_tab(self):
        """Создать вкладку с настройками."""
        # Заголовок
        header = ctk.CTkLabel(
            self.tab_settings,
            text="⚙️ Настройки бота",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        header.pack(padx=20, pady=(20, 10), anchor="w")

        # Контейнер для настроек (scrollable)
        settings_frame = ctk.CTkScrollableFrame(self.tab_settings)
        settings_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # === Секция 1: Настройки торговли ===
        trading_section = self._create_settings_section(settings_frame, "Настройки торговли", "💰")

        self._create_setting_field(
            trading_section,
            label="Минимальный профит (%):",
            entry_var="profit_entry",
            placeholder="5.0",
            description="Покупать только предметы с профитом выше этого значения"
        )
        self.profit_entry.insert(0, str(self.bot_config.get('min_profit_pct', 5.0)))

        self._create_setting_field(
            trading_section,
            label="Интервал между циклами (мин):",
            entry_var="interval_entry",
            placeholder="5",
            description="Пауза между торговыми циклами в 24/7 режиме"
        )
        self.interval_entry.insert(0, str(self.bot_config.get('cycle_interval_minutes', 5)))

        # === Секция 2: База данных ===
        db_section = self._create_settings_section(settings_frame, "База данных", "💾")

        # Путь к БД (отдельная обработка для ширины 300px)
        db_frame = ctk.CTkFrame(db_section, fg_color="transparent")
        db_frame.pack(fill="x", pady=8)

        ctk.CTkLabel(
            db_frame,
            text="Путь к bottm.db:",
            width=220,
            anchor="w",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=(0, 15))

        self.db_path_entry = ctk.CTkEntry(
            db_frame,
            width=300,
            height=35,
            placeholder_text="data/main.db",
            corner_radius=8,
            border_width=1,
            border_color="#3A3D45"
        )
        self.db_path_entry.pack(side="left", padx=(0, 15))
        self.db_path_entry.insert(0, self.bot_config.get('bottm_db_path', 'data/main.db'))

        ctk.CTkLabel(
            db_frame,
            text="База данных с прибыльными предметами",
            text_color="#808080",
            font=ctk.CTkFont(size=11)
        ).pack(side="left")

        # === Секция 3: Выставление ордеров ===
        orders_section = self._create_settings_section(settings_frame, "Выставление ордеров", "📋")

        self._create_setting_field(
            orders_section,
            label="Мин. цена предмета (RUB):",
            entry_var="trade_min_price_entry",
            placeholder="100",
            description="Минимальная цена для выставления ордеров"
        )
        self.trade_min_price_entry.insert(0, str(self.bot_config.get('trade_min_price', 100)))

        self._create_setting_field(
            orders_section,
            label="Макс. цена предмета (RUB):",
            entry_var="trade_max_price_entry",
            placeholder="5000",
            description="Максимальная цена для выставления ордеров"
        )
        self.trade_max_price_entry.insert(0, str(self.bot_config.get('trade_max_price', 5000)))

        # === Секция 4: TM Parser (сканер) ===
        parser_section = self._create_settings_section(settings_frame, "TM Parser (сканер выгодных предметов)", "🔍")

        self._create_setting_field(
            parser_section,
            label="Минимальная цена (RUB):",
            entry_var="min_price_entry",
            placeholder="1000",
            description="Фильтр дешевых предметов"
        )
        self.min_price_entry.insert(0, str(self.bot_config.get('scanner_min_price', 1000)))

        self._create_setting_field(
            parser_section,
            label="Максимальная цена (RUB):",
            entry_var="max_price_entry",
            placeholder="10000",
            description="Фильтр дорогих предметов"
        )
        self.max_price_entry.insert(0, str(self.bot_config.get('scanner_max_price', 10000)))

        self._create_setting_field(
            parser_section,
            label="Мин. профит сканера (%):",
            entry_var="scanner_profit_entry",
            placeholder="-5.0",
            description="Порог для сохранения предмета в БД (может быть отрицательным)"
        )
        self.scanner_profit_entry.insert(0, str(self.bot_config.get('scanner_min_profit', -5.0)))

        self._create_setting_field(
            parser_section,
            label="Комиссия CSGO.TM (%):",
            entry_var="commission_entry",
            placeholder="7.0",
            description="Комиссия площадки при продаже"
        )
        self.commission_entry.insert(0, str(self.bot_config.get('csgo_commission', 7.0)))

        self._create_setting_field(
            parser_section,
            label="Мин. продаж за 7 дней:",
            entry_var="sales_7d_entry",
            placeholder="50",
            description="Фильтр ликвидности предметов"
        )
        self.sales_7d_entry.insert(0, str(self.bot_config.get('min_sales_7d', 50)))

        # Файл прокси (отдельная обработка для ширины 300px)
        proxy_file_frame = ctk.CTkFrame(parser_section, fg_color="transparent")
        proxy_file_frame.pack(fill="x", pady=8)

        ctk.CTkLabel(
            proxy_file_frame,
            text="Файл прокси:",
            width=220,
            anchor="w",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=(0, 15))

        self.proxy_file_entry = ctk.CTkEntry(
            proxy_file_frame,
            width=300,
            height=35,
            placeholder_text="proxies.txt",
            corner_radius=8,
            border_width=1,
            border_color="#3A3D45"
        )
        self.proxy_file_entry.pack(side="left", padx=(0, 15))
        self.proxy_file_entry.insert(0, self.bot_config.get('proxy_file', 'proxies.txt'))

        ctk.CTkLabel(
            proxy_file_frame,
            text="Файл со списком прокси (опционально)",
            text_color="#808080",
            font=ctk.CTkFont(size=11)
        ).pack(side="left")

        self._create_setting_field(
            parser_section,
            label="Запросов на прокси:",
            entry_var="requests_per_proxy_entry",
            placeholder="15",
            description="Менять прокси после N запросов"
        )
        self.requests_per_proxy_entry.insert(0, str(self.bot_config.get('requests_per_proxy', 15)))

        self._create_setting_field(
            parser_section,
            label="Макс. предметов для скана:",
            entry_var="max_items_entry",
            placeholder="10",
            description="Количество предметов за один проход"
        )
        self.max_items_entry.insert(0, str(self.bot_config.get('scanner_max_items', 10)))

        self._create_setting_field(
            parser_section,
            label="Задержка между запросами (сек):",
            entry_var="delay_entry",
            placeholder="7.0",
            description="Задержка для избежания блокировки"
        )
        self.delay_entry.insert(0, str(self.bot_config.get('scanner_delay', 7.0)))

        self._create_setting_field(
            parser_section,
            label="Параллельных воркеров:",
            entry_var="workers_entry",
            placeholder="1",
            description="Количество одновременных запросов"
        )
        self.workers_entry.insert(0, str(self.bot_config.get('scanner_workers', 1)))

        # === Секция 5: Auto Scanner ===
        auto_scanner_section = self._create_settings_section(settings_frame, "Auto Scanner (автоматическое сканирование)", "⏰")

        self._create_setting_field(
            auto_scanner_section,
            label="Интервал новых (мин):",
            entry_var="as_interval_entry",
            placeholder="30",
            description="Искать новые предметы каждые N минут"
        )
        self.as_interval_entry.insert(0, str(self.bot_config.get('auto_scan_interval', 30)))

        self._create_setting_field(
            auto_scanner_section,
            label="Кол-во новых:",
            entry_var="as_new_items_entry",
            placeholder="10",
            description="Сколько новых предметов искать за раз"
        )
        self.as_new_items_entry.insert(0, str(self.bot_config.get('auto_scan_new_items', 10)))

        self._create_setting_field(
            auto_scanner_section,
            label="Интервал ресканирования (мин):",
            entry_var="as_rescan_entry",
            placeholder="60",
            description="Проверять актуальность БД каждые N минут"
        )
        self.as_rescan_entry.insert(0, str(self.bot_config.get('auto_rescan_interval', 60)))

        # === Секция 6: Proxy Manager ===
        proxy_manager_section = self._create_settings_section(settings_frame, "Proxy Manager (ротация прокси)", "🔄")

        self._create_setting_field(
            proxy_manager_section,
            label="Макс. запросов:",
            entry_var="pm_max_requests_entry",
            placeholder="15",
            description="Менять прокси после N запросов"
        )
        self.pm_max_requests_entry.insert(0, str(self.bot_config.get('proxy_max_requests', 15)))

        self._create_setting_field(
            proxy_manager_section,
            label="Cooldown (секунды):",
            entry_var="pm_cooldown_entry",
            placeholder="60",
            description="Пауза перед повторным использованием"
        )
        self.pm_cooldown_entry.insert(0, str(self.bot_config.get('proxy_cooldown', 60)))

        self._create_setting_field(
            proxy_manager_section,
            label="Blacklist (минуты):",
            entry_var="pm_blacklist_entry",
            placeholder="30",
            description="Время блокировки плохого прокси"
        )
        self.pm_blacklist_entry.insert(0, str(self.bot_config.get('proxy_blacklist_duration', 30)))

        # === Секция 7: Дополнительные настройки ===
        extra_section = self._create_settings_section(settings_frame, "Дополнительные настройки", "🔧")

        # Автообновление статистики (switch)
        auto_refresh_frame = ctk.CTkFrame(extra_section, fg_color="transparent")
        auto_refresh_frame.pack(fill="x", pady=8)

        ctk.CTkLabel(
            auto_refresh_frame,
            text="Автообновление статистики:",
            width=220,
            anchor="w",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=(0, 15))

        self.auto_refresh_var = ctk.BooleanVar(value=self.bot_config.get('auto_refresh', True))
        auto_refresh_switch = ctk.CTkSwitch(
            auto_refresh_frame,
            text="Включено",
            variable=self.auto_refresh_var
        )
        auto_refresh_switch.pack(side="left")

        # Отладочные логи (switch)
        debug_frame = ctk.CTkFrame(extra_section, fg_color="transparent")
        debug_frame.pack(fill="x", pady=8)

        ctk.CTkLabel(
            debug_frame,
            text="Отладочные логи:",
            width=220,
            anchor="w",
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=(0, 15))

        self.debug_var = ctk.BooleanVar(value=self.bot_config.get('debug_mode', False))
        debug_switch = ctk.CTkSwitch(
            debug_frame,
            text="Включено",
            variable=self.debug_var
        )
        debug_switch.pack(side="left")

        # Кнопки управления настройками
        btn_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=20)

        save_btn = ctk.CTkButton(
            btn_frame,
            text="💾 Сохранить настройки",
            command=self._save_bot_config,
            fg_color="green",
            hover_color="darkgreen",
            width=200,
            height=40
        )
        save_btn.pack(side="left", padx=5)

        reset_btn = ctk.CTkButton(
            btn_frame,
            text="🔄 Сбросить",
            command=self._reset_bot_config,
            width=150,
            height=40
        )
        reset_btn.pack(side="left", padx=5)

        # Информация о настройках
        info_frame = ctk.CTkFrame(settings_frame)
        info_frame.pack(fill="x", pady=10)

        info_label = ctk.CTkLabel(
            info_frame,
            text="ℹ️ Настройки сохраняются в файл bot_config.json\n"
                 "Изменения применяются сразу после сохранения.\n"
                 "Для настройки аккаунтов используйте файл accounts.json",
            justify="left",
            text_color="gray"
        )
        info_label.pack(padx=15, pady=15)

    def _create_logs_tab(self):
        """Создать вкладку с логами."""
        # Текстовое поле для логов
        self.logs_text = ctk.CTkTextbox(
            self.tab_logs,
            wrap="word",
            font=ctk.CTkFont(size=13)
        )
        self.logs_text.pack(fill="both", expand=True, padx=10, pady=10)

        # Кнопка очистки логов
        btn_clear = ctk.CTkButton(
            self.tab_logs,
            text="🗑️ Очистить логи",
            command=self._clear_logs,
            width=150,
            height=35,
            font=ctk.CTkFont(size=13)
        )
        btn_clear.pack(pady=(0, 10))

    def _create_statusbar(self):
        """Создать статус бар."""
        self.statusbar = ctk.CTkFrame(
            self,
            height=35,
            fg_color=COLORS["bg_tertiary"],
            corner_radius=0
        )
        self.statusbar.pack(fill="x", side="bottom")

        # Версия
        version_label = ctk.CTkLabel(
            self.statusbar,
            text="v2.0",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"]
        )
        version_label.pack(side="left", padx=15, pady=5)

        # Разделитель
        sep1 = ctk.CTkLabel(
            self.statusbar,
            text="|",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["border"]
        )
        sep1.pack(side="left")

        # Статистика подключений
        self.connection_label = ctk.CTkLabel(
            self.statusbar,
            text="🌐 Не подключено",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"]
        )
        self.connection_label.pack(side="left", padx=15, pady=5)

        # Время
        self.time_label = ctk.CTkLabel(
            self.statusbar,
            text=f"🕒 {datetime.now().strftime('%H:%M:%S')}",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"]
        )
        self.time_label.pack(side="right", padx=15, pady=5)

        # Обновление времени
        self._update_time()

    def _update_time(self):
        """Обновить время в статус баре."""
        self.time_label.configure(text=f"🕒 {datetime.now().strftime('%H:%M:%S')}")

        # Обновляем статус подключений
        if self.account_manager:
            logged_in = sum(1 for acc in self.account_manager.accounts if acc.is_logged_in())
            total = len(self.account_manager.accounts)
            self.connection_label.configure(text=f"🌐 {logged_in}/{total} аккаунтов")

        self.after(1000, self._update_time)

    # ========== Логика управления ботом ==========

    def _load_accounts(self):
        """Загрузить аккаунты из accounts.json."""
        try:
            if not Path("accounts.json").exists():
                self._log("⚠️ Файл accounts.json не найден")
                return

            self.account_manager = AccountManager("accounts.json")
            self._log(f"✅ Загружено аккаунтов: {len(self.account_manager.accounts)}")
            self._refresh_accounts_list()

            # Обновляем список аккаунтов в селекторе dashboard
            if hasattr(self, 'account_selector'):
                account_names = ["Все аккаунты"]
                account_names.extend([acc.name for acc in self.account_manager.accounts])
                self.account_selector.configure(values=account_names)
                self._log(f"✅ Обновлен селектор аккаунтов: {len(account_names)} вариантов")

            # Обновляем балансы аккаунтов после загрузки
            self._update_accounts_balances()

            # Обновляем dashboard stats после загрузки аккаунтов
            self._update_dashboard_stats()

        except Exception as e:
            self._log(f"❌ Ошибка загрузки аккаунтов: {e}")

    def _load_bot_config(self):
        """Загрузить настройки бота из bot_config.json."""
        try:
            config_path = Path("bot_config.json")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.bot_config.update(loaded_config)

                # Обновляем GUI поля значениями из конфига
                self._update_gui_from_config()

                self._log(f"✅ Настройки загружены из bot_config.json")
            else:
                self._log("ℹ️ Файл bot_config.json не найден, используются настройки по умолчанию")
        except Exception as e:
            self._log(f"❌ Ошибка загрузки настроек: {e}")

    def _update_gui_from_config(self):
        """Обновить поля GUI значениями из bot_config."""
        try:
            # Основные настройки
            self.profit_entry.delete(0, 'end')
            self.profit_entry.insert(0, str(self.bot_config.get('min_profit_pct', 5.0)))

            self.interval_entry.delete(0, 'end')
            self.interval_entry.insert(0, str(self.bot_config.get('cycle_interval_minutes', 5)))

            self.db_path_entry.delete(0, 'end')
            self.db_path_entry.insert(0, self.bot_config.get('bottm_db_path', 'data/main.db'))

            self.auto_refresh_var.set(self.bot_config.get('auto_refresh', True))
            self.debug_var.set(self.bot_config.get('debug_mode', False))

            # Trading настройки
            self.trade_min_price_entry.delete(0, 'end')
            self.trade_min_price_entry.insert(0, str(self.bot_config.get('trade_min_price', 100)))

            self.trade_max_price_entry.delete(0, 'end')
            self.trade_max_price_entry.insert(0, str(self.bot_config.get('trade_max_price', 5000)))

            # TM Parser настройки
            self.min_price_entry.delete(0, 'end')
            self.min_price_entry.insert(0, str(self.bot_config.get('scanner_min_price', 1000)))

            self.max_price_entry.delete(0, 'end')
            self.max_price_entry.insert(0, str(self.bot_config.get('scanner_max_price', 10000)))

            self.scanner_profit_entry.delete(0, 'end')
            self.scanner_profit_entry.insert(0, str(self.bot_config.get('scanner_min_profit', -5.0)))

            self.commission_entry.delete(0, 'end')
            self.commission_entry.insert(0, str(self.bot_config.get('csgo_commission', 7.0)))

            self.sales_7d_entry.delete(0, 'end')
            self.sales_7d_entry.insert(0, str(self.bot_config.get('min_sales_7d', 50)))

            self.proxy_file_entry.delete(0, 'end')
            self.proxy_file_entry.insert(0, self.bot_config.get('proxy_file', 'proxies.txt'))

            self.requests_per_proxy_entry.delete(0, 'end')
            self.requests_per_proxy_entry.insert(0, str(self.bot_config.get('requests_per_proxy', 15)))

            self.max_items_entry.delete(0, 'end')
            self.max_items_entry.insert(0, str(self.bot_config.get('scanner_max_items', 10)))

            self.delay_entry.delete(0, 'end')
            self.delay_entry.insert(0, str(self.bot_config.get('scanner_delay', 7.0)))

            self.workers_entry.delete(0, 'end')
            self.workers_entry.insert(0, str(self.bot_config.get('scanner_workers', 1)))

        except Exception as e:
            logger.error(f"Error updating GUI from config: {e}")

    def _save_bot_config(self):
        """Сохранить настройки бота в bot_config.json."""
        try:
            # Собираем настройки из полей
            min_profit = float(self.profit_entry.get())
            cycle_interval = int(self.interval_entry.get())

            # Валидация
            if cycle_interval < 1:
                self._log("❌ Ошибка: интервал между циклами должен быть минимум 1 минута")
                return

            # Предупреждение о отрицательном профите
            if min_profit < 0:
                self._log("⚠️ ВНИМАНИЕ: Установлен отрицательный профит!")
                self._log(f"⚠️ Бот будет покупать предметы с УБЫТКОМ до {abs(min_profit):.1f}%")
                self._log("⚠️ Это может привести к финансовым потерям!")
                # Можно добавить диалог подтверждения здесь
            elif min_profit < 3:
                self._log(f"⚠️ Предупреждение: низкий профит {min_profit:.1f}% может не покрывать комиссию CSGO.TM (~10%)")

            self.bot_config['min_profit_pct'] = min_profit
            self.bot_config['cycle_interval_minutes'] = cycle_interval
            self.bot_config['bottm_db_path'] = self.db_path_entry.get()
            self.bot_config['auto_refresh'] = self.auto_refresh_var.get()
            self.bot_config['debug_mode'] = self.debug_var.get()

            # Trading настройки (выставление ордеров)
            self.bot_config['trade_min_price'] = float(self.trade_min_price_entry.get())
            self.bot_config['trade_max_price'] = float(self.trade_max_price_entry.get())

            # TM Parser настройки
            self.bot_config['scanner_min_price'] = float(self.min_price_entry.get())
            self.bot_config['scanner_max_price'] = float(self.max_price_entry.get())
            self.bot_config['scanner_min_profit'] = float(self.scanner_profit_entry.get())
            self.bot_config['csgo_commission'] = float(self.commission_entry.get())
            self.bot_config['min_sales_7d'] = int(self.sales_7d_entry.get())

            # TM Parser - дополнительные настройки
            self.bot_config['proxy_file'] = self.proxy_file_entry.get()
            self.bot_config['requests_per_proxy'] = int(self.requests_per_proxy_entry.get())
            self.bot_config['scanner_max_items'] = int(self.max_items_entry.get())
            self.bot_config['scanner_delay'] = float(self.delay_entry.get())
            self.bot_config['scanner_workers'] = int(self.workers_entry.get())

            # Auto Scanner настройки
            self.bot_config['auto_scan_interval'] = int(self.as_interval_entry.get())
            self.bot_config['auto_scan_new_items'] = int(self.as_new_items_entry.get())
            self.bot_config['auto_rescan_interval'] = int(self.as_rescan_entry.get())

            # Proxy Manager настройки
            self.bot_config['proxy_max_requests'] = int(self.pm_max_requests_entry.get())
            self.bot_config['proxy_cooldown'] = int(self.pm_cooldown_entry.get())
            self.bot_config['proxy_blacklist_duration'] = int(self.pm_blacklist_entry.get())

            # Сохраняем в файл
            with open("bot_config.json", 'w', encoding='utf-8') as f:
                json.dump(self.bot_config, f, indent=2, ensure_ascii=False)

            self._log("✅ Настройки сохранены в bot_config.json")

            if min_profit >= 0:
                self._log(f"✅ Минимальный профит: {min_profit:.1f}%")

            # Обновляем параметры в TradingBot
            from src.trading_bot import TradingBot
            TradingBot.MIN_PROFIT_PCT = self.bot_config['min_profit_pct']
            TradingBot.TRADE_MIN_PRICE = self.bot_config['trade_min_price']
            TradingBot.TRADE_MAX_PRICE = self.bot_config['trade_max_price']

        except ValueError as e:
            self._log(f"❌ Ошибка: неверный формат данных. Проверьте введенные значения.")
        except Exception as e:
            self._log(f"❌ Ошибка сохранения настроек: {e}")

    def _reset_bot_config(self):
        """Сбросить настройки к значениям по умолчанию."""
        # Сбрасываем к дефолтным значениям
        self.bot_config = {
            'min_profit_pct': 5.0,
            'cycle_interval_minutes': 5,
            'bottm_db_path': 'data/main.db',
            'auto_refresh': True,
            'debug_mode': False,
            'auto_scan_interval': 30,
            'auto_scan_new_items': 10,
            'auto_rescan_interval': 60,
        }

        # Обновляем поля
        self.profit_entry.delete(0, 'end')
        self.profit_entry.insert(0, "5.0")

        self.interval_entry.delete(0, 'end')
        self.interval_entry.insert(0, "5")

        self.db_path_entry.delete(0, 'end')
        self.db_path_entry.insert(0, "data/main.db")

        self.auto_refresh_var.set(True)
        self.debug_var.set(False)

        # Auto Scanner поля
        if hasattr(self, 'as_interval_entry'):
            self.as_interval_entry.delete(0, 'end')
            self.as_interval_entry.insert(0, "30")
        if hasattr(self, 'as_new_items_entry'):
            self.as_new_items_entry.delete(0, 'end')
            self.as_new_items_entry.insert(0, "10")
        if hasattr(self, 'as_rescan_entry'):
            self.as_rescan_entry.delete(0, 'end')
            self.as_rescan_entry.insert(0, "60")

        self._log("🔄 Настройки сброшены к значениям по умолчанию")

    def _refresh_accounts_list(self):
        """Обновить список аккаунтов."""
        # Очищаем текущий список
        for widget in self.accounts_scrollable.winfo_children():
            widget.destroy()

        # Очищаем словарь balance labels
        self.account_balance_labels.clear()

        if not self.account_manager:
            return

        # Добавляем аккаунты
        for account in self.account_manager.accounts:
            self._create_account_card(account)

        # Обновляем селектор аккаунтов в dashboard
        if hasattr(self, 'account_selector'):
            account_names = ["Все аккаунты"]
            account_names.extend([acc.name for acc in self.account_manager.accounts])
            self.account_selector.configure(values=account_names)

    def _create_account_card(self, account):
        """Создать карточку аккаунта."""
        card = ctk.CTkFrame(self.accounts_scrollable)
        card.pack(fill="x", padx=5, pady=5)

        # Имя аккаунта
        name_label = ctk.CTkLabel(
            card,
            text=f"👤 {account.name}",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        name_label.pack(side="left", padx=10, pady=10)

        # Статус
        status_text = "✅ Включен" if account.config.enabled else "⏸️ Выключен"
        status_label = ctk.CTkLabel(card, text=status_text)
        status_label.pack(side="left", padx=10)

        # Валюта аккаунта
        currency = getattr(account.config, 'currency', 'RUB')
        currency_label = ctk.CTkLabel(card, text=f"💱 {currency}", text_color="gray")
        currency_label.pack(side="left", padx=10)

        # Баланс (будет обновляться)
        balance_label = ctk.CTkLabel(card, text="💰 Баланс: загрузка...")
        balance_label.pack(side="left", padx=10)

        # Сохраняем ссылку на balance_label для обновления
        self.account_balance_labels[account.name] = balance_label

        # Кнопки управления
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(side="right", padx=10)

        # Кнопка определения валюты
        btn_detect_currency = ctk.CTkButton(
            btn_frame,
            text="🔍 Валюта",
            command=lambda a=account: self._detect_account_currency(a),
            width=100,
            fg_color="#3498DB",
            hover_color="#2980B9"
        )
        btn_detect_currency.pack(side="left", padx=5)

        btn_toggle = ctk.CTkButton(
            btn_frame,
            text="Вкл/Выкл",
            command=lambda a=account: self._toggle_account(a),
            width=80
        )
        btn_toggle.pack(side="left", padx=5)

    def _start_bot(self):
        """Запустить бота."""
        if self.bot_running:
            return

        try:
            self.bot_running = True
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.status_label.configure(text="▶️ Бот запущен")

            # Запускаем в отдельном потоке
            self.bot_thread = threading.Thread(target=self._bot_loop, daemon=True)
            self.bot_thread.start()

            self._log("▶️ Бот запущен")

        except Exception as e:
            self._log(f"❌ Ошибка запуска бота: {e}")
            self.bot_running = False
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")

    def _stop_bot(self):
        """Остановить бота."""
        self.bot_running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_label.configure(text="⏸️ Бот остановлен")
        self._log("⏸️ Бот остановлен")

    def _bot_loop(self):
        """Главный цикл бота (выполняется в отдельном потоке)."""
        try:
            if not self.account_manager:
                self._log("❌ AccountManager не инициализирован")
                return

            # Применяем настройки к TradingBot
            from src.trading_bot import TradingBot
            TradingBot.MIN_PROFIT_PCT = self.bot_config.get('min_profit_pct', 5.0)
            TradingBot.TRADE_MIN_PRICE = self.bot_config.get('trade_min_price', 100.0)
            TradingBot.TRADE_MAX_PRICE = self.bot_config.get('trade_max_price', 5000.0)
            self._log(f"⚙️ Минимальный профит установлен: {TradingBot.MIN_PROFIT_PCT}%")
            self._log(f"⚙️ Диапазон цен для ордеров: {TradingBot.TRADE_MIN_PRICE:.0f}-{TradingBot.TRADE_MAX_PRICE:.0f} RUB")

            # Логин аккаунтов
            self._log("🔐 Логин в аккаунты...")
            login_results = self.account_manager.login_all_sync()

            logged_in_count = sum(1 for v in login_results.values() if v)
            self._log(f"✅ Залогинено: {logged_in_count}/{len(login_results)}")

            # Автоматически определяем валюту для аккаунтов, если не была определена
            self._log("🔍 Проверка валют аккаунтов...")
            for account in self.account_manager.get_enabled_accounts():
                if not self.bot_running:
                    break

                # Skip if account is not logged in
                if not account.is_logged_in():
                    self._log(f"[{account.name}] ⚠️ Пропущено (не залогинен)")
                    continue

                # Используем новый async метод для определения валюты
                try:
                    self._log(f"[{account.name}] Определение валюты...")
                    detected_currency = account.detect_currency_sync()

                    if detected_currency:
                        balance = account.get_wallet_balance_sync()
                        self._log(f"[{account.name}] ✅ Валюта: {detected_currency}, Баланс: {balance:.2f} {detected_currency}")
                    else:
                        self._log(f"[{account.name}] ℹ️ Используется валюта по умолчанию: {account.config.currency}")

                except Exception as e:
                    self._log(f"[{account.name}] ❌ Ошибка определения валюты: {e}")
                    self._log(f"[{account.name}] ℹ️ Используется валюта по умолчанию: {account.config.currency}")

                if not self.bot_running:
                    break

            # Обновляем dashboard после логина и определения валют
            if self.bot_running:
                self.after(0, self._update_dashboard_stats)
                self._log("✅ Dashboard обновлен с балансами")

            # Главный цикл
            cycle_count = 0
            while self.bot_running:
                cycle_count += 1
                self._log(f"\n{'='*50}")
                self._log(f"🔄 Цикл #{cycle_count}")
                self._log(f"{'='*50}")

                # Запускаем цикл для каждого аккаунта
                for account in self.account_manager.get_enabled_accounts():
                    if not self.bot_running:
                        break

                    # Skip if account is not logged in
                    if not account.is_logged_in():
                        self._log(f"[{account.name}] ⚠️ Пропущено (не залогинен)")
                        continue

                    try:
                        from src.async_helper import run_async_in_gui

                        bot = TradingBot(account)
                        # Торговый цикл может занять несколько минут, устанавливаем таймаут 5 минут
                        stats = run_async_in_gui(bot.run_cycle(), timeout=300.0)

                        self._log(
                            f"[{account.name}] Цикл завершен: "
                            f"отменено={stats.get('orders_cancelled', 0)}, "
                            f"активно={stats.get('orders_synced', 0)}, "
                            f"создано={stats['orders_created']}, "
                            f"исполнено={stats['orders_filled']}, "
                            f"выставлено={stats['items_listed']}"
                        )

                    except Exception as e:
                        self._log(f"❌ [{account.name}] Ошибка цикла: {e}")

                # Обновляем статистику в GUI
                self.after(0, self._refresh_data)

                # Пауза между циклами (из настроек)
                interval_minutes = self.bot_config.get('cycle_interval_minutes', 5)
                interval_seconds = interval_minutes * 60
                self._log(f"⏰ Следующий цикл через {interval_minutes} минут...")
                time.sleep(interval_seconds)

        except Exception as e:
            self._log(f"❌ Критическая ошибка в bot_loop: {e}")
        finally:
            # Logout
            if self.account_manager:
                self.account_manager.logout_all()
            self.bot_running = False
            self.after(0, lambda: self.btn_start.configure(state="normal"))
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))

    def _refresh_data(self):
        """Обновить данные на всех вкладках."""
        try:
            # Обновляем статистику
            selected_account = self.account_selector.get() if hasattr(self, 'account_selector') else "Все аккаунты"
            self._update_dashboard_stats(selected_account)
            self._update_accounts_balances()
            self._refresh_orders_list()
            self._refresh_inventory_list()
            self._refresh_profitable_items()

            # Обновляем таблицы на Dashboard
            self._refresh_recent_trades()
            self._refresh_active_orders_table()

        except Exception as e:
            logger.error(f"Error refreshing data: {e}")

    def _update_dashboard_stats(self, account_name: str = "Все аккаунты"):
        """
        Обновить статистику на Dashboard для выбранного аккаунта.

        Args:
            account_name: Имя аккаунта или "Все аккаунты"
        """
        try:
            # Балансы
            total_steam = 0.0
            total_csgotm = 0.0
            currency = "RUB"

            if self.account_manager:
                try:
                    if account_name == "Все аккаунты":
                        # Суммировать по всем аккаунтам
                        # get_total_balance_sync() возвращает балансы в RUB (с конвертацией)
                        currency = "RUB"  # Всегда RUB для "Все аккаунты"

                        balances = self.account_manager.get_total_balance_sync()
                        total_steam = balances.get('steam_balance', 0.0)
                        total_csgotm = balances.get('csgotm_balance', 0.0)
                    else:
                        # Баланс конкретного аккаунта
                        account = next((acc for acc in self.account_manager.accounts if acc.name == account_name), None)
                        if account:
                            total_steam = account.get_wallet_balance_sync()
                            total_csgotm = account.get_csgotm_balance()
                            currency = getattr(account.config, 'currency', 'RUB')
                except Exception as e:
                    logger.error(f"Error getting balances: {e}")

            # Конвертируем CSGO.TM баланс если валюта не RUB (CSGO.TM всегда возвращает RUB)
            display_csgotm = total_csgotm
            if currency != "RUB" and total_csgotm > 0:
                display_csgotm = currency_converter.convert_from_rub(total_csgotm, currency)

            self.stats_cards['balance_steam'].value_label.configure(
                text=f"{total_steam:.2f} {currency}"
            )
            self.stats_cards['balance_csgotm'].value_label.configure(
                text=f"{display_csgotm:.2f} {currency}" + (f" ({total_csgotm:.2f} RUB)" if currency != "RUB" and total_csgotm > 0 else "")
            )

            # Статистика из БД
            # Проверяем, поддерживают ли методы фильтрацию по account_name
            try:
                if account_name == "Все аккаунты":
                    active_orders = trades_db.get_active_orders_count()
                    on_hold = trades_db.get_purchased_items_count()
                    profit_data = trades_db.get_total_profit()
                    sold_count = trades_db.get_sold_items_count()
                else:
                    # Пробуем передать account_name (если метод поддерживает)
                    try:
                        active_orders = trades_db.get_active_orders_count(account_name=account_name)
                    except TypeError:
                        # Метод не поддерживает account_name, используем общий подсчет
                        active_orders = trades_db.get_active_orders_count()

                    try:
                        on_hold = trades_db.get_purchased_items_count(account_name=account_name)
                    except TypeError:
                        on_hold = trades_db.get_purchased_items_count()

                    try:
                        profit_data = trades_db.get_total_profit(account_name=account_name)
                    except TypeError:
                        profit_data = trades_db.get_total_profit()

                    try:
                        sold_count = trades_db.get_sold_items_count(account_name=account_name)
                    except TypeError:
                        sold_count = trades_db.get_sold_items_count()
            except Exception as e:
                logger.error(f"Error getting DB stats: {e}")
                active_orders = 0
                on_hold = 0
                profit_data = {}
                sold_count = 0

            total_profit = profit_data.get('total_profit', 0.0) if profit_data else 0.0

            self.stats_cards['active_orders'].value_label.configure(text=str(active_orders))
            self.stats_cards['on_hold'].value_label.configure(text=str(on_hold))
            self.stats_cards['profit'].value_label.configure(text=f"${total_profit:.2f}")
            self.stats_cards['sold_items'].value_label.configure(text=str(sold_count))

        except Exception as e:
            logger.error(f"Error updating stats: {e}")

    def _update_accounts_balances(self):
        """Обновить балансы всех аккаунтов."""
        if not self.account_manager:
            return

        try:
            for account in self.account_manager.accounts:
                if account.name in self.account_balance_labels:
                    try:
                        # Проверяем, есть ли кешированный баланс
                        steam_balance = 0.0
                        if hasattr(account, '_cached_steam_balance') and account._cached_steam_balance:
                            # Используем кешированный баланс (чтобы не делать лишние запросы к Steam API)
                            steam_balance = account._cached_steam_balance.get('balance', 0.0)
                            currency = account._cached_steam_balance.get('currency', 'RUB')
                        else:
                            # Если кеша нет, используем валюту из конфига, но НЕ запрашиваем баланс
                            # Баланс будет показан только после нажатия "Определить валюту"
                            currency = getattr(account.config, 'currency', 'RUB')
                            steam_balance = 0.0

                        # Получаем баланс CSGO.TM (это быстро и не вызывает rate limit)
                        try:
                            csgotm_balance = account.get_csgotm_balance()  # Всегда в RUB
                        except Exception as e:
                            logger.warning(f"Failed to get CSGO.TM balance for {account.name}: {e}")
                            csgotm_balance = 0.0

                        # Если валюта не RUB, конвертируем TM баланс
                        if currency != 'RUB':
                            # Steam баланс уже в нужной валюте
                            # TM баланс в RUB -> конвертируем в валюту аккаунта
                            csgotm_converted = currency_converter.convert_from_rub(csgotm_balance, currency)
                            if steam_balance > 0:
                                balance_text = f"💰 Steam: {steam_balance:.2f} {currency} | TM: {csgotm_converted:.2f} {currency} ({csgotm_balance:.2f} RUB)"
                            else:
                                balance_text = f"💰 Steam: нажмите '🔍 Валюта' | TM: {csgotm_converted:.2f} {currency} ({csgotm_balance:.2f} RUB)"
                        else:
                            if steam_balance > 0:
                                balance_text = f"💰 Steam: {steam_balance:.2f} {currency} | TM: {csgotm_balance:.2f} {currency}"
                            else:
                                balance_text = f"💰 Steam: нажмите '🔍 Валюта' | TM: {csgotm_balance:.2f} {currency}"

                        self.account_balance_labels[account.name].configure(text=balance_text)

                    except Exception as e:
                        logger.error(f"Error getting balance for {account.name}: {e}")
                        self.account_balance_labels[account.name].configure(
                            text="💰 Ошибка загрузки баланса"
                        )

        except Exception as e:
            logger.error(f"Error updating account balances: {e}")

    def _refresh_orders_list(self):
        """Обновить список ордеров."""
        # Очищаем
        for widget in self.orders_scrollable.winfo_children():
            widget.destroy()

        try:
            # Получаем активные ордера
            orders = trades_db.get_all_active_orders()

            if not orders:
                label = ctk.CTkLabel(
                    self.orders_scrollable,
                    text="Нет активных ордеров",
                    font=ctk.CTkFont(size=14)
                )
                label.pack(pady=20)
                return

            # Создаем заголовок таблицы
            header = ctk.CTkFrame(self.orders_scrollable)
            header.pack(fill="x", pady=(0, 5))

            # Настраиваем grid для адаптивной ширины
            header.grid_columnconfigure(0, weight=1, minsize=150)  # Аккаунт
            header.grid_columnconfigure(1, weight=4, minsize=350)  # Предмет
            header.grid_columnconfigure(2, weight=1, minsize=120)  # Цена
            header.grid_columnconfigure(3, weight=1, minsize=150)  # Создан

            headers = ["Аккаунт", "Предмет", "Цена", "Создан"]
            for i, text in enumerate(headers):
                label = ctk.CTkLabel(
                    header,
                    text=text,
                    font=ctk.CTkFont(size=14, weight="bold")
                )
                label.grid(row=0, column=i, padx=10, pady=8, sticky="ew")

            # Добавляем ордера
            for order in orders:
                row = ctk.CTkFrame(self.orders_scrollable)
                row.pack(fill="x", pady=3)

                # Настраиваем grid для строки
                row.grid_columnconfigure(0, weight=1, minsize=150)
                row.grid_columnconfigure(1, weight=4, minsize=350)
                row.grid_columnconfigure(2, weight=1, minsize=120)
                row.grid_columnconfigure(3, weight=1, minsize=150)

                values = [
                    order.get('account_name', 'N/A'),
                    order.get('item_name', 'N/A'),
                    f"{order.get('order_price', 0):.2f} ₽",
                    order.get('created_at', 'N/A')[:16]
                ]

                for i, value in enumerate(values):
                    label = ctk.CTkLabel(
                        row,
                        text=value,
                        font=ctk.CTkFont(size=13)
                    )
                    label.grid(row=0, column=i, padx=10, pady=6, sticky="ew")

        except Exception as e:
            logger.error(f"Error refreshing orders: {e}")

    def _refresh_inventory_list(self):
        """Обновить список предметов на холде."""
        # Очищаем
        for widget in self.inventory_scrollable.winfo_children():
            widget.destroy()

        try:
            # Получаем фильтр по аккаунту
            account_filter = None
            if hasattr(self, 'inventory_account_filter'):
                selected = self.inventory_account_filter.get()
                if selected != "Все аккаунты":
                    account_filter = selected

            # Получаем все предметы (не только на холде)
            items = trades_db.get_all_purchased_items(account_name=account_filter)

            if not items:
                label = ctk.CTkLabel(
                    self.inventory_scrollable,
                    text="Нет предметов",
                    font=ctk.CTkFont(size=14)
                )
                label.pack(pady=20)
                return

            # Фиксированные ширины колонок: Аккаунт, Предмет, Куплен за, CSGO.TM, Профит ₽, Разблокировка
            col_widths = [110, 450, 100, 100, 100, 160]

            # Создаем заголовок
            header = ctk.CTkFrame(self.inventory_scrollable, fg_color=COLORS["bg_secondary"])
            header.pack(fill="x", pady=(0, 2))

            headers = ["Аккаунт", "Предмет", "Куплен за", "CSGO.TM", "Профит ₽", "Разблокировка"]
            for i, text in enumerate(headers):
                ctk.CTkLabel(
                    header,
                    text=text,
                    width=col_widths[i],
                    anchor="w",
                    font=ctk.CTkFont(size=14, weight="bold")
                ).pack(side="left", padx=5, pady=6)

            # Добавляем предметы
            for item in items:
                row = ctk.CTkFrame(self.inventory_scrollable, fg_color=COLORS["bg_tertiary"], corner_radius=3)
                row.pack(fill="x", pady=1)

                # Аккаунт
                ctk.CTkLabel(
                    row,
                    text=item.get('account_name', 'N/A'),
                    width=col_widths[0],
                    anchor="w",
                    font=ctk.CTkFont(size=13)
                ).pack(side="left", padx=5, pady=4)

                # Предмет (кликабельная ссылка)
                item_name = item.get('item_name', 'N/A')
                market_hash_name = item.get('market_hash_name', '')
                # Обрезаем длинные названия
                display_name = item_name[:55] + "..." if len(item_name) > 58 else item_name

                item_frame = ctk.CTkFrame(row, fg_color="transparent", width=col_widths[1], height=24)
                item_frame.pack(side="left", padx=5, pady=4)
                item_frame.pack_propagate(False)

                item_label = ctk.CTkLabel(
                    item_frame,
                    text=display_name,
                    anchor="w",
                    font=ctk.CTkFont(size=13),
                    text_color="#3498db",
                    cursor="hand2"
                )
                item_label.pack(side="left")

                if market_hash_name:
                    from urllib.parse import quote
                    steam_url = f"https://steamcommunity.com/market/listings/730/{quote(market_hash_name)}"
                    item_label.bind("<Button-1>", lambda e, url=steam_url: self._open_url(url))

                    # CSGO.TM link
                    csgotm_label = ctk.CTkLabel(
                        item_frame,
                        text="[TM]",
                        font=ctk.CTkFont(size=11),
                        text_color="#e74c3c",
                        cursor="hand2"
                    )
                    csgotm_label.pack(side="left", padx=(3, 0))

                    # Определяем категорию оружия
                    weapon_categories = {
                        'AK-47': 'Rifle/AK-47', 'M4A4': 'Rifle/M4A4', 'M4A1-S': 'Rifle/M4A1-S',
                        'AWP': 'Rifle/AWP', 'USP-S': 'Pistol/USP-S', 'Glock-18': 'Pistol/Glock-18',
                        'Desert Eagle': 'Pistol/Desert%20Eagle', 'P250': 'Pistol/P250',
                        'Five-SeveN': 'Pistol/Five-SeveN', 'Tec-9': 'Pistol/Tec-9',
                        'MP9': 'SMG/MP9', 'MAC-10': 'SMG/MAC-10', 'UMP-45': 'SMG/UMP-45',
                        'P90': 'SMG/P90', 'MP7': 'SMG/MP7', 'MP5-SD': 'SMG/MP5-SD',
                        'FAMAS': 'Rifle/FAMAS', 'Galil AR': 'Rifle/Galil%20AR',
                        'SSG 08': 'Rifle/SSG%2008', 'SG 553': 'Rifle/SG%20553',
                        'AUG': 'Rifle/AUG', 'G3SG1': 'Rifle/G3SG1', 'SCAR-20': 'Rifle/SCAR-20',
                        'Nova': 'Shotgun/Nova', 'XM1014': 'Shotgun/XM1014', 'MAG-7': 'Shotgun/MAG-7',
                        'Sawed-Off': 'Shotgun/Sawed-Off', 'M249': 'Machinegun/M249',
                        'Negev': 'Machinegun/Negev', 'CZ75-Auto': 'Pistol/CZ75-Auto',
                        'R8 Revolver': 'Pistol/R8%20Revolver', 'Dual Berettas': 'Pistol/Dual%20Berettas',
                    }
                    weapon_path = ''
                    for weapon, path in weapon_categories.items():
                        if weapon in market_hash_name:
                            weapon_path = path
                            break
                    if weapon_path:
                        csgotm_url = f"https://market.csgo.com/ru/{weapon_path}/{quote(market_hash_name)}"
                    else:
                        csgotm_url = f"https://market.csgo.com/ru/?search={quote(market_hash_name)}"
                    csgotm_label.bind("<Button-1>", lambda e, url=csgotm_url: self._open_url(url))

                # Цена покупки
                purchase_price = item.get('purchase_price', 0)
                ctk.CTkLabel(
                    row,
                    text=f"{purchase_price:.0f} ₽",
                    width=col_widths[2],
                    anchor="w",
                    font=ctk.CTkFont(size=13)
                ).pack(side="left", padx=5, pady=4)

                # CSGO.TM Price (текущая)
                current_csgotm = item.get('current_csgotm_price')
                csgotm_text = f"{current_csgotm:.0f} ₽" if current_csgotm else "—"
                ctk.CTkLabel(
                    row,
                    text=csgotm_text,
                    width=col_widths[3],
                    anchor="w",
                    font=ctk.CTkFont(size=13),
                    text_color="#e74c3c" if current_csgotm else None
                ).pack(side="left", padx=5, pady=4)

                # Профит в рублях (CSGO.TM - цена покупки)
                if current_csgotm and purchase_price:
                    profit_rub = current_csgotm - purchase_price
                    profit_color = "#27ae60" if profit_rub > 0 else "#e74c3c"
                    profit_text = f"{profit_rub:+.0f} ₽"
                else:
                    profit_color = None
                    profit_text = "—"

                ctk.CTkLabel(
                    row,
                    text=profit_text,
                    width=col_widths[4],
                    anchor="w",
                    font=ctk.CTkFont(size=13, weight="bold" if current_csgotm else "normal"),
                    text_color=profit_color
                ).pack(side="left", padx=5, pady=4)

                # Разблокировка - форматируем как в Steam (8:00 GMT)
                unlock_date = item.get('unlock_date', 'N/A')
                if unlock_date and unlock_date != 'N/A':
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(unlock_date.replace(' ', 'T')[:19])
                        unlock_text = dt.strftime('%Y-%m-%d 08:00')
                    except Exception:
                        unlock_text = unlock_date[:16] if len(unlock_date) > 16 else unlock_date
                else:
                    unlock_text = 'N/A'

                ctk.CTkLabel(
                    row,
                    text=unlock_text,
                    width=col_widths[5],
                    anchor="w",
                    font=ctk.CTkFont(size=13)
                ).pack(side="left", padx=5, pady=4)

        except Exception as e:
            logger.error(f"Error refreshing inventory: {e}")

    def _open_url(self, url: str):
        """Открыть URL в браузере."""
        import webbrowser
        webbrowser.open(url)

    def _refresh_item_prices(self):
        """Обновить текущие цены CSGO.TM для всех предметов в инвентаре."""
        import threading

        def update_prices():
            try:
                self._log("🔄 Обновление цен CSGO.TM для предметов на холде...")

                # Получаем все предметы
                items = trades_db.get_all_purchased_items()
                if not items:
                    self._log("Нет предметов для обновления")
                    return

                # Получаем CSGO.TM клиент из первого активного аккаунта
                csgotm_client = None
                if self.account_manager:
                    for account in self.account_manager.get_enabled_accounts():
                        if account.csgotm_client:
                            csgotm_client = account.csgotm_client
                            break

                if not csgotm_client:
                    self._log("❌ CSGO.TM клиент не найден. Авторизуйтесь в аккаунте.")
                    return

                updated = 0
                for item in items:
                    market_hash_name = item.get('market_hash_name', '')
                    if not market_hash_name:
                        continue

                    try:
                        # Получаем цену с CSGO.TM
                        price_info = csgotm_client.get_item_price(market_hash_name)
                        if price_info and 'min_price' in price_info:
                            csgotm_price = price_info['min_price']

                            # Обновляем в БД
                            trades_db.update_item_current_prices(
                                item['id'],
                                current_csgotm_price=csgotm_price
                            )
                            updated += 1
                            self._log(f"✅ {market_hash_name[:40]}: {csgotm_price:.0f} ₽")

                        import time
                        time.sleep(0.5)  # Rate limiting

                    except Exception as e:
                        self._log(f"⚠️ Ошибка для {market_hash_name[:30]}: {e}")

                self._log(f"✅ Обновлено цен: {updated}/{len(items)}")

                # Обновляем таблицу в GUI
                self.after(100, self._refresh_inventory_list)

            except Exception as e:
                self._log(f"❌ Ошибка обновления цен: {e}")

        # Запускаем в отдельном потоке
        thread = threading.Thread(target=update_prices, daemon=True)
        thread.start()

    def _toggle_profit_sort(self):
        """Переключить сортировку по профиту."""
        self.sort_by_profit = not self.sort_by_profit
        self._refresh_profitable_items()

    def _refresh_profitable_items(self):
        """Обновить список выгодных предметов из БД."""
        # Очищаем (с защитой от ошибок при удалении виджетов)
        try:
            for widget in self.parser_scrollable.winfo_children():
                try:
                    widget.destroy()
                except Exception:
                    pass  # Виджет уже удален или недоступен
        except Exception:
            pass

        try:
            # Определяем фильтр по профиту
            if self.profit_filter_enabled_var.get():
                # Фильтр включен - используем значение из поля
                try:
                    min_profit = float(self.parser_min_profit_entry.get())
                except ValueError:
                    min_profit = -5.0  # Fallback значение
            else:
                # Фильтр выключен - показываем ВСЕ предметы
                min_profit = None

            items = trades_db.get_active_profitable_items(min_profit=min_profit, limit=100)

            # Фильтруем фейк-профиты (где buy_order >= lowest_sell)
            fake_profit_items = []
            filtered_items = []
            for item in items:
                steam_buy = item.get('steam_buy_order')
                steam_sell = item.get('steam_lowest_sell')

                # Если есть данные о lowest_sell и buy_order >= lowest_sell - это фейк
                if steam_sell is not None and steam_buy is not None and steam_sell > 0 and steam_buy >= steam_sell:
                    fake_profit_items.append(item.get('market_hash_name'))
                else:
                    filtered_items.append(item)

            # Удаляем фейк-профиты из БД
            if fake_profit_items:
                logger.info(f"Обнаружено {len(fake_profit_items)} фейк-профитов, удаляем...")
                trades_db.mark_items_inactive(fake_profit_items)
                self._log(f"🗑️ Удалено {len(fake_profit_items)} фейк-профитов")

            items = filtered_items

            # Сортировка по профиту если включена
            if self.sort_by_profit and items:
                # Обрабатываем None значения: ставим их в конец списка (-999)
                items.sort(key=lambda x: x.get('profit_pct') if x.get('profit_pct') is not None else -999, reverse=True)

            # Обновляем счётчик предметов
            if hasattr(self, 'parser_items_count_label'):
                self.parser_items_count_label.configure(
                    text=f"Найдено: {len(items)} предметов"
                )

            if not items:
                label = ctk.CTkLabel(
                    self.parser_scrollable,
                    text="Нет выгодных предметов. Запустите сканирование!",
                    font=ctk.CTkFont(size=14)
                )
                label.pack(pady=20)
                return

            # Создаем заголовок таблицы
            header = ctk.CTkFrame(self.parser_scrollable)
            header.pack(fill="x", pady=(0, 5))

            headers = ["Предмет", "Steam Buy", "CSGO Sell (мин.)", "Профит %", "Рек. цена", "Обновлено", "Действия"]
            # Используем grid weights для адаптивной ширины
            header.grid_columnconfigure(0, weight=4, minsize=350)  # Название предмета - самая широкая
            header.grid_columnconfigure(1, weight=1, minsize=100)  # Steam Buy
            header.grid_columnconfigure(2, weight=1, minsize=100)  # CSGO Sell
            header.grid_columnconfigure(3, weight=1, minsize=90)   # Профит
            header.grid_columnconfigure(4, weight=1, minsize=100)  # Рек. цена
            header.grid_columnconfigure(5, weight=1, minsize=140)  # Обновлено
            header.grid_columnconfigure(6, weight=1, minsize=180)  # Действия

            for i, text in enumerate(headers):
                # Для "Профит %" делаем кликабельную кнопку для сортировки
                if text == "Профит %":
                    sort_indicator = " ▼" if self.sort_by_profit else ""
                    profit_btn = ctk.CTkButton(
                        header,
                        text=f"{text}{sort_indicator}",
                        command=self._toggle_profit_sort,
                        font=ctk.CTkFont(size=14, weight="bold"),
                        fg_color="transparent",
                        hover_color=("gray70", "gray30"),
                        width=90
                    )
                    profit_btn.grid(row=0, column=i, padx=8, pady=8, sticky="ew")
                else:
                    label = ctk.CTkLabel(
                        header,
                        text=text,
                        font=ctk.CTkFont(size=14, weight="bold"),
                    )
                    label.grid(row=0, column=i, padx=8, pady=8, sticky="ew")

            # Добавляем предметы
            for item in items:
                row = ctk.CTkFrame(self.parser_scrollable)
                row.pack(fill="x", pady=3)

                # Настраиваем grid для каждой строки с теми же пропорциями
                row.grid_columnconfigure(0, weight=4, minsize=350)
                row.grid_columnconfigure(1, weight=1, minsize=100)
                row.grid_columnconfigure(2, weight=1, minsize=100)
                row.grid_columnconfigure(3, weight=1, minsize=90)
                row.grid_columnconfigure(4, weight=1, minsize=100)
                row.grid_columnconfigure(5, weight=1, minsize=140)
                row.grid_columnconfigure(6, weight=1, minsize=180)

                market_hash_name = item.get('market_hash_name', 'N/A')

                # Получаем профит (используем recommended если есть, иначе обычный)
                # Обрабатываем None значения корректно
                profit_pct = item.get('profit_pct') if item.get('profit_pct') is not None else 0
                recommended_profit_pct = item.get('recommended_profit_pct')
                best_profit = recommended_profit_pct if recommended_profit_pct is not None else profit_pct

                # Цвет в зависимости от профита (обрабатываем None)
                if best_profit is None:
                    best_profit = 0
                profit_color = COLORS["accent_green"] if best_profit >= 5 else COLORS["accent_yellow"] if best_profit >= 0 else COLORS["accent_red"]

                # Название предмета (только отображение)
                item_label = ctk.CTkLabel(
                    row,
                    text=market_hash_name[:50] + "..." if len(market_hash_name) > 50 else market_hash_name,
                    anchor="w",
                    font=ctk.CTkFont(size=13)
                )
                item_label.grid(row=0, column=0, padx=8, pady=6, sticky="ew")

                # Steam Buy Order (кнопка-ссылка на Steam Market)
                def open_steam(name=market_hash_name):
                    import webbrowser
                    encoded_name = name.replace(' ', '%20').replace('|', '%7C')
                    webbrowser.open(f"https://steamcommunity.com/market/listings/730/{encoded_name}")

                # Обработка None значений для steam_buy_order
                steam_price = item.get('steam_buy_order') or 0
                steam_btn = ctk.CTkButton(
                    row,
                    text=f"{steam_price:.2f} ₽",
                    command=open_steam,
                    fg_color="transparent",
                    hover_color=("gray70", "gray30"),
                    font=ctk.CTkFont(size=13)
                )
                steam_btn.grid(row=0, column=1, padx=8, pady=6, sticky="ew")

                # CSGO Market Sell (кнопка-ссылка)
                def open_csgotm(name=market_hash_name):
                    import webbrowser
                    encoded_name = quote(name)
                    webbrowser.open(f"https://market.csgo.com/ru/{encoded_name}")

                # Обработка None значений для csgo_price
                csgo_price = item.get('csgo_price') or 0
                csgo_btn = ctk.CTkButton(
                    row,
                    text=f"{csgo_price:.2f} ₽",
                    command=open_csgotm,
                    fg_color="transparent",
                    hover_color=("gray70", "gray30"),
                    font=ctk.CTkFont(size=13)
                )
                csgo_btn.grid(row=0, column=2, padx=8, pady=6, sticky="ew")

                # Профит
                profit_label = ctk.CTkLabel(
                    row,
                    text=f"{best_profit:.2f}%",
                    text_color=profit_color,
                    font=ctk.CTkFont(size=14, weight="bold")
                )
                profit_label.grid(row=0, column=3, padx=8, pady=6, sticky="ew")

                # Рекомендованная цена (обработка None)
                rec_price = item.get('recommended_buy_order') or 0
                rec_label = ctk.CTkLabel(
                    row,
                    text=f"{rec_price:.2f} ₽",
                    font=ctk.CTkFont(size=13)
                )
                rec_label.grid(row=0, column=4, padx=8, pady=6, sticky="ew")

                # Время обновления
                updated_label = ctk.CTkLabel(
                    row,
                    text=item.get('updated_at', 'N/A')[:16],
                    font=ctk.CTkFont(size=12)
                )
                updated_label.grid(row=0, column=5, padx=8, pady=6, sticky="ew")

                # Кнопки действий
                actions_frame = ctk.CTkFrame(row, fg_color="transparent")
                actions_frame.grid(row=0, column=6, padx=8, pady=6, sticky="ew")

                # Кнопка обновления
                def update_item(name=market_hash_name):
                    self._update_single_item(name)

                update_btn = ctk.CTkButton(
                    actions_frame,
                    text="🔄",
                    command=update_item,
                    width=60,
                    height=32,
                    fg_color=("gray75", "gray25"),
                    hover_color=("gray65", "gray35"),
                    font=ctk.CTkFont(size=16)
                )
                update_btn.pack(side="left", padx=3)

                # Кнопка удаления
                def delete_item(name=market_hash_name):
                    self._delete_profitable_item(name)

                delete_btn = ctk.CTkButton(
                    actions_frame,
                    text="🗑️",
                    command=delete_item,
                    width=60,
                    height=32,
                    fg_color=("red", "darkred"),
                    hover_color=("darkred", "red"),
                    font=ctk.CTkFont(size=16)
                )
                delete_btn.pack(side="left", padx=3)

        except Exception as e:
            logger.error(f"Error refreshing profitable items: {e}")

    def _delete_profitable_item(self, market_hash_name: str):
        """Удалить предмет из списка выгодных."""
        try:
            # Удаляем из БД
            trades_db.remove_profitable_item(market_hash_name)
            self._log(f"🗑️ Удален предмет: {market_hash_name}")

            # Обновляем отображение
            self._refresh_profitable_items()
        except Exception as e:
            logger.error(f"Error deleting profitable item: {e}")
            self._log(f"❌ Ошибка удаления предмета: {e}")

    def _update_single_item(self, market_hash_name: str):
        """Обновить данные одного предмета."""
        try:
            # Проверяем, не обновляем ли мы слишком часто
            if hasattr(self, '_last_update_time'):
                elapsed = time.time() - self._last_update_time
                if elapsed < 60.0:  # Минимум 60 секунд между обновлениями
                    remaining = 60.0 - elapsed
                    self._log(f"Подождите {remaining:.0f} секунд перед следующим обновлением (cooldown)")
                    return

            self._log(f"Обновление предмета: {market_hash_name}")
            self._log(f"Steam может заблокировать при частых запросах. Рекомендуется использовать 'Пересканировать все' вместо ручного обновления.")
            self._update_scanner_status(f"Обновление: {market_hash_name}", "yellow")

            self._last_update_time = time.time()

            # Запускаем обновление в отдельном потоке
            update_thread = threading.Thread(
                target=self._update_item_thread,
                args=(market_hash_name,),
                daemon=True
            )
            update_thread.start()
        except Exception as e:
            logger.error(f"Error updating item: {e}")
            self._log(f"Ошибка обновления предмета: {e}")

    def _update_item_thread(self, market_hash_name: str):
        """Поток для обновления одного предмета."""
        import asyncio

        try:
            asyncio.run(self._update_item_async(market_hash_name))
        except Exception as e:
            logger.error(f"Error in update item thread: {e}", exc_info=True)
            self._log(f"Ошибка обновления: {e}")
            self._update_scanner_status("Готов", "green")

    async def _update_item_async(self, market_hash_name: str):
        """Async update single item using aiosteampy."""
        try:
            from src.csgotm_client import CsgoTmClient
            import os

            # Get logged in account
            account = None
            if self.account_manager and len(self.account_manager.accounts) > 0:
                account = self.account_manager.accounts[0]
                if not account.is_logged_in():
                    self._log(f"⚠️ Аккаунт не залогинен")
                    self._update_scanner_status("Готов", "green")
                    return

            if not account:
                self._log(f"⚠️ Нет залогиненного аккаунта")
                self._update_scanner_status("Готов", "green")
                return

            steam_client = account.steam_client
            csgotm_client = account.csgotm_client

            # Get min profit from config
            min_profit = self.bot_config.get('min_profit_percent', 15)

            self._log(f"Запрос цены на Steam Market...")

            # Get current Steam price using aiosteampy
            histogram = await steam_client.get_item_histogram(market_hash_name)
            if not histogram or not histogram.get('highest_buy_order'):
                self._log(f"Не удалось получить данные Steam")
                self._update_scanner_status("Готов", "green")
                return

            steam_buy_order = histogram['highest_buy_order']
            steam_lowest_sell = histogram.get('lowest_sell_order')
            self._log(f"Steam buy order: {steam_buy_order:.2f} RUB")

            # Check for fake profit
            if steam_lowest_sell and steam_buy_order >= steam_lowest_sell:
                self._log(f"❌ ФЕЙК ПРОФИТ! Buy order ({steam_buy_order:.2f}) >= Lowest sell ({steam_lowest_sell:.2f})")
                self._log(f"Предмет {market_hash_name} удалён из списка")
                trades_db.mark_items_inactive([market_hash_name])
                self._update_scanner_status("Готов", "green")
                self.after(0, self._refresh_profitable_items)
                return

            # Get CSGO.TM price
            self._log(f"Запрос цены на CSGO.TM...")
            tm_price_data = csgotm_client.get_item_price(market_hash_name)
            if not tm_price_data or 'min_price' not in tm_price_data:
                self._log(f"Не удалось получить цену CSGO.TM для {market_hash_name}")
                self._update_scanner_status("Готов", "green")
                return

            csgo_price = tm_price_data['min_price']
            self._log(f"CSGO.TM price: {csgo_price:.2f} RUB")

            # Calculate profit (with 7% commission on CSGO.TM)
            net_revenue = csgo_price * 0.93
            if steam_buy_order > 0:
                instant_profit_pct = ((net_revenue - steam_buy_order) / steam_buy_order) * 100
            else:
                instant_profit_pct = 0

            # Recommended buy order price
            recommended_buy_order = steam_buy_order + 0.01

            # Check if still profitable
            if instant_profit_pct >= min_profit:
                # Update in DB
                trades_db.add_profitable_item(
                    market_hash_name=market_hash_name,
                    item_type='weapon',
                    steam_buy_order=steam_buy_order,
                    recommended_buy_order=recommended_buy_order,
                    csgo_price=csgo_price,
                    csgo_buy_order=0,
                    instant_profit_pct=instant_profit_pct,
                    wait_profit_pct=instant_profit_pct,
                    recommended_instant_pct=instant_profit_pct,
                    recommended_wait_pct=instant_profit_pct,
                    orders_above=0
                )
                self._log(f"Предмет обновлен: {market_hash_name} (профит: {instant_profit_pct:.2f}%)")
            else:
                self._log(f"Предмет больше не выгоден: {market_hash_name} (профит: {instant_profit_pct:.2f}% < {min_profit}%)")

            # Update display
            self.after(0, self._refresh_profitable_items)
            self._update_scanner_status("Готов", "green")

        except Exception as e:
            logger.error(f"Error updating item: {e}", exc_info=True)
            self._log(f"Ошибка обновления: {e}")
            self._update_scanner_status("Готов", "green")

    def _on_profit_filter_toggle(self):
        """Обработка переключения чекбокса фильтра по профиту."""
        if self.profit_filter_enabled_var.get():
            # Фильтр включен - активируем поле ввода
            self.parser_min_profit_entry.configure(state="normal")
        else:
            # Фильтр выключен - отключаем поле ввода
            self.parser_min_profit_entry.configure(state="disabled")

        # Автоматически применяем фильтр при переключении
        self._apply_profit_filter()

    def _apply_profit_filter(self):
        """Применить фильтр по минимальному профиту."""
        try:
            if self.profit_filter_enabled_var.get():
                # Фильтр включен - проверяем и сохраняем значение
                min_profit = float(self.parser_min_profit_entry.get())
                self.bot_config['scanner_min_profit'] = min_profit
                self._log(f"✅ Фильтр включен: мин. профит {min_profit}%")
            else:
                # Фильтр выключен - показываем все предметы
                self._log("✅ Фильтр по профиту выключен - показываем ВСЕ предметы")

            self._refresh_profitable_items()
        except ValueError:
            self._log("❌ Неверное значение минимального профита")

    def _load_proxies(self, proxy_file: str) -> list[str]:
        """Загрузить прокси из файла."""
        proxies = []
        proxy_path = Path(proxy_file)

        if not proxy_path.exists():
            self._log(f"ℹ️ Файл прокси не найден: {proxy_file}. Работаем без прокси.")
            return proxies

        try:
            with open(proxy_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue

                    # Auto-add socks5:// if no protocol specified
                    if '://' not in line:
                        line = f'socks5://{line}'

                    proxies.append(line)

            if proxies:
                self._log(f"✅ Загружено {len(proxies)} прокси из {proxy_file}")
            else:
                self._log(f"ℹ️ Файл прокси пуст: {proxy_file}. Работаем без прокси.")
        except Exception as e:
            self._log(f"❌ Ошибка чтения файла прокси: {e}. Работаем без прокси.")

        return proxies

    def _start_scanner(self):
        """Запустить сканер выгодных предметов."""
        # Prevent multiple simultaneous scans
        if hasattr(self, 'scanner_running') and self.scanner_running:
            self._log("⚠️ Сканер уже работает!")
            return

        self.scanner_running = True
        self._log("🔄 Запуск сканера TM Parser...")
        self.scanner_status_label.configure(text="Статус: запуск...", text_color="yellow")

        # Run scanner in separate thread to not block GUI
        scanner_thread = threading.Thread(target=self._run_scanner_subprocess, daemon=True)
        scanner_thread.start()

    def _rescan_all_items(self):
        """Пересканировать все предметы из БД."""
        if hasattr(self, 'scanner_running') and self.scanner_running:
            self._log("⚠️ Сканер уже работает!")
            return

        # Получаем все предметы из БД
        all_items = trades_db.get_all_profitable_items()

        if not all_items:
            self._log("⚠️ В базе нет предметов для пересканирования")
            return

        self._log(f"🔁 Пересканирование {len(all_items)} предметов из базы...")
        self._log("⚠️ Это может занять некоторое время (проверка актуальности цен)...")

        # Run rescan in background thread
        self.scanner_running = True
        self.scanner_status_label.configure(text="Статус: пересканирование...", text_color="yellow")
        rescan_thread = threading.Thread(target=self._rescan_items_thread, args=(all_items,), daemon=True)
        rescan_thread.start()

    def _rescan_items_thread(self, items: list[dict]):
        """Thread function for rescanning items."""
        import asyncio

        # Run async function in this thread
        try:
            asyncio.run(self._rescan_items_async(items))
        except Exception as e:
            logger.error(f"Rescan thread error: {e}", exc_info=True)
            self._log(f"❌ Ошибка пересканирования: {e}")
            self._update_scanner_status("Статус: ошибка", "red")
        finally:
            self.scanner_running = False

    async def _rescan_items_async(self, items: list[dict]):
        """Async rescan implementation using aiosteampy."""
        try:
            from src.csgotm_client import CsgoTmClient
            from src.steam_client_aiosteampy import SteamClientAio
            import os

            # Получаем конфиг первого аккаунта
            account = None
            if self.account_manager and len(self.account_manager.accounts) > 0:
                account = self.account_manager.accounts[0]

            if not account:
                self._log(f"⚠️ Нет аккаунтов для пересканирования")
                self._update_scanner_status("Статус: ошибка", "red")
                return

            account_currency = account.config.currency

            # Cookies хранятся в data/cookies/
            cookies_file = f"data/cookies/{account.name}_aio.json"

            if not os.path.exists(cookies_file):
                self._log(f"⚠️ Нет файла cookies: {cookies_file}")
                self._update_scanner_status("Статус: ошибка", "red")
                return

            self._log(f"🔄 Создаём новый Steam клиент для пересканирования...")

            # Получаем URL прокси из конфига
            proxy_url = None
            if account.config.proxy and account.config.proxy.enabled and account.config.proxy.url:
                proxy_url = account.config.proxy.url

            # Создаём НОВЫЙ SteamClient в текущем event loop
            steam_client = SteamClientAio(
                account_name=account.name,
                proxy=proxy_url,
                cookies_file=cookies_file,
            )

            # Логинимся с credentials (cookies будут загружены автоматически)
            success = await steam_client.login(
                username=account.config.steam_username,
                password=account.config.steam_password,
                shared_secret=account.config.steam_shared_secret,
                identity_secret=account.config.steam_identity_secret,
                api_key=account.config.steam_api_key,
                steam_id=account.config.steamid,
                cookie_file=cookies_file,
            )
            if success:
                self._log(f"✅ Steam клиент готов, валюта: {account_currency}")
            else:
                self._log(f"⚠️ Не удалось войти в Steam")
                self._update_scanner_status("Статус: ошибка", "red")
                return

            # Используем CSGO.TM клиент аккаунта или создаём новый
            csgotm_client = account.csgotm_client
            if not csgotm_client:
                self._log(f"ℹ️ Создаём CSGO.TM клиент...")
                csgotm_client = CsgoTmClient(api_key=account.config.csgotm_api_key)
                if not csgotm_client.ping():
                    self._log(f"⚠️ CSGO.TM не отвечает")
                    self._update_scanner_status("Статус: ошибка", "red")
                    return

            still_profitable = 0
            no_longer_profitable = 0
            errors = 0

            for idx, item in enumerate(items, 1):
                try:
                    item_name = item['market_hash_name']
                    self._log(f"[{idx}/{len(items)}] Проверка: {item_name}")

                    # Get current Steam price using aiosteampy
                    histogram = await steam_client.get_market_histogram(item_name)
                    if not histogram or not histogram.get('highest_buy_order'):
                        self._log(f"  ⚠️ Нет данных Steam")
                        errors += 1
                        continue

                    steam_buy_order = histogram['highest_buy_order']
                    steam_lowest_sell = histogram.get('lowest_sell_order')

                    # Check for fake profit
                    if steam_lowest_sell and steam_buy_order >= steam_lowest_sell:
                        self._log(f"  ❌ Фейк профит: buy {steam_buy_order:.0f} >= sell {steam_lowest_sell:.0f}")
                        trades_db.mark_items_inactive([item_name])
                        no_longer_profitable += 1
                        continue

                    # Get current CSGO.TM price
                    csgotm_price_data = csgotm_client.get_item_price(item_name)
                    if not csgotm_price_data or not csgotm_price_data.get('min_price'):
                        self._log(f"  ⚠️ Нет данных CSGO.TM")
                        errors += 1
                        continue

                    csgotm_price = csgotm_price_data['min_price']

                    # Log prices for debugging
                    steam_sell_str = f"{steam_lowest_sell:.2f}" if steam_lowest_sell else "N/A"
                    self._log(f"  💰 Цены: Steam buy={steam_buy_order:.2f}, sell={steam_sell_str}, CSGO.TM={csgotm_price:.2f}")

                    # Calculate profit
                    net_revenue = csgotm_price * 0.93
                    profit_pct = ((net_revenue - steam_buy_order) / steam_buy_order) * 100

                    # Check if still profitable
                    min_profit = float(self.scanner_profit_entry.get() or -5.0)
                    if profit_pct < min_profit:
                        self._log(f"  ❌ Больше не выгоден: профит {profit_pct:.1f}% < {min_profit}%")
                        trades_db.mark_items_inactive([item_name])
                        no_longer_profitable += 1
                    else:
                        self._log(f"  ✅ Актуален: профит {profit_pct:.1f}%")
                        # Update prices in DB
                        trades_db.add_or_update_profitable_item({
                            'market_hash_name': item_name,
                            'item_type': item.get('item_type', 'unknown'),
                            'steam_buy_order': steam_buy_order,
                            'recommended_buy_order': steam_buy_order,
                            'csgo_price': csgotm_price,
                            'csgo_buy_order': csgotm_price_data.get('buy_order', 0),
                            'instant_profit_pct': profit_pct,
                            'wait_profit_pct': profit_pct,
                            'recommended_instant_pct': profit_pct,
                            'recommended_wait_pct': profit_pct,
                            'orders_above': 0,
                        })
                        still_profitable += 1

                    # Small delay to avoid rate limits
                    await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Error rescanning {item.get('market_hash_name', 'unknown')}: {e}")
                    self._log(f"  ❌ Ошибка: {e}")
                    errors += 1

            self._log(f"\n✅ Пересканирование завершено!")
            self._log(f"Актуальны: {still_profitable}, Удалены: {no_longer_profitable}, Ошибки: {errors}")
            self._update_scanner_status("Статус: пересканирование завершено", "green")
            # Обновление GUI из фонового потока через after()
            self.after(0, self._refresh_profitable_items)

        except Exception as e:
            logger.error(f"Rescan error: {e}", exc_info=True)
            self._log(f"❌ Ошибка пересканирования: {e}")
            self._update_scanner_status("Статус: ошибка", "red")
        finally:
            # Закрываем созданный клиент
            if 'steam_client' in locals() and steam_client:
                try:
                    await steam_client.close()
                except Exception:
                    pass

    def _scan_new_items(self):
        """Искать только новые предметы (не в БД)."""
        if hasattr(self, 'scanner_running') and self.scanner_running:
            self._log("⚠️ Сканер уже работает!")
            return

        self._log("⭐ Поиск новых предметов (пропускаем те что уже в БД)...")

        # Get existing items from DB
        existing_items = trades_db.get_all_profitable_items()
        existing_names = {item['market_hash_name'] for item in existing_items}

        self._log(f"ℹ️ В базе {len(existing_names)} предметов, ищем новые...")
        self._log("ℹ️ Запускаю обычное сканирование с фильтрацией...")

        # Store skip list and run normal scanner
        self.skip_existing_items = existing_names
        self._start_scanner()

    def _scan_new_items_auto(self, max_items: int = 10):
        """
        Автоматическое сканирование новых предметов.
        Вызывается из AutoScanner.

        Args:
            max_items: Максимальное количество новых предметов для сканирования
        """
        if hasattr(self, 'scanner_running') and self.scanner_running:
            self._log("⚠️ Сканер уже работает, пропускаем автосканирование")
            return

        self._log(f"🔄 Автосканирование: поиск {max_items} новых предметов...")

        # Get existing items from DB
        existing_items = trades_db.get_all_profitable_items()
        existing_names = {item['market_hash_name'] for item in existing_items}

        self._log(f"ℹ️ В базе {len(existing_names)} предметов")

        # Store skip list and max items limit for scanner
        self.skip_existing_items = existing_names
        self.auto_scan_max_items = max_items
        self._start_scanner()

    def _run_scanner_subprocess(self):
        """Run scanner as subprocess (called from thread)."""
        import subprocess
        import json
        from pathlib import Path

        try:
            # Read settings from GUI
            config = {
                'min_price': float(self.min_price_entry.get() or 1000),
                'max_price': float(self.max_price_entry.get() or 10000),
                'min_profit': float(self.scanner_profit_entry.get() or -5.0),
                'min_sales_7d': int(self.sales_7d_entry.get() or 50),
                'proxy_file': self.proxy_file_entry.get() or 'proxies.txt',
                'requests_per_proxy': int(self.requests_per_proxy_entry.get() or 15),
                'max_items': int(self.max_items_entry.get() or 100),
                'delay': float(self.delay_entry.get() or 1.5),
                'workers': int(self.workers_entry.get() or 3),
            }

            self._log(f"📊 Настройки: цена {config['min_price']}-{config['max_price']}, мин. профит {config['min_profit']}%")
            self._log(f"📊 Макс. предметов: {config['max_items']}, задержка: {config['delay']}s, воркеров: {config['workers']}")

            # Save config to JSON file
            config_file = Path("scanner_config.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            # Start subprocess
            import sys
            process = subprocess.Popen(
                [sys.executable, "-m", "src.bottm.scanner_process"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Read output line by line
            for line in process.stdout:
                line = line.strip()
                if line:
                    # Parse log line and display in GUI
                    # Format: "HH:MM:SS [LEVEL] module: message"
                    if '[INFO]' in line or '[WARNING]' in line or '[ERROR]' in line:
                        # Extract just the message part
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            message = parts[2].strip()
                        else:
                            message = line
                        self._log(message)
                    else:
                        self._log(line)

            # Wait for process to complete
            return_code = process.wait()

            if return_code == 0:
                self._log("✅ Сканирование завершено успешно!")
                self._update_scanner_status("Статус: завершено", "green")
                # Обновление GUI из фонового потока через after()
                self.after(0, self._refresh_profitable_items)
            else:
                self._log(f"❌ Сканер завершился с ошибкой (код: {return_code})")
                self._update_scanner_status("Статус: ошибка", "red")

        except Exception as e:
            logger.error(f"Scanner subprocess error: {e}", exc_info=True)
            self._log(f"❌ Ошибка сканера: {e}")
            self._update_scanner_status("Статус: ошибка", "red")
        finally:
            self.scanner_running = False

    def _log(self, message: str):
        """Добавить сообщение в логи (thread-safe)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"

        # Schedule GUI update in main thread
        def update_log():
            try:
                self.logs_text.configure(state="normal")
                self.logs_text.insert("end", log_line)
                self.logs_text.see("end")
                self.logs_text.configure(state="disabled")
            except Exception:
                # Widget might be destroyed, ignore
                pass

        try:
            self.after(0, update_log)
        except Exception:
            # If after() fails, just print to console
            pass

        # Также выводим в консоль (с обработкой кодировки для Windows)
        try:
            print(log_line.strip())
        except UnicodeEncodeError:
            # Если консоль не поддерживает UTF-8, выводим без эмодзи
            print(log_line.strip().encode('ascii', 'ignore').decode('ascii'))

    def _update_scanner_status(self, text: str, color: str):
        """Update scanner status label (thread-safe)."""
        def update():
            try:
                self.scanner_status_label.configure(text=text, text_color=color)
            except Exception:
                pass

        try:
            self.after(0, update)
        except Exception:
            pass

    def _clear_logs(self):
        """Очистить логи."""
        self.logs_text.configure(state="normal")
        self.logs_text.delete("1.0", "end")
        self.logs_text.configure(state="disabled")

    def _add_account(self):
        """Добавить новый аккаунт (заглушка)."""
        self._log("ℹ️ Функция добавления аккаунта еще не реализована")

    def _toggle_account(self, account):
        """Переключить статус аккаунта (включить/выключить)."""
        # Переключаем статус
        account.config.enabled = not account.config.enabled

        status = "включен" if account.config.enabled else "выключен"
        self._log(f"ℹ️ Аккаунт {account.name} {status}")

        # Обновляем отображение
        self._refresh_accounts_list()

        # Сохраняем изменения в файл конфигурации
        self._save_accounts_config()

    def _save_accounts_config(self):
        """Сохранить текущую конфигурацию аккаунтов в файл."""
        if not self.account_manager:
            return

        import json
        from pathlib import Path

        config_file = Path("accounts.json")

        try:
            # Собираем данные всех аккаунтов
            accounts_data = []
            for account in self.account_manager.accounts:
                acc_data = {
                    "name": account.config.name,
                    "enabled": account.config.enabled,
                    "currency": account.config.currency,
                    "steam": {
                        "username": account.config.steam_username,
                        "password": account.config.steam_password,
                        "api_key": account.config.steam_api_key,
                        "shared_secret": account.config.steam_shared_secret,
                        "identity_secret": account.config.steam_identity_secret,
                        "steamid": account.config.steamid or ""
                    },
                    "csgotm": {
                        "api_key": account.config.csgotm_api_key
                    },
                    "limits": {
                        "max_items": account.config.max_items,
                        "max_price_per_item": account.config.max_price_per_item,
                        "total_budget": account.config.total_budget
                    }
                }

                # Добавляем прокси, если есть (конвертируем объект в dict)
                if account.config.proxy:
                    acc_data["proxy"] = {
                        "enabled": account.config.proxy.enabled,
                        "url": account.config.proxy.url or ""
                    }
                else:
                    acc_data["proxy"] = {
                        "enabled": False,
                        "url": ""
                    }

                accounts_data.append(acc_data)

            # Сохраняем в файл с красивым форматированием (атомарная запись)
            import os
            import tempfile
            import shutil

            # Create backup
            backup_file = str(config_file) + '.backup'
            if config_file.exists():
                shutil.copy2(config_file, backup_file)

            # Write to temporary file first
            temp_fd, temp_path = tempfile.mkstemp(dir=config_file.parent, text=True)
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(accounts_data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                # Replace original file atomically
                shutil.move(temp_path, str(config_file))
                logger.info(f"Accounts config saved to {config_file}")

            except Exception as write_error:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise write_error

        except Exception as e:
            logger.error(f"Failed to save accounts config: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self._log(f"❌ Ошибка сохранения конфигурации: {e}")

    def _detect_account_currency(self, account):
        """
        Определить валюту аккаунта автоматически из Steam.

        Args:
            account: Account instance
        """
        def detect_thread():
            try:
                self._log(f"Определение валюты для аккаунта {account.name}...")

                # Проверяем, залогинен ли аккаунт
                if not account.is_logged_in():
                    self._log(f"Аккаунт {account.name} не залогинен. Попытка логина...")
                    success = account.login_sync()
                    if not success:
                        self._log(f"Не удалось залогиниться для {account.name}")
                        return

                # Используем новый async метод через sync обертку
                detected_currency = account.detect_currency_sync()

                if detected_currency:
                    self._log(f"Валюта для {account.name}: {detected_currency}")

                    # Обновляем отображение
                    self.after(0, self._refresh_accounts_list)

                    # Обновляем баланс в GUI
                    if account.name in self.account_balance_labels:
                        try:
                            steam_balance = account.get_wallet_balance_sync()
                            csgotm_balance = account.get_csgotm_balance()

                            if detected_currency != 'RUB':
                                from src.currency_converter import currency_converter
                                csgotm_converted = currency_converter.convert_from_rub(csgotm_balance, detected_currency)
                                balance_text = f"💰 Steam: {steam_balance:.2f} {detected_currency} | TM: {csgotm_converted:.2f} {detected_currency} ({csgotm_balance:.2f} RUB)"
                            else:
                                balance_text = f"💰 Steam: {steam_balance:.2f} {detected_currency} | TM: {csgotm_balance:.2f} {detected_currency}"

                            self.after(0, lambda: self.account_balance_labels[account.name].configure(text=balance_text))
                        except Exception as e:
                            logger.error(f"Failed to update balance display: {e}")

                    # Сохраняем изменения
                    self._save_accounts_config()
                else:
                    self._log(f"Не удалось определить валюту для {account.name}")

            except Exception as e:
                logger.error(f"Error detecting currency for {account.name}: {e}")
                import traceback
                traceback.print_exc()
                self._log(f"Ошибка определения валюты: {e}")

        # Запускаем в отдельном потоке
        thread = threading.Thread(target=detect_thread, daemon=True)
        thread.start()

    def _detect_all_currencies(self):
        """Определить валюту для всех аккаунтов."""
        if not self.account_manager:
            self._log("❌ Аккаунты не загружены")
            return

        def detect_all_thread():
            try:
                self._log("🔍 Начинаем определение валюты для всех аккаунтов...")

                for account in self.account_manager.accounts:
                    if not account.config.enabled:
                        self._log(f"⏭️ Пропускаем {account.name} (выключен)")
                        continue

                    self._log(f"Определение валюты для аккаунта {account.name}...")

                    # Проверяем, залогинен ли аккаунт
                    if not account.is_logged_in():
                        self._log(f"Аккаунт {account.name} не залогинен. Попытка логина...")
                        success = account.login_sync()
                        if not success:
                            self._log(f"❌ Не удалось залогиниться для {account.name}")
                            continue

                    # Определяем валюту
                    detected_currency = account.detect_currency_sync()

                    if detected_currency:
                        self._log(f"✅ Валюта для {account.name}: {detected_currency}")

                        # Обновляем баланс
                        try:
                            steam_balance = account.get_wallet_balance_sync()
                            csgotm_balance = account.get_csgotm_balance()

                            if detected_currency != 'RUB':
                                from src.currency_converter import currency_converter
                                csgotm_converted = currency_converter.convert_from_rub(csgotm_balance, detected_currency)
                                balance_text = f"💰 Steam: {steam_balance:.2f} {detected_currency} | TM: {csgotm_converted:.2f} {detected_currency} ({csgotm_balance:.2f} RUB)"
                            else:
                                balance_text = f"💰 Steam: {steam_balance:.2f} {detected_currency} | TM: {csgotm_balance:.2f} {detected_currency}"

                            if account.name in self.account_balance_labels:
                                self.after(0, lambda text=balance_text, name=account.name:
                                    self.account_balance_labels[name].configure(text=text))
                        except Exception as e:
                            logger.error(f"Failed to update balance for {account.name}: {e}")
                    else:
                        self._log(f"❌ Не удалось определить валюту для {account.name}")

                # Обновляем GUI
                self.after(0, self._refresh_accounts_list)
                self.after(0, self._update_dashboard_stats)

                # Сохраняем изменения
                self._save_accounts_config()

                self._log("✅ Определение валюты завершено для всех аккаунтов")

            except Exception as e:
                logger.error(f"Error detecting all currencies: {e}")
                import traceback
                traceback.print_exc()
                self._log(f"❌ Ошибка определения валют: {e}")

        # Запускаем в отдельном потоке
        thread = threading.Thread(target=detect_all_thread, daemon=True)
        thread.start()

    # ============================================================
    # НОВЫЕ МЕТОДЫ: Auto Buyer, Auto Scanner, Statistics
    # ============================================================

    def _toggle_auto_scan(self):
        """Переключить автосканирование."""
        if self.auto_scanner and self.auto_scanner.is_running():
            # Остановить
            self.auto_scanner.stop()
            self.auto_scan_toggle_btn.configure(
                text="⏰ Auto Scan: OFF",
                fg_color="#95A5A6"
            )
            self._log("⏰ Автосканирование остановлено")
        else:
            # Запустить
            scan_interval = self.bot_config.get('auto_scan_interval', 30)
            rescan_interval = self.bot_config.get('auto_rescan_interval', 60)
            new_items_count = self.bot_config.get('auto_scan_new_items', 10)

            # Создаём AutoScanner если его нет
            if not self.auto_scanner:
                self.auto_scanner = AutoScanner(
                    scan_callback=self._start_scanner,
                    rescan_callback=self._rescan_all_items,
                    new_items_callback=self._scan_new_items_auto,
                    interval_minutes=scan_interval,
                    rescan_interval_minutes=rescan_interval,
                    new_items_count=new_items_count,
                    enabled=False
                )

            self.auto_scanner.set_interval(scan_interval)
            self.auto_scanner.set_rescan_interval(rescan_interval)
            self.auto_scanner.set_new_items_count(new_items_count)
            self.auto_scanner.start()

            self.auto_scan_toggle_btn.configure(
                text=f"⏰ Auto Scan: ON ({scan_interval}m)",
                fg_color="#27AE60"
            )
            self._log(f"⏰ Автосканирование запущено:")
            self._log(f"   - Новые предметы: каждые {scan_interval} минут ({new_items_count} шт)")
            self._log(f"   - Пересканирование: каждые {rescan_interval} минут")

    def _show_statistics_window(self):
        """Показать окно статистики."""
        # Создаём окно статистики
        stats_window = ctk.CTkToplevel(self)
        stats_window.title("Статистика торговли")
        stats_window.geometry("900x700")
        stats_window.transient(self)

        # Создаём TradingStatistics если его нет
        if not self.statistics:
            self.statistics = TradingStatistics(trades_db)

        # Заголовок
        header_frame = ctk.CTkFrame(stats_window)
        header_frame.pack(fill="x", padx=20, pady=20)

        header = ctk.CTkLabel(
            header_frame,
            text="Статистика торговли",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        header.pack(side="left")

        # Выбор периода
        period_frame = ctk.CTkFrame(stats_window)
        period_frame.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(period_frame, text="Период:", font=ctk.CTkFont(size=14)).pack(side="left", padx=10)

        period_var = ctk.StringVar(value="30")
        period_options = ctk.CTkOptionMenu(
            period_frame,
            values=["7", "14", "30", "60", "90", "365"],
            variable=period_var,
            width=100,
            font=ctk.CTkFont(size=13)
        )
        period_options.pack(side="left", padx=5)

        ctk.CTkLabel(period_frame, text="дней", font=ctk.CTkFont(size=14)).pack(side="left", padx=5)

        # Кнопка обновления
        refresh_btn = ctk.CTkButton(
            period_frame,
            text="Обновить",
            command=lambda: update_report(),
            width=120,
            height=32,
            font=ctk.CTkFont(size=13)
        )
        refresh_btn.pack(side="right", padx=10)

        # Scrollable frame для статистики
        stats_scroll = ctk.CTkScrollableFrame(stats_window)
        stats_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # Контейнеры для данных
        summary_label = ctk.CTkLabel(
            stats_scroll,
            text="",
            font=ctk.CTkFont(size=13),
            anchor="w",
            justify="left"
        )
        summary_label.pack(fill="both", expand=True, padx=10, pady=10)

        def update_report():
            try:
                days = int(period_var.get())
                summary = self.statistics.get_summary(days=days)

                if not summary:
                    summary_label.configure(text="Нет данных для отображения")
                    return

                # Форматируем статистику
                text = f"""
ОТЧЁТ О ТОРГОВЛЕ (за {summary['period_days']} дней)
{'=' * 60}

ПОКУПКИ И ПРОДАЖИ:
  Куплено:              {summary['items_purchased']} шт
  Продано:              {summary['items_sold']} шт

АКТИВНЫЕ ПОЗИЦИИ:
  Buy ордеров на Steam: {summary.get('active_orders', 0)} шт
  Выгодных предметов:   {summary['active_profitable_items']} шт

ФИНАНСЫ:
  Потрачено:            {summary['total_spent']:.2f} ₽
  Получено:             {summary['total_earned']:.2f} ₽
  Профит:               {summary['total_profit']:.2f} ₽

ЭФФЕКТИВНОСТЬ:
  ROI:                  {summary['roi_percent']:.2f} %
  Ср. профит:           {summary['avg_profit_per_trade']:.2f} ₽/сделка

{'=' * 60}

Примечания:
- "Buy ордеров" - активные заявки на покупку на Steam Market
- "Выгодных предметов" - найденные предметы с профитом в TM Parser
"""
                summary_label.configure(text=text)

            except Exception as e:
                logger.error(f"Error updating report: {e}", exc_info=True)
                summary_label.configure(text=f"Ошибка загрузки статистики: {e}")

        # Загружаем отчёт
        update_report()

    def _export_data(self):
        """Экспортировать данные в CSV."""
        def export_thread():
            try:
                self._log("📤 Экспорт данных...")

                # Создаём TradingStatistics если его нет
                if not self.statistics:
                    self.statistics = TradingStatistics(trades_db)

                # Создаём папку exports
                export_dir = Path("exports")
                export_dir.mkdir(exist_ok=True)

                # Генерируем имя файла с датой
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = export_dir / f"trading_data_{timestamp}.csv"

                # Экспортируем все данные
                success = self.statistics.export_to_csv(
                    output_file=str(output_file),
                    data_type='all',
                    days=30
                )

                if success:
                    self._log(f"✅ Данные экспортированы в {output_file.parent}")
                    self._log(f"   - {output_file.stem}_purchased.csv")
                    self._log(f"   - {output_file.stem}_sold.csv")
                    self._log(f"   - {output_file.stem}_profitable.csv")
                else:
                    self._log("❌ Ошибка экспорта данных")

            except Exception as e:
                logger.error(f"Error exporting data: {e}", exc_info=True)
                self._log(f"❌ Ошибка экспорта: {e}")

        thread = threading.Thread(target=export_thread, daemon=True)
        thread.start()

    def _on_closing(self):
        """Обработка закрытия окна."""
        if self.bot_running:
            self._stop_bot()
            time.sleep(1)

        # Shutdown AsyncRunner
        if hasattr(self, 'async_runner') and self.async_runner:
            from src.async_helper import shutdown_async_runner
            logger.info("Shutting down AsyncRunner...")
            shutdown_async_runner()

        self.destroy()


def main():
    """Запуск GUI приложения."""
    app = TradingBotGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
