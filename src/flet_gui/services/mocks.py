"""
Mock services for testing the GUI without real backend.
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

from flet_gui.state.app_state import AppState, AccountState


class MockServices:
    """
    Mock implementations of all backend services.

    Use these to test the GUI visually and verify performance
    without connecting to real Steam/CSGO.TM APIs.
    """

    def __init__(self, state: AppState):
        self.state = state

    def load_mock_data(self):
        """Load all mock data into state."""
        self._load_accounts()
        self._load_stats()
        self._load_orders()
        self._load_inventory()
        self._load_profitable_items()
        self._load_recent_sales()
        self._load_history()
        self._add_sample_logs()

    def _load_accounts(self):
        """Load mock accounts."""
        self.state.accounts = [
            AccountState(
                name="MainAccount",
                enabled=True,
                logged_in=True,
                currency="RUB",
                steam_balance=12500.50,
                csgotm_balance=8300.00,
            ),
            AccountState(
                name="SecondAccount",
                enabled=True,
                logged_in=True,
                currency="EUR",
                steam_balance=85.20,
                csgotm_balance=2100.00,
            ),
            AccountState(
                name="TestAccount",
                enabled=False,
                logged_in=False,
                currency="USD",
                steam_balance=0,
                csgotm_balance=0,
            ),
        ]

    def _load_stats(self):
        """Load mock dashboard stats."""
        self.state.stats = {
            'balance_steam': 12585.70,
            'balance_csgotm': 10400.00,
            'active_orders': 47,
            'items_on_hold': 12,
            'total_profit': 15420.30,
            'sold_items': 156,
        }

    def _load_orders(self):
        """Load mock active orders."""
        items = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Battle-Scarred)",
            "M4A4 | Desolate Space (Minimal Wear)",
            "Glock-18 | Water Elemental (Factory New)",
            "USP-S | Kill Confirmed (Well-Worn)",
            "Desert Eagle | Blaze (Factory New)",
            "StatTrak™ AK-47 | Frontside Misty (Field-Tested)",
            "AWP | Dragon Lore (Battle-Scarred)",
            "M4A1-S | Hyper Beast (Field-Tested)",
            "Karambit | Doppler (Factory New)",
        ]

        orders = []
        for i in range(50):
            item = random.choice(items)
            price = random.uniform(500, 8000)
            orders.append({
                'id': i + 1,
                'account_name': random.choice(['MainAccount', 'SecondAccount']),
                'item_name': item,
                'market_hash_name': item,
                'order_id': f"order_{i + 1000}",
                'price': price,
                'quantity': 1,
                'expected_sell_price': random.uniform(600, 9000),
                'created_at': (datetime.now() - timedelta(hours=random.randint(1, 72))).isoformat(),
                'status': 'active',
            })

        self.state.active_orders = orders

    def _load_inventory(self):
        """Load mock items on hold."""
        items = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Battle-Scarred)",
            "M4A4 | The Emperor (Field-Tested)",
            "Glock-18 | Fade (Factory New)",
            "USP-S | Neo-Noir (Minimal Wear)",
        ]

        inventory = []
        for i in range(15):
            item = random.choice(items)
            buy_price = random.uniform(1000, 5000)
            current_price = buy_price * random.uniform(0.9, 1.3)
            unlock_date = datetime.now() + timedelta(days=random.randint(1, 7))
            hold_time_remaining = random.randint(0, 168)  # 0-168 hours

            inventory.append({
                'id': i + 1,
                'account_name': random.choice(['MainAccount', 'SecondAccount']),
                'item_name': item,
                'market_hash_name': item,
                'buy_price': buy_price,
                'current_price': current_price,
                'expected_sell_price': buy_price * 1.15,
                'purchase_date': (datetime.now() - timedelta(days=random.randint(1, 6))).isoformat(),
                'unlock_date': unlock_date.isoformat(),
                'hold_time_remaining': hold_time_remaining,
                'status': 'holding' if hold_time_remaining > 0 else 'ready',
            })

        self.state.items_on_hold = inventory

    def _load_profitable_items(self):
        """Load mock profitable items from scanner."""
        items = [
            ("AK-47 | Redline (Field-Tested)", "Weapon"),
            ("AWP | Asiimov (Battle-Scarred)", "Weapon"),
            ("M4A4 | Desolate Space (Minimal Wear)", "Weapon"),
            ("Sticker | Natus Vincere (Holo) | Katowice 2014", "Sticker"),
            ("Glock-18 | Fade (Factory New)", "Weapon"),
            ("USP-S | Kill Confirmed (Factory New)", "Weapon"),
            ("Desert Eagle | Blaze (Factory New)", "Weapon"),
            ("Sport Gloves | Pandora's Box (Field-Tested)", "Gloves"),
            ("Butterfly Knife | Doppler (Factory New)", "Knife"),
            ("AK-47 | Fire Serpent (Field-Tested)", "Weapon"),
        ]

        profitable = []
        for i, (name, item_type) in enumerate(items):
            steam_price = random.uniform(1000, 15000)
            csgo_price = steam_price * random.uniform(1.05, 1.25)
            profit_pct = ((csgo_price * 0.9) / steam_price - 1) * 100

            profitable.append({
                'id': i + 1,
                'market_hash_name': name,
                'item_type': item_type,
                'steam_buy_order': steam_price,
                'recommended_buy_order': steam_price * 0.98,
                'csgo_price': csgo_price,
                'profit_pct': profit_pct,
                'recommended_profit_pct': profit_pct + 2,
                'orders_above': random.randint(0, 10),
                'found_at': (datetime.now() - timedelta(hours=random.randint(1, 48))).isoformat(),
                'updated_at': datetime.now().isoformat(),
                'is_active': 1,
            })

        # Sort by profit
        profitable.sort(key=lambda x: x['profit_pct'], reverse=True)
        self.state.profitable_items = profitable

    def _load_recent_sales(self):
        """Load mock recent sales."""
        items = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Battle-Scarred)",
            "M4A4 | Desolate Space (Minimal Wear)",
        ]

        sales = []
        for i in range(10):
            item = random.choice(items)
            buy_price = random.uniform(1000, 5000)
            sale_price = buy_price * random.uniform(1.05, 1.2)
            profit = sale_price * 0.9 - buy_price

            sales.append({
                'id': i + 1,
                'account_name': random.choice(['MainAccount', 'SecondAccount']),
                'item_name': item,
                'buy_price': buy_price,
                'sale_price': sale_price,
                'profit': profit,
                'profit_pct': (profit / buy_price) * 100,
                'sale_date': (datetime.now() - timedelta(days=random.randint(1, 14))).isoformat(),
            })

        self.state.recent_sales = sales

    def _load_history(self):
        """Load mock transaction history."""
        items = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Battle-Scarred)",
            "M4A4 | Desolate Space (Minimal Wear)",
        ]

        history = []
        for i in range(50):
            item = random.choice(items)
            trans_type = random.choice(['purchase', 'sale', 'order'])
            price = random.uniform(1000, 5000)
            profit = random.uniform(-200, 500) if trans_type == 'sale' else 0

            history.append({
                'id': i + 1,
                'type': trans_type,
                'account_name': random.choice(['MainAccount', 'SecondAccount']),
                'item_name': item,
                'price': price,
                'profit': profit,
                'date': (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat(),
            })

        # Sort by date
        history.sort(key=lambda x: x['date'], reverse=True)
        self.state.history = history

    def _add_sample_logs(self):
        """Add sample log messages."""
        sample_logs = [
            "[INFO] Application started",
            "[INFO] Loaded 3 accounts from config",
            "[SUCCESS] MainAccount logged in successfully",
            "[SUCCESS] SecondAccount logged in successfully",
            "[WARNING] TestAccount is disabled",
            "[INFO] Bot initialized and ready",
            "Scanning for profitable items...",
            "[SUCCESS] Found 10 profitable items",
            "Processing buy orders...",
            "[INFO] Created 5 new buy orders",
            "[INFO] Dashboard stats updated",
        ]

        for log in sample_logs:
            self.state.add_log(log)


async def simulate_bot_cycle(state: AppState):
    """Simulate a bot trading cycle for demo."""
    state.add_log("[INFO] Starting bot cycle...")
    await asyncio.sleep(1)

    state.add_log("Syncing orders with Steam...")
    await asyncio.sleep(2)

    state.add_log("[SUCCESS] Synced 47 active orders")
    await asyncio.sleep(1)

    state.add_log("Checking for filled orders...")
    await asyncio.sleep(1)

    filled = random.randint(0, 3)
    if filled > 0:
        state.add_log(f"[SUCCESS] {filled} orders filled!")

    state.add_log("Scanning profitable items...")
    await asyncio.sleep(2)

    new_items = random.randint(0, 5)
    state.add_log(f"[INFO] Found {new_items} new profitable items")

    state.add_log("[SUCCESS] Bot cycle completed")
