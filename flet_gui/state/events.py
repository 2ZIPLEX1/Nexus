"""
Event bus for cross-component communication.

Provides decoupled event-driven communication between components.
"""

import threading
from enum import Enum, auto
from typing import Any, Callable


class EventType(Enum):
    """All event types in the application."""

    # Bot lifecycle events
    BOT_STARTED = auto()
    BOT_STOPPED = auto()
    BOT_CYCLE_STARTED = auto()
    BOT_CYCLE_COMPLETE = auto()
    BOT_ERROR = auto()

    # Account events
    ACCOUNT_LOGIN_STARTED = auto()
    ACCOUNT_LOGIN_SUCCESS = auto()
    ACCOUNT_LOGIN_FAILED = auto()
    ACCOUNT_LOGOUT = auto()
    ACCOUNT_BALANCE_UPDATED = auto()
    ACCOUNT_CURRENCY_DETECTED = auto()

    # Scanner events
    SCANNER_STARTED = auto()
    SCANNER_STOPPED = auto()
    SCANNER_ITEM_FOUND = auto()
    SCANNER_RESCAN_STARTED = auto()
    SCANNER_RESCAN_COMPLETE = auto()

    # Order events
    ORDER_CREATED = auto()
    ORDER_FILLED = auto()
    ORDER_CANCELLED = auto()
    ORDERS_SYNCED = auto()

    # Inventory events
    ITEM_PURCHASED = auto()
    ITEM_LISTED = auto()
    ITEM_SOLD = auto()
    PRICES_UPDATED = auto()

    # Data refresh events
    DATA_REFRESH_REQUESTED = auto()
    DATA_REFRESH_COMPLETE = auto()

    # UI events
    TAB_CHANGED = auto()
    FILTER_CHANGED = auto()
    SORT_CHANGED = auto()

    # Log events
    LOG_MESSAGE = auto()
    LOG_ERROR = auto()
    LOG_WARNING = auto()

    # Confirmation events (для аккаунтов без identity_secret)
    CONFIRMATION_REQUIRED = auto()         # {account_name: str, message: str}
    CONFIRMATION_COMPLETED = auto()        # {account_name: str}
    CONFIRMATION_USER_CONFIRMED = auto()   # {account_name: str} — пользователь нажал "Подтвердил"

    # Config events
    CONFIG_LOADED = auto()
    CONFIG_SAVED = auto()


class EventBus:
    """
    Singleton event bus for application-wide event communication.

    Usage:
        bus = EventBus()
        bus.on(EventType.BOT_STARTED, lambda data: print("Bot started!"))
        bus.emit(EventType.BOT_STARTED, {"account": "main"})
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._handlers: dict[EventType, list[Callable]] = {}
        return cls._instance

    def on(self, event_type: EventType, handler: Callable[[Any], None]) -> None:
        """
        Subscribe to an event type.

        Args:
            event_type: The event type to listen for
            handler: Callback function that receives event data
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def off(self, event_type: EventType, handler: Callable[[Any], None]) -> None:
        """
        Unsubscribe from an event type.

        Args:
            event_type: The event type to stop listening for
            handler: The callback to remove
        """
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    def emit(self, event_type: EventType, data: Any = None) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: The event type to emit
            data: Optional data to pass to handlers
        """
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    print(f"Error in event handler for {event_type.name}: {e}")

    def once(self, event_type: EventType, handler: Callable[[Any], None]) -> None:
        """
        Subscribe to an event type for a single emission only.

        Args:
            event_type: The event type to listen for
            handler: Callback function that receives event data
        """
        def wrapper(data):
            handler(data)
            self.off(event_type, wrapper)

        self.on(event_type, wrapper)

    def clear(self, event_type: EventType = None) -> None:
        """
        Clear event handlers.

        Args:
            event_type: If provided, clear only handlers for this type.
                       If None, clear all handlers.
        """
        if event_type:
            self._handlers[event_type] = []
        else:
            self._handlers.clear()

    def has_handlers(self, event_type: EventType) -> bool:
        """Check if an event type has any handlers."""
        return event_type in self._handlers and len(self._handlers[event_type]) > 0
