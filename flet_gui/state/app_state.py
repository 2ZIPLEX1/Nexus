"""
Centralized application state with reactive observer pattern.

All UI components subscribe to state changes and update automatically.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass
class AccountState:
    """State for a single account."""
    name: str
    enabled: bool = True
    logged_in: bool = False
    currency: str = "RUB"
    steam_balance: float = 0.0
    csgotm_balance: float = 0.0
    csgotm_settlement: float = 0.0  # Money in hold on CSGO.TM


@dataclass
class BotState:
    """State for the trading bot."""
    running: bool = False
    current_cycle: int = 0
    last_cycle_time: Optional[str] = None
    status_text: str = "Stopped"


@dataclass
class ScannerState:
    """State for the auto-scanner."""
    running: bool = False
    status_text: str = "Ready"
    items_found: int = 0
    last_scan_time: Optional[str] = None
    next_scan_time: Optional[str] = None


class AppState:
    """
    Centralized reactive state for the entire application.

    Uses singleton pattern and observer pattern for UI updates.
    Components subscribe to specific keys and get notified on changes.

    Usage:
        state = AppState()
        state.subscribe('active_orders', lambda: update_ui())
        state.active_orders = new_orders  # triggers notification
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_state()

    def _init_state(self):
        """Initialize all state variables."""
        # Account states
        self._accounts: list[AccountState] = []
        self._selected_account: str = "All Accounts"

        # Bot and scanner states
        self._bot_state = BotState()
        self._scanner_state = ScannerState()

        # Data lists
        self._active_orders: list[dict] = []
        self._items_on_hold: list[dict] = []
        self._profitable_items: list[dict] = []
        self._recent_sales: list[dict] = []
        self._history: list[dict] = []
        self._logs: list[str] = []

        # Dashboard statistics
        self._stats = {
            'balance_steam': 0.0,
            'balance_csgotm': 0.0,
            'active_orders': 0,
            'items_on_hold': 0,
            'total_profit': 0.0,
            'sold_items': 0,
        }

        # Configuration
        self._config: dict = {}

        # Observer registry: key -> list of callbacks
        self._observers: dict[str, list[Callable]] = {}

    # =========================================================================
    # Observer Pattern Methods
    # =========================================================================

    def subscribe(self, key: str, callback: Callable) -> None:
        """
        Subscribe to state changes for a specific key.

        Args:
            key: State property name (e.g., 'active_orders', 'stats')
            callback: Function to call when state changes (no arguments)
        """
        if key not in self._observers:
            self._observers[key] = []
        if callback not in self._observers[key]:
            self._observers[key].append(callback)

    def unsubscribe(self, key: str, callback: Callable) -> None:
        """
        Unsubscribe from state changes.

        Args:
            key: State property name
            callback: Previously subscribed callback
        """
        if key in self._observers and callback in self._observers[key]:
            self._observers[key].remove(callback)

    def _notify(self, key: str) -> None:
        """
        Notify all observers of a state change.

        Args:
            key: State property name that changed
        """
        if key in self._observers:
            for callback in self._observers[key]:
                try:
                    callback()
                except Exception as e:
                    print(f"Error in observer callback for '{key}': {e}")

    # =========================================================================
    # Account Properties
    # =========================================================================

    @property
    def accounts(self) -> list[AccountState]:
        return self._accounts

    @accounts.setter
    def accounts(self, value: list[AccountState]) -> None:
        self._accounts = value
        self._notify('accounts')

    @property
    def selected_account(self) -> str:
        return self._selected_account

    @selected_account.setter
    def selected_account(self, value: str) -> None:
        self._selected_account = value
        self._notify('selected_account')
        # Also trigger data refreshes
        self._notify('active_orders')
        self._notify('stats')

    # =========================================================================
    # Bot & Scanner Properties
    # =========================================================================

    @property
    def bot_state(self) -> BotState:
        return self._bot_state

    @bot_state.setter
    def bot_state(self, value: BotState) -> None:
        self._bot_state = value
        self._notify('bot_state')

    @property
    def scanner_state(self) -> ScannerState:
        return self._scanner_state

    @scanner_state.setter
    def scanner_state(self, value: ScannerState) -> None:
        self._scanner_state = value
        self._notify('scanner_state')

    def update_bot_status(self, running: bool, status_text: str = None) -> None:
        """Helper to update bot status."""
        self._bot_state.running = running
        if status_text:
            self._bot_state.status_text = status_text
        self._notify('bot_state')

    def update_scanner_status(self, running: bool, status_text: str = None) -> None:
        """Helper to update scanner status."""
        self._scanner_state.running = running
        if status_text:
            self._scanner_state.status_text = status_text
        self._notify('scanner_state')

    # =========================================================================
    # Data List Properties
    # =========================================================================

    @property
    def active_orders(self) -> list[dict]:
        return self._active_orders

    @active_orders.setter
    def active_orders(self, value: list[dict]) -> None:
        self._active_orders = value
        self._stats['active_orders'] = len(value)
        self._notify('active_orders')
        self._notify('stats')

    @property
    def items_on_hold(self) -> list[dict]:
        return self._items_on_hold

    @items_on_hold.setter
    def items_on_hold(self, value: list[dict]) -> None:
        self._items_on_hold = value
        self._stats['items_on_hold'] = len(value)
        self._notify('items_on_hold')
        self._notify('stats')

    @property
    def profitable_items(self) -> list[dict]:
        return self._profitable_items

    @profitable_items.setter
    def profitable_items(self, value: list[dict]) -> None:
        self._profitable_items = value
        self._notify('profitable_items')

    @property
    def recent_sales(self) -> list[dict]:
        return self._recent_sales

    @recent_sales.setter
    def recent_sales(self, value: list[dict]) -> None:
        self._recent_sales = value
        self._notify('recent_sales')

    @property
    def history(self) -> list[dict]:
        return self._history

    @history.setter
    def history(self, value: list[dict]) -> None:
        self._history = value
        self._notify('history')

    @property
    def logs(self) -> list[str]:
        return self._logs

    def add_log(self, message: str) -> None:
        """Add a log message (max 1000 lines).

        Сообщение проходит редакцию секретов: этот буфер виден в GUI и в веб-панели,
        а зовут add_log из сотни мест, куда легко попадает URL прокси с паролем.
        """
        try:
            from src.logger import redact_text
            message = redact_text(message)
        except Exception:
            pass
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._logs.append(f"[{timestamp}] {message}")
        # Ring buffer - keep last 1000 lines
        if len(self._logs) > 1000:
            self._logs = self._logs[-1000:]
        self._notify('logs')

    def clear_logs(self) -> None:
        """Clear all logs."""
        self._logs = []
        self._notify('logs')

    # =========================================================================
    # Statistics Properties
    # =========================================================================

    @property
    def stats(self) -> dict:
        return self._stats

    @stats.setter
    def stats(self, value: dict) -> None:
        self._stats.update(value)
        self._notify('stats')

    def update_stat(self, key: str, value: Any) -> None:
        """Update a single stat."""
        self._stats[key] = value
        self._notify('stats')

    # =========================================================================
    # Configuration Properties
    # =========================================================================

    @property
    def config(self) -> dict:
        return self._config

    @config.setter
    def config(self, value: dict) -> None:
        self._config = value
        self._notify('config')

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_filtered_orders(self) -> list[dict]:
        """Get orders filtered by selected account."""
        if self._selected_account == "All Accounts":
            return self._active_orders
        return [
            o for o in self._active_orders
            if o.get('account_name') == self._selected_account
        ]

    def get_filtered_items(self) -> list[dict]:
        """Get items on hold filtered by selected account."""
        if self._selected_account == "All Accounts":
            return self._items_on_hold
        return [
            i for i in self._items_on_hold
            if i.get('account_name') == self._selected_account
        ]

    def get_account_by_name(self, name: str) -> Optional[AccountState]:
        """Get account state by name."""
        for acc in self._accounts:
            if acc.name == name:
                return acc
        return None

    def reset(self) -> None:
        """Reset all state to initial values."""
        self._init_state()
        # Notify all observers
        for key in list(self._observers.keys()):
            self._notify(key)
