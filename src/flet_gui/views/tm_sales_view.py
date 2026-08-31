"""
CSGO.TM Sales view - управление автоматическими продажами.

Показывает:
- Статус продаж для каждого аккаунта
- Предметы готовые к продаже (холд прошел)
- Предметы на продаже
- Статистику продаж
- Кнопки управления (Start/Stop sales, Update inventory)
"""

import asyncio
from datetime import datetime
from typing import Optional

import flet as ft

from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState
from flet_gui.services.tm_sales_service import TmSalesService, SalesStatus


def create_tm_sales_view(
    sales_service: Optional[TmSalesService] = None,
    account_service=None,
    db_service=None,
    page: Optional[ft.Page] = None
) -> ft.Container:
    """
    Create CSGO.TM Sales view.

    Shows:
    - Account sales status cards
    - Items ready for sale
    - Active listings
    - Sales statistics
    """
    state = AppState()

    # Refs for dynamic updates
    accounts_column_ref = ft.Ref[ft.Column]()
    ready_items_column_ref = ft.Ref[ft.Column]()
    listed_items_column_ref = ft.Ref[ft.Column]()
    stats_row_ref = ft.Ref[ft.Row]()

    def get_status_color(status: SalesStatus) -> str:
        """Get color for sales status."""
        return {
            SalesStatus.ONLINE: COLORS["status_online"],
            SalesStatus.STARTING: COLORS["accent_yellow"],
            SalesStatus.OFFLINE: COLORS["text_secondary"],
            SalesStatus.ERROR: COLORS["accent_red"],
            SalesStatus.STOPPED: COLORS["text_secondary"],
        }.get(status, COLORS["text_secondary"])

    def get_status_text(status: SalesStatus) -> str:
        """Get text for sales status."""
        return {
            SalesStatus.ONLINE: "Online",
            SalesStatus.STARTING: "Starting...",
            SalesStatus.OFFLINE: "Offline",
            SalesStatus.ERROR: "Error",
            SalesStatus.STOPPED: "Stopped",
        }.get(status, "Unknown")

    def create_account_card(account_name: str, status: SalesStatus, stats=None, sell_status=None) -> ft.Container:
        """Create card for account sales status."""
        status_color = get_status_color(status)
        status_text = get_status_text(status)

        # Sell status indicators
        sell_indicators = []
        if sell_status:
            indicators = [
                ("Trade Link", sell_status.get("user_token", False)),
                ("Trade Check", sell_status.get("trade_check", False)),
                ("API Key", sell_status.get("steam_web_api_key", False)),
                ("No Ban", sell_status.get("site_notmpban", True)),
            ]
            for name, ok in indicators:
                color = COLORS["status_online"] if ok else COLORS["accent_red"]
                sell_indicators.append(
                    ft.Container(
                        content=ft.Text(name, size=10, color=color),
                        bgcolor=f"{color}20",
                        border_radius=4,
                        padding=ft.padding.symmetric(horizontal=4, vertical=2),
                    )
                )

        # Stats row
        stats_items = []
        if stats:
            stats_items = [
                ft.Text(f"Listed: {stats.items_listed}", size=FONT_SIZES["sm"], color=COLORS["accent_blue"]),
                ft.Text(f"Sold: {stats.items_sold}", size=FONT_SIZES["sm"], color=COLORS["status_online"]),
                ft.Text(f"Trades: {stats.trades_confirmed}", size=FONT_SIZES["sm"], color=COLORS["accent_purple"]),
            ]
            if stats.last_ping_time:
                ping_ago = (datetime.now() - stats.last_ping_time).seconds
                stats_items.append(
                    ft.Text(f"Ping: {ping_ago}s ago", size=FONT_SIZES["xs"], color=COLORS["text_secondary"])
                )
            if stats.last_error:
                stats_items.append(
                    ft.Text(f"Error: {stats.last_error[:30]}", size=FONT_SIZES["xs"], color=COLORS["accent_red"])
                )

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(account_name, size=FONT_SIZES["base"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    ft.Container(
                        content=ft.Text(status_text, size=FONT_SIZES["xs"], color=status_color),
                        bgcolor=f"{status_color}20",
                        border_radius=8,
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row(sell_indicators, spacing=4, wrap=True) if sell_indicators else ft.Container(),
                ft.Row(stats_items, spacing=12) if stats_items else ft.Container(),
            ], spacing=8),
            bgcolor=COLORS["bg_surface"],
            border_radius=RADIUS["md"],
            padding=16,
            border=ft.border.all(1, COLORS["border"]),
        )

    def create_item_row(item: dict) -> ft.DataRow:
        """Create row for item ready for sale."""
        market_name = item.get("market_hash_name", item.get("item_name", "Unknown"))
        account = item.get("account_name", "")
        expected_price = item.get("expected_sell_price", 0)
        purchase_price = item.get("purchase_price", 0)
        # Профит считаем от цены закупки в Steam
        profit_pct = ((expected_price - purchase_price) / purchase_price * 100) if purchase_price > 0 else 0
        unlock_date = item.get("unlock_date", "")
        # Format unlock_date to show time in GMT
        unlock_date_str = ""
        if unlock_date:
            # Extract date and time from unlock_date string
            unlock_date_str = str(unlock_date)[:16] + " GMT"  # Show "YYYY-MM-DD HH:MM GMT"

        return ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(market_name[:40], size=FONT_SIZES["sm"], color=COLORS["text_primary"])),
                ft.DataCell(ft.Text(account, size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                ft.DataCell(ft.Text(f"{purchase_price:.0f}", size=FONT_SIZES["sm"], color=COLORS["accent_blue"])),  # Цена закупки
                ft.DataCell(ft.Text(f"{profit_pct:.1f}%", size=FONT_SIZES["sm"],
                    color=COLORS["status_online"] if profit_pct > 0 else COLORS["accent_red"])),
                ft.DataCell(ft.Text(unlock_date_str, size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
            ]
        )

    async def refresh_view():
        """Refresh the view with current data."""
        # Refresh account cards
        if accounts_column_ref.current and sales_service:
            cards = []
            statuses = sales_service.get_all_statuses()

            for acc_name, status in statuses.items():
                stats = sales_service.get_stats(acc_name)
                sell_status = sales_service.get_sell_status(acc_name)
                cards.append(create_account_card(acc_name, status, stats, sell_status))

            if not cards:
                # Show placeholder if no accounts
                for acc in state.accounts:
                    if acc.enabled:
                        cards.append(create_account_card(acc.name, SalesStatus.STOPPED))

            accounts_column_ref.current.controls = cards
            accounts_column_ref.current.update()

        # Refresh items ready for sale
        if ready_items_column_ref.current and db_service:
            try:
                from src.database import TradesDatabase
                # Run DB query in thread to avoid blocking GUI
                db = TradesDatabase()
                items = await asyncio.to_thread(db.get_items_ready_for_sale)

                rows = [create_item_row(item) for item in items[:50]]  # Limit to 50 items

                # Double-check ref is still valid before updating
                if not ready_items_column_ref.current:
                    return

                if rows:
                    ready_items_column_ref.current.controls = [
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Item", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                                ft.DataColumn(ft.Text("Account", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                                ft.DataColumn(ft.Text("Buy Price", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                                ft.DataColumn(ft.Text("Profit %", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                                ft.DataColumn(ft.Text("Unlocked", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                            ],
                            rows=rows,
                            border=ft.border.all(1, COLORS["border"]),
                            border_radius=RADIUS["sm"],
                            heading_row_color=COLORS["bg_surface"],
                            data_row_min_height=40,
                            column_spacing=20,
                            width=float('inf'),
                        )
                    ]
                else:
                    ready_items_column_ref.current.controls = [
                        ft.Text("No items ready for sale", color=COLORS["text_secondary"])
                    ]
                ready_items_column_ref.current.update()
            except Exception as e:
                import traceback
                logger.error(f"Failed to load ready items: {e}\n{traceback.format_exc()}")
                state.add_log(f"[ERROR] Failed to load items: {e}")

        # Refresh listed items on CSGO.TM
        if listed_items_column_ref.current and account_service:
            await load_listed_items()

        if page:
            page.update()

    async def load_listed_items():
        """Load items currently listed on CSGO.TM."""
        try:
            all_listed_items = []

            # Получаем предметы для всех аккаунтов
            for acc in state.accounts:
                if not acc.enabled:
                    continue

                # Получаем аккаунт из account_service
                if account_service and account_service.account_manager:
                    account = account_service.account_manager.get_account(acc.name)
                    if not account:
                        state.add_log(f"[WARNING] [{acc.name}] Account not found in account_manager")
                        continue
                    if not account.csgotm_client:
                        state.add_log(f"[WARNING] [{acc.name}] CSGO.TM client not initialized")
                        continue

                    if account and account.csgotm_client:
                        # Получаем все предметы с CSGO.TM (в потоке чтобы не блокировать GUI)
                        items = await asyncio.to_thread(account.csgotm_client.get_all_items)
                        state.add_log(f"[DEBUG] [{acc.name}] Loaded {len(items)} items from CSGO.TM")

                        # Синхронизируем статусы с базой данных
                        from src.database import TradesDatabase
                        db = TradesDatabase()

                        # Фильтруем только предметы на продаже (status=1)
                        items_on_sale = 0
                        for item in items:
                            status = str(item.get("status", ""))
                            if status == "1":
                                items_on_sale += 1
                                # Получаем цену напрямую из API (уже в рублях)
                                price = item.get("price", 0)
                                market_hash_name = item.get("market_hash_name", "Unknown")

                                # Синхронизация: если предмет на CSGO.TM, обновляем статус в базе на 'listed'
                                our_items = await asyncio.to_thread(db.get_purchased_items, account_name=acc.name)
                                for our_item in our_items:
                                    if our_item.get("market_hash_name") == market_hash_name and our_item.get("status") == "holding":
                                        await asyncio.to_thread(db.update_purchased_item_status, our_item["id"], "listed")
                                        state.add_log(f"[INFO] [{acc.name}] Synced status to 'listed': {market_hash_name[:30]}")
                                        break

                                all_listed_items.append({
                                    "account_name": acc.name,
                                    "market_hash_name": market_hash_name,
                                    "price": price,  # Цена в рублях
                                    "lowest_market_price": "...",  # Будет загружено позже
                                    "item_id": item.get("item_id", ""),
                                    "csgotm_client": account.csgotm_client,  # Для отложенной загрузки
                                })

                        state.add_log(f"[DEBUG] [{acc.name}] Found {items_on_sale} items with status=1 (on sale)")

            # Создаем таблицу с текстовыми элементами, которые можно обновлять
            if all_listed_items:
                rows = []
                price_text_refs = []  # Сохраняем ссылки на текстовые элементы

                for idx, item in enumerate(all_listed_items[:20]):  # Показываем первые 20
                    price_text = ft.Text(str(item['lowest_market_price']), size=FONT_SIZES["sm"], color=COLORS["accent_blue"])
                    price_text_refs.append((idx, price_text, item))

                    rows.append(
                        ft.DataRow(cells=[
                            ft.DataCell(ft.Text(item["market_hash_name"][:40], size=FONT_SIZES["sm"])),
                            ft.DataCell(ft.Text(item["account_name"], size=FONT_SIZES["sm"])),
                            ft.DataCell(ft.Text(f"{item['price']:.2f}", size=FONT_SIZES["sm"])),
                            ft.DataCell(price_text),
                        ])
                    )

                # Check ref is still valid before updating
                if not listed_items_column_ref.current:
                    return

                listed_items_column_ref.current.controls = [
                    ft.Text(f"Total: {len(all_listed_items)} items", size=FONT_SIZES["sm"], color=COLORS["accent_blue"]),
                    ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text("Item", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                            ft.DataColumn(ft.Text("Account", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                            ft.DataColumn(ft.Text("My Price", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                            ft.DataColumn(ft.Text("Top-1 Price", size=FONT_SIZES["sm"], color=COLORS["text_secondary"])),
                        ],
                        rows=rows,
                        border=ft.border.all(1, COLORS["border"]),
                        border_radius=RADIUS["sm"],
                        vertical_lines=ft.border.BorderSide(1, COLORS["border"]),
                        horizontal_lines=ft.border.BorderSide(1, COLORS["border"]),
                        width=float('inf'),
                    )
                ]

                # Обновляем таблицу сразу
                if listed_items_column_ref.current:
                    listed_items_column_ref.current.update()

                # Запускаем фоновую загрузку цен
                if page:
                    page.run_task(load_bid_ask_prices, price_text_refs)
            else:
                # Check ref is still valid before updating
                if not listed_items_column_ref.current:
                    return

                listed_items_column_ref.current.controls = [
                    ft.Text("No items on sale", color=COLORS["text_secondary"])
                ]
                listed_items_column_ref.current.update()

        except Exception as e:
            logger.error(f"Failed to load listed items: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            state.add_log(f"[ERROR] Failed to load listed items: {e}")

    async def load_bid_ask_prices(price_text_refs):
        """Load bid-ask prices in background and update table cells."""
        for idx, price_text, item in price_text_refs:
            try:
                # Проверяем что контрол ещё на странице
                if not hasattr(price_text, 'page') or price_text.page is None:
                    return  # Страница закрыта, прекращаем загрузку

                csgotm_client = item.get("csgotm_client")
                market_hash_name = item.get("market_hash_name")

                if not csgotm_client or not market_hash_name:
                    continue

                # Получаем bid-ask данные (в потоке чтобы не блокировать GUI)
                bid_ask_data = await asyncio.to_thread(csgotm_client.get_bid_ask, market_hash_name)

                if bid_ask_data and bid_ask_data.get("ask"):
                    # Берем самую низкую цену (top-1)
                    asks = bid_ask_data["ask"]
                    if asks:
                        lowest_ask = asks[0]["price"]
                        price_text.value = f"{lowest_ask:.2f}"
                    else:
                        price_text.value = "N/A"
                else:
                    price_text.value = "N/A"

                # Обновляем UI только если контрол на странице
                try:
                    if price_text.page:
                        price_text.update()
                except RuntimeError:
                    return  # Страница закрыта

                # Небольшая задержка между запросами
                await asyncio.sleep(0.3)

            except RuntimeError:
                # Control not on page - stop loading
                return
            except Exception as e:
                # Только логируем если это не ошибка страницы
                if "Control must be added" not in str(e):
                    state.add_log(f"[DEBUG] Failed to load bid-ask for {item.get('market_hash_name', 'unknown')}: {e}")

    async def on_start_sales(e):
        """Start sales service."""
        if not sales_service:
            state.add_log("[ERROR] Sales service not available")
            return

        state.add_log("[INFO] Starting TM Sales service...")
        await sales_service.start()
        # Ждем немного чтобы клиенты инициализировались
        await asyncio.sleep(2)
        await refresh_view()

    async def on_stop_sales(e):
        """Stop sales service."""
        if not sales_service:
            return

        state.add_log("[INFO] Stopping TM Sales service...")
        await sales_service.stop()
        await refresh_view()

    async def on_update_inventory(e):
        """Update inventory on CSGO.TM for all accounts."""
        if not sales_service:
            return

        state.add_log("[INFO] Updating inventory on CSGO.TM...")
        for acc in state.accounts:
            if acc.enabled:
                await sales_service.update_inventory(acc.name)
                await asyncio.sleep(2)

        state.add_log("[SUCCESS] Inventory update requested for all accounts")

    async def on_import_from_inventory(e):
        """Import items from Steam inventory that are not tracked in DB."""
        if not account_service or not db_service:
            state.add_log("[WARNING] Account service or DB service not available")
            return

        state.add_log("[INFO] Importing items from Steam inventory...")
        results = await account_service.import_items_from_inventory(db_service)

        # Refresh data after import
        db_service.refresh_inventory()

        state.add_log(
            f"[SUCCESS] Import complete: "
            f"{results['imported']} imported, "
            f"{results['skipped']} skipped"
        )

        if results['errors']:
            for err in results['errors']:
                state.add_log(f"[ERROR] {err}")

        # Refresh view
        await refresh_view()

    async def on_update_prices(e):
        """Update overpriced items to top-1 price."""
        if not sales_service:
            state.add_log("[WARNING] Sales service not available")
            return

        state.add_log("[INFO] Checking for overpriced items...")

        # Обновляем цены для всех аккаунтов
        result = await sales_service.update_overpriced_items()

        if result['updated'] > 0:
            state.add_log(
                f"[SUCCESS] Price update complete: "
                f"{result['updated']} updated, "
                f"{result['skipped']} skipped"
            )
        else:
            state.add_log("[INFO] No overpriced items found or all updates failed")

        if result['errors']:
            for err in result['errors'][:5]:  # Показываем первые 5 ошибок
                state.add_log(f"[ERROR] {err}")

        # Refresh view
        await refresh_view()

    async def on_refresh(e):
        """Refresh view."""
        await refresh_view()

    async def on_manual_ping(e, account_name: str):
        """Manual ping for account."""
        if not sales_service:
            return

        state.add_log(f"[INFO] Manual ping for {account_name}...")
        await sales_service.manual_ping(account_name)
        await refresh_view()

    # Header with controls
    header = ft.Container(
        content=ft.Row([
            ft.Text("CSGO.TM Sales", size=FONT_SIZES["xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ft.Row([
                ft.FilledButton(
                    "Start Sales",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=lambda e: page.run_task(on_start_sales, e) if page else None,
                    style=ft.ButtonStyle(bgcolor=COLORS["status_online"], color=COLORS["text_primary"]),
                    disabled=sales_service.is_running() if sales_service else True,
                ),
                ft.FilledButton(
                    "Stop Sales",
                    icon=ft.Icons.STOP,
                    on_click=lambda e: page.run_task(on_stop_sales, e) if page else None,
                    style=ft.ButtonStyle(bgcolor=COLORS["accent_red"], color=COLORS["text_primary"]),
                    disabled=not sales_service.is_running() if sales_service else True,
                ),
                ft.OutlinedButton(
                    "Update Inventory",
                    icon=ft.Icons.REFRESH,
                    on_click=lambda e: page.run_task(on_update_inventory, e) if page else None,
                ),
                ft.OutlinedButton(
                    "Import from Inventory",
                    icon=ft.Icons.DOWNLOAD,
                    on_click=lambda e: page.run_task(on_import_from_inventory, e) if page else None,
                    tooltip="Import items from Steam inventory to DB",
                ),
                ft.OutlinedButton(
                    "Update Prices",
                    icon=ft.Icons.TRENDING_DOWN,
                    on_click=lambda e: page.run_task(on_update_prices, e) if page else None,
                    tooltip="Update overpriced items to top-1",
                    disabled=not sales_service.is_running() if sales_service else True,
                ),
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_color=COLORS["text_secondary"],
                    on_click=lambda e: page.run_task(on_refresh, e) if page else None,
                    tooltip="Refresh",
                ),
            ], spacing=8),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=ft.padding.only(bottom=16),
    )

    # Account status cards
    accounts_section = ft.Container(
        content=ft.Column([
            ft.Text("Account Status", size=FONT_SIZES["lg"], weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ft.Column(
                ref=accounts_column_ref,
                controls=[
                    create_account_card(acc.name, SalesStatus.STOPPED)
                    for acc in state.accounts if acc.enabled
                ] or [ft.Text("No enabled accounts", color=COLORS["text_secondary"])],
                spacing=8,
            ),
        ], spacing=12),
        padding=ft.padding.only(bottom=24),
    )

    # Items ready for sale
    items_section = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Items Ready for Sale", size=FONT_SIZES["lg"], weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
                ft.Text("(Hold period passed)", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
            ], spacing=8),
            ft.Column(
                ref=ready_items_column_ref,
                controls=[
                    ft.Row([
                        ft.ProgressRing(width=16, height=16, stroke_width=2, color=COLORS["accent_purple"]),
                        ft.Text("Loading items...", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                    ], spacing=8),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ], spacing=12),
    )

    # Items currently on sale on CSGO.TM
    listed_items_section = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Items on Sale (CSGO.TM)", size=FONT_SIZES["lg"], weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
                ft.TextButton(
                    "Refresh",
                    on_click=lambda e: page.run_task(refresh_view) if page else None,
                ),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Column(
                ref=listed_items_column_ref,
                controls=[
                    ft.Row([
                        ft.ProgressRing(width=16, height=16, stroke_width=2, color=COLORS["accent_purple"]),
                        ft.Text("Loading items from CSGO.TM...", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                    ], spacing=8),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ], spacing=12),
        padding=ft.padding.only(top=24),
    )

    # Info section
    info_section = ft.Container(
        content=ft.Column([
            ft.Text("How it works", size=FONT_SIZES["base"], weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ft.Text(
                "1. Start Sales - enables auto-selling (ping every 3 min)\n"
                "2. Items with passed hold are auto-listed on CSGO.TM\n"
                "3. When sold, trades are auto-confirmed\n"
                "4. Access token refreshes every 23 hours",
                size=FONT_SIZES["sm"],
                color=COLORS["text_secondary"],
            ),
        ], spacing=8),
        bgcolor=COLORS["bg_surface"],
        border_radius=RADIUS["md"],
        padding=16,
        margin=ft.margin.only(top=24),
    )

    # Main layout
    content = ft.Column([
        header,
        accounts_section,
        items_section,
        listed_items_section,
        info_section,
    ])

    # Initial data load
    if page:
        page.run_task(refresh_view)

    # Обернем контент в контейнер со скроллом
    return ft.Container(
        content=ft.Column([
            ft.Container(
                content=content,
                padding=24,
            )
        ], scroll=ft.ScrollMode.AUTO, expand=True),
        expand=True,
    )
