"""
Ожидание ручного подтверждения ордеров в Steam Mobile Guard.

Для аккаунтов без identity_secret.

Два пути:
- GUI: ждёт кнопку "Подтвердил" (EventBus CONFIRMATION_USER_CONFIRMED)
- CLI: ждёт Enter от пользователя
"""

import asyncio
from typing import Optional, Callable

from src.logger import get_logger

logger = get_logger(__name__)


class ManualConfirmationWaiter:
    """
    Ожидает ручного подтверждения buy order в Steam Mobile Guard.

    GUI-путь: ждёт EventBus CONFIRMATION_USER_CONFIRMED (кнопка "Подтвердил" в UI).
    CLI-путь: ждёт input() если GUI не слушает.

    После первого подтверждения all subsequent orders skip the wait
    (управляется через ManualTwoFactorSteamClient.first_confirmation_done).
    """

    MAX_WAIT_TIME = 300  # 5 минут максимум

    def __init__(
        self,
        steam_client,
        account_name: str,
        on_waiting: Optional[Callable] = None,
        on_confirmed: Optional[Callable] = None,
    ):
        self.steam_client = steam_client
        self.account_name = account_name
        self.on_waiting = on_waiting
        self.on_confirmed = on_confirmed
        self._confirmed_event: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def signal_user_confirmed(self) -> None:
        """
        Вызывается из UI (кнопка "Подтвердил") или из любого потока.
        Thread-safe.
        """
        if self._confirmed_event is not None and self._loop is not None:
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._confirmed_event.set)

    async def wait_for_confirmation(self, confirmation_id: int) -> None:
        """
        Ожидает пока пользователь подтвердит ордер на телефоне.
        Вызывается как callback из aiosteampy (confirm_market_purchase).
        После возврата aiosteampy сделает второй place_buy_order → ордер будет выставлен.
        """
        self._loop = asyncio.get_running_loop()
        self._confirmed_event = asyncio.Event()

        logger.info(
            f"[{self.account_name}] Ожидание ручного подтверждения ордера "
            f"(confirmation_id={confirmation_id})..."
        )

        if self.on_waiting:
            try:
                self.on_waiting(self.account_name, confirmation_id)
            except Exception as e:
                logger.warning(f"[{self.account_name}] on_waiting callback error: {e}")

        confirmed = await self._wait_for_signal()

        if confirmed:
            logger.info(f"[{self.account_name}] Получен сигнал подтверждения от пользователя")
        else:
            logger.warning(
                f"[{self.account_name}] Таймаут ожидания подтверждения ({self.MAX_WAIT_TIME}s). "
                f"Продолжаем — aiosteampy повторит вызов place_buy_order..."
            )

        self._confirmed_event = None
        self._fire_confirmed()

    async def _wait_for_signal(self) -> bool:
        """
        Ждёт сигнала подтверждения одновременно из двух источников:
        - input() в консоли (нажать Enter после подтверждения на телефоне)
        - EventBus CONFIRMATION_USER_CONFIRMED (кнопка в GUI если открыт)
        Кто первый сработает — тот и побеждает.
        """
        loop = self._loop

        # Подписываемся на EventBus (для GUI-кнопки)
        _eventbus_cleanup = None
        try:
            from flet_gui.state.events import EventBus, EventType
            bus = EventBus()
            account_name = self.account_name

            def _on_gui_confirmed(data):
                if data and data.get("account_name") == account_name:
                    if self._confirmed_event is not None and loop is not None:
                        loop.call_soon_threadsafe(self._confirmed_event.set)

            bus.on(EventType.CONFIRMATION_USER_CONFIRMED, _on_gui_confirmed)
            _eventbus_cleanup = lambda: bus.off(EventType.CONFIRMATION_USER_CONFIRMED, _on_gui_confirmed)
        except ImportError:
            pass

        # Запускаем input() в потоке — нажатие Enter тоже сетит event
        def _stdin_waiter():
            try:
                input()
                if self._confirmed_event is not None and loop is not None:
                    loop.call_soon_threadsafe(self._confirmed_event.set)
            except EOFError:
                pass

        executor_future = asyncio.get_event_loop().run_in_executor(None, _stdin_waiter)

        try:
            await asyncio.wait_for(self._confirmed_event.wait(), timeout=self.MAX_WAIT_TIME)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            if _eventbus_cleanup:
                _eventbus_cleanup()
            executor_future.cancel()

    def _fire_confirmed(self) -> None:
        if self.on_confirmed:
            try:
                self.on_confirmed(self.account_name)
            except Exception as e:
                logger.warning(f"[{self.account_name}] on_confirmed callback error: {e}")
