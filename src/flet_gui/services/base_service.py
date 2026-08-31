"""
BaseService - base class for all GUI services.

Provides:
- Common error handling patterns
- Logging to both logger and state.add_log
- Async loop management for background tasks
- Service initialization pattern
"""

import asyncio
import functools
from typing import Optional, Callable, Any, TypeVar, ParamSpec
from abc import ABC

from flet_gui.state.app_state import AppState
from src.logger import get_logger

logger = get_logger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


# ============================================================================
# DECORATORS FOR COMMON PATTERNS
# ============================================================================

def log_errors(operation_name: str = "operation"):
    """
    Decorator that logs errors to both logger and state.

    Usage:
        @log_errors("login")
        def login_account(self, name):
            ...
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> T:
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                logger.error(f"Failed to {operation_name}: {e}")
                if hasattr(self, 'state') and self.state:
                    self.state.add_log(f"[ERROR] Failed to {operation_name}: {str(e)}")
                raise
        return wrapper
    return decorator


def log_errors_async(operation_name: str = "operation"):
    """
    Async decorator that logs errors to both logger and state.

    Usage:
        @log_errors_async("login")
        async def login_account(self, name):
            ...
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs) -> T:
            try:
                return await func(self, *args, **kwargs)
            except asyncio.CancelledError:
                raise  # Don't log cancellation as error
            except Exception as e:
                logger.error(f"Failed to {operation_name}: {e}")
                if hasattr(self, 'state') and self.state:
                    self.state.add_log(f"[ERROR] Failed to {operation_name}: {str(e)}")
                raise
        return wrapper
    return decorator


def require_service(service_name: str):
    """
    Decorator that checks if a service is available before execution.

    Usage:
        @require_service("account_service")
        def do_something(self):
            ...
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Optional[T]:
            service = getattr(self, service_name, None)
            if not service:
                if hasattr(self, 'state') and self.state:
                    self.state.add_log(f"[ERROR] {service_name} not available")
                logger.error(f"{service_name} not available")
                return None
            return func(self, *args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# BASE SERVICE CLASS
# ============================================================================

class BaseService(ABC):
    """
    Base class for all GUI services.

    Provides common functionality:
    - State management
    - Logging shortcuts
    - Error handling
    - Background task management
    """

    def __init__(self, state: AppState):
        """Initialize base service with state."""
        self.state = state
        self._running = False
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._running

    def log_info(self, message: str):
        """Log info message to both logger and state."""
        logger.info(message)
        self.state.add_log(f"[INFO] {message}")

    def log_success(self, message: str):
        """Log success message to both logger and state."""
        logger.info(message)
        self.state.add_log(f"[SUCCESS] {message}")

    def log_warning(self, message: str):
        """Log warning message to both logger and state."""
        logger.warning(message)
        self.state.add_log(f"[WARNING] {message}")

    def log_error(self, message: str, exc: Exception = None):
        """Log error message to both logger and state."""
        if exc:
            logger.error(f"{message}: {exc}")
            self.state.add_log(f"[ERROR] {message}: {str(exc)}")
        else:
            logger.error(message)
            self.state.add_log(f"[ERROR] {message}")

    async def run_in_thread(self, func: Callable, *args, **kwargs) -> Any:
        """Run blocking function in thread pool to avoid GUI freeze."""
        return await asyncio.to_thread(func, *args, **kwargs)

    def start_background_task(self, coro, name: str = None):
        """Start a background task and track it."""
        task = asyncio.create_task(coro)
        if name:
            task.set_name(name)
        self._tasks.append(task)
        return task

    async def stop_all_tasks(self):
        """Stop all background tasks gracefully."""
        self._running = False

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()


# ============================================================================
# ASYNC LOOP MIXIN
# ============================================================================

class AsyncLoopMixin:
    """
    Mixin for services that need to run periodic async loops.

    Eliminates duplication of the common async loop pattern found in:
    - tm_sales_service.py (_ping_loop, _hold_check_loop, etc.)
    - scanner_service.py
    - auto_buy_service.py

    Usage:
        class MyService(BaseService, AsyncLoopMixin):
            async def start(self):
                self._running = True
                self.create_loop("ping", self._do_ping, interval=60)
                self.create_loop("check", self._do_check, interval=120)

            async def _do_ping(self):
                # Your logic here
                pass
    """

    _loops: dict  # Will be initialized in create_loop

    def create_loop(
        self,
        name: str,
        callback: Callable,
        interval: float,
        error_interval: float = None,
        on_error: Callable[[Exception], None] = None
    ) -> asyncio.Task:
        """
        Create a managed async loop.

        Args:
            name: Loop identifier for logging
            callback: Async function to call each iteration
            interval: Seconds between iterations
            error_interval: Seconds to wait after error (defaults to interval)
            on_error: Optional error handler

        Returns:
            asyncio.Task that can be cancelled
        """
        if not hasattr(self, '_loops'):
            self._loops = {}

        if error_interval is None:
            error_interval = min(interval, 60)

        async def loop_runner():
            while getattr(self, '_running', False):
                try:
                    await callback()
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    if hasattr(self, 'log_error'):
                        self.log_error(f"Error in {name} loop", e)
                    else:
                        logger.error(f"Error in {name} loop: {e}")

                    if on_error:
                        try:
                            on_error(e)
                        except:
                            pass

                    await asyncio.sleep(error_interval)

        task = asyncio.create_task(loop_runner())
        task.set_name(f"loop_{name}")
        self._loops[name] = task

        if hasattr(self, '_tasks'):
            self._tasks.append(task)

        return task

    async def stop_loop(self, name: str):
        """Stop a specific loop by name."""
        if hasattr(self, '_loops') and name in self._loops:
            task = self._loops[name]
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            del self._loops[name]

    async def stop_all_loops(self):
        """Stop all managed loops."""
        if not hasattr(self, '_loops'):
            return

        for name in list(self._loops.keys()):
            await self.stop_loop(name)
