"""
Async Helper - запуск async кода из синхронного GUI.

Позволяет выполнять async корутины из синхронного кода (threading).
"""
import asyncio
import sys
import threading
from typing import Any, Callable
from functools import wraps

from src.logger import get_logger

logger = get_logger(__name__)


class AsyncRunner:
    """
    Запускает async функции в отдельном event loop.

    Используется для интеграции async кода (aiosteampy) с синхронным GUI (tkinter).
    """

    def __init__(self):
        """Initialize async runner."""
        self.loop = None
        self.thread = None
        self._started = False

    def start(self):
        """Start event loop in separate thread."""
        if self._started:
            logger.warning("AsyncRunner already started")
            return

        def run_loop():
            # Set Windows event loop policy
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            logger.info("AsyncRunner event loop started")
            self.loop.run_forever()
            logger.info("AsyncRunner event loop stopped")

        self.thread = threading.Thread(target=run_loop, daemon=True, name="AsyncRunner")
        self.thread.start()

        # Wait for loop to be ready
        import time
        timeout = 5.0
        elapsed = 0.0
        while self.loop is None and elapsed < timeout:
            time.sleep(0.01)
            elapsed += 0.01

        if self.loop is None:
            raise RuntimeError("Failed to start AsyncRunner event loop")

        self._started = True
        logger.info("AsyncRunner initialized successfully")

    def stop(self):
        """Stop event loop."""
        if not self._started:
            return

        logger.info("Stopping AsyncRunner...")

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning("AsyncRunner thread did not stop gracefully")

        self._started = False
        logger.info("AsyncRunner stopped")

    def run_async(self, coro, timeout: float = 30.0):
        """
        Run async coroutine and wait for result.

        Args:
            coro: Coroutine to run
            timeout: Timeout in seconds (default: 30)

        Returns:
            Result of coroutine

        Raises:
            RuntimeError: If AsyncRunner not started
            TimeoutError: If coroutine takes longer than timeout
            Exception: Any exception raised by coroutine
        """
        if not self._started or not self.loop:
            raise RuntimeError("AsyncRunner not started. Call start() first.")

        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            result = future.result(timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"AsyncRunner: Coroutine timed out after {timeout}s")
            raise TimeoutError(f"Coroutine timed out after {timeout}s")
        except Exception as e:
            logger.error(f"AsyncRunner: Error running coroutine: {e}")
            raise

    def is_running(self) -> bool:
        """Check if AsyncRunner is running."""
        return self._started and self.loop is not None and self.loop.is_running()


# Глобальный singleton
_async_runner: AsyncRunner = None
_runner_lock = threading.Lock()


def get_async_runner() -> AsyncRunner:
    """
    Get global AsyncRunner instance (singleton).

    Automatically starts the runner if not already started.

    Returns:
        Global AsyncRunner instance
    """
    global _async_runner

    with _runner_lock:
        if _async_runner is None:
            logger.info("Creating global AsyncRunner instance")
            _async_runner = AsyncRunner()
            _async_runner.start()

    return _async_runner


def run_async_in_gui(coro, timeout: float = 30.0):
    """
    Helper function to run async code from GUI thread.

    Usage:
        result = run_async_in_gui(account.login_async())
        balance = run_async_in_gui(steam_client.get_wallet_balance())

    Args:
        coro: Coroutine to run
        timeout: Timeout in seconds

    Returns:
        Result of coroutine

    Raises:
        TimeoutError: If operation times out
        Exception: Any exception from coroutine
    """
    runner = get_async_runner()
    return runner.run_async(coro, timeout=timeout)


def shutdown_async_runner():
    """
    Shutdown global AsyncRunner.

    Should be called when application is closing.
    """
    global _async_runner

    with _runner_lock:
        if _async_runner is not None:
            _async_runner.stop()
            _async_runner = None
            logger.info("Global AsyncRunner shutdown complete")


# Декоратор для создания синхронных оберток из async функций
def make_sync(async_func: Callable) -> Callable:
    """
    Decorator to create sync wrapper from async function.

    Usage:
        @make_sync
        async def async_function(arg1, arg2):
            return await some_async_call()

        # Now can be called synchronously:
        result = async_function(arg1, arg2)

    Args:
        async_func: Async function to wrap

    Returns:
        Synchronous wrapper function
    """
    @wraps(async_func)
    def sync_wrapper(*args, **kwargs):
        coro = async_func(*args, **kwargs)
        return run_async_in_gui(coro)

    return sync_wrapper
