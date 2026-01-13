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

# Примерные курсы (будут обновляться из Steam API)
DEFAULT_RATES_TO_RUB = {
    'RUB': 1.0,
    'EUR': 110.0,   # ~110 руб за евро
    'USD': 100.0,   # ~100 руб за доллар
    'UAH': 2.7,     # ~2.7 руб за гривну
    'KZT': 0.21,    # ~0.21 руб за тенге
    'BYN': 31.0,    # ~31 руб за бел. рубль
}


class CurrencyConverter:
    """Конвертер валют с актуальными курсами Steam."""

    def __init__(self):
        self.rates_to_rub: Dict[str, float] = DEFAULT_RATES_TO_RUB.copy()
        self._last_update = None

    def update_rates_from_steam_prices(self, item_prices: Dict[str, Dict[str, float]]):
        """
        Обновить курсы на основе цен предмета в разных валютах.

        Args:
            item_prices: {'RUB': {'price': 1000}, 'EUR': {'price': 9.5}, ...}
        """
        try:
            if 'RUB' not in item_prices:
                return

            rub_price = item_prices['RUB'].get('price', 0)
            if rub_price <= 0:
                return

            for currency, data in item_prices.items():
                if currency == 'RUB':
                    continue

                foreign_price = data.get('price', 0)
                if foreign_price > 0:
                    # Вычисляем курс: сколько рублей за 1 единицу валюты
                    rate = rub_price / foreign_price
                    self.rates_to_rub[currency] = rate
                    logger.debug(f"Updated rate: 1 {currency} = {rate:.2f} RUB")

        except Exception as e:
            logger.error(f"Error updating currency rates: {e}")

    def convert_to_rub(self, amount: float, from_currency: str) -> float:
        """
        Конвертировать в рубли.

        Args:
            amount: Сумма в исходной валюте
            from_currency: Валюта (RUB, EUR, USD, ...)

        Returns:
            Сумма в рублях
        """
        if from_currency == 'RUB':
            return amount

        rate = self.rates_to_rub.get(from_currency, 1.0)
        return amount * rate

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

        rate = self.rates_to_rub.get(to_currency, 1.0)
        return amount_rub / rate

    def get_rate(self, currency: str) -> float:
        """Получить курс валюты к рублю."""
        return self.rates_to_rub.get(currency, 1.0)

    def get_steam_currency_code(self, currency: str) -> int:
        """Получить код валюты для Steam API."""
        return STEAM_CURRENCY_CODES.get(currency, 5)  # Default: RUB


# Глобальный экземпляр конвертера
currency_converter = CurrencyConverter()
