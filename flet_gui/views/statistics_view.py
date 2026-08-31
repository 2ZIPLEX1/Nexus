"""
Statistics view - displays trading statistics and allows export.
"""

import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState


def create_statistics_view(statistics_service=None, page=None) -> ft.Container:
    """
    Statistics view with summary, charts, and export options.

    Args:
        statistics_service: StatisticsService instance
        page: Flet page for dialogs
    """
    state = AppState()

    # Refs for dynamic updates
    period_dropdown = ft.Ref[ft.Dropdown]()
    summary_column = ft.Ref[ft.Column]()
    top_items_column = ft.Ref[ft.Column]()

    def get_summary_data(days: int = 30) -> dict:
        """Get summary data."""
        if statistics_service:
            return statistics_service.get_summary(days=days)
        # Mock data if no service
        return {
            'period_days': days,
            'items_purchased': 0,
            'items_sold': 0,
            'total_spent': 0.0,
            'total_earned': 0.0,
            'total_profit': 0.0,
            'roi_percent': 0.0,
            'avg_profit_per_trade': 0.0,
            'active_profitable_items': 0,
            'active_orders': 0
        }

    def create_stat_row(label: str, value: str, icon: str = None, color: str = None):
        """Create a stat row."""
        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=16, color=color or COLORS["text_secondary"]) if icon else ft.Container(width=16),
                ft.Text(label, size=FONT_SIZES["base"], color=COLORS["text_secondary"], expand=True),
                ft.Text(value, size=FONT_SIZES["base"], weight=ft.FontWeight.BOLD, color=color or COLORS["text_primary"]),
            ], spacing=10),
            padding=ft.padding.only(top=6, bottom=6, right=12),
        )

    def build_summary_content(summary: dict):
        """Build summary content."""
        profit = summary.get('total_profit', 0)
        profit_color = COLORS["profit_positive"] if profit >= 0 else COLORS["profit_negative"]
        roi = summary.get('roi_percent', 0)
        roi_color = COLORS["profit_positive"] if roi >= 0 else COLORS["profit_negative"]

        # Calculate total balances from all accounts with currency conversion
        from src.currency_rates import get_currency_provider
        currency_provider = get_currency_provider()
        total_steam = 0
        total_tm = 0
        total_settlement = 0

        for acc in state.accounts:
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

        def section_title(text: str):
            """Create section title with right padding."""
            return ft.Container(
                content=ft.Text(text, size=FONT_SIZES["base"], weight=ft.FontWeight.BOLD, color=COLORS["accent_purple"]),
                padding=ft.padding.only(right=12),
            )

        return [
            ft.Container(
                content=ft.Text(f"Trading Report ({summary.get('period_days', 30)} days)",
                       size=FONT_SIZES["xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                padding=ft.padding.only(right=12),
            ),
            ft.Container(
                content=ft.Divider(height=1, color=COLORS["border"]),
                padding=ft.padding.only(right=12),
            ),

            # Account Balances section
            section_title("Account Balances"),
            create_stat_row("Steam Wallet", f"{total_steam:,.2f} RUB",
                          ft.Icons.ACCOUNT_BALANCE_WALLET, COLORS["accent_blue"]),
            create_stat_row("CSGO.TM Balance", f"{total_tm:,.2f} RUB",
                          ft.Icons.CURRENCY_EXCHANGE, COLORS["accent_lime"]),
            create_stat_row("Money in Hold", f"{total_settlement:,.2f} RUB",
                          ft.Icons.HOURGLASS_EMPTY, COLORS["accent_yellow"]),

            ft.Container(height=10),

            # Purchases & Sales section
            section_title("Purchases & Sales"),
            create_stat_row("Items Purchased", f"{summary.get('items_purchased', 0)} pcs",
                          ft.Icons.SHOPPING_CART, COLORS["accent_blue"]),
            create_stat_row("Items Sold", f"{summary.get('items_sold', 0)} pcs",
                          ft.Icons.SELL, COLORS["accent_lime"]),

            ft.Container(height=10),

            # Active positions section
            section_title("Active Positions"),
            create_stat_row("Active Buy Orders", f"{summary.get('active_orders', 0)} pcs",
                          ft.Icons.PENDING_ACTIONS, COLORS["accent_yellow"]),
            create_stat_row("Profitable Items", f"{summary.get('active_profitable_items', 0)} pcs",
                          ft.Icons.STAR, COLORS["accent_cyan"]),

            ft.Container(height=10),

            # Financials section
            section_title("Financials"),
            create_stat_row("Total Spent", f"{summary.get('total_spent', 0):,.2f} RUB",
                          ft.Icons.ARROW_DOWNWARD, COLORS["accent_red"]),
            create_stat_row("Total Earned", f"{summary.get('total_earned', 0):,.2f} RUB",
                          ft.Icons.ARROW_UPWARD, COLORS["accent_lime"]),
            create_stat_row("Total Profit", f"{profit:,.2f} RUB",
                          ft.Icons.TRENDING_UP if profit >= 0 else ft.Icons.TRENDING_DOWN, profit_color),

            ft.Container(height=10),

            # Efficiency section
            section_title("Efficiency"),
            create_stat_row("ROI", f"{roi:.2f}%",
                          ft.Icons.PERCENT, roi_color),
            create_stat_row("Avg Profit/Trade", f"{summary.get('avg_profit_per_trade', 0):.2f} RUB",
                          ft.Icons.ANALYTICS, COLORS["accent_blue"]),
        ]

    def build_top_items_header():
        """Build top items table header (sticky)."""
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    ft.Text("Item", size=FONT_SIZES["xs"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    expand=4,
                ),
                ft.Container(
                    ft.Text("Trades", size=FONT_SIZES["xs"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                    expand=1,
                ),
                ft.Container(
                    ft.Text("Profit", size=FONT_SIZES["xs"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.RIGHT),
                    expand=2,
                ),
            ], spacing=8),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_elevated"],
            border=ft.border.only(bottom=ft.BorderSide(2, COLORS["border"])),
        )

    def build_top_items_rows(items: list):
        """Build top items table rows."""
        if not items:
            return [ft.Container(
                content=ft.Text("No data available", size=FONT_SIZES["sm"], color=COLORS["text_secondary"], text_align=ft.TextAlign.CENTER),
                padding=20,
            )]

        rows = []
        for idx, item in enumerate(items[:10]):
            profit = item.get('total_profit', 0)
            profit_color = COLORS["profit_positive"] if profit >= 0 else COLORS["profit_negative"]

            # Alternate row background for better readability
            row_bg = COLORS["bg_elevated"] if idx % 2 == 0 else None

            rows.append(
                ft.Container(
                    content=ft.Row([
                        ft.Container(
                            ft.Text(
                                item.get('item_name', '-')[:35],
                                size=FONT_SIZES["xs"],
                                color=COLORS["text_primary"],
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            expand=4,
                            tooltip=item.get('item_name', '-'),
                        ),
                        ft.Container(
                            ft.Text(
                                str(item.get('trades', 0)),
                                size=FONT_SIZES["xs"],
                                color=COLORS["text_secondary"],
                                text_align=ft.TextAlign.CENTER,
                            ),
                            expand=1,
                        ),
                        ft.Container(
                            ft.Text(
                                f"{profit:+.0f}" if profit != 0 else "0",
                                size=FONT_SIZES["xs"],
                                color=profit_color,
                                weight=ft.FontWeight.BOLD,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                            expand=2,
                        ),
                    ], spacing=8),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    bgcolor=row_bg,
                    border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
                )
            )

        return rows

    def on_period_change(e):
        """Handle period dropdown change."""
        try:
            days = int(period_dropdown.current.value)
            summary = get_summary_data(days)

            if summary_column.current:
                summary_column.current.controls = build_summary_content(summary)

            # Update top items
            if statistics_service:
                top_items = statistics_service.get_top_items(limit=10, by='profit')
            else:
                top_items = []

            if top_items_column.current:
                top_items_column.current.controls = build_top_items_rows(top_items)

            if page:
                page.update()

        except Exception as ex:
            state.add_log(f"[ERROR] Failed to update statistics: {str(ex)}")

    def on_export_csv(e):
        """Export data to CSV."""
        if not statistics_service:
            state.add_log("[ERROR] Statistics service not available")
            return

        try:
            days = int(period_dropdown.current.value) if period_dropdown.current else 30
            result = statistics_service.export_to_csv(data_type='all', days=days)
            if result:
                state.add_log(f"[SUCCESS] Data exported to {result}")
        except Exception as ex:
            state.add_log(f"[ERROR] Export failed: {str(ex)}")

    def on_export_json(e):
        """Export data to JSON."""
        if not statistics_service:
            state.add_log("[ERROR] Statistics service not available")
            return

        try:
            days = int(period_dropdown.current.value) if period_dropdown.current else 30
            result = statistics_service.export_to_json(data_type='all', days=days)
            if result:
                state.add_log(f"[SUCCESS] Data exported to {result}")
        except Exception as ex:
            state.add_log(f"[ERROR] Export failed: {str(ex)}")

    # Initial data
    initial_summary = get_summary_data(30)
    initial_top_items = statistics_service.get_top_items(limit=10, by='profit') if statistics_service else []

    return ft.Container(
        content=ft.Column(
            controls=[
                # Header
                ft.Row([
                    ft.Text("Statistics", size=FONT_SIZES["2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    ft.Row([
                        ft.Text("Period:", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                        ft.Dropdown(
                            ref=period_dropdown,
                            value="30",
                            options=[
                                ft.DropdownOption(key="7", text="7 days"),
                                ft.DropdownOption(key="14", text="14 days"),
                                ft.DropdownOption(key="30", text="30 days"),
                                ft.DropdownOption(key="60", text="60 days"),
                                ft.DropdownOption(key="90", text="90 days"),
                                ft.DropdownOption(key="365", text="1 year"),
                            ],
                            width=120,
                            on_select=on_period_change,
                        ),
                        ft.FilledButton(
                            "Export CSV",
                            icon=ft.Icons.DOWNLOAD,
                            on_click=on_export_csv,
                        ),
                        ft.FilledButton(
                            "Export JSON",
                            icon=ft.Icons.CODE,
                            on_click=on_export_json,
                        ),
                    ], spacing=10),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                # Content - two columns
                ft.Row([
                    # Left: Summary - scroll inside container border
                    ft.Container(
                        content=ft.Column(
                            ref=summary_column,
                            controls=build_summary_content(initial_summary),
                            spacing=4,
                            scroll=ft.ScrollMode.AUTO,
                            expand=True,
                        ),
                        bgcolor=COLORS["bg_surface"],
                        border_radius=RADIUS["lg"],
                        border=ft.border.all(1, COLORS["border"]),
                        padding=ft.padding.only(left=16, top=16, bottom=16, right=4),
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        expand=True,
                    ),

                    # Right: Top Items - sticky header with scroll on rows
                    ft.Container(
                        content=ft.Column([
                            # Title
                            ft.Container(
                                content=ft.Text("Top Items by Profit", size=FONT_SIZES["lg"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                                padding=ft.padding.only(left=12, top=12, right=12, bottom=8),
                            ),
                            # Sticky header
                            build_top_items_header(),
                            # Scrollable rows
                            ft.Column(
                                ref=top_items_column,
                                controls=build_top_items_rows(initial_top_items),
                                spacing=0,
                                scroll=ft.ScrollMode.AUTO,
                                expand=True,
                            ),
                        ], spacing=0, expand=True),
                        bgcolor=COLORS["bg_surface"],
                        border_radius=RADIUS["lg"],
                        border=ft.border.all(1, COLORS["border"]),
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        expand=True,
                    ),
                ], spacing=16, expand=True),
            ],
            spacing=16,
            expand=True,
        ),
        padding=20,
        expand=True,
    )


StatisticsView = create_statistics_view
