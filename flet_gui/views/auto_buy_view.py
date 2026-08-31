"""
AutoBuy view - управление автопокупкой предметов.
"""

import flet as ft
import asyncio

from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState


def create_auto_buy_view(page=None, auto_buy_service=None, account_service=None) -> ft.Container:
    """AutoBuy view с управлением и статистикой."""
    state = AppState()

    # Refs для обновления
    stats_column_ref = ft.Ref[ft.Column]()
    status_text_ref = ft.Ref[ft.Text]()
    start_button_ref = ft.Ref[ft.FilledButton]()
    stop_button_ref = ft.Ref[ft.FilledButton]()
    account_dropdown_ref = ft.Ref[ft.Dropdown]()
    orders_info_ref = ft.Ref[ft.Text]()  # Информация о сумме ордеров и лимите

    def make_item_row(item_info, is_charm=False):
        """Создать строку с информацией о предмете."""
        name = item_info['name']
        current = item_info['current']
        target = item_info['target']
        pending = item_info['pending']
        needed = item_info['needed']

        # Цвет и текст в зависимости от статуса
        if current >= target:
            status_bg = COLORS["status_online"]
            status_text = "OK"
            text_color = COLORS["text_primary"]
        elif pending > 0:
            status_bg = COLORS["accent_yellow"]
            status_text = f"Pending: {pending}"
            text_color = COLORS["text_primary"]
        else:
            status_bg = COLORS["accent_red"]
            status_text = f"Need: {needed}"
            text_color = COLORS["text_primary"]

        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text(name, size=FONT_SIZES["sm"], color=COLORS["text_primary"]),
                    expand=5,
                    padding=ft.padding.only(left=8),  # Отступ слева
                ),
                ft.Text(f"{current}/{target}", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                ft.Container(
                    content=ft.Text(status_text, size=FONT_SIZES["xs"], color=text_color, weight=ft.FontWeight.W_500),
                    bgcolor=status_bg,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    border_radius=RADIUS["sm"],
                ),
            ], spacing=12, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=4, vertical=12),
            border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )

    async def get_orders_info_async() -> tuple:
        """Получить информацию о сумме ордеров и лимите (баланс x10). Non-blocking."""
        # Маппинг кодов валют Steam на символы
        CURRENCY_SYMBOLS = {
            1: "$",      # USD
            3: "€",      # EUR
            5: "₽",      # RUB
            18: "R$",    # BRL
            9: "£",      # GBP
            23: "¥",     # CNY
        }

        total_orders_sum = 0.0
        wallet_balance = 0.0
        order_limit = 0.0
        currency_symbol = "₽"  # По умолчанию рубли

        if account_service and account_service.account_manager:
            # Получаем выбранный аккаунт или первый залогиненный
            selected_name = auto_buy_service.selected_account_name if auto_buy_service else None
            account = None

            for acc in account_service.account_manager.accounts:
                if selected_name:
                    if acc.name == selected_name and acc.is_logged_in():
                        account = acc
                        break
                elif acc.is_logged_in():
                    account = acc
                    break

            if account:
                try:
                    # Async call - no GUI blocking
                    wallet_info = await account.steam_client.get_wallet_balance()

                    wallet_balance = wallet_info.balance
                    currency_symbol = CURRENCY_SYMBOLS.get(wallet_info.currency, "₽")
                    order_limit = wallet_balance * 10  # Лимит = баланс x10

                    # Получаем все активные ордера и считаем их сумму
                    try:
                        my_orders = await account.steam_client.get_my_market_orders()

                        # Подсчитываем общую сумму активных buy ордеров
                        for order in my_orders:
                            if order.get('type') == 'buy':
                                price = order.get('price', 0)  # Цена за 1 шт
                                quantity = order.get('quantity', 1)
                                total_orders_sum += (price * quantity)

                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).error(f"Failed to get orders sum: {e}")

                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Failed to get wallet balance: {e}")

        return total_orders_sum, wallet_balance, order_limit, currency_symbol

    async def update_orders_info():
        """Обновить информацию о сумме ордеров (non-blocking)."""
        if not orders_info_ref.current:
            return

        total_sum, balance, limit, currency_symbol = await get_orders_info_async()

        if balance > 0:
            remaining_limit = limit - total_sum
            orders_info_ref.current.value = f"{balance:.2f} {currency_symbol} | Orders: {total_sum:.2f}/{limit:.2f} {currency_symbol}"

            # Цвет в зависимости от использования лимита
            usage_percent = (total_sum / limit * 100) if limit > 0 else 0
            if usage_percent >= 90:
                orders_info_ref.current.color = COLORS["accent_red"]
            elif usage_percent >= 70:
                orders_info_ref.current.color = COLORS["accent_yellow"]
            else:
                orders_info_ref.current.color = COLORS["text_primary"]
        else:
            orders_info_ref.current.value = "Login to see balance"
            orders_info_ref.current.color = COLORS["text_secondary"]

        if page:
            page.update()

    async def refresh_stats():
        """Обновить статистику (non-blocking)."""
        if not auto_buy_service or not stats_column_ref.current:
            return

        # Обновляем информацию о балансе и лимите
        await update_orders_info()

        stats = auto_buy_service.get_stats()

        controls = []

        # Скины
        if stats['skins']:
            controls.append(
                ft.Container(
                    content=ft.Text("Skins (Target: 10 each)", size=FONT_SIZES["base"],
                                   weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
                    padding=ft.padding.only(left=8, top=8, bottom=4)
                )
            )
            for item in stats['skins']:
                controls.append(make_item_row(item, is_charm=False))

        # Разделитель
        if stats['skins'] and stats['charms']:
            controls.append(ft.Divider(height=20, color=COLORS["border"]))

        # Брелки
        if stats['charms']:
            controls.append(
                ft.Container(
                    content=ft.Text("Charms (Target: 25 each)", size=FONT_SIZES["base"],
                                   weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
                    padding=ft.padding.only(left=8, top=8, bottom=4)
                )
            )
            for item in stats['charms']:
                controls.append(make_item_row(item, is_charm=True))

        if not controls:
            controls.append(
                ft.Text("No items configured in skins.txt",
                       size=FONT_SIZES["sm"], color=COLORS["text_secondary"])
            )

        stats_column_ref.current.controls = controls
        if page:
            page.update()

    def update_status():
        """Обновить статус сервиса."""
        if not auto_buy_service:
            return

        is_running = auto_buy_service.is_running()

        if status_text_ref.current:
            status_text_ref.current.value = "Running" if is_running else "Stopped"
            status_text_ref.current.color = COLORS["status_online"] if is_running else COLORS["text_secondary"]

        if start_button_ref.current:
            start_button_ref.current.disabled = is_running

        if stop_button_ref.current:
            stop_button_ref.current.disabled = not is_running

        if page:
            page.update()

    async def on_start(e):
        """Запустить автопокупку."""
        if not auto_buy_service:
            state.add_log("[ERROR] AutoBuy service not available")
            return

        state.add_log("[INFO] Starting AutoBuy service...")
        await auto_buy_service.start()

        # Сразу делаем первую проверку инвентаря и синхронизацию ордеров
        state.add_log("[INFO] Checking inventory and syncing orders...")
        await auto_buy_service._check_inventory()

        update_status()
        await refresh_stats()

    async def on_stop(e):
        """Остановить автопокупку."""
        if not auto_buy_service:
            return

        state.add_log("[INFO] Stopping AutoBuy service...")
        await auto_buy_service.stop()
        update_status()

    async def on_refresh(e):
        """Обновить статистику (non-blocking)."""
        await refresh_stats()

    async def on_account_change(e):
        """Обработка смены аккаунта (non-blocking)."""
        if not auto_buy_service:
            return

        selected_account = e.control.value

        # Пустая строка означает "Auto"
        if selected_account == "":
            auto_buy_service.set_selected_account(None)
            state.add_log("[INFO] AutoBuy: Using auto mode (first logged in account)")
        else:
            auto_buy_service.set_selected_account(selected_account)
            state.add_log(f"[INFO] AutoBuy: Selected account: {selected_account}")

        # Обновление UI
        if page:
            page.update()

    def get_account_options():
        """Получить список аккаунтов для dropdown."""
        if not auto_buy_service:
            return []

        accounts = auto_buy_service.get_available_accounts()

        # Create options with explicit text and key
        options = [ft.dropdown.Option(key=acc, text=acc) for acc in accounts]

        # Добавляем "Auto (first logged in)" как первый вариант
        options.insert(0, ft.dropdown.Option(key="", text="Auto (first logged in)"))

        return options

    async def sync_pending_orders():
        """Синхронизировать pending_orders с реальными ордерами Steam."""
        if not auto_buy_service or not account_service:
            return

        try:
            accounts = account_service.account_manager.accounts if account_service.account_manager else []

            # Собираем все активные ордера со всех залогиненных аккаунтов
            all_orders = {}
            for account in accounts:
                if not account.is_logged_in():
                    continue

                try:
                    existing_orders = await auto_buy_service._get_existing_orders(account)
                    # Объединяем ордера со всех аккаунтов
                    for item_name, quantity in existing_orders.items():
                        all_orders[item_name] = all_orders.get(item_name, 0) + quantity
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to get orders for {account.name}: {e}")

            # Синхронизируем pending_orders с реальными ордерами
            for item in auto_buy_service.items:
                item.pending_orders = all_orders.get(item.name, 0)

            state.add_log("[INFO] Pending orders synced successfully")

        except Exception as e:
            state.add_log(f"[ERROR] Failed to sync pending orders: {e}")

    async def on_create_orders(e):
        """Создать ордера на покупку недостающих предметов."""
        if not auto_buy_service:
            state.add_log("[ERROR] auto_buy_service is None")
            return

        from flet_gui.components.progress_overlay import ProgressOverlay
        progress = ProgressOverlay(page)

        try:
            # Сначала синхронизируем pending_orders с реальными ордерами Steam
            progress.show("Syncing pending orders...")
            state.add_log("[INFO] Syncing pending orders before creating new ones...")
            await sync_pending_orders()

            # Теперь считаем needed с актуальными pending_orders
            items_list = []
            for item in auto_buy_service.items:
                needed = item.target_count - item.current_count - item.pending_orders
                if needed > 0:
                    items_list.append((item, needed))

            if not items_list:
                state.add_log("[INFO] No items needed, all targets met!")
                # Обновляем статистику даже если ничего не нужно
                await refresh_stats()
                return

            total_needed = sum(count for _, count in items_list)
            progress.update_message(f"Creating {total_needed} buy orders...")
            state.add_log(f"[INFO] Creating buy orders for {total_needed} items ({len(items_list)} types)...")

            # Call the actual order creation
            await auto_buy_service._create_orders(items_list)

            # Синхронизировать pending_orders с реальными ордерами после создания
            progress.update_message("Syncing orders...")
            state.add_log("[INFO] Syncing pending orders after creation...")
            await sync_pending_orders()

            # Refresh stats after creating orders
            await refresh_stats()
            state.add_log(f"[SUCCESS] Created {total_needed} buy orders!")

        except Exception as ex:
            state.add_log(f"[ERROR] Create orders failed: {str(ex)}")
        finally:
            progress.hide()
            await refresh_stats()
            if page:
                page.update()

    # Header
    header = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Icon(ft.Icons.SHOPPING_BAG, color=COLORS["accent_purple"], size=24),
                ft.Text("Auto Buy", size=FONT_SIZES["lg"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ], spacing=8),
            ft.Row([
                ft.Text("Status:", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                ft.Text("Stopped", ref=status_text_ref, size=FONT_SIZES["sm"],
                       color=COLORS["text_secondary"], weight=ft.FontWeight.W_600),
            ], spacing=8),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=16,
        bgcolor=COLORS["bg_surface"],
        border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
    )

    # Account dropdown
    account_dropdown = ft.Dropdown(
        ref=account_dropdown_ref,
        options=get_account_options(),
        value="",  # Auto by default
        width=250,
        height=45,
        text_size=FONT_SIZES["sm"],
        border_color=COLORS["border"],
        focused_border_color=COLORS["accent_purple"],
        bgcolor=COLORS["bg_surface"],
        hint_text="Select account",
        on_select=on_account_change,
        border_radius=RADIUS["md"],
    )

    # Account selection with balance info
    account_selector = ft.Container(
        content=ft.Row([
            ft.Column([
                ft.Text("Account:", size=FONT_SIZES["sm"], color=COLORS["text_secondary"], weight=ft.FontWeight.W_500),
                account_dropdown,
            ], spacing=4),
            ft.Column([
                ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=16, color=COLORS["text_secondary"]),
                ft.Text(
                    "Login to see balance",
                    ref=orders_info_ref,
                    size=FONT_SIZES["xs"],
                    color=COLORS["text_secondary"],
                ),
            ], spacing=4, alignment=ft.MainAxisAlignment.CENTER),
        ], spacing=16, alignment=ft.MainAxisAlignment.START),
        padding=ft.padding.only(left=16, right=16, top=12, bottom=12),
        bgcolor=COLORS["bg_elevated"],
        border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
    )

    # Controls
    controls_row = ft.Container(
        content=ft.Row([
            ft.FilledButton(
                "Start Monitoring",
                icon=ft.Icons.PLAY_ARROW,
                on_click=on_start,
                style=ft.ButtonStyle(bgcolor=COLORS["status_online"], color=COLORS["text_primary"]),
                ref=start_button_ref,
            ),
            ft.FilledButton(
                "Stop Monitoring",
                icon=ft.Icons.STOP,
                on_click=on_stop,
                style=ft.ButtonStyle(bgcolor=COLORS["accent_red"], color=COLORS["text_primary"]),
                disabled=True,
                ref=stop_button_ref,
            ),
            ft.FilledButton(
                "Create Orders",
                icon=ft.Icons.ADD_SHOPPING_CART,
                on_click=on_create_orders,
                style=ft.ButtonStyle(bgcolor=COLORS["accent_purple"], color=COLORS["text_primary"]),
                tooltip="Create buy orders for missing items",
            ),
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                icon_color=COLORS["text_secondary"],
                on_click=on_refresh,
                tooltip="Refresh",
            ),
        ], spacing=12),
        padding=ft.padding.only(left=16, right=16, bottom=16),
    )

    # Stats section - занимает всё доступное пространство
    stats_section = ft.Container(
        content=ft.Column([
            ft.Text("Items Status", size=FONT_SIZES["lg"], weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ft.Container(
                content=ft.Column(
                    ref=stats_column_ref,
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                ),
                bgcolor=COLORS["bg_surface"],
                border=ft.border.all(1, COLORS["border"]),
                border_radius=RADIUS["md"],
                padding=0,
                expand=True,
            ),
        ], spacing=12, expand=True),
        padding=16,
        expand=True,  # Эта секция растягивается, занимая всё доступное место
    )

    content = ft.Column([
        header,
        account_selector,
        controls_row,
        stats_section,
    ], spacing=0, expand=True)

    # Auto-refresh task
    auto_refresh_task = None

    async def auto_refresh_loop():
        """Автоматическое обновление каждые 30 секунд."""
        while True:
            await asyncio.sleep(30)
            try:
                await refresh_stats()
                update_status()
            except Exception:
                pass  # Игнорируем ошибки при обновлении

    async def initial_load():
        """Initial async load of stats."""
        update_status()
        await refresh_stats()

    def start_auto_refresh():
        """Запустить автообновление."""
        nonlocal auto_refresh_task
        if page and auto_refresh_task is None:
            auto_refresh_task = asyncio.create_task(auto_refresh_loop())

    # Подписываемся на события подтверждения ордеров (для аккаунтов без identity_secret)
    _pending_confirmation_account: list = [None]  # [account_name] — текущий аккаунт ожидающий подтверждения

    def _on_confirmation_required(data):
        if not page:
            return
        account_name = data.get("account_name", "")
        _pending_confirmation_account[0] = account_name

        def _on_confirmed_click(e):
            """Пользователь нажал 'Подтвердил' — сигналим боту."""
            from flet_gui.state.events import EventBus, EventType as ET
            EventBus().emit(ET.CONFIRMATION_USER_CONFIRMED, {"account_name": account_name})
            if page.snack_bar:
                page.snack_bar.open = False
                page.update()

        page.snack_bar = ft.SnackBar(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.PHONE_ANDROID, color=COLORS["accent_yellow"], size=20),
                    ft.Text(
                        f"[{account_name}] Подтвердите buy order в Steam Guard на телефоне",
                        color=COLORS["text_primary"],
                        size=FONT_SIZES["sm"],
                        expand=True,
                    ),
                    ft.TextButton(
                        "Подтвердил ✓",
                        on_click=_on_confirmed_click,
                        style=ft.ButtonStyle(
                            color=COLORS["accent_green"],
                        ),
                    ),
                ],
                spacing=8,
            ),
            bgcolor=COLORS["bg_elevated"],
            duration=300000,  # 5 минут — ждём пока не нажмут
        )
        page.snack_bar.open = True
        page.update()

    def _on_confirmation_completed(data):
        _pending_confirmation_account[0] = None
        if page and page.snack_bar:
            page.snack_bar.open = False
            page.update()

    from flet_gui.state.events import EventBus, EventType
    bus = EventBus()
    bus.on(EventType.CONFIRMATION_REQUIRED, _on_confirmation_required)
    bus.on(EventType.CONFIRMATION_COMPLETED, _on_confirmation_completed)

    # Initial update (non-blocking)
    if page:
        update_status()
        page.run_task(initial_load)
        # Запускаем автообновление
        start_auto_refresh()

    return ft.Container(
        content=content,
        expand=True,
    )
