"""
Dashboard view - reactive with refs and state subscriptions.
"""

import flet as ft

from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState
from src.currency_rates import get_currency_provider


def create_dashboard_view(page=None) -> ft.Container:
    """Dashboard with uniform stat cards and tables - reactive updates."""
    state = AppState()

    # Helper to create stat cards with background
    def make_card(title, value, icon, icon_color):
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(icon, color=icon_color, size=24),
                    ft.Text(title, size=FONT_SIZES["xs"], color=COLORS["text_secondary"]),
                ], spacing=8),
                ft.Text(value, size=FONT_SIZES["xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ], spacing=6),
            padding=12,
            bgcolor=COLORS["bg_surface"],
            border=ft.border.all(1, COLORS["border"]),
            border_radius=RADIUS["md"],
            col={"sm": 12, "md": 6, "lg": 4, "xl": 2},
        )

    def build_stat_cards():
        """Build stat cards from current state."""
        stats = state.stats
        accounts = state.accounts

        # Calculate total balances with real-time currency conversion
        currency_provider = get_currency_provider()
        total_steam = 0
        total_tm = 0
        total_settlement = 0

        for acc in accounts:
            steam_bal = acc.steam_balance or 0
            tm_bal = acc.csgotm_balance or 0
            settlement_bal = acc.csgotm_settlement or 0
            currency = acc.currency or "RUB"

            # Convert Steam balance to RUB
            steam_bal_rub = currency_provider.convert_to_rub(steam_bal, currency)

            # CSGO.TM balances are ALWAYS in RUB - no conversion needed
            tm_bal_rub = tm_bal
            settlement_bal_rub = settlement_bal

            total_steam += steam_bal_rub
            total_tm += tm_bal_rub
            total_settlement += settlement_bal_rub

        # Calculate stats from all accounts
        active_orders_count = len(state.active_orders)
        items_on_hold_count = len(state.items_on_hold)
        total_profit_value = sum(s.get('profit', 0) or 0 for s in state.recent_sales)
        total_sales_count = len(state.recent_sales)

        # Use 'or 0' to handle None values
        return [
            make_card("Steam Balance", f"{total_steam:,.0f} RUB",
                     ft.Icons.ACCOUNT_BALANCE_WALLET, COLORS["accent_blue"]),
            make_card("CSGO.TM Balance", f"{total_tm:,.0f} RUB",
                     ft.Icons.CURRENCY_EXCHANGE, COLORS["accent_purple"]),
            make_card("Money in Hold", f"{total_settlement:,.0f} RUB",
                     ft.Icons.HOURGLASS_EMPTY, COLORS["accent_yellow"]),
            make_card("Active Orders", str(active_orders_count),
                     ft.Icons.SHOPPING_CART, COLORS["accent_cyan"]),
            make_card("Items on Hold", str(items_on_hold_count),
                     ft.Icons.INVENTORY_2, COLORS["accent_red"]),
            make_card("Total Profit", f"{total_profit_value:,.0f} RUB",
                     ft.Icons.TRENDING_UP, COLORS["accent_lime"]),
        ]

    def build_trades_rows():
        """Build trades table rows from current state."""
        trades = state.recent_sales[:5]

        # Header row
        header = ft.Container(
            content=ft.Row([
                ft.Container(ft.Text("Date", size=12, weight=ft.FontWeight.BOLD), expand=2),
                ft.Container(ft.Text("Item", size=12, weight=ft.FontWeight.BOLD), expand=5),
                ft.Container(ft.Text("Profit", size=12, weight=ft.FontWeight.BOLD), expand=2),
            ]),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )

        rows = [header]
        for trade in trades:
            # Use 'or 0' to handle None values
            profit = trade.get('profit') or 0
            profit_color = COLORS["profit_positive"] if profit >= 0 else COLORS["profit_negative"]
            rows.append(
                ft.Container(
                    content=ft.Row([
                        ft.Container(ft.Text(str(trade.get('sale_date') or '-')[:10], size=12, color=COLORS["text_secondary"]), expand=2),
                        ft.Container(ft.Text(str(trade.get('item_name') or '-')[:30], size=12, color=COLORS["text_primary"]), expand=5),
                        ft.Container(ft.Text(f"{profit:.0f}", size=12, color=profit_color, weight=ft.FontWeight.BOLD), expand=2),
                    ]),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
                )
            )

        if len(rows) == 1:  # Only header
            rows.append(ft.Container(
                content=ft.Text("No recent trades", size=12, color=COLORS["text_secondary"]),
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
            ))

        return rows

    def build_orders_rows():
        """Build orders table rows from current state."""
        orders = state.active_orders[:10]

        # Header row
        header = ft.Container(
            content=ft.Row([
                ft.Container(ft.Text("Item", size=12, weight=ft.FontWeight.BOLD), expand=7),
                ft.Container(ft.Text("Price", size=12, weight=ft.FontWeight.BOLD), expand=2),
                ft.Container(ft.Text("Status", size=12, weight=ft.FontWeight.BOLD), expand=1),
            ]),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )

        rows = [header]
        for order in orders:
            status_color = COLORS["status_online"] if order.get('status') == 'active' else COLORS["text_secondary"]
            # Use 'or 0' to handle None values
            price = order.get('price') or 0
            rows.append(
                ft.Container(
                    content=ft.Row([
                        ft.Container(ft.Text(str(order.get('item_name') or '-'), size=12, color=COLORS["text_primary"]), expand=7),
                        ft.Container(ft.Text(f"{price:.0f}", size=12, color=COLORS["text_secondary"]), expand=2),
                        ft.Container(ft.Text(str(order.get('status') or '-'), size=12, color=status_color), expand=1),
                    ]),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
                )
            )

        if len(rows) == 1:  # Only header
            rows.append(ft.Container(
                content=ft.Text("No active orders", size=12, color=COLORS["text_secondary"]),
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
            ))

        return rows

    return ft.Container(
        content=ft.Column(
            controls=[
                # Header
                ft.Text("Dashboard", size=FONT_SIZES["2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),

                # Stat cards
                ft.ResponsiveRow(
                    controls=build_stat_cards(),
                    run_spacing=12,
                    spacing=12,
                ),

                # Two tables side by side - expand to fill space
                ft.Row([
                    # Recent trades
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Recent Trades", size=FONT_SIZES["base"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                            ft.Column(
                                controls=build_trades_rows(),
                                spacing=0,
                                expand=True,
                            ),
                        ], spacing=8),
                        bgcolor=COLORS["bg_surface"],
                        border_radius=12,
                        border=ft.border.all(1, COLORS["border"]),
                        padding=12,
                        expand=True,
                    ),

                    # Active orders
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Active Orders", size=FONT_SIZES["base"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                            ft.Column(
                                controls=build_orders_rows(),
                                spacing=0,
                                expand=True,
                                scroll=ft.ScrollMode.AUTO,
                            ),
                        ], spacing=8),
                        bgcolor=COLORS["bg_surface"],
                        border_radius=12,
                        border=ft.border.all(1, COLORS["border"]),
                        padding=12,
                        expand=True,
                    ),
                ], spacing=12, expand=True),
            ],
            spacing=16,
            expand=True,
        ),
        padding=20,
        expand=True,
    )


DashboardView = create_dashboard_view
