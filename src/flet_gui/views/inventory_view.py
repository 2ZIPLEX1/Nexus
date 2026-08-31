"""
Inventory view - displays items on hold with full-width responsive table.
Reactive updates via state subscriptions.
"""

import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState


def create_inventory_view(page=None, db_service=None, auto_buy_service=None) -> ft.Container:
    """Inventory view with full-width custom table - reactive updates."""
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
                    ft.Container(
                        content=ft.Text("Item", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=5,
                    ),
                    ft.Container(
                        content=ft.Text("Buy Price", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                    ft.Container(
                        content=ft.Text("Expected", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                    ft.Container(
                        content=ft.Text("Current TM", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                    ft.Container(
                        content=ft.Text("Profit", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                    ft.Container(
                        content=ft.Text("Hold Time", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                        expand=2,
                    ),
                ],
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor=COLORS["bg_elevated"],
            border=ft.border.only(bottom=ft.BorderSide(2, COLORS["border"])),
        )

    def show_edit_price_dialog(item_id: int, item_name: str, current_value: float, field: str = "buy_price"):
        """Show dialog to edit buy_price or expected_price."""
        price_input = ft.TextField(
            value=str(int(current_value)) if current_value > 0 else "",
            label=f"{'Buy Price' if field == 'buy_price' else 'Expected Price'} (RUB)",
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True,
            width=200,
        )

        async def on_save(e):
            try:
                new_price = float(price_input.value) if price_input.value else 0
                if new_price <= 0:
                    state.add_log(f"[WARNING] Invalid price: {price_input.value}")
                    return

                # Update in database
                from src.database import TradesDatabase
                import asyncio
                db = TradesDatabase()

                def _update_price():
                    with db._get_connection() as conn:
                        cursor = conn.cursor()
                        if field == "buy_price":
                            cursor.execute("""
                                UPDATE purchased_items
                                SET purchase_price = ?
                                WHERE id = ?
                            """, (new_price, item_id))
                        else:
                            cursor.execute("""
                                UPDATE purchased_items
                                SET expected_sell_price = ?,
                                    expected_profit_pct = ((? - purchase_price) / purchase_price * 100)
                                WHERE id = ?
                            """, (new_price, new_price, item_id))

                await asyncio.to_thread(_update_price)
                state.add_log(f"[SUCCESS] Updated {field} for {item_name[:30]}: {new_price:.0f} RUB")

                # Refresh inventory
                if db_service:
                    await db_service.refresh_inventory_async()

                # Close dialog
                dialog.open = False
                if page:
                    page.update()

            except Exception as ex:
                state.add_log(f"[ERROR] Failed to update price: {ex}")

        def on_cancel(e):
            dialog.open = False
            if page:
                page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit {'Buy' if field == 'buy_price' else 'Expected'} Price"),
            content=ft.Column([
                ft.Text(item_name, size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                price_input,
                ft.Text("Enter price in RUB", size=FONT_SIZES["xs"], color=COLORS["text_secondary"]),
            ], tight=True, spacing=8),
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel),
                ft.FilledButton("Save", on_click=lambda e: page.run_task(on_save, e) if page else None),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        if page:
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

    def build_table_rows():
        """Build table rows from current state."""
        # Filter out auto_buy items and items with zero purchase price
        def is_valid_item(item):
            """Check if item should be displayed."""
            # Filter out items with zero purchase price
            buy_price = item.get('buy_price') or item.get('purchase_price') or 0
            if buy_price <= 0:
                return False

            # Filter out auto_buy items
            if auto_buy_service:
                item_name = item.get('item_name') or item.get('market_hash_name') or ''
                if auto_buy_service.is_auto_buy_item(item_name):
                    return False

                market_hash_name = item.get('market_hash_name', '')
                if market_hash_name and auto_buy_service.is_auto_buy_item(market_hash_name):
                    return False

            return True

        items = [item for item in state.items_on_hold if is_valid_item(item)]

        rows = []

        for item in items:
            hold_time = item.get('hold_time_remaining') or 0
            hold_color = COLORS["accent_yellow"] if hold_time > 0 else COLORS["status_online"]

            # Use 'or 0' to handle None values (when key exists but value is None)
            buy_price = item.get('buy_price') or 0
            expected_price = item.get('expected_sell_price') or 0
            current_price = item.get('current_price') or 0
            account_name = str(item.get('account_name') or 'default')

            # Calculate profit vs expected price
            if expected_price > 0 and current_price > 0:
                profit_diff = current_price - expected_price
                profit_pct = (profit_diff / expected_price) * 100
                profit_color = COLORS["profit_positive"] if profit_diff >= 0 else COLORS["profit_negative"]
                profit_text = f"{profit_diff:+.0f} ({profit_pct:+.1f}%)"
            else:
                profit_color = COLORS["text_secondary"]
                profit_text = "-"

            # Closure for click handler
            item_id = item.get('id')
            item_name = item.get('item_name') or item.get('market_hash_name') or '-'

            def make_buy_price_click_handler(iid, iname, iprice):
                def handler(e):
                    show_edit_price_dialog(iid, iname, iprice, "buy_price")
                return handler

            def make_expected_price_click_handler(iid, iname, iprice):
                def handler(e):
                    show_edit_price_dialog(iid, iname, iprice, "expected_price")
                return handler

            row = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(ft.Text(account_name, size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=2),
                        ft.Container(
                            content=ft.Text(str(item_name), size=FONT_SIZES["sm"], color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=5,
                        ),
                        # Clickable buy_price cell
                        ft.Container(
                            content=ft.TextButton(
                                content=ft.Text(f"{buy_price:.0f}", size=FONT_SIZES["sm"], color=COLORS["accent_blue"]),
                                on_click=make_buy_price_click_handler(item_id, item_name, buy_price),
                                style=ft.ButtonStyle(padding=0),
                                tooltip="Click to edit buy price",
                            ),
                            expand=2,
                        ),
                        # Clickable expected_price cell
                        ft.Container(
                            content=ft.TextButton(
                                content=ft.Text(f"{expected_price:.0f}" if expected_price > 0 else "-", size=FONT_SIZES["sm"], color=COLORS["accent_purple"]),
                                on_click=make_expected_price_click_handler(item_id, item_name, expected_price),
                                style=ft.ButtonStyle(padding=0),
                                tooltip="Click to edit expected price",
                            ),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(f"{current_price:.0f}" if current_price > 0 else "-", size=FONT_SIZES["sm"], color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(profit_text, size=FONT_SIZES["sm"], color=profit_color, text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(f"{hold_time}h" if hold_time > 0 else "Ready", size=FONT_SIZES["sm"], color=hold_color, text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                    ],
                    spacing=0,
                ),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
            )
            rows.append(row)

        # If no items
        if len(rows) == 0:
            rows.append(ft.Container(
                content=ft.Column([
                    ft.Text("No items on hold", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
            ))
        else:
            # Calculate totals
            total_buy_price = sum(item.get('buy_price', 0) or 0 for item in items)
            total_expected_price = sum(item.get('expected_sell_price', 0) or 0 for item in items)
            total_current_price = sum(item.get('current_price', 0) or 0 for item in items)

            # Calculate total profit (current vs buy)
            total_profit = total_current_price - total_buy_price if total_current_price > 0 and total_buy_price > 0 else 0
            total_profit_pct = (total_profit / total_buy_price * 100) if total_buy_price > 0 else 0

            # Calculate expected profit (expected vs buy)
            expected_profit = total_expected_price - total_buy_price if total_expected_price > 0 and total_buy_price > 0 else 0
            expected_profit_pct = (expected_profit / total_buy_price * 100) if total_buy_price > 0 else 0

            profit_color = COLORS["profit_positive"] if total_profit >= 0 else COLORS["profit_negative"]

            # Add summary footer row
            rows.append(ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Text("TOTAL", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                            expand=7
                        ),
                        ft.Container(
                            content=ft.Text(f"{total_buy_price:.0f}", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(f"{total_expected_price:.0f}" if total_expected_price > 0 else "-", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_secondary"], text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(f"{total_current_price:.0f}" if total_current_price > 0 else "-", size=14, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"], text_align=ft.TextAlign.CENTER),
                            expand=2,
                        ),
                        ft.Container(
                            content=ft.Text(
                                f"{total_profit:+.0f} ({total_profit_pct:+.1f}%)" if total_profit != 0 else "-",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=profit_color,
                                text_align=ft.TextAlign.CENTER
                            ),
                            expand=2,
                        ),
                        ft.Container(expand=2),  # Hold Time column - empty for totals
                    ],
                    spacing=0,
                ),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                bgcolor=COLORS["bg_elevated"],
                border=ft.border.only(top=ft.BorderSide(2, COLORS["border"])),
            ))

        return rows

    def update_inventory():
        """Update inventory table."""
        try:
            # Filter items same way as in build_table_rows
            def is_valid_item(item):
                buy_price = item.get('buy_price') or item.get('purchase_price') or 0
                if buy_price <= 0:
                    return False
                if auto_buy_service:
                    item_name = item.get('item_name') or item.get('market_hash_name') or ''
                    if auto_buy_service.is_auto_buy_item(item_name):
                        return False
                    market_hash_name = item.get('market_hash_name', '')
                    if market_hash_name and auto_buy_service.is_auto_buy_item(market_hash_name):
                        return False
                return True

            items = [item for item in state.items_on_hold if is_valid_item(item)]

            if table_column_ref.current:
                table_column_ref.current.controls = build_table_rows()

            if count_text_ref.current:
                count_text_ref.current.value = f"{len(items)} items on hold"

            if page:
                page.update()
        except Exception as e:
            print(f"Inventory update error: {e}")

    # Subscribe to state changes
    state.subscribe('items_on_hold', update_inventory)

    async def on_refresh_prices(e):
        """Handle refresh prices button click (non-blocking)."""
        if not db_service:
            state.add_log("[WARNING] Database service not available")
            return

        state.add_log("[INFO] Updating prices for items on hold...")
        await _refresh_prices_async()

    async def _refresh_prices_async():
        """Fetch current prices from CSGO.TM and update database (non-blocking)."""
        try:
            import asyncio
            from src.csgotm_client import CsgoTmClient
            from src.database import TradesDatabase
            import json

            # Get API key from accounts.json (file I/O in thread pool)
            def _load_api_key():
                with open('accounts.json', 'r') as f:
                    accounts_data = json.load(f)
                return accounts_data[0].get('csgotm', {}).get('api_key')

            try:
                api_key = await asyncio.to_thread(_load_api_key)
                if not api_key:
                    state.add_log("[ERROR] No CSGOTM API key found in accounts.json")
                    return
            except Exception as e:
                state.add_log(f"[ERROR] Failed to load API key: {e}")
                return

            csgotm = CsgoTmClient(api_key=api_key)
            db = TradesDatabase()

            # Get items in thread pool (SQLite is blocking)
            items = await asyncio.to_thread(db.get_items_on_hold)
            updated_count = 0
            errors_count = 0

            state.add_log(f"[INFO] Fetching prices for {len(items)} items from CSGO.TM...")

            for i, item in enumerate(items):
                item_id = item.get('id')
                market_hash_name = item.get('market_hash_name')
                expected_sell_price = item.get('expected_sell_price')

                if not market_hash_name or not item_id:
                    continue

                try:
                    # Run sync API call in thread pool
                    price_data = await asyncio.to_thread(
                        csgotm.get_item_price,
                        market_hash_name
                    )

                    if price_data and price_data.get('min_price'):
                        current_price = price_data['min_price']

                        # Update current CSGO.TM price in thread pool (SQLite is blocking)
                        def _update_current_price():
                            db.update_item_current_prices(
                                item_id=item_id,
                                current_csgotm_price=current_price
                            )
                        await asyncio.to_thread(_update_current_price)

                        # If expected_sell_price is missing, set it to current price
                        if not expected_sell_price or expected_sell_price == 0:
                            def _update_expected_price():
                                with db._get_connection() as conn:
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                        UPDATE purchased_items
                                        SET expected_sell_price = ?,
                                            expected_profit_pct = ((? - purchase_price) / purchase_price * 100)
                                        WHERE id = ?
                                    """, (current_price, current_price, item_id))
                            await asyncio.to_thread(_update_expected_price)

                        updated_count += 1
                        state.add_log(f"[INFO] [{i+1}/{len(items)}] {market_hash_name[:40]}: {current_price:.0f} RUB")
                    else:
                        errors_count += 1

                    # Small delay between requests
                    await asyncio.sleep(0.2)

                except Exception as e:
                    errors_count += 1
                    state.add_log(f"[WARNING] Failed: {market_hash_name[:30]}... ({e})")

            # Refresh inventory from database (non-blocking)
            await db_service.refresh_inventory_async()

            state.add_log(f"[SUCCESS] Updated {updated_count}/{len(items)} prices ({errors_count} errors)")

            if page:
                page.update()
        except Exception as e:
            state.add_log(f"[ERROR] Failed to refresh prices: {str(e)}")

    # Filter items for display (excluding auto_buy items and items with zero price)
    def get_filtered_items():
        def is_valid_item(item):
            buy_price = item.get('buy_price') or item.get('purchase_price') or 0
            if buy_price <= 0:
                return False
            if auto_buy_service:
                item_name = item.get('item_name') or item.get('market_hash_name') or ''
                if auto_buy_service.is_auto_buy_item(item_name):
                    return False
                market_hash_name = item.get('market_hash_name', '')
                if market_hash_name and auto_buy_service.is_auto_buy_item(market_hash_name):
                    return False
            return True
        return [item for item in state.items_on_hold if is_valid_item(item)]

    items = get_filtered_items()

    # Calculate summary stats
    def get_summary_stats():
        current_items = get_filtered_items()
        total_buy = sum(item.get('buy_price', 0) or 0 for item in current_items)
        total_expected = sum(item.get('expected_sell_price', 0) or 0 for item in current_items)
        total_current = sum(item.get('current_price', 0) or 0 for item in current_items)
        total_profit = total_current - total_buy if total_current > 0 and total_buy > 0 else 0
        total_profit_pct = (total_profit / total_buy * 100) if total_buy > 0 else 0
        return {
            'total_buy': total_buy,
            'total_expected': total_expected,
            'total_current': total_current,
            'total_profit': total_profit,
            'total_profit_pct': total_profit_pct,
        }

    stats = get_summary_stats()
    profit_color = COLORS["profit_positive"] if stats['total_profit'] >= 0 else COLORS["profit_negative"]

    # Stats cards
    stats_cards = ft.Row(
        controls=[
            # Total Buy Price
            ft.Container(
                content=ft.Column([
                    ft.Text("Total Invested", size=12, color=COLORS["text_secondary"]),
                    ft.Text(f"{stats['total_buy']:.0f} ₽", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                ], spacing=4),
                padding=16,
                bgcolor=COLORS["bg_surface"],
                border_radius=RADIUS["lg"],
                border=ft.border.all(1, COLORS["border"]),
                expand=1,
            ),
            # Total Expected
            ft.Container(
                content=ft.Column([
                    ft.Text("Expected Value", size=12, color=COLORS["text_secondary"]),
                    ft.Text(f"{stats['total_expected']:.0f} ₽" if stats['total_expected'] > 0 else "-", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                ], spacing=4),
                padding=16,
                bgcolor=COLORS["bg_surface"],
                border_radius=RADIUS["lg"],
                border=ft.border.all(1, COLORS["border"]),
                expand=1,
            ),
            # Total Current TM
            ft.Container(
                content=ft.Column([
                    ft.Text("Current TM Value", size=12, color=COLORS["text_secondary"]),
                    ft.Text(f"{stats['total_current']:.0f} ₽" if stats['total_current'] > 0 else "-", size=20, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                ], spacing=4),
                padding=16,
                bgcolor=COLORS["bg_surface"],
                border_radius=RADIUS["lg"],
                border=ft.border.all(1, COLORS["border"]),
                expand=1,
            ),
            # Total Profit
            ft.Container(
                content=ft.Column([
                    ft.Text("Total Profit", size=12, color=COLORS["text_secondary"]),
                    ft.Row([
                        ft.Text(
                            f"{stats['total_profit']:+.0f} ₽" if stats['total_profit'] != 0 else "0 ₽",
                            size=20,
                            weight=ft.FontWeight.BOLD,
                            color=profit_color
                        ),
                        ft.Text(
                            f"({stats['total_profit_pct']:+.1f}%)" if stats['total_profit'] != 0 else "(0%)",
                            size=14,
                            color=profit_color
                        ),
                    ], spacing=4),
                ], spacing=4),
                padding=16,
                bgcolor=COLORS["bg_surface"],
                border_radius=RADIUS["lg"],
                border=ft.border.all(1, COLORS["border"]),
                expand=1,
            ),
        ],
        spacing=12,
    )

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
                        ft.Text("Inventory - Items on Hold", size=FONT_SIZES["2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                        ft.FilledButton(
                            "Refresh Prices",
                            icon=ft.Icons.REFRESH,
                            on_click=on_refresh_prices if db_service else None,
                            disabled=not db_service,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # Item count
                ft.Text(
                    ref=count_text_ref,
                    value=f"{len(items)} items on hold",
                    size=FONT_SIZES["sm"],
                    color=COLORS["text_secondary"],
                ),
                # Stats cards
                stats_cards,
                # Table (fills remaining space)
                table_container,
            ],
            spacing=12,
            expand=True,
        ),
        padding=20,
        expand=True,
    )


InventoryView = create_inventory_view
