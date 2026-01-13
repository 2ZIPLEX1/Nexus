"""
Автоматическое сканирование выгодных предметов по расписанию.

Функции:
- Сканирование по таймеру
- Управление расписанием
- Уведомления о находках
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

from src.logger import get_logger

logger = get_logger(__name__)


class AutoScanner:
    """Автоматическое сканирование по расписанию."""

    def __init__(
        self,
        scan_callback: Callable,
        interval_minutes: int = 30,
        enabled: bool = False
    ):
        """
        Initialize auto scanner.

        Args:
            scan_callback: Функция для запуска сканирования
            interval_minutes: Интервал между сканированиями (минуты)
            enabled: Включен ли автосканер
        """
        self.scan_callback = scan_callback
        self.interval_minutes = interval_minutes
        self.enabled = enabled

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_scan_time: Optional[datetime] = None
        self._next_scan_time: Optional[datetime] = None
        self._scan_count = 0

    def start(self):
        """Запустить автосканер."""
        if self._thread and self._thread.is_alive():
            logger.warning("Auto scanner is already running")
            return

        self.enabled = True
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info(f"Auto scanner started (interval: {self.interval_minutes} min)")

    def stop(self):
        """Остановить автосканер."""
        self.enabled = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Auto scanner stopped")

    def _run_loop(self):
        """Основной цикл автосканирования."""
        logger.info("Auto scanner loop started")

        while self.enabled and not self._stop_event.is_set():
            try:
                # Вычисляем время следующего сканирования
                if self._last_scan_time is None:
                    # Первый запуск - сканируем сразу
                    self._perform_scan()
                else:
                    # Проверяем, пора ли сканировать
                    now = datetime.now()
                    if now >= self._next_scan_time:
                        self._perform_scan()

                # Ждём 1 минуту перед следующей проверкой
                self._stop_event.wait(60)

            except Exception as e:
                logger.error(f"Error in auto scanner loop: {e}", exc_info=True)
                # Ждём перед повтором при ошибке
                self._stop_event.wait(300)  # 5 минут

        logger.info("Auto scanner loop ended")

    def _perform_scan(self):
        """Выполнить сканирование."""
        try:
            logger.info(f"Auto scan #{self._scan_count + 1} starting...")

            self._last_scan_time = datetime.now()
            self._next_scan_time = self._last_scan_time + timedelta(minutes=self.interval_minutes)
            self._scan_count += 1

            # Вызываем callback для запуска сканирования
            self.scan_callback()

            logger.info(f"Auto scan #{self._scan_count} completed. Next scan at {self._next_scan_time.strftime('%H:%M:%S')}")

        except Exception as e:
            logger.error(f"Error performing auto scan: {e}", exc_info=True)

    def set_interval(self, minutes: int):
        """
        Изменить интервал сканирования.

        Args:
            minutes: Новый интервал в минутах
        """
        old_interval = self.interval_minutes
        self.interval_minutes = minutes

        # Пересчитываем время следующего сканирования
        if self._last_scan_time:
            self._next_scan_time = self._last_scan_time + timedelta(minutes=minutes)

        logger.info(f"Scan interval changed: {old_interval} → {minutes} minutes")

    def get_status(self) -> dict:
        """
        Получить статус автосканера.

        Returns:
            Dict со статусом
        """
        return {
            'enabled': self.enabled,
            'interval_minutes': self.interval_minutes,
            'scan_count': self._scan_count,
            'last_scan_time': self._last_scan_time.isoformat() if self._last_scan_time else None,
            'next_scan_time': self._next_scan_time.isoformat() if self._next_scan_time else None,
            'time_until_next_scan': self._get_time_until_next_scan()
        }

    def _get_time_until_next_scan(self) -> Optional[int]:
        """Получить секунды до следующего сканирования."""
        if not self._next_scan_time:
            return None

        delta = self._next_scan_time - datetime.now()
        return max(0, int(delta.total_seconds()))

    def is_running(self) -> bool:
        """Проверить, запущен ли автосканер."""
        return self.enabled and self._thread and self._thread.is_alive()
