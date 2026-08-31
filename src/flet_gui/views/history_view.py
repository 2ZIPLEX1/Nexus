"""
History view - displays transaction history with full-width responsive table.
Reactive updates via state subscriptions.
"""

import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState


def create_history_view(page=None) -> ft.Container:
    """History view with full-width custom table - reactive updates."""
    state = AppState()

    # Refs for dynamic updates
    table_column_ref = ft.Ref[ft.Column]()
    count_text_ref = ft.Ref[ft.Text]()

    def build_table_header():
        """Build table header row."""
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(ft.Text("Account", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=2),
                    ft.Container(ft.Text("Date", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=2),
                    ft.Container(ft.Text("Item", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=3),
                    ft.Container(ft.Text("Buy Price (RUB)", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=2),
                    ft.Container(ft.Text("Sell Price (RUB)", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=2),
                    ft.Container(ft.Text("Profit (RUB)", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=2),
                ],
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor=COLORS["bg_elevated"],
            border=ft.border.only(bottom=ft.BorderSide(2, COLORS["border"])),
        )

    def build_table_rows():
        """Build table rows from current state."""
        sales = state.recent_sales

        rows = []

        for sale in sales:
            # Use 'or 0' to handle None values (when key exists but value is None)
            profit = sale.get('profit') or 0
            buy_price = sale.get('buy_price') or 0
            sell_price = sale.get('sell_price') or 0
            profit_color = COLORS["profit_positive"] if profit >= 0 else COLORS["profit_negative"]
            account_name = str(sale.get('account_name') or 'default')

            # Safely get sale_date
            sale_date = str(sale.get('sale_date') or '-')[:16] if sale.get('sale_date') else '-'

            row = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(ft.Text(account_name, size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=2),
                        ft.Container(ft.Text(sale_date, size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=2),
                        ft.Container(ft.Text(str(sale.get('item_name') or '-'), size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=3),
                        ft.Container(ft.Text(f"{buy_price:.0f}", size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=2),
                        ft.Container(ft.Text(f"{sell_price:.0f}", size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=2),
                        ft.Container(ft.Text(f"{profit:.0f}", size=FONT_SIZES["sm"], color=profit_color, weight=ft.FontWeight.BOLD), expand=2),
                    ],
                    spacing=0,
                ),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
            )
            rows.append(row)

        # If no sales
        if len(rows) == 0:
            rows.append(ft.Container(
                content=ft.Column([
                    ft.Text("No sales history", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
            ))

        return rows

    def update_history():
        """Update history table."""
        try:
            sales = state.recent_sales

            if table_column_ref.current:
                table_column_ref.current.controls = build_table_rows()

            if count_text_ref.current:
                count_text_ref.current.value = f"{len(sales)} transactions"

            if page:
                page.update()
        except Exception as e:
            print(f"History update error: {e}")

    # Subscribe to state changes
    state.subscribe('recent_sales', update_history)

    sales = state.recent_sales

    # Table with sticky header
    table_container = ft.Container(
        content=ft.Column([
            # Sticky header (outside scroll)
            build_table_header(),
            # Scrollable rows
            ft.Column(
                ref=table_column_ref,
                controls=build_table_rows(),
                spacing=0,
                scroll=ft.ScrollMode.ALWAYS,
                expand=True,
            ),
        ], spacing=0, expand=True),
        bgcolor=COLORS["bg_surface"],
        border_radius=RADIUS["lg"],
        border=ft.border.all(1, COLORS["border"]),
        expand=True,
    )

    return ft.Container(
        content=ft.Column(
            controls=[
                # Header row
                ft.Row(
                    controls=[
                        ft.Text("Transaction History", size=FONT_SIZES["2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    ],
                ),
                # Transaction count
                ft.Text(
                    ref=count_text_ref,
                    value=f"{len(sales)} transactions",
                    size=FONT_SIZES["sm"],
                    color=COLORS["text_secondary"],
                ),
                # Table (fills remaining space)
                table_container,
            ],
            spacing=12,
            expand=True,
        ),
        padding=20,
        expand=True,
    )


HistoryView = create_history_view
