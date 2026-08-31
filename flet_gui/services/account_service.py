"""
Account service - integrates AccountManager with GUI state.
"""

from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.account_manager import AccountManager, Account
from flet_gui.state.app_state import AppState, AccountState
from src.logger import get_logger

logger = get_logger(__name__)


class AccountService:
    """Service for managing accounts in GUI."""

    def __init__(self, state: AppState, config_file: str = "accounts.json"):
        """Initialize account service."""
        self.state = state
        try:
            self.account_manager = AccountManager(config_file=config_file)
            logger.info(f"AccountService initialized with {len(self.account_manager)} accounts")
            self.load_accounts()
        except Exception as e:
            logger.error(f"Failed to initialize AccountManager: {e}")
            self.account_manager = None
            self.state.add_log(f"[ERROR] Failed to load accounts: {str(e)}")

    def load_accounts(self):
        """Load accounts from AccountManager into state."""
        if not self.account_manager:
            return

        try:
            accounts = []
            for acc in self.account_manager.get_all_accounts():
                account_info = AccountState(
                    name=acc.config.name,
                    enabled=acc.config.enabled,
                    logged_in=acc.is_logged_in(),
                    currency=acc.config.currency or "RUB",
                    steam_balance=0.0,  # Will be updated on login
                    csgotm_balance=0.0,
                    csgotm_settlement=0.0,  # Will be updated on login
                )
                accounts.append(account_info)

            self.state.accounts = accounts
            logger.info(f"Loaded {len(accounts)} accounts into state")
            self.state.add_log(f"[INFO] Loaded {len(accounts)} accounts")

        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            self.state.add_log(f"[ERROR] Failed to load accounts: {str(e)}")

    def login_account(self, account_name: str) -> bool:
        """Login a specific account (sync version)."""
        if not self.account_manager:
            return False

        try:
            account = self.account_manager.get_account(account_name)
            if not account:
                self.state.add_log(f"[ERROR] Account {account_name} not found")
                return False

            self.state.add_log(f"[INFO] Logging in {account_name}...")
            success = account.login_sync()

            if success:
                # Update balance
                balance = account.get_wallet_balance_sync()

                # Update CSGO.TM balance and settlement
                csgotm_money = account.get_csgotm_money()

                # Update state
                for acc_info in self.state.accounts:
                    if acc_info.name == account_name:
                        acc_info.logged_in = True
                        acc_info.steam_balance = balance
                        acc_info.csgotm_balance = csgotm_money.get("money", 0.0)
                        acc_info.csgotm_settlement = csgotm_money.get("money_settlement", 0.0)
                        break

                self.state.add_log(f"[SUCCESS] {account_name} logged in successfully")
                return True
            else:
                self.state.add_log(f"[ERROR] Failed to login {account_name}")
                return False

        except Exception as e:
            logger.error(f"Failed to login account: {e}")
            self.state.add_log(f"[ERROR] Login failed: {str(e)}")
            return False

    async def login_account_async(self, account_name: str) -> bool:
        """Login a specific account (async version - use inside event loop)."""
        if not self.account_manager:
            return False

        try:
            account = self.account_manager.get_account(account_name)
            if not account:
                self.state.add_log(f"[ERROR] Account {account_name} not found")
                return False

            # IMPORTANT: Reinitialize steam client in current event loop
            # This prevents "attached to a different loop" errors with aiohttp
            account.reinitialize_steam_client()

            self.state.add_log(f"[INFO] Logging in {account_name}...")
            success = await account.login_async()

            if success:
                # Update balance (async via steam_client)
                balance = 0.0
                try:
                    wallet_info = await account.steam_client.get_wallet_balance()
                    if wallet_info:
                        balance = wallet_info.balance
                        # IMPORTANT: Cache balance for sync methods (TradingBot uses sync)
                        account._last_wallet_balance = balance
                        self.state.add_log(f"[INFO] {account_name} balance: {balance:.2f}")
                except Exception as e:
                    self.state.add_log(f"[WARNING] Failed to get balance: {e}")

                # Update CSGO.TM balance and settlement (non-blocking via thread pool)
                import asyncio
                csgotm_money = await asyncio.to_thread(account.get_csgotm_money)

                # Update state
                for acc_info in self.state.accounts:
                    if acc_info.name == account_name:
                        acc_info.logged_in = True
                        acc_info.steam_balance = balance
                        acc_info.csgotm_balance = csgotm_money.get("money", 0.0)
                        acc_info.csgotm_settlement = csgotm_money.get("money_settlement", 0.0)
                        break

                # Notify observers about account changes
                self.state._notify('accounts')

                # Update stats with total balance
                total_steam_balance = sum(acc.steam_balance for acc in self.state.accounts)
                self.state.update_stat('balance_steam', total_steam_balance)

                self.state.add_log(f"[SUCCESS] {account_name} logged in successfully")
                return True
            else:
                self.state.add_log(f"[ERROR] Failed to login {account_name}")
                return False

        except Exception as e:
            logger.error(f"Failed to login account: {e}")
            self.state.add_log(f"[ERROR] Login failed: {str(e)}")
            return False

    def login_all_accounts(self) -> dict[str, bool]:
        """Login all enabled accounts in parallel."""
        if not self.account_manager:
            return {}

        try:
            from src.async_helper import run_async_in_gui
            import asyncio

            async def _login_all_with_balance_update():
                """Login all accounts and update balances in parallel."""
                enabled = self.account_manager.get_enabled_accounts()

                # Parallel login
                results = {}
                async def login_one(account):
                    # Reinitialize steam client in current event loop
                    account.reinitialize_steam_client()
                    success = await account.login_async()
                    return account.name, success

                login_results = await asyncio.gather(*[login_one(acc) for acc in enabled], return_exceptions=True)

                for result in login_results:
                    if isinstance(result, tuple):
                        account_name, success = result
                        results[account_name] = success
                    else:
                        # Exception occurred
                        logger.error(f"Login error: {result}")

                # Update balances in parallel for successful logins
                async def update_balance(account):
                    if not results.get(account.name, False):
                        return

                    try:
                        # Get Steam balance (async)
                        balance = 0.0
                        wallet_info = await account.steam_client.get_wallet_balance()
                        if wallet_info:
                            balance = wallet_info.balance

                        # Get CSGO.TM balance (blocking, so run in thread pool)
                        csgotm_money = await asyncio.to_thread(account.get_csgotm_money)

                        # Update state
                        for acc_info in self.state.accounts:
                            if acc_info.name == account.name:
                                acc_info.logged_in = True
                                acc_info.steam_balance = balance
                                acc_info.csgotm_balance = csgotm_money.get("money", 0.0)
                                acc_info.csgotm_settlement = csgotm_money.get("money_settlement", 0.0)
                                break
                    except Exception as e:
                        logger.error(f"[{account.name}] Failed to update balance: {e}")

                await asyncio.gather(*[update_balance(acc) for acc in enabled], return_exceptions=True)

                return results

            self.state.add_log(f"[INFO] Logging in all enabled accounts in parallel...")
            results = run_async_in_gui(_login_all_with_balance_update())

            # Update state
            for account_name, success in results.items():
                for acc_info in self.state.accounts:
                    if acc_info.name == account_name:
                        acc_info.logged_in = success
                        break

            success_count = sum(1 for v in results.values() if v)
            failed_count = len(results) - success_count

            if failed_count > 0:
                failed_names = [name for name, success in results.items() if not success]
                self.state.add_log(f"[WARNING] Failed to login {failed_count} accounts: {', '.join(failed_names)}")

            self.state.add_log(f"[SUCCESS] Logged in {success_count}/{len(results)} accounts")

            return results

        except Exception as e:
            logger.error(f"Failed to login all accounts: {e}")
            self.state.add_log(f"[ERROR] Failed to login accounts: {str(e)}")
            return {}

    def logout_account(self, account_name: str):
        """Logout a specific account."""
        if not self.account_manager:
            return

        try:
            account = self.account_manager.get_account(account_name)
            if account:
                account.logout()
                # Update state
                for acc_info in self.state.accounts:
                    if acc_info.name == account_name:
                        acc_info.logged_in = False
                        break
                self.state.add_log(f"[INFO] {account_name} logged out")

        except Exception as e:
            logger.error(f"Failed to logout account: {e}")
            self.state.add_log(f"[ERROR] Logout failed: {str(e)}")

    def logout_all_accounts(self):
        """Logout all accounts."""
        if not self.account_manager:
            return

        try:
            self.account_manager.logout_all()
            # Update state
            for acc_info in self.state.accounts:
                acc_info.logged_in = False

            self.state.add_log("[INFO] All accounts logged out")

        except Exception as e:
            logger.error(f"Failed to logout all accounts: {e}")
            self.state.add_log(f"[ERROR] Failed to logout accounts: {str(e)}")

    def get_total_balance(self) -> dict:
        """Get total balance across all accounts."""
        if not self.account_manager:
            return {'steam': 0, 'csgotm': 0}

        try:
            return self.account_manager.get_total_balance_sync()
        except Exception as e:
            logger.error(f"Failed to get total balance: {e}")
            return {'steam': 0, 'csgotm': 0}

    def detect_currency(self, account_name: str) -> Optional[str]:
        """Detect currency for an account."""
        if not self.account_manager:
            return None

        try:
            account = self.account_manager.get_account(account_name)
            if account:
                currency = account.detect_currency_sync()
                # Update state
                for acc_info in self.state.accounts:
                    if acc_info.name == account_name:
                        acc_info.currency = currency or "RUB"
                        break
                self.state.add_log(f"[INFO] Detected currency for {account_name}: {currency}")
                return currency

        except Exception as e:
            logger.error(f"Failed to detect currency: {e}")
            self.state.add_log(f"[ERROR] Currency detection failed: {str(e)}")
            return None

    async def sync_orders_from_steam(self, db_service) -> dict:
        """
        Sync orders and inventory from Steam without running trading cycle.

        Фильтрует только предметы дороже 800 RUB (≈8 EUR) для экономии ресурсов.

        Returns dict with: synced, filled, cancelled, errors
        """
        # ВАЖНО: Минимальная цена предмета для отслеживания (800 RUB ≈ 8 EUR)
        MIN_ITEM_PRICE_RUB = 800.0

        # ВАЖНО: Список предметов, которые нужно игнорировать (не отслеживать)
        IGNORED_ITEMS = [
            'Shroud of the North Star',  # ШИРП - дешевый предмет для личного использования
            'StatTrak™ Glock-18 | Winterized (Field-Tested)',
            'StatTrak™ MAC-10 | Monkeyflage (Field-Tested)',
            # Добавьте сюда другие предметы, которые не нужно отслеживать
        ]

        results = {'synced': 0, 'filled': 0, 'cancelled': 0, 'errors': []}

        if not self.account_manager:
            results['errors'].append("Account manager not available")
            return results

        for account in self.account_manager.get_enabled_accounts():
            try:
                # Reinitialize steam client in current event loop if needed
                # and login if not logged in
                if not account.is_logged_in():
                    self.state.add_log(f"[INFO] [{account.name}] Logging in for sync...")
                    account.reinitialize_steam_client()
                    success = await account.login_async()
                    if not success:
                        results['errors'].append(f"{account.name}: login failed")
                        continue
                    # Update state
                    for acc_info in self.state.accounts:
                        if acc_info.name == account.name:
                            acc_info.logged_in = True
                            break
                    self.state._notify('accounts')

                self.state.add_log(f"[INFO] [{account.name}] Syncing orders from Steam...")

                # Check existing orders in DB for this account
                existing_db_orders = [o for o in db_service.db.get_active_orders() if o['account_name'] == account.name]

                # Get active orders from Steam
                steam_orders = await account.steam_client.get_active_buy_orders()
                steam_order_ids = {str(order['order_id']) for order in steam_orders}

                self.state.add_log(f"[INFO] [{account.name}] Found {len(steam_orders)} active orders in Steam, {len(existing_db_orders)} already in DB")

                # Sync new orders to DB (только дорогие предметы ≥800 RUB)
                filtered_count = 0
                synced_count = 0
                skipped_existing = 0

                for order in steam_orders:
                    market_hash_name = order['market_hash_name']

                    # ВАЖНО: Игнорируем предметы из списка игнорируемых
                    if market_hash_name in IGNORED_ITEMS:
                        filtered_count += 1
                        continue  # Пропускаем игнорируемые предметы

                    # Convert order price to RUB
                    order_price_rub = order['price']
                    account_currency = account.config.currency or 'RUB'
                    if account_currency != 'RUB':
                        from src.currency_rates import get_currency_provider
                        provider = get_currency_provider()
                        order_price_rub = provider.convert_to_rub(order['price'], account_currency)

                    # ВАЖНО: Синхронизируем только дорогие ордера (≥800 RUB)
                    if order_price_rub < MIN_ITEM_PRICE_RUB:
                        filtered_count += 1
                        continue  # Пропускаем дешевые ордера

                    existing = db_service.get_order_by_id(order['order_id'])
                    if not existing:
                        # New order - add to DB (сохраняем в оригинальной валюте)
                        db_service.add_order(
                            account_name=account.name,
                            item_name=order['market_hash_name'],
                            market_hash_name=order['market_hash_name'],
                            order_id=order['order_id'],
                            order_price=order['price'],  # Оригинальная цена
                            quantity=order['quantity'],
                            expected_sell_price=None,
                        )
                        synced_count += 1
                        results['synced'] += 1
                        self.state.add_log(f"[SUCCESS] [{account.name}] New order: {order['market_hash_name']} ({order_price_rub:.2f} RUB)")
                    elif existing.get('status') != 'active':
                        # Order exists but was cancelled/filled - reactivate it
                        db_service.update_order_status(order['order_id'], 'active')
                        synced_count += 1
                        results['synced'] += 1
                    else:
                        # Already exists and active
                        skipped_existing += 1

                # Summary log
                if synced_count > 0:
                    self.state.add_log(f"[INFO] [{account.name}] Synced {synced_count} orders")
                if filtered_count > 0:
                    self.state.add_log(f"[INFO] [{account.name}] Filtered {filtered_count} cheap orders (< {MIN_ITEM_PRICE_RUB} RUB)")

                # ALWAYS load inventory to check for filled orders
                self.state.add_log(f"[INFO] [{account.name}] Loading Steam inventory...")
                inventory_counts = {}
                inventory_items = {}  # {market_hash_name: [item_objects]}
                inventory = await account.steam_client.get_inventory()
                if inventory:
                    for item in inventory:
                        name = item.market_hash_name
                        inventory_counts[name] = inventory_counts.get(name, 0) + 1
                        if name not in inventory_items:
                            inventory_items[name] = []
                        inventory_items[name].append(item)
                    self.state.add_log(f"[INFO] [{account.name}] Found {len(inventory)} items in Steam inventory")
                    self.state.add_log(f"[INFO] [{account.name}] Unique item types: {len(inventory_counts)}")

                    # Update unlock_date from real Steam trade hold data
                    updated_count = 0
                    items_with_hold = 0
                    items_ready = 0
                    for item in inventory:
                        if not item.assetid or not item.market_hash_name:
                            continue

                        # ВАЖНО: Игнорируем предметы из списка игнорируемых
                        if item.market_hash_name in IGNORED_ITEMS:
                            continue

                        # Count items with tradable_after (items on hold)
                        if item.tradable_after:
                            items_with_hold += 1
                            # Update unlock_date in DB based on real tradable_after from Steam
                            db_service.db.update_unlock_date_from_steam(
                                account_name=account.name,
                                market_hash_name=item.market_hash_name,
                                asset_id=item.assetid,
                                unlock_date=item.tradable_after
                            )
                            updated_count += 1
                        else:
                            # Item has no trade hold - it's ready for sale
                            # Set unlock_date to past (GMT) so it appears in "ready for sale"
                            items_ready += 1
                            unlock_date_past = datetime.utcnow() - timedelta(days=1)
                            db_service.db.update_unlock_date_from_steam(
                                account_name=account.name,
                                market_hash_name=item.market_hash_name,
                                asset_id=item.assetid,
                                unlock_date=unlock_date_past
                            )
                            updated_count += 1

                    self.state.add_log(f"[INFO] [{account.name}] Found {items_with_hold} items with trade hold, {items_ready} ready for sale")
                    if updated_count > 0:
                        self.state.add_log(f"[INFO] [{account.name}] Updated unlock dates for {updated_count} items from Steam")
                    else:
                        self.state.add_log(f"[DEBUG] [{account.name}] No items updated (no items in inventory)")

                # Account for EXISTING purchased_items for this account
                existing_purchased = db_service.get_purchased_items(account_name=account.name)
                matched_counts = {}
                for item in existing_purchased:
                    name = item.get('market_hash_name', '')
                    if name:
                        matched_counts[name] = matched_counts.get(name, 0) + 1

                self.state.add_log(f"[INFO] [{account.name}] Already tracked in DB: {len(existing_purchased)} purchased items")

                # Get profitable items for expected_sell_price lookup
                min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
                profitable_items = db_service.db.get_active_profitable_items(min_profit=min_profit, limit=1000)
                profitable_dict = {item['market_hash_name']: item for item in profitable_items}

                # Get ALL orders (active + filled + cancelled) for this account
                all_db_orders = db_service.db.get_all_orders_for_account(account.name) if hasattr(db_service.db, 'get_all_orders_for_account') else []
                if not all_db_orders:
                    # Fallback: get all orders from active_orders table
                    with db_service.db._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT * FROM active_orders WHERE account_name = ?", (account.name,))
                        all_db_orders = [dict(row) for row in cursor.fetchall()]

                active_orders = [o for o in all_db_orders if o.get('status') == 'active']

                self.state.add_log(f"[INFO] [{account.name}] Checking {len(all_db_orders)} total orders (active + filled + cancelled)")

                # Count how many items match ANY orders (not just active)
                items_from_orders = 0
                for order in all_db_orders:
                    order_name = order.get('market_hash_name', '')
                    if order_name and inventory_counts.get(order_name, 0) > 0:
                        items_from_orders += min(inventory_counts[order_name], order.get('quantity', 1))

                self.state.add_log(f"[INFO] [{account.name}] Items matching ANY orders: {items_from_orders}")

                # Check ALL orders (not just active) against inventory
                for order in all_db_orders:
                    order_id = str(order['order_id'])
                    market_hash_name = order.get('market_hash_name', '')

                    # ВАЖНО: Игнорируем предметы из списка игнорируемых
                    if market_hash_name in IGNORED_ITEMS:
                        continue  # Пропускаем игнорируемые предметы

                    # Convert order price to RUB for filtering
                    # ВАЖНО: Цены в БД могут быть как в EUR (старые < 100), так и в RUB (новые >= 100)
                    order_price_rub = order['order_price']
                    account_currency = account.config.currency or 'RUB'

                    # Эвристика: если цена < 100, то это EUR и нужна конвертация
                    if account_currency != 'RUB' and order_price_rub < 100:
                        from src.currency_rates import get_currency_provider
                        provider = get_currency_provider()
                        order_price_rub = provider.convert_to_rub(order['order_price'], account_currency)
                    # Иначе цена уже в RUB

                    # ВАЖНО: Проверяем только дорогие предметы (≥800 RUB)
                    if order_price_rub < MIN_ITEM_PRICE_RUB:
                        continue  # Пропускаем дешевые предметы

                    available_count = inventory_counts.get(market_hash_name, 0)
                    matched_count = matched_counts.get(market_hash_name, 0)
                    current_status = order.get('status', 'active')

                    # If item is in inventory and not yet matched, mark as filled and add to purchased_items
                    if market_hash_name and available_count > matched_count:
                        # Update status to filled (if not already)
                        if current_status != 'filled':
                            db_service.update_order_status(order_id, 'filled')
                            self.state.add_log(f"[SUCCESS] [{account.name}] Order filled - item in inventory: {order['item_name']} ({order_price_rub:.2f} RUB)")

                        # Get expected_sell_price from profitable_items
                        expected_sell_price = None
                        profitable_item = profitable_dict.get(market_hash_name)
                        if profitable_item:
                            # Use csgo_price (цена продажи на CSGOTM) as expected sell price
                            expected_sell_price = profitable_item.get('csgo_price')

                        # Add to purchased_items (only if not already tracked)
                        db_service.add_purchased_item(
                            account_name=account.name,
                            item_name=order['item_name'],
                            market_hash_name=market_hash_name,
                            purchase_price=order_price_rub,  # Уже в RUB
                            expected_sell_price=expected_sell_price,
                            order_id=order_id,
                        )
                        results['filled'] += 1
                        matched_counts[market_hash_name] = matched_count + 1
                    elif current_status == 'active' and str(order_id) not in steam_order_ids:
                        # Order is marked as active but not in Steam and not in inventory = cancelled
                        db_service.update_order_status(order_id, 'cancelled')
                        results['cancelled'] += 1
                        self.state.add_log(f"[WARNING] [{account.name}] Cancelled: {order['item_name']}")

                # Final summary
                total_tracked = len(existing_purchased) + results['filled']
                self.state.add_log(f"[INFO] [{account.name}] Summary: {total_tracked} items tracked in DB, {results['filled']} newly filled, {results['cancelled']} cancelled")

            except Exception as e:
                results['errors'].append(f"{account.name}: {str(e)}")
                self.state.add_log(f"[ERROR] [{account.name}] Sync error: {e}")

        return results

    async def import_items_from_inventory(self, db_service, account_name: str = None, min_price_rub: float = 800.0) -> dict:
        """
        Import items from Steam inventory that are not tracked in DB yet.

        Args:
            db_service: Database service
            account_name: Specific account to import (None = all logged in accounts)
            min_price_rub: Minimum price to import (default 800 RUB)

        Returns:
            dict with: imported, skipped, errors
        """
        results = {'imported': 0, 'skipped': 0, 'errors': []}

        accounts_to_process = []
        if account_name:
            account = self.account_manager.get_account(account_name)
            if account:
                accounts_to_process = [account]
        else:
            accounts_to_process = [acc for acc in self.account_manager.accounts if acc.is_logged_in() and acc.steam_client]

        for account in accounts_to_process:
            try:
                self.state.add_log(f"[INFO] [{account.name}] Importing items from Steam inventory...")

                # Load inventory
                inventory = await account.steam_client.get_inventory()
                if not inventory:
                    self.state.add_log(f"[WARNING] [{account.name}] Empty inventory")
                    continue

                # Get existing tracked items (by asset_id)
                existing_items = db_service.db.get_purchased_items(account_name=account.name)
                existing_asset_ids = {item.get('asset_id') for item in existing_items if item.get('asset_id')}
                existing_names = {item.get('market_hash_name') for item in existing_items}

                self.state.add_log(f"[INFO] [{account.name}] Found {len(inventory)} items in inventory, {len(existing_asset_ids)} already tracked")

                # Get profitable_items once (outside the loop)
                min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
                profitable_items = db_service.db.get_active_profitable_items(min_profit=min_profit, limit=1000)
                profitable_dict = {pi['market_hash_name']: pi for pi in profitable_items}
                self.state.add_log(f"[DEBUG] [{account.name}] Loaded {len(profitable_dict)} profitable items for price lookup (min profit: {min_profit}%)")

                # ВАЖНО: Список игнорируемых предметов (используем тот же список)
                IGNORED_ITEMS = [
                    'Shroud of the North Star',
                    'StatTrak™ Glock-18 | Winterized (Field-Tested)',
                    'StatTrak™ MAC-10 | Monkeyflage (Field-Tested)',
                ]

                # Track skip reasons
                skip_reasons = {
                    'ignored': 0,
                    'already_tracked': 0,
                    'no_market_name': 0,
                    'not_profitable': 0,
                    'too_cheap': 0
                }

                # Import items not in DB
                for item in inventory:
                    # Skip if already tracked by asset_id
                    if item.assetid in existing_asset_ids:
                        skip_reasons['already_tracked'] += 1
                        continue

                    # Skip if item name missing
                    if not item.market_hash_name:
                        skip_reasons['no_market_name'] += 1
                        continue

                    # ВАЖНО: Игнорируем предметы из списка игнорируемых
                    if item.market_hash_name in IGNORED_ITEMS:
                        skip_reasons['ignored'] += 1
                        continue

                    profitable_item = profitable_dict.get(item.market_hash_name)

                    # ONLY import items from profitable_items table
                    if not profitable_item:
                        skip_reasons['not_profitable'] += 1
                        continue

                    # Get prices from profitable_items
                    purchase_price = profitable_item.get('steam_buy_order') or profitable_item.get('steam_lowest_sell') or min_price_rub
                    expected_sell_price = profitable_item.get('csgo_price', 0)

                    # Skip if price is too cheap
                    if purchase_price > 0 and purchase_price < min_price_rub:
                        skip_reasons['too_cheap'] += 1
                        continue

                    # Add to DB
                    item_id = db_service.db.add_purchased_item(
                        account_name=account.name,
                        item_name=item.name or item.market_hash_name,
                        market_hash_name=item.market_hash_name,
                        purchase_price=purchase_price,
                        asset_id=item.assetid,
                        expected_sell_price=expected_sell_price,
                        order_id=None  # No order_id for manually imported items
                    )

                    if item_id:
                        # Update unlock_date from real Steam data (GMT time)
                        # If no tradable_after, item is already tradable - set unlock_date to past (GMT)
                        unlock_date = item.tradable_after if item.tradable_after else (datetime.utcnow() - timedelta(days=1))
                        db_service.db.update_unlock_date_from_steam(
                            account_name=account.name,
                            market_hash_name=item.market_hash_name,
                            asset_id=item.assetid,
                            unlock_date=unlock_date
                        )
                        results['imported'] += 1

                        if item.tradable_after:
                            hours_left = int((item.tradable_after - datetime.utcnow()).total_seconds() / 3600)
                            self.state.add_log(f"[SUCCESS] [{account.name}] Imported: {item.market_hash_name[:40]} ({hours_left}h left GMT)")
                        else:
                            self.state.add_log(f"[SUCCESS] [{account.name}] Imported (ready for sale): {item.market_hash_name[:40]}")

                # Update total skipped count
                results['skipped'] = sum(skip_reasons.values())

                # Log detailed skip reasons
                self.state.add_log(f"[INFO] [{account.name}] Import complete: {results['imported']} imported, {results['skipped']} skipped")
                self.state.add_log(f"[DEBUG] [{account.name}] Skip reasons:")
                self.state.add_log(f"[DEBUG]   - Ignored items: {skip_reasons['ignored']}")
                self.state.add_log(f"[DEBUG]   - Already tracked: {skip_reasons['already_tracked']}")
                self.state.add_log(f"[DEBUG]   - No market name: {skip_reasons['no_market_name']}")
                self.state.add_log(f"[DEBUG]   - Not in profitable_items DB: {skip_reasons['not_profitable']}")
                self.state.add_log(f"[DEBUG]   - Too cheap (< {min_price_rub} RUB): {skip_reasons['too_cheap']}")

            except Exception as e:
                results['errors'].append(f"{account.name}: {str(e)}")
                self.state.add_log(f"[ERROR] [{account.name}] Import error: {e}")

        return results

    async def check_and_cancel_unprofitable_orders(self, db_service, min_profit_percent: float = 5.0, check_realtime: bool = False, excluded_items: set = None) -> dict:
        """
        Check active orders against current profitable items and cancel unprofitable ones.

        Args:
            db_service: Database service
            min_profit_percent: Minimum profit percentage to keep order (default 5%)
            check_realtime: If True, check profit in real-time for items not in profitable_items table
            excluded_items: Set of item names to skip (e.g. auto_buy items)

        Returns:
            dict with: checked, cancelled, errors
        """
        results = {'checked': 0, 'cancelled': 0, 'skipped': 0, 'errors': []}
        excluded_items = excluded_items or set()

        if not self.account_manager:
            results['errors'].append("Account manager not available")
            return results

        # Get profitable items from DB
        min_profit = self.state.config.get('scanner_min_profit', -5.0) if hasattr(self.state, 'config') else -5.0
        profitable_items = db_service.db.get_active_profitable_items(min_profit=min_profit, limit=1000)
        profitable_dict = {item['market_hash_name']: item for item in profitable_items}

        self.state.add_log(f"[INFO] Checking orders against {len(profitable_items)} profitable items (min profit: {min_profit}%)...")

        for account in self.account_manager.get_enabled_accounts():
            try:
                # Счетчики для текущего аккаунта
                account_checked = 0
                account_cancelled = 0

                # Ensure logged in
                if not account.is_logged_in():
                    self.state.add_log(f"[INFO] [{account.name}] Logging in to check orders...")
                    account.reinitialize_steam_client()
                    success = await account.login_async()
                    if not success:
                        results['errors'].append(f"{account.name}: login failed")
                        continue

                # Get active orders from DB
                with db_service.db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT order_id, market_hash_name, order_price, item_name
                        FROM active_orders
                        WHERE account_name = ? AND status = 'active'
                    """, (account.name,))
                    active_orders = [dict(row) for row in cursor.fetchall()]

                self.state.add_log(f"[INFO] [{account.name}] Checking {len(active_orders)} active orders...")

                for order in active_orders:
                    market_hash_name = order['market_hash_name']
                    order_id = str(order['order_id'])

                    # Skip auto_buy items - they are not for profit
                    if market_hash_name in excluded_items:
                        results['skipped'] += 1
                        continue

                    results['checked'] += 1
                    account_checked += 1

                    # Check if item is in profitable items
                    profitable_item = profitable_dict.get(market_hash_name)

                    if not profitable_item:
                        # Item not in profitable items table
                        if check_realtime:
                            # Check profit in real-time using Steam + CSGO.TM APIs
                            self.state.add_log(f"[INFO] [{account.name}] Item not in table, checking real-time: {market_hash_name}")
                            try:
                                from src.csgotm_client import CsgoTmClient
                                import json

                                # Get CSGO.TM API key
                                with open('accounts.json', 'r') as f:
                                    accounts_data = json.load(f)
                                api_key = accounts_data[0].get('csgotm', {}).get('api_key')

                                if not api_key:
                                    self.state.add_log(f"[WARNING] [{account.name}] No API key, skipping real-time check")
                                    continue

                                # Get current CSGO.TM price
                                csgotm_client = CsgoTmClient(api_key=api_key)
                                tm_price_data = csgotm_client.get_item_price(market_hash_name)

                                if not tm_price_data or 'min_price' not in tm_price_data:
                                    self.state.add_log(f"[WARNING] [{account.name}] No CSGO.TM data, skipping")
                                    continue

                                csgo_price = tm_price_data['min_price']
                                order_price = order.get('order_price', 0)

                                # Calculate profit with commission from config
                                commission_pct = self.state.config.get('csgo_commission', 10.0)
                                commission_multiplier = 1.0 - (commission_pct / 100.0)
                                net_revenue = csgo_price * commission_multiplier

                                if order_price > 0:
                                    current_profit_pct = ((net_revenue - order_price) / order_price) * 100
                                else:
                                    current_profit_pct = 0

                                self.state.add_log(f"[INFO] [{account.name}] Real-time profit: {current_profit_pct:.1f}% (order: {order_price:.0f}, TM: {csgo_price:.0f})")

                                if current_profit_pct < min_profit_percent:
                                    # Profit too low - cancel
                                    self.state.add_log(f"[WARNING] [{account.name}] Low profit ({current_profit_pct:.1f}%): {market_hash_name}")

                                    import asyncio
                                    await asyncio.create_task(account.steam_client.cancel_buy_order(order_id))
                                    db_service.update_order_status(order_id, 'cancelled')
                                    results['cancelled'] += 1
                                    account_cancelled += 1

                                    self.state.add_log(f"[SUCCESS] [{account.name}] Cancelled low-profit order: {order['item_name']} ({current_profit_pct:.1f}%)")
                                else:
                                    self.state.add_log(f"[INFO] [{account.name}] Order is profitable, keeping: {market_hash_name} ({current_profit_pct:.1f}%)")

                            except Exception as e:
                                self.state.add_log(f"[ERROR] [{account.name}] Real-time check failed: {e}")
                                results['errors'].append(f"{account.name}/{market_hash_name}: {str(e)}")

                            continue
                        else:
                            # Item not in profitable items table
                            # Skip instead of cancelling - it might still be profitable
                            # User should enable check_realtime=True to verify actual profitability
                            self.state.add_log(f"[INFO] [{account.name}] Item not in profitable_items table, skipping: {market_hash_name}")
                            results['skipped'] += 1
                            continue

                    # Check profit percentage - try multiple fields in order of preference
                    current_profit_pct = (
                        profitable_item.get('current_profit_pct') or
                        profitable_item.get('profit_pct') or
                        profitable_item.get('recommended_instant_pct') or
                        profitable_item.get('instant_profit_pct') or
                        0
                    )

                    # Only cancel if profit is actually negative or below threshold
                    # Skip if profit is 0 (unknown) to avoid false cancellations
                    if current_profit_pct == 0:
                        # Unknown profit - skip this order
                        self.state.add_log(f"[INFO] [{account.name}] Profit unknown, skipping: {market_hash_name}")
                        continue

                    if current_profit_pct < min_profit_percent:
                        # Profit too low - cancel order
                        self.state.add_log(f"[WARNING] [{account.name}] Low profit ({current_profit_pct:.1f}%): {market_hash_name}")

                        # Cancel order in Steam
                        try:
                            import asyncio
                            await asyncio.create_task(account.steam_client.cancel_buy_order(order_id))

                            # Update status in DB
                            db_service.update_order_status(order_id, 'cancelled')
                            results['cancelled'] += 1
                            account_cancelled += 1

                            self.state.add_log(f"[SUCCESS] [{account.name}] Cancelled low-profit order: {order['item_name']} ({current_profit_pct:.1f}%)")
                        except Exception as e:
                            self.state.add_log(f"[ERROR] [{account.name}] Failed to cancel order {order_id}: {e}")
                            results['errors'].append(f"{account.name}/{order_id}: {str(e)}")

                self.state.add_log(f"[INFO] [{account.name}] Checked {account_checked} orders, cancelled {account_cancelled}")

            except Exception as e:
                results['errors'].append(f"{account.name}: {str(e)}")
                self.state.add_log(f"[ERROR] [{account.name}] Check error: {e}")

        return results

    def set_account_enabled(self, account_name: str, enabled: bool) -> bool:
        """
        Set account enabled status and save to accounts.json.

        Args:
            account_name: Account name
            enabled: True to enable, False to disable

        Returns:
            True if successful, False otherwise
        """
        try:
            import json

            # Update in-memory state
            for acc in self.state.accounts:
                if acc.name == account_name:
                    acc.enabled = enabled
                    break

            # Load accounts.json
            config_file = Path("accounts.json")
            if not config_file.exists():
                logger.error(f"accounts.json not found")
                return False

            with open(config_file, 'r', encoding='utf-8') as f:
                accounts_config = json.load(f)

            # Update enabled status in config
            for acc_config in accounts_config:
                if acc_config.get('name') == account_name:
                    acc_config['enabled'] = enabled
                    break

            # Save back to accounts.json
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(accounts_config, f, indent=2, ensure_ascii=False)

            logger.info(f"Account {account_name} {'enabled' if enabled else 'disabled'}")
            return True

        except Exception as e:
            logger.error(f"Failed to set account enabled status: {e}")
            return False

    def get_logged_in_account(self):
        """Get first logged in account."""
        if not self.account_manager:
            return None

        for account in self.account_manager.get_all_accounts():
            if account.is_logged_in():
                return account
        return None
