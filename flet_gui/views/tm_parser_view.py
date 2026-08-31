"""
TM Parser view - displays profitable items with full-width responsive table.
"""

import flet as ft
import urllib.parse
import webbrowser
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState
from src.proxy_utils import load_proxy_file
from src.logger import get_logger

logger = get_logger(__name__)


def get_steam_market_url(market_hash_name: str) -> str:
    """Generate Steam Community Market URL for an item."""
    encoded_name = urllib.parse.quote(market_hash_name, safe="")
    return f"https://steamcommunity.com/market/listings/730/{encoded_name}"


def get_csgotm_url(market_hash_name: str) -> str:
    """Generate CSGO.TM Market URL for an item."""
    # Parse weapon type from market_hash_name
    # Format: "Weapon | Skin (Condition)" e.g. "AWP | Chromatic Aberration (Battle-Scarred)"

    # Weapon categories mapping
    weapon_categories = {
        'AWP': 'Sniper Rifle',
        'SSG 08': 'Sniper Rifle',
        'SCAR-20': 'Sniper Rifle',
        'G3SG1': 'Sniper Rifle',
        'AK-47': 'Rifle',
        'M4A4': 'Rifle',
        'M4A1-S': 'Rifle',
        'AUG': 'Rifle',
        'SG 553': 'Rifle',
        'FAMAS': 'Rifle',
        'Galil AR': 'Rifle',
        'Desert Eagle': 'Pistol',
        'USP-S': 'Pistol',
        'Glock-18': 'Pistol',
        'P250': 'Pistol',
        'Five-SeveN': 'Pistol',
        'Tec-9': 'Pistol',
        'CZ75-Auto': 'Pistol',
        'Dual Berettas': 'Pistol',
        'R8 Revolver': 'Pistol',
        'P2000': 'Pistol',
        'MAC-10': 'SMG',
        'MP9': 'SMG',
        'MP7': 'SMG',
        'UMP-45': 'SMG',
        'P90': 'SMG',
        'PP-Bizon': 'SMG',
        'MP5-SD': 'SMG',
        'Nova': 'Shotgun',
        'XM1014': 'Shotgun',
        'MAG-7': 'Shotgun',
        'Sawed-Off': 'Shotgun',
        'M249': 'Machinegun',
        'Negev': 'Machinegun',
        'Knife': 'Knife',
        'Bayonet': 'Knife',
        'Karambit': 'Knife',
        'M9 Bayonet': 'Knife',
        'Butterfly Knife': 'Knife',
        'Flip Knife': 'Knife',
        'Gut Knife': 'Knife',
        'Huntsman Knife': 'Knife',
        'Falchion Knife': 'Knife',
        'Shadow Daggers': 'Knife',
        'Bowie Knife': 'Knife',
        'Ursus Knife': 'Knife',
        'Navaja Knife': 'Knife',
        'Stiletto Knife': 'Knife',
        'Talon Knife': 'Knife',
        'Classic Knife': 'Knife',
        'Paracord Knife': 'Knife',
        'Survival Knife': 'Knife',
        'Nomad Knife': 'Knife',
        'Skeleton Knife': 'Knife',
        'Kukri Knife': 'Knife',
    }

    # Extract weapon name (before |)
    weapon_name = market_hash_name.split('|')[0].strip() if '|' in market_hash_name else market_hash_name

    # Handle StatTrak
    if weapon_name.startswith('StatTrak'):
        weapon_name = weapon_name.replace('StatTrak™ ', '').replace('StatTrak ', '')

    # Handle Souvenir
    if weapon_name.startswith('Souvenir'):
        weapon_name = weapon_name.replace('Souvenir ', '')

    # Get category
    category = weapon_categories.get(weapon_name, 'Rifle')

    # Build URL
    encoded_name = urllib.parse.quote(market_hash_name, safe="")
    encoded_weapon = urllib.parse.quote(weapon_name)
    encoded_category = urllib.parse.quote(category)

    return f"https://market.csgo.com/ru/{encoded_category}/{encoded_weapon}/{encoded_name}"


def create_tm_parser_view(scanner_service=None, db_service=None, page=None, account_service=None) -> ft.Container:
    """TM Parser view with full-width custom table."""
    state = AppState()

    # Track last update time to prevent rate limiting
    import time
    last_update_time = {'value': 0}

    # Filter state
    min_profit_filter = ft.Ref[ft.TextField]()
    filter_enabled = ft.Ref[ft.Checkbox]()
    table_column_ref = ft.Ref[ft.Column]()
    item_count_ref = ft.Ref[ft.Text]()
    auto_scan_switch = ft.Ref[ft.Switch]()

    def get_filtered_items():
        """Get items with filter applied."""
        items = state.profitable_items

        # Apply profit filter if enabled
        if filter_enabled.current and filter_enabled.current.value:
            try:
                min_profit = float(min_profit_filter.current.value or 0)
                items = [item for item in items if (item.get('profit_pct') or 0) >= min_profit]
            except ValueError:
                pass

        return items

    # Button handlers
    def on_create_order(item_data):
        """Create order for specific item."""
        def handler(e):
            state.add_log(f"[WARNING] Order creation not yet implemented for {item_data.get('market_hash_name', 'Unknown')}")
        return handler

    def on_delete_item(item_data):
        """Delete item from database (async to avoid GUI blocking)."""
        async def handler(e):
            if not db_service:
                state.add_log("[ERROR] Database service not available")
                return
            try:
                market_hash_name = item_data.get('market_hash_name', '')
                if market_hash_name:
                    state.add_log(f"[INFO] Deleting item: {market_hash_name}")
                    # Use async method to avoid blocking GUI
                    success = await db_service.delete_profitable_item_async(market_hash_name)
                    if success:
                        refresh_table()
            except Exception as ex:
                state.add_log(f"[ERROR] Failed to delete item: {str(ex)}")
        return handler

    def on_rescan_item(item_data):
        """Rescan specific item - update prices from Steam and CSGO.TM."""
        def handler(e):
            market_hash_name = item_data.get('market_hash_name', '')
            if not market_hash_name:
                return

            # Check cooldown (60 seconds between updates)
            elapsed = time.time() - last_update_time['value']
            if elapsed < 60.0:
                remaining = 60.0 - elapsed
                state.add_log(f"[WARNING] Please wait {remaining:.0f}s before next rescan (rate limit)")
                return

            last_update_time['value'] = time.time()
            state.add_log(f"[INFO] Rescanning item: {market_hash_name}")

            # Run rescan in background
            if page:
                page.run_task(lambda: rescan_item_async(market_hash_name))

        return handler

    async def rescan_item_async(market_hash_name: str):
        """Async rescan of single item using direct aiohttp with proxy."""
        session = None
        try:
            import asyncio
            import re
            from pathlib import Path
            from urllib.parse import quote
            import aiohttp
            from aiohttp_socks import ProxyConnector
            from src.csgotm_client import CsgoTmClient
            from concurrent.futures import ThreadPoolExecutor
            import json

            # Load proxies from proxies.txt
            proxy_list = []
            proxy_file = Path('proxies.txt')
            if proxy_file.exists():
                proxy_list, skipped_proxies = load_proxy_file(proxy_file)
                if skipped_proxies:
                    state.add_log(f"[WARNING] Skipped {skipped_proxies} invalid proxy entries from proxies.txt")

            # Get CSGO.TM API key from accounts.json
            try:
                with open('accounts.json', 'r') as f:
                    accounts_data = json.load(f)
                api_key = accounts_data[0].get('csgotm', {}).get('api_key')
                if not api_key:
                    state.add_log("[ERROR] No CSGOTM API key found in accounts.json")
                    return
            except Exception as ex:
                state.add_log(f"[ERROR] Failed to load API key: {ex}")
                return

            csgotm_client = CsgoTmClient(api_key=api_key)
            loop = asyncio.get_event_loop()

            # Get min profit from config
            min_profit = state.config.get('scanner_min_profit', -5.0)

            state.add_log(f"[INFO] Fetching Steam Market price...")

            proxy = proxy_list[0] if proxy_list else None
            if proxy:
                proxy_display = proxy.split('@')[-1] if '@' in proxy else proxy
                state.add_log(f"[INFO] Using proxy: {proxy_display}")

            from src.bottm.api.steam_market import SteamMarketAPI
            from src.bottm.config import Currency

            steam_api = SteamMarketAPI(currency=Currency.RUB, proxy_url=proxy)
            try:
                buy_order_info = await steam_api.get_buy_orders(market_hash_name, max_retries=1)
            finally:
                await steam_api.close()

            if not buy_order_info.success:
                state.add_log(f"[ERROR] Steam Market error: {buy_order_info.error or 'unknown'}")
                return

            steam_buy_order = buy_order_info.highest_buy_order
            steam_lowest_sell = buy_order_info.lowest_sell_order

            if not steam_buy_order:
                state.add_log(f"[ERROR] No buy orders for {market_hash_name}")
                return

            state.add_log(f"[INFO] Steam buy order: {steam_buy_order:.2f} RUB")

            # Check for fake profit
            if steam_lowest_sell and steam_buy_order >= steam_lowest_sell:
                state.add_log(f"[WARNING] FAKE PROFIT! Buy order ({steam_buy_order:.2f}) >= Lowest sell ({steam_lowest_sell:.2f})")
                state.add_log(f"[INFO] Marking item {market_hash_name} as inactive")
                if db_service:
                    db_service.mark_items_inactive([market_hash_name])
                    db_service.refresh_profitable_items()
                refresh_table()
                return

            # Get CSGO.TM price (sync method, run in executor)
            state.add_log(f"[INFO] Fetching CSGO.TM price...")
            with ThreadPoolExecutor() as executor:
                tm_price_data = await loop.run_in_executor(
                    executor,
                    csgotm_client.get_item_price,
                    market_hash_name
                )

            if not tm_price_data or 'min_price' not in tm_price_data:
                state.add_log(f"[ERROR] Failed to get CSGO.TM price for {market_hash_name}")
                return

            csgo_price = tm_price_data['min_price']
            state.add_log(f"[INFO] CSGO.TM price: {csgo_price:.2f} RUB")

            # Calculate profit with commission from config
            commission_pct = state.config.get('csgo_commission', 10.0)
            commission_multiplier = 1.0 - (commission_pct / 100.0)  # e.g., 10% -> 0.90, 0% -> 1.0
            net_revenue = csgo_price * commission_multiplier
            if steam_buy_order > 0:
                instant_profit_pct = ((net_revenue - steam_buy_order) / steam_buy_order) * 100
            else:
                instant_profit_pct = 0

            # Recommended buy order price
            recommended_buy_order = steam_buy_order + 0.01

            # Check if still profitable
            if instant_profit_pct >= min_profit:
                # Update in DB
                if db_service:
                    db_service.update_profitable_item(
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
                        profit_pct=instant_profit_pct,
                        recommended_profit_pct=instant_profit_pct,
                        orders_above=0
                    )
                state.add_log(f"[SUCCESS] Item updated: {market_hash_name} (profit: {instant_profit_pct:.2f}%)")
            else:
                state.add_log(f"[WARNING] Item no longer profitable: {market_hash_name} (profit: {instant_profit_pct:.2f}% < {min_profit}%)")
                if db_service:
                    db_service.mark_items_inactive([market_hash_name])

            # Refresh display
            if db_service:
                db_service.refresh_profitable_items()
            refresh_table()

        except Exception as ex:
            state.add_log(f"[ERROR] Rescan failed: {str(ex)}")
        finally:
            # Always close the session
            if session and not session.closed:
                await session.close()

    def create_clickable_price(price_value, url, color=COLORS["accent_blue"]):
        """Create a clickable price text that opens URL."""
        def on_click(e):
            state.add_log(f"[INFO] Opening URL: {url}")
            try:
                webbrowser.open(url)
            except Exception as ex:
                state.add_log(f"[ERROR] Failed to open URL: {str(ex)}")

        return ft.TextButton(
            content=ft.Text(f"{price_value:.0f}", size=FONT_SIZES["sm"], color=color, weight=ft.FontWeight.W_500),
            on_click=on_click,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
            ),
            tooltip=url,
        )

    def build_item_row(item):
        """Build a single table row for an item."""
        profit_pct = item.get('profit_pct') or 0
        profit_color = COLORS["profit_positive"] if profit_pct >= 0 else COLORS["profit_negative"]
        market_hash_name = item.get('market_hash_name', '-')

        steam_url = get_steam_market_url(market_hash_name)
        tm_url = get_csgotm_url(market_hash_name)

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(ft.Text(market_hash_name, size=FONT_SIZES["sm"], color=COLORS["text_primary"]), expand=5),
                    ft.Container(
                        create_clickable_price(item.get('steam_buy_order', 0), steam_url, COLORS["accent_blue"]),
                        expand=2,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        create_clickable_price(item.get('csgo_price', 0), tm_url, COLORS["accent_purple"]),
                        expand=2,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        ft.Text(f"{profit_pct:.1f}%", size=FONT_SIZES["sm"], color=profit_color, weight=ft.FontWeight.BOLD),
                        expand=2,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        content=ft.Row([
                            ft.IconButton(
                                icon=ft.Icons.ADD_SHOPPING_CART,
                                icon_size=16,
                                tooltip="Create Order",
                                on_click=on_create_order(item),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                icon_size=16,
                                tooltip="Rescan Item",
                                on_click=on_rescan_item(item),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE,
                                icon_size=16,
                                tooltip="Delete Item",
                                on_click=on_delete_item(item),
                                icon_color=COLORS["accent_red"],
                            ),
                        ], spacing=0),
                        width=120,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                ],
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=8),
            border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )

    def build_table_rows():
        """Build all table rows from filtered items."""
        items = get_filtered_items()
        if not items:
            return [ft.Container(
                content=ft.Column([
                    ft.Text("No profitable items found", size=FONT_SIZES["sm"], color=COLORS["text_secondary"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
            )]
        return [build_item_row(item) for item in items]

    def refresh_table():
        """Refresh table with current filter settings."""
        items = get_filtered_items()

        # Update item count
        if item_count_ref.current:
            item_count_ref.current.value = f"{len(items)} profitable items found"

        # Rebuild and update table rows
        if table_column_ref.current:
            table_column_ref.current.controls = build_table_rows()

        if page:
            page.update()

    def on_filter_apply(e):
        """Handle filter apply button click."""
        state.add_log("[INFO] Applying profit filter...")
        refresh_table()

    def on_auto_scan_change(e):
        """Handle Auto Scanner switch change."""
        if not scanner_service:
            state.add_log("[ERROR] Scanner service not available")
            return

        try:
            is_enabled = e.control.value

            if not is_enabled:
                # Stop auto scanner if running
                if state.scanner_state.running:
                    scanner_service.stop_scanner()
                    state.add_log("[INFO] Auto Scanner stopped")
            else:
                # Start auto scanner if not running
                if not state.scanner_state.running:
                    if scanner_service.start_scanner():
                        scan_interval = state.config.get('scan_interval_minutes', 30)
                        state.add_log(f"[SUCCESS] Auto Scanner started (interval: {scan_interval} min)")

        except Exception as ex:
            logger.error(f"Auto Scanner change error: {ex}", exc_info=True)
            state.add_log(f"[ERROR] Auto Scanner change failed: {str(ex)}")

    async def on_start_scan(e):
        """Handle Start Scan button click - runs ONE scan cycle without enabling auto-scan."""
        if not scanner_service:
            state.add_log("[ERROR] Scanner service not available")
            return

        state.add_log("[INFO] Starting single scan cycle...")
        try:
            # Get max items from config
            max_items = state.config.get('auto_scan_new_items', 10)

            # Run a SINGLE scan cycle (not auto-scanner)
            items = await scanner_service.run_single_scan_async(max_items=max_items)

            # Refresh view with new data from database
            if db_service:
                min_profit = state.config.get('scanner_min_profit', -5.0)
                profitable = db_service.db.get_active_profitable_items(min_profit=min_profit, limit=100)
                state.profitable_items = profitable
                state.add_log(f"[SUCCESS] Loaded {len(profitable)} profitable items from database (min profit: {min_profit}%)")

            refresh_table()
        except Exception as ex:
            state.add_log(f"[ERROR] Scan failed: {str(ex)}")

    async def on_rescan_all(e):
        """Handle Rescan All button click - rescan ALL items and remove unprofitable ones."""
        if not db_service:
            state.add_log("[ERROR] Database service not available")
            return

        state.add_log("[INFO] Rescanning all existing items...")
        try:
            import asyncio
            from pathlib import Path
            from urllib.parse import quote
            import aiohttp
            from aiohttp_socks import ProxyConnector
            from src.csgotm_client import CsgoTmClient
            from concurrent.futures import ThreadPoolExecutor
            import json

            # Get all items from database
            min_profit = state.config.get('scanner_min_profit', -5.0)
            existing_items = db_service.db.get_active_profitable_items(min_profit=min_profit, limit=1000)
            total_items = len(existing_items)
            state.add_log(f"[INFO] Found {total_items} items to rescan (min profit: {min_profit}%)")

            if total_items == 0:
                state.add_log("[WARNING] No items to rescan")
                return

            # Load proxies from proxies.txt
            proxy_list = []
            proxy_file = Path('proxies.txt')
            if proxy_file.exists():
                proxy_list, skipped_proxies = load_proxy_file(proxy_file)
                state.add_log(f"[INFO] Loaded {len(proxy_list)} proxies from proxies.txt")
                if skipped_proxies:
                    state.add_log(f"[WARNING] Skipped {skipped_proxies} invalid proxy entries from proxies.txt")
            else:
                state.add_log("[WARNING] proxies.txt not found, using direct connection")

            # Get CSGO.TM API key from accounts.json
            try:
                with open('accounts.json', 'r') as f:
                    accounts_data = json.load(f)
                api_key = accounts_data[0].get('csgotm', {}).get('api_key')
                if not api_key:
                    state.add_log("[ERROR] No CSGOTM API key found in accounts.json")
                    return
            except Exception as ex:
                state.add_log(f"[ERROR] Failed to load API key: {ex}")
                return

            csgotm_client = CsgoTmClient(api_key=api_key)
            min_profit = state.config.get('scanner_min_profit', -5.0)
            loop = asyncio.get_event_loop()

            updated_count = 0
            removed_count = 0
            error_count = 0
            proxy_idx = 0
            requests_on_proxy = 0
            REQUESTS_PER_PROXY = 8
            TRANSIENT_STEAM_ERROR_TOKENS = (
                'rate_limit',
                'timeout',
                'nameid_not_found',
                'orderbook',
                'ClientConnector',
                'Connection',
                'ContentTypeError',
            )

            async def get_steam_buy_orders(proxy_url: str | None, market_hash_name: str) -> dict:
                """Get buy orders via the shared SteamMarketAPI beta-compatible path."""
                from src.bottm.api.steam_market import SteamMarketAPI
                from src.bottm.config import Currency

                api = SteamMarketAPI(currency=Currency.RUB, proxy_url=proxy_url)
                try:
                    info = await api.get_buy_orders(market_hash_name, max_retries=1)
                    return {
                        'success': info.success,
                        'error': info.error,
                        'highest_buy_order': info.highest_buy_order,
                        'lowest_sell_order': info.lowest_sell_order,
                    }
                finally:
                    await api.close()

            try:
                for i, item in enumerate(existing_items):
                    market_hash_name = item.get('market_hash_name', '')
                    if not market_hash_name:
                        continue

                    try:
                        state.add_log(f"[INFO] [{i+1}/{total_items}] Checking: {market_hash_name[:50]}...")

                        # Retry logic for rate limits
                        MAX_RETRIES = 3
                        retry_count = 0
                        result = None

                        while retry_count < MAX_RETRIES:
                            current_proxy = proxy_list[proxy_idx] if proxy_list else None
                            if current_proxy:
                                proxy_display = current_proxy.split('@')[-1] if '@' in current_proxy else current_proxy
                                state.add_log(f"[INFO] Using proxy [{proxy_idx+1}/{len(proxy_list)}]: {proxy_display}")

                            # Get current Steam buy orders
                            result = await get_steam_buy_orders(current_proxy, market_hash_name)
                            requests_on_proxy += 1

                            if result['success']:
                                break  # Success, exit retry loop

                            error_msg = result.get('error', 'unknown')
                            is_transient = any(token in str(error_msg) for token in TRANSIENT_STEAM_ERROR_TOKENS)

                            # On rate limit or timeout, rotate proxy and retry
                            if is_transient and proxy_list and retry_count < MAX_RETRIES - 1:
                                # Rotate to next proxy
                                old_proxy_idx = proxy_idx
                                proxy_idx = (proxy_idx + 1) % len(proxy_list)
                                requests_on_proxy = 0

                                # Show which proxy we're switching to
                                next_proxy = proxy_list[proxy_idx]
                                next_proxy_display = next_proxy.split('@')[-1] if '@' in next_proxy else next_proxy
                                state.add_log(f"[WARNING] [{i+1}/{total_items}] {error_msg}, rotating proxy [{old_proxy_idx+1}→{proxy_idx+1}]: {next_proxy_display} (retry {retry_count+1}/{MAX_RETRIES})")

                                await asyncio.sleep(2.0)
                                retry_count += 1
                                continue  # Retry with new proxy
                            elif proxy_list and requests_on_proxy >= REQUESTS_PER_PROXY:
                                proxy_idx = (proxy_idx + 1) % len(proxy_list)
                                requests_on_proxy = 0
                            else:
                                # Other error or max retries reached
                                break

                        # Check if all retries failed
                        if not result or not result['success']:
                            error_msg = result.get('error', 'unknown') if result else 'no result'
                            state.add_log(f"[WARNING] [{i+1}/{total_items}] Steam error after {retry_count} retries: {error_msg}")
                            error_count += 1
                            await asyncio.sleep(1.0)
                            continue

                        steam_buy_order = result.get('highest_buy_order')
                        steam_lowest_sell = result.get('lowest_sell_order')

                        if not steam_buy_order:
                            state.add_log(f"[WARNING] [{i+1}/{total_items}] No buy orders")
                            error_count += 1
                            await asyncio.sleep(1.0)
                            continue

                        # Check for fake profit
                        if steam_lowest_sell and steam_buy_order >= steam_lowest_sell:
                            state.add_log(f"[WARNING] [{i+1}/{total_items}] FAKE PROFIT - removing")
                            db_service.mark_items_inactive([market_hash_name])
                            removed_count += 1
                            await asyncio.sleep(1.5)
                            continue

                        # Get CSGO.TM price (sync method, run in executor)
                        with ThreadPoolExecutor() as executor:
                            tm_price_data = await loop.run_in_executor(
                                executor,
                                csgotm_client.get_item_price,
                                market_hash_name
                            )

                        if not tm_price_data or 'min_price' not in tm_price_data:
                            state.add_log(f"[WARNING] [{i+1}/{total_items}] No CSGO.TM data, skipping")
                            error_count += 1
                            await asyncio.sleep(1.0)
                            continue

                        csgo_price = tm_price_data['min_price']

                        # Calculate profit with commission from config
                        commission_pct = state.config.get('csgo_commission', 10.0)
                        commission_multiplier = 1.0 - (commission_pct / 100.0)  # e.g., 10% -> 0.90, 0% -> 1.0
                        net_revenue = csgo_price * commission_multiplier
                        if steam_buy_order > 0:
                            instant_profit_pct = ((net_revenue - steam_buy_order) / steam_buy_order) * 100
                        else:
                            instant_profit_pct = 0

                        # Check if still profitable
                        if instant_profit_pct >= min_profit:
                            # Update in DB
                            recommended_buy_order = steam_buy_order + 0.01
                            db_service.update_profitable_item(
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
                                profit_pct=instant_profit_pct,
                                recommended_profit_pct=instant_profit_pct,
                                orders_above=0
                            )
                            state.add_log(f"[SUCCESS] [{i+1}/{total_items}] {market_hash_name[:40]}: {instant_profit_pct:.1f}%")
                            updated_count += 1
                        else:
                            state.add_log(f"[WARNING] [{i+1}/{total_items}] Not profitable ({instant_profit_pct:.1f}% < {min_profit}%) - removing")
                            db_service.mark_items_inactive([market_hash_name])
                            removed_count += 1

                        # Delay to avoid rate limiting (Steam API)
                        await asyncio.sleep(2.0)

                    except Exception as ex:
                        state.add_log(f"[ERROR] [{i+1}/{total_items}] Failed: {str(ex)[:50]}")
                        error_count += 1
                        await asyncio.sleep(1.0)

            finally:
                pass

            # Final refresh
            db_service.refresh_profitable_items()
            refresh_table()

            state.add_log(f"[SUCCESS] Rescan complete: {updated_count} updated, {removed_count} removed, {error_count} errors")

        except Exception as ex:
            import traceback
            state.add_log(f"[ERROR] Rescan failed: {str(ex)}")
            logger.error(f"Rescan error: {traceback.format_exc()}")

    async def on_scan_new(e):
        """Handle Scan New Items button click."""
        if not scanner_service:
            state.add_log("[ERROR] Scanner service not available")
            return

        state.add_log("[INFO] Scanning for new items...")
        try:
            # Get max items from config
            max_items = state.config.get('auto_scan_new_items', 10)

            # Run async scan (we're already in async context from Flet)
            items = await scanner_service.run_single_scan_async(max_items=max_items)

            # Load profitable items from database
            if db_service:
                min_profit = state.config.get('scanner_min_profit', -5.0)
                profitable = db_service.db.get_active_profitable_items(min_profit=min_profit, limit=100)
                state.profitable_items = profitable
                state.add_log(f"[SUCCESS] Loaded {len(profitable)} profitable items from database (min profit: {min_profit}%)")

            refresh_table()
        except Exception as ex:
            logger.error(f"Scan new items error: {ex}", exc_info=True)
            state.add_log(f"[ERROR] Scan new items failed: {str(ex)}")

    # Table header
    header = ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(ft.Text("Item", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]), expand=5),
                ft.Container(
                    ft.Text("Steam Buy", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    expand=2,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Container(
                    ft.Text("TM Sell", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    expand=2,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Container(
                    ft.Text("Profit %", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    expand=2,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                ft.Container(
                    ft.Text("Actions", size=FONT_SIZES["sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    width=120,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
            ],
            spacing=0,
        ),
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        bgcolor=COLORS["bg_elevated"],
        border=ft.border.only(bottom=ft.BorderSide(2, COLORS["border"])),
    )

    # Table with sticky header
    table_container = ft.Container(
        content=ft.Column([
            # Sticky header (outside scroll)
            header,
            # Scrollable rows only
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

    container = ft.Container(
        content=ft.Column(
            controls=[
                # Header row
                ft.Row(
                    controls=[
                        ft.Text("TM Parser", size=FONT_SIZES["2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                        ft.Row([
                            ft.FilledButton(
                                "Start Scan",
                                icon=ft.Icons.PLAY_ARROW,
                                on_click=on_start_scan,
                                disabled=not scanner_service,
                            ),
                            ft.FilledButton(
                                "Rescan All",
                                icon=ft.Icons.REFRESH,
                                on_click=on_rescan_all,
                                disabled=not db_service,
                            ),
                            ft.FilledButton(
                                "Scan New",
                                icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                on_click=on_scan_new,
                                disabled=not scanner_service,
                            ),
                            ft.Switch(
                                ref=auto_scan_switch,
                                label="Auto Scan",
                                value=False,
                                active_color=COLORS["accent_purple"],
                                on_change=on_auto_scan_change,
                                disabled=not scanner_service,
                            ),
                        ], spacing=8),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # Filter row
                ft.Row([
                    ft.Checkbox(
                        ref=filter_enabled,
                        label="Enable profit filter",
                        value=False,
                        on_change=on_filter_apply,
                    ),
                    ft.TextField(
                        ref=min_profit_filter,
                        label="Min Profit %",
                        value="0",
                        width=120,
                        height=40,
                        text_size=FONT_SIZES["sm"],
                        content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    ),
                    ft.FilledButton(
                        "Apply Filter",
                        icon=ft.Icons.FILTER_ALT,
                        on_click=on_filter_apply,
                        height=40,
                    ),
                    ft.Text(
                        ref=item_count_ref,
                        value=f"{len(get_filtered_items())} profitable items found",
                        size=FONT_SIZES["sm"],
                        color=COLORS["text_secondary"],
                    ),
                ], spacing=12, alignment=ft.MainAxisAlignment.START),
                # Table (fills remaining space)
                table_container,
            ],
            spacing=12,
            expand=True,
        ),
        padding=20,
        expand=True,
    )

    def update_auto_scan_switch():
        """Update auto scan switch based on scanner state."""
        try:
            if auto_scan_switch.current:
                is_running = state.scanner_state.running
                # Only update if value actually changed to avoid spam
                if auto_scan_switch.current.value != is_running:
                    auto_scan_switch.current.value = is_running
                    logger.debug(f"Auto scan switch updated: {is_running}")
                    if page:
                        page.update()
        except Exception as e:
            logger.error(f"Failed to update auto scan switch: {e}", exc_info=True)

    # Subscribe to state changes
    state.subscribe('profitable_items', refresh_table)
    state.subscribe('scanner_state', update_auto_scan_switch)

    return container


TMParserView = create_tm_parser_view
