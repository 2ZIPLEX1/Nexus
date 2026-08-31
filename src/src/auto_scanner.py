"""
Автоматическое сканирование выгодных предметов по расписанию.

Функции:
- Сканирование по таймеру
- Пересканирование существующих предметов на актуальность
- Поиск новых предметов
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
        rescan_callback: Optional[Callable] = None,
        new_items_callback: Optional[Callable] = None,
        interval_minutes: int = 30,
        rescan_interval_minutes: int = 60,
        new_items_count: int = 10,
        enabled: bool = False
    ):
        """
        Initialize auto scanner.

        Args:
            scan_callback: Функция для запуска полного сканирования
            rescan_callback: Функция для пересканирования существующих предметов
            new_items_callback: Функция для поиска новых предметов
            interval_minutes: Интервал между сканированиями новых (минуты)
            rescan_interval_minutes: Интервал пересканирования существующих (минуты)
            new_items_count: Количество новых предметов для сканирования
            enabled: Включен ли автосканер
        """
        self.scan_callback = scan_callback
        self.rescan_callback = rescan_callback
        self.new_items_callback = new_items_callback
        self.interval_minutes = interval_minutes
        self.rescan_interval_minutes = rescan_interval_minutes
        self.new_items_count = new_items_count
        self.enabled = enabled

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_scan_time: Optional[datetime] = None
        self._last_rescan_time: Optional[datetime] = None
        self._next_scan_time: Optional[datetime] = None
        self._next_rescan_time: Optional[datetime] = None
        self._scan_count = 0
        self._rescan_count = 0

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
                now = datetime.now()

                # Проверяем, нужно ли пересканировать существующие предметы
                if self.rescan_callback:
                    if self._last_rescan_time is None:
                        # Первый запуск - пересканируем сразу
                        self._perform_rescan()
                    elif self._next_rescan_time and now >= self._next_rescan_time:
                        self._perform_rescan()

                # Проверяем, нужно ли сканировать новые предметы
                if self._last_scan_time is None:
                    # Первый запуск - сканируем сразу (через 5 сек после rescan)
                    self._stop_event.wait(5)
                    if not self._stop_event.is_set():
                        self._perform_scan()
                elif self._next_scan_time and now >= self._next_scan_time:
                    self._perform_scan()

                # Ждём 1 минуту перед следующей проверкой
                self._stop_event.wait(60)

            except Exception as e:
                logger.error(f"Error in auto scanner loop: {e}", exc_info=True)
                # Ждём перед повтором при ошибке
                self._stop_event.wait(300)  # 5 минут

        logger.info("Auto scanner loop ended")

    def _perform_rescan(self):
        """Пересканировать существующие предметы на актуальность."""
        if not self.rescan_callback:
            return

        try:
            logger.info(f"Auto rescan #{self._rescan_count + 1} starting...")

            self._last_rescan_time = datetime.now()
            self._next_rescan_time = self._last_rescan_time + timedelta(minutes=self.rescan_interval_minutes)
            self._rescan_count += 1

            # Вызываем callback для пересканирования
            self.rescan_callback()

            logger.info(f"Auto rescan #{self._rescan_count} completed. Next rescan at {self._next_rescan_time.strftime('%H:%M:%S')}")

        except Exception as e:
            logger.error(f"Error performing auto rescan: {e}", exc_info=True)

    def _perform_scan(self):
        """Выполнить сканирование новых предметов."""
        try:
            logger.info(f"Auto scan #{self._scan_count + 1} starting...")

            self._last_scan_time = datetime.now()
            self._next_scan_time = self._last_scan_time + timedelta(minutes=self.interval_minutes)
            self._scan_count += 1

            # Используем callback для новых предметов если есть, иначе обычный scan
            if self.new_items_callback:
                self.new_items_callback(max_items=self.new_items_count)
            else:
                self.scan_callback()

            logger.info(f"Auto scan #{self._scan_count} completed. Next scan at {self._next_scan_time.strftime('%H:%M:%S')}")

        except Exception as e:
            logger.error(f"Error performing auto scan: {e}", exc_info=True)

    def set_interval(self, minutes: int):
        """
        Изменить интервал сканирования новых предметов.

        Args:
            minutes: Новый интервал в минутах
        """
        old_interval = self.interval_minutes
        self.interval_minutes = minutes

        # Пересчитываем время следующего сканирования
        if self._last_scan_time:
            self._next_scan_time = self._last_scan_time + timedelta(minutes=minutes)

        logger.info(f"Scan interval changed: {old_interval} → {minutes} minutes")

    def set_rescan_interval(self, minutes: int):
        """
        Изменить интервал пересканирования существующих предметов.

        Args:
            minutes: Новый интервал в минутах
        """
        old_interval = self.rescan_interval_minutes
        self.rescan_interval_minutes = minutes

        # Пересчитываем время следующего пересканирования
        if self._last_rescan_time:
            self._next_rescan_time = self._last_rescan_time + timedelta(minutes=minutes)

        logger.info(f"Rescan interval changed: {old_interval} → {minutes} minutes")

    def set_new_items_count(self, count: int):
        """
        Изменить количество новых предметов для сканирования.

        Args:
            count: Новое количество
        """
        self.new_items_count = count
        logger.info(f"New items count set to: {count}")

    def get_status(self) -> dict:
        """
        Получить статус автосканера.

        Returns:
            Dict со статусом
        """
        return {
            'enabled': self.enabled,
            'interval_minutes': self.interval_minutes,
            'rescan_interval_minutes': self.rescan_interval_minutes,
            'new_items_count': self.new_items_count,
            'scan_count': self._scan_count,
            'rescan_count': self._rescan_count,
            'last_scan_time': self._last_scan_time.isoformat() if self._last_scan_time else None,
            'last_rescan_time': self._last_rescan_time.isoformat() if self._last_rescan_time else None,
            'next_scan_time': self._next_scan_time.isoformat() if self._next_scan_time else None,
            'next_rescan_time': self._next_rescan_time.isoformat() if self._next_rescan_time else None,
            'time_until_next_scan': self._get_time_until_next_scan(),
            'time_until_next_rescan': self._get_time_until_next_rescan()
        }

    def _get_time_until_next_scan(self) -> Optional[int]:
        """Получить секунды до следующего сканирования."""
        if not self._next_scan_time:
            return None

        delta = self._next_scan_time - datetime.now()
        return max(0, int(delta.total_seconds()))

    def _get_time_until_next_rescan(self) -> Optional[int]:
        """Получить секунды до следующего пересканирования."""
        if not self._next_rescan_time:
            return None

        delta = self._next_rescan_time - datetime.now()
        return max(0, int(delta.total_seconds()))

    def is_running(self) -> bool:
        """Проверить, запущен ли автосканер."""
        return self.enabled and self._thread and self._thread.is_alive()
