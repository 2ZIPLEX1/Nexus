"""
Settings view - comprehensive bot configuration.
"""

import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState
import json


def create_settings_view(config_service=None, page=None) -> ft.Container:
    """Settings view with all configuration options."""
    state = AppState()
    config = state.config

    # Refs for all input fields
    # General
    min_profit_ref = ft.Ref[ft.TextField]()
    cycle_interval_ref = ft.Ref[ft.TextField]()
    db_path_ref = ft.Ref[ft.TextField]()
    auto_refresh_ref = ft.Ref[ft.Switch]()
    debug_mode_ref = ft.Ref[ft.Switch]()

    # Trading (выставление ордеров)
    trade_min_price_ref = ft.Ref[ft.TextField]()
    trade_max_price_ref = ft.Ref[ft.TextField]()
    check_orders_min_profit_ref = ft.Ref[ft.TextField]()

    # TM Parser
    scanner_min_price_ref = ft.Ref[ft.TextField]()
    scanner_max_price_ref = ft.Ref[ft.TextField]()
    scanner_min_profit_ref = ft.Ref[ft.TextField]()
    csgo_commission_ref = ft.Ref[ft.TextField]()
    min_sales_7d_ref = ft.Ref[ft.TextField]()

    # TM Parser - дополнительные
    proxy_file_ref = ft.Ref[ft.TextField]()
    requests_per_proxy_ref = ft.Ref[ft.TextField]()
    scanner_max_items_ref = ft.Ref[ft.TextField]()
    scanner_delay_ref = ft.Ref[ft.TextField]()
    scanner_workers_ref = ft.Ref[ft.TextField]()

    # Auto Scanner
    auto_scan_interval_ref = ft.Ref[ft.TextField]()
    auto_scan_new_items_ref = ft.Ref[ft.TextField]()
    auto_rescan_interval_ref = ft.Ref[ft.TextField]()

    # Proxy Manager
    proxy_max_requests_ref = ft.Ref[ft.TextField]()
    proxy_cooldown_ref = ft.Ref[ft.TextField]()
    proxy_blacklist_duration_ref = ft.Ref[ft.TextField]()

    # Price Monitoring (TM Sales)
    auto_update_prices_ref = ft.Ref[ft.Switch]()
    price_threshold_ref = ft.Ref[ft.TextField]()

    def create_section(title: str, icon: str = "⚙️"):
        """Create settings section header."""
        return ft.Container(
            content=ft.Row([
                ft.Text(icon, size=FONT_SIZES["xl"]),
                ft.Text(title, size=FONT_SIZES["lg"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ], spacing=8),
            margin=ft.margin.only(top=12, bottom=8),
        )

    def create_field(label: str, ref, value, width: int = 250, hint: str = ""):
        """Create text field."""
        return ft.TextField(
            ref=ref,
            label=label,
            value=str(value),
            width=width,
            height=50,
            border_color=COLORS["border"],
            hint_text=hint,
            text_size=FONT_SIZES["sm"],
        )

    def create_switch(label: str, ref, value: bool):
        """Create switch control."""
        return ft.Switch(
            ref=ref,
            label=label,
            value=value,
            active_color=COLORS["accent_purple"],
        )

    async def on_save(e):
        """Save settings to config (non-blocking file I/O)."""
        try:
            # Collect all values (UI reads are instant)
            new_config = {
                # General
                'min_profit_pct': float(min_profit_ref.current.value),
                'cycle_interval_minutes': int(cycle_interval_ref.current.value),
                'bottm_db_path': db_path_ref.current.value,
                'auto_refresh': auto_refresh_ref.current.value,
                'debug_mode': debug_mode_ref.current.value,

                # Trading
                'trade_min_price': float(trade_min_price_ref.current.value),
                'trade_max_price': float(trade_max_price_ref.current.value),
                'check_orders_min_profit': float(check_orders_min_profit_ref.current.value),

                # TM Parser
                'scanner_min_price': float(scanner_min_price_ref.current.value),
                'scanner_max_price': float(scanner_max_price_ref.current.value),
                'scanner_min_profit': float(scanner_min_profit_ref.current.value),
                'csgo_commission': float(csgo_commission_ref.current.value),
                'min_sales_7d': int(min_sales_7d_ref.current.value),

                # TM Parser - дополнительные
                'proxy_file': proxy_file_ref.current.value,
                'requests_per_proxy': int(requests_per_proxy_ref.current.value),
                'scanner_max_items': int(scanner_max_items_ref.current.value),
                'scanner_delay': float(scanner_delay_ref.current.value),
                'scanner_workers': int(scanner_workers_ref.current.value),

                # Auto Scanner
                'auto_scan_interval': int(auto_scan_interval_ref.current.value),
                'auto_scan_new_items': int(auto_scan_new_items_ref.current.value),
                'auto_rescan_interval': int(auto_rescan_interval_ref.current.value),

                # Proxy Manager
                'proxy_max_requests': int(proxy_max_requests_ref.current.value),
                'proxy_cooldown': int(proxy_cooldown_ref.current.value),
                'proxy_blacklist_duration': int(proxy_blacklist_duration_ref.current.value),

                # Price Monitoring (TM Sales)
                'auto_update_prices': auto_update_prices_ref.current.value,
                'price_check_threshold_percent': float(price_threshold_ref.current.value),
            }

            # Update state config
            state.config.update(new_config)

            # Save to file (non-blocking I/O)
            import asyncio
            if config_service:
                await asyncio.to_thread(config_service.save_config)
            else:
                def _save_direct():
                    with open("bot_config.json", 'w', encoding='utf-8') as f:
                        json.dump(state.config, f, indent=2, ensure_ascii=False)
                await asyncio.to_thread(_save_direct)

            state.add_log("[SUCCESS] Settings saved to bot_config.json")

            if page:
                page.update()

        except ValueError as ex:
            state.add_log(f"[ERROR] Invalid value format: {str(ex)}")
        except Exception as ex:
            state.add_log(f"[ERROR] Failed to save settings: {str(ex)}")

    def on_reset(e):
        """Reset to default values."""
        # Set default values
        defaults = {
            'min_profit_pct': 5.0,
            'cycle_interval_minutes': 5,
            'bottm_db_path': 'data/my_trades.db',
            'auto_refresh': True,
            'debug_mode': False,
            'trade_min_price': 1000.0,
            'trade_max_price': 10000.0,
            'check_orders_min_profit': 5.0,
            'scanner_min_price': 1000.0,
            'scanner_max_price': 10000.0,
            'scanner_min_profit': -5.0,
            'csgo_commission': 10.0,
            'min_sales_7d': 50,
            'proxy_file': 'proxies.txt',
            'requests_per_proxy': 50,
            'scanner_max_items': 10,
            'scanner_delay': 7.0,
            'scanner_workers': 1,
            'auto_scan_interval': 30,
            'auto_scan_new_items': 10,
            'auto_rescan_interval': 60,
            'proxy_max_requests': 100,
            'proxy_cooldown': 60,
            'proxy_blacklist_duration': 300,
            'auto_update_prices': False,
            'price_check_threshold_percent': 10.0,
        }

        # Update all fields
        min_profit_ref.current.value = str(defaults['min_profit_pct'])
        cycle_interval_ref.current.value = str(defaults['cycle_interval_minutes'])
        db_path_ref.current.value = defaults['bottm_db_path']
        auto_refresh_ref.current.value = defaults['auto_refresh']
        debug_mode_ref.current.value = defaults['debug_mode']

        trade_min_price_ref.current.value = str(defaults['trade_min_price'])
        trade_max_price_ref.current.value = str(defaults['trade_max_price'])
        check_orders_min_profit_ref.current.value = str(defaults['check_orders_min_profit'])

        scanner_min_price_ref.current.value = str(defaults['scanner_min_price'])
        scanner_max_price_ref.current.value = str(defaults['scanner_max_price'])
        scanner_min_profit_ref.current.value = str(defaults['scanner_min_profit'])
        csgo_commission_ref.current.value = str(defaults['csgo_commission'])
        min_sales_7d_ref.current.value = str(defaults['min_sales_7d'])

        proxy_file_ref.current.value = defaults['proxy_file']
        requests_per_proxy_ref.current.value = str(defaults['requests_per_proxy'])
        scanner_max_items_ref.current.value = str(defaults['scanner_max_items'])
        scanner_delay_ref.current.value = str(defaults['scanner_delay'])
        scanner_workers_ref.current.value = str(defaults['scanner_workers'])

        auto_scan_interval_ref.current.value = str(defaults['auto_scan_interval'])
        auto_scan_new_items_ref.current.value = str(defaults['auto_scan_new_items'])
        auto_rescan_interval_ref.current.value = str(defaults['auto_rescan_interval'])

        proxy_max_requests_ref.current.value = str(defaults['proxy_max_requests'])
        proxy_cooldown_ref.current.value = str(defaults['proxy_cooldown'])
        proxy_blacklist_duration_ref.current.value = str(defaults['proxy_blacklist_duration'])

        auto_update_prices_ref.current.value = defaults['auto_update_prices']
        price_threshold_ref.current.value = str(defaults['price_check_threshold_percent'])

        state.add_log("[INFO] Settings reset to defaults")

        if page:
            page.update()

    # Settings form with all sections
    settings_form = ft.Container(
        content=ft.Column(
            [
                # === General Settings ===
                create_section("Общие настройки", "⚙️"),
                ft.Row([
                    create_field("Минимальный профит (%)", min_profit_ref, config.get('min_profit_pct', 5.0)),
                    create_field("Интервал цикла (мин)", cycle_interval_ref, config.get('cycle_interval_minutes', 5)),
                ], spacing=16),
                create_field("Путь к БД", db_path_ref, config.get('bottm_db_path', 'data/my_trades.db'), width=520),
                ft.Row([
                    create_switch("Автообновление", auto_refresh_ref, config.get('auto_refresh', True)),
                    create_switch("Режим отладки", debug_mode_ref, config.get('debug_mode', False)),
                ], spacing=32),

                ft.Divider(height=20, color=COLORS["border"]),

                # === Trading Settings ===
                create_section("Выставление ордеров", "💰"),
                ft.Row([
                    create_field("Мин. цена (RUB)", trade_min_price_ref, config.get('trade_min_price', 1000.0)),
                    create_field("Макс. цена (RUB)", trade_max_price_ref, config.get('trade_max_price', 10000.0)),
                ], spacing=16),
                ft.Row([
                    create_field("Мин. профит для проверки (%)", check_orders_min_profit_ref, config.get('check_orders_min_profit', 5.0)),
                ], spacing=16),

                ft.Divider(height=20, color=COLORS["border"]),

                # === TM Parser Settings ===
                create_section("TM Parser (сканер выгодных предметов)", "🔍"),
                ft.Row([
                    create_field("Мин. цена (RUB)", scanner_min_price_ref, config.get('scanner_min_price', 1000.0)),
                    create_field("Макс. цена (RUB)", scanner_max_price_ref, config.get('scanner_max_price', 10000.0)),
                ], spacing=16),
                ft.Row([
                    create_field("Мин. профит (%)", scanner_min_profit_ref, config.get('scanner_min_profit', -5.0)),
                    create_field("Комиссия CSGO.TM (%)", csgo_commission_ref, config.get('csgo_commission', 10.0)),
                ], spacing=16),
                create_field("Мин. продаж за 7 дней", min_sales_7d_ref, config.get('min_sales_7d', 50)),

                # TM Parser - дополнительные настройки
                ft.Text("Дополнительные настройки сканера", size=FONT_SIZES["base"], weight=ft.FontWeight.W_500, color=COLORS["text_secondary"]),
                create_field("Файл с прокси", proxy_file_ref, config.get('proxy_file', 'proxies.txt'), width=520),
                ft.Row([
                    create_field("Запросов на прокси", requests_per_proxy_ref, config.get('requests_per_proxy', 50)),
                    create_field("Макс. предметов", scanner_max_items_ref, config.get('scanner_max_items', 10)),
                ], spacing=16),
                ft.Row([
                    create_field("Задержка (сек)", scanner_delay_ref, config.get('scanner_delay', 7.0)),
                    create_field("Количество воркеров", scanner_workers_ref, config.get('scanner_workers', 1)),
                ], spacing=16),

                ft.Divider(height=20, color=COLORS["border"]),

                # === Auto Scanner Settings ===
                create_section("Auto Scanner (автоматическое сканирование)", "⏰"),
                ft.Row([
                    create_field("Интервал новых (мин)", auto_scan_interval_ref, config.get('auto_scan_interval', 30)),
                    create_field("Кол-во новых", auto_scan_new_items_ref, config.get('auto_scan_new_items', 10)),
                ], spacing=16),
                create_field("Интервал ресканирования (мин)", auto_rescan_interval_ref, config.get('auto_rescan_interval', 60)),

                ft.Divider(height=20, color=COLORS["border"]),

                # === Proxy Manager Settings ===
                create_section("Proxy Manager (ротация прокси)", "🔄"),
                ft.Row([
                    create_field("Макс. запросов", proxy_max_requests_ref, config.get('proxy_max_requests', 100)),
                    create_field("Cooldown (сек)", proxy_cooldown_ref, config.get('proxy_cooldown', 60)),
                ], spacing=16),
                create_field("Время блокировки (сек)", proxy_blacklist_duration_ref, config.get('proxy_blacklist_duration', 300)),

                ft.Divider(height=20, color=COLORS["border"]),

                # === Price Monitoring Settings (TM Sales) ===
                create_section("Мониторинг цен (TM Sales)", "💰"),
                ft.Container(
                    content=ft.Column([
                        create_switch(
                            "Автоматически обновлять цены",
                            auto_update_prices_ref,
                            config.get('auto_update_prices', False)
                        ),
                        ft.Text(
                            "• Включено: цены обновляются автоматически до топ-1\n"
                            "• Выключено: уведомления в Telegram с кнопками для выбора",
                            size=FONT_SIZES["xs"],
                            color=COLORS["text_secondary"],
                        ),
                        create_field(
                            "Порог для уведомления (%)",
                            price_threshold_ref,
                            config.get('price_check_threshold_percent', 10.0),
                            hint="Если цена выше рынка на X%"
                        ),
                    ], spacing=4),
                    padding=ft.padding.only(left=8),
                ),

                ft.Divider(height=30, color=COLORS["border"]),

                # Action Buttons
                ft.Row([
                    ft.FilledButton(
                        "💾 Сохранить настройки",
                        icon=ft.Icons.SAVE,
                        on_click=on_save,
                        style=ft.ButtonStyle(
                            bgcolor=COLORS["accent_purple"],
                            color="white",
                        ),
                    ),
                    ft.FilledButton(
                        "🔄 Сбросить",
                        icon=ft.Icons.REFRESH,
                        on_click=on_reset,
                        style=ft.ButtonStyle(
                            bgcolor=COLORS["accent_red"],
                            color="white",
                        ),
                    ),
                ], spacing=12),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        bgcolor=COLORS["bg_surface"],
        border=ft.border.all(1, COLORS["border"]),
        border_radius=RADIUS["lg"],
        padding=20,
        expand=True,
    )

    return ft.Container(
        content=ft.Column(
            [
                # Header
                ft.Text(
                    "Настройки бота",
                    size=FONT_SIZES["2xl"],
                    weight=ft.FontWeight.BOLD,
                    color=COLORS["text_primary"],
                ),
                ft.Text(
                    "Конфигурация поведения бота и параметров торговли",
                    size=FONT_SIZES["sm"],
                    color=COLORS["text_secondary"],
                ),
                # Settings form
                settings_form,
            ],
            spacing=16,
            expand=True,
        ),
        padding=20,
        expand=True,
    )


SettingsView = create_settings_view
