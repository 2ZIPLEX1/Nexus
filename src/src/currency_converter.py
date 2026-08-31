"""
Конвертер валют для Steam и CSGO.TM.

CSGO.TM всегда работает в RUB, Steam - в разных валютах.
Используем актуальные курсы Steam для конвертации.
"""
from typing import Dict, Optional
from src.logger import get_logger

logger = get_logger(__name__)

# Steam currency codes
STEAM_CURRENCY_CODES = {
    'RUB': 5,   # Российский рубль
    'EUR': 3,   # Евро
    'USD': 1,   # Доллар США
    'UAH': 18,  # Гривна
    'KZT': 37,  # Тенге
    'BYN': 36,  # Белорусский рубль
}


class CurrencyConverter:
    """Конвертер валют с актуальными курсами Steam (использует currency_rates.py)."""

    def __init__(self):
        # Используем currency_rates provider для получения актуальных курсов
        from src.currency_rates import get_currency_provider
        self._provider = get_currency_provider()
        self._last_update = None

    def update_rates_from_steam_prices(self, item_prices: Dict[str, Dict[str, float]]):
        """
        Обновить курсы на основе цен предмета в разных валютах.

        УСТАРЕЛО: Теперь используем currency_rates.py с автоматическим обновлением из Steam API.
        Метод оставлен для обратной совместимости, но ничего не делает.

        Args:
            item_prices: {'RUB': {'price': 1000}, 'EUR': {'price': 9.5}, ...}
        """
        # Ничего не делаем - курсы автоматически берутся из currency_rates
        pass

    def convert_to_rub(self, amount: float, from_currency: str) -> float:
        """
        Конвертировать в рубли.

        Args:
            amount: Сумма в исходной валюте
            from_currency: Валюта (RUB, EUR, USD, ...)

        Returns:
            Сумма в рублях
        """
        return self._provider.convert_to_rub(amount, from_currency)

    def convert_from_rub(self, amount_rub: float, to_currency: str) -> float:
        """
        Конвертировать из рублей в другую валюту.

        Args:
            amount_rub: Сумма в рублях
            to_currency: Целевая валюта

        Returns:
            Сумма в целевой валюте
        """
        if to_currency == 'RUB':
            return amount_rub

        # Делегируем в currency_rates provider (избегаем дублирования)
        # provider работает со Steam currency codes (1=USD, 3=EUR, 5=RUB)
        steam_code = self.get_steam_currency_code(to_currency)
        return self._provider.convert_rub_to_currency(amount_rub, steam_code)

    def get_rate(self, currency: str) -> float:
        """
        Получить курс валюты к рублю (сколько RUB за 1 единицу валюты).

        Например: get_rate('EUR') вернет ~90.7, что означает 1 EUR = 90.7 RUB
        """
        if currency == 'RUB':
            return 1.0

        # Используем провайдер для получения курсов (избегаем дублирования)
        # Конвертируем 1 единицу валюты в рубли
        return self._provider.convert_to_rub(1.0, currency)

    def get_steam_currency_code(self, currency: str) -> int:
        """Получить код валюты для Steam API."""
        return STEAM_CURRENCY_CODES.get(currency, 5)  # Default: RUB


# Глобальный экземпляр конвертера
currency_converter = CurrencyConverter()
