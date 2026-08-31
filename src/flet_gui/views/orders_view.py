"""
Orders view - displays active orders with full-width responsive table.
Reactive updates via state subscriptions.
"""

import logging
import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState

logger = logging.getLogger(__name__)


def create_orders_view(page=None, account_service=None, db_service=None, auto_buy_service=None) -> ft.Container:
    """Orders view with full-width custom table - reactive updates."""
    state = AppState()

    # Get excluded items from auto_buy
    excluded_items = set()
    if auto_buy_service:
        excluded_items = {item.name for item in auto_buy_service.items}

    # Refs for dynamic updates
    table_column_ref = ft.Ref[ft.Column]()
    count_text_ref = ft.Ref[ft.Text]()

    async def check_profitability():
        """Check profitability of active orders and cancel unprofitable ones."""
        if not account_service or not db_service:
            state.add_log("[ERROR] Services not available")
            return

        # Get min profit from config
        min_profit = state.config.get('check_orders_min_profit', 5.0)
        state.add_log(f"[INFO] Starting profitability check (min profit: {min_profit}%)...")

        # Pass excluded_items to skip auto_buy items
        results = await account_service.check_and_cancel_unprofitable_orders(
            db_service,
            min_profit_percent=min_profit,
            check_realtime=True,
            excluded_items=excluded_items
        )

        # Refresh data
        db_service.load_all_data()

        skipped_msg = f", {results['skipped']} skipped (auto_buy)" if results.get('skipped', 0) > 0 else ""
        state.add_log(f"[SUCCESS] Profitability check complete: {results['checked']} checked, {results['cancelled']} cancelled{skipped_msg}")

    def build_table_header():
        """Build table header row."""
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(ft.Text("Account", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=2),
                    ft.Container(
                        content=ft.Text("Created", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                    ft.Container(
                        content=ft.Text("Item", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=5,
                    ),
                    ft.Container(
                        content=ft.Text("Price (RUB)", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                    ft.Container(
                        content=ft.Text("Status", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=1,
                    ),
                ],
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor=COLORS["bg_elevated"],
            border=ft.border.only(bottom=ft.BorderSide(2, COLORS["border"])),
        )

    def build_table_rows():
        """Build table rows from current state."""
        # Filter out auto_buy orders
        def is_not_auto_buy(order):
            """Check if order is NOT an auto_buy order."""
            if not auto_buy_service:
                return True

            item_name = order.get('item_name') or order.get('market_hash_name') or ''

            # Check exact match
            if auto_buy_service.is_auto_buy_item(item_name):
                logger.debug(f"Filtering out auto_buy order (item_name): {item_name}")
                return False

            # Also check market_hash_name separately
            market_hash_name = order.get('market_hash_name', '')
            if market_hash_name and auto_buy_service.is_auto_buy_item(market_hash_name):
                logger.debug(f"Filtering out auto_buy order (market_hash_name): {market_hash_name}")
                return False

            return True

        filtered_orders = [
            order for order in state.active_orders
            if is_not_auto_buy(order)
        ]
        orders = filtered_orders[:50]  # Show first 50 non-auto_buy orders

        rows = []

        for order in orders:
            status_color = COLORS["status_online"] if order.get('status') == 'active' else COLORS["text_secondary"]

            # Safely get created_at
            created_at = str(order.get('created_at') or '-')[:16] if order.get('created_at') else '-'

            # Use 'or 0' to handle None values (when key exists but value is None)
            price = order.get('price') or 0
            account_name = str(order.get('account_name') or 'default')

            row = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(ft.Text(account_name, size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=2),
                        ft.Container(
                            content=ft.Text(created_at, size=FONT_SIZES["sm"], color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(str(order.get('item_name') or '-'), size=FONT_SIZES["sm"], color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=5,
                        ),
                        ft.Container(
                            content=ft.Text(f"{price:.0f}", size=FONT_SIZES["sm"], color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(str(order.get('status') or '-'), size=FONT_SIZES["sm"], color=status_color, text_align=ft.TextAlign.CENTER),
                            expand=1,
                        ),
                    ],
                    spacing=0,
                ),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
            )
            rows.append(row)

        # If no orders
        if len(rows) == 0:
            rows.append(ft.Container(
                content=ft.Column([
                    ft.Text("No active orders", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
            ))

        return rows

    def update_orders():
        """Update orders table."""
        try:
            orders = state.active_orders[:50]

            if table_column_ref.current:
                table_column_ref.current.controls = build_table_rows()

            if count_text_ref.current:
                count_text_ref.current.value = f"{len(orders)} active orders"

            if page:
                page.update()
        except Exception as e:
            print(f"Orders update error: {e}")

    # Subscribe to state changes
    state.subscribe('active_orders', update_orders)

    orders = state.active_orders[:50]

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
                        ft.Text("Active Orders", size=FONT_SIZES["2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                        ft.FilledButton(
                            "Check Profitability",
                            icon=ft.Icons.SEARCH,
                            on_click=lambda e: page.run_task(check_profitability) if page and hasattr(page, 'run_task') else None,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # Order count
                ft.Text(
                    ref=count_text_ref,
                    value=f"{len(orders)} active orders",
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


OrdersView = create_orders_view
