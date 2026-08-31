"""
Simplified Flet GUI - works with Flet 0.80+
Quick demo to test the design and layout.
"""

import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES
from flet_gui.state.app_state import AppState
from flet_gui.services.mocks import MockServices


def main(page: ft.Page):
    """Main entry point."""
    # Setup
    page.title = "Steam Trading Bot"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = COLORS["bg_primary"]
    page.padding = 0

    # State
    state = AppState()
    mock = MockServices(state)
    mock.load_mock_data()

    # Current view index
    current_view = [0]

    # Navigation
    def on_nav_change(e):
        current_view[0] = e.control.selected_index
        update_content()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        bgcolor=COLORS["bg_surface"],
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD, label="Dashboard"),
            ft.NavigationRailDestination(icon=ft.Icons.PERSON, label="Accounts"),
            ft.NavigationRailDestination(icon=ft.Icons.LIST_ALT, label="Orders"),
            ft.NavigationRailDestination(icon=ft.Icons.INVENTORY_2, label="Inventory"),
            ft.NavigationRailDestination(icon=ft.Icons.SEARCH, label="Parser"),
            ft.NavigationRailDestination(icon=ft.Icons.HISTORY, label="History"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS, label="Settings"),
            ft.NavigationRailDestination(icon=ft.Icons.TERMINAL, label="Logs"),
        ],
        on_change=on_nav_change,
    )

    # Content area ref
    content_area = ft.Container(expand=True, bgcolor=COLORS["bg_primary"])

    def create_stat_card(title, value, icon, color):
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(icon, color=color, size=20),
                    ft.Text(title, size=12, color=COLORS["text_secondary"]),
                ]),
                ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ], spacing=8),
            padding=16,
            bgcolor=COLORS["bg_surface"],
            border=ft.border.all(1, COLORS["border"]),
            border_radius=12,
        )

    def create_dashboard():
        stats = state.stats
        return ft.Container(
            content=ft.Column([
                ft.Text("Dashboard", size=28, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                ft.Row([
                    create_stat_card("Steam Balance", f"{stats.get('balance_steam', 0):,.0f} RUB",
                                   ft.Icons.ACCOUNT_BALANCE_WALLET, COLORS["accent_blue"]),
                    create_stat_card("CSGO.TM Balance", f"{stats.get('balance_csgotm', 0):,.0f} RUB",
                                   ft.Icons.CURRENCY_EXCHANGE, COLORS["accent_purple"]),
                    create_stat_card("Active Orders", str(stats.get('active_orders', 0)),
                                   ft.Icons.SHOPPING_CART, COLORS["accent_yellow"]),
                ], spacing=16, wrap=True),
                ft.Row([
                    create_stat_card("Items on Hold", str(stats.get('items_on_hold', 0)),
                                   ft.Icons.INVENTORY_2, COLORS["accent_cyan"]),
                    create_stat_card("Total Profit", f"{stats.get('total_profit', 0):,.0f} RUB",
                                   ft.Icons.TRENDING_UP, COLORS["accent_lime"]),
                    create_stat_card("Sold Items", str(stats.get('sold_items', 0)),
                                   ft.Icons.SELL, COLORS["status_online"]),
                ], spacing=16, wrap=True),
            ], spacing=24),
            padding=24,
            expand=True,
        )

    def create_accounts():
        accounts_list = []
        for acc in state.accounts:
            status_color = COLORS["status_online"] if acc.logged_in else COLORS["status_offline"]
            accounts_list.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(acc.name, size=16, weight=ft.FontWeight.BOLD),
                            ft.Text("Online" if acc.logged_in else "Offline",
                                  size=12, color=status_color),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(f"Currency: {acc.currency} | Steam: {acc.steam_balance:,.0f} | TM: {acc.csgotm_balance:,.0f}",
                              size=12, color=COLORS["text_secondary"]),
                    ], spacing=8),
                    padding=16,
                    bgcolor=COLORS["bg_surface"],
                    border=ft.border.all(1, COLORS["border"]),
                    border_radius=12,
                )
            )

        return ft.Container(
            content=ft.Column([
                ft.Text("Accounts", size=28, weight=ft.FontWeight.BOLD),
                ft.Column(accounts_list, spacing=16, scroll=ft.ScrollMode.AUTO),
            ], spacing=24),
            padding=24,
            expand=True,
        )

    def create_logs():
        log_entries = []
        for log in state.logs:
            color = COLORS["text_secondary"]
            if "[ERROR]" in log:
                color = COLORS["accent_red"]
            elif "[WARNING]" in log:
                color = COLORS["accent_yellow"]
            elif "[SUCCESS]" in log:
                color = COLORS["accent_lime"]
            elif "[INFO]" in log:
                color = COLORS["accent_blue"]

            log_entries.append(ft.Text(log, size=12, color=color, font_family="monospace"))

        return ft.Container(
            content=ft.Column([
                ft.Text("Logs", size=28, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Column(log_entries, spacing=2, scroll=ft.ScrollMode.AUTO),
                    padding=16,
                    bgcolor=COLORS["bg_primary"],
                    border=ft.border.all(1, COLORS["border"]),
                    border_radius=8,
                    expand=True,
                ),
            ], spacing=24),
            padding=24,
            expand=True,
        )

    def create_placeholder(title):
        return ft.Container(
            content=ft.Column([
                ft.Text(title, size=28, weight=ft.FontWeight.BOLD),
                ft.Text(f"{title} view - coming soon", size=16, color=COLORS["text_secondary"]),
            ], spacing=16),
            padding=24,
            expand=True,
        )

    views = [
        create_dashboard,
        create_accounts,
        lambda: create_placeholder("Orders"),
        lambda: create_placeholder("Inventory"),
        lambda: create_placeholder("TM Parser"),
        lambda: create_placeholder("History"),
        lambda: create_placeholder("Settings"),
        create_logs,
    ]

    def update_content():
        view_factory = views[current_view[0]]
        content_area.content = view_factory()
        page.update()

    # Header
    header = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Icon(ft.Icons.SMART_TOY, color=COLORS["accent_purple"], size=28),
                ft.Text("Steam Trading Bot", size=18, weight=ft.FontWeight.BOLD),
            ], spacing=12),
            ft.Text("Ready", size=14, color=COLORS["text_secondary"]),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=ft.padding.symmetric(horizontal=24, vertical=16),
        bgcolor=COLORS["bg_surface"],
        border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
    )

    # Status bar
    status = ft.Container(
        content=ft.Row([
            ft.Text("v1.0.0", size=11, color=COLORS["text_tertiary"]),
            ft.Text(f"Accounts: {len([a for a in state.accounts if a.logged_in])}/{len(state.accounts)} online",
                  size=11, color=COLORS["text_secondary"]),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=ft.padding.symmetric(horizontal=24, vertical=8),
        bgcolor=COLORS["bg_surface"],
        border=ft.border.only(top=ft.BorderSide(1, COLORS["border"])),
    )

    # Initial content
    update_content()

    # Layout
    page.add(
        header,
        ft.Row([
            ft.Container(
                content=nav_rail,
                border=ft.border.only(right=ft.BorderSide(1, COLORS["border"])),
            ),
            content_area,
        ], expand=True, spacing=0),
        status,
    )


if __name__ == "__main__":
    ft.app(main)
