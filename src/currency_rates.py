"""
Модуль для получения актуальных курсов валют.
Использует несколько источников с кешированием на 24 часа.
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional
import requests

from src.logger import get_logger

logger = get_logger(__name__)

# Кеш файл для курсов валют
CACHE_FILE = Path("data/currency_rates_cache.json")
CACHE_TTL = 24 * 60 * 60  # 24 часа в секундах


class CurrencyRatesProvider:
    """Провайдер курсов валют с кешированием."""

    # Коды валют Steam
    STEAM_CURRENCIES = {
        1: 'USD',
        3: 'EUR',
        5: 'RUB',
        18: 'UAH',
        19: 'TRY',
        23: 'BRL',
        25: 'CNY',
        36: 'BYN',
        37: 'KZT',
    }

    def __init__(self):
        """Инициализация провайдера."""
        self.cache_file = CACHE_FILE
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._rates_cache: Optional[Dict] = None
        self._cache_timestamp: float = 0

    def get_rates(self) -> Dict[str, float]:
        """
        Получить курсы валют (1 USD = X валюты).

        Returns:
            Dict с курсами: {'RUB': 95.5, 'EUR': 0.92, 'UAH': 41.0, ...}
        """
        # Проверяем кеш в памяти
        if self._rates_cache and (time.time() - self._cache_timestamp) < CACHE_TTL:
            logger.debug("Using in-memory currency rates cache")
            return self._rates_cache

        # Проверяем кеш в файле
        cached_rates = self._load_from_cache()
        if cached_rates:
            logger.info("Loaded currency rates from file cache")
            self._rates_cache = cached_rates
            self._cache_timestamp = time.time()
            return cached_rates

        # Загружаем свежие курсы
        logger.info("Fetching fresh currency rates...")
        rates = self._fetch_rates()

        if rates:
            self._save_to_cache(rates)
            self._rates_cache = rates
            self._cache_timestamp = time.time()
            logger.info(f"Currency rates updated: {rates}")
            return rates

        # Fallback: используем статические курсы
        logger.warning("Failed to fetch currency rates, using fallback static rates")
        return self._get_fallback_rates()

    def _load_from_cache(self) -> Optional[Dict[str, float]]:
        """Загрузить курсы из файла кеша."""
        try:
            if not self.cache_file.exists():
                return None

            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            timestamp = data.get('timestamp', 0)
            rates = data.get('rates', {})

            # Проверяем актуальность
            if time.time() - timestamp < CACHE_TTL and rates:
                return rates

            return None

        except Exception as e:
            logger.error(f"Failed to load currency cache: {e}")
            return None

    def _save_to_cache(self, rates: Dict[str, float]):
        """Сохранить курсы в файл кеша."""
        try:
            data = {
                'timestamp': time.time(),
                'rates': rates,
            }

            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Currency rates saved to cache: {self.cache_file}")

        except Exception as e:
            logger.error(f"Failed to save currency cache: {e}")

    def _fetch_rates(self) -> Optional[Dict[str, float]]:
        """
        Получить актуальные курсы валют из API.

        Пробует несколько источников и объединяет их для лучшего покрытия валют.
        """
        # Источник 1: Steam rates API (официальные курсы Steam для основных валют)
        steam_rates = self._fetch_from_steam_rates()

        # Источник 2: exchangerate-api.com (широкое покрытие валют, включая BYN, TRY)
        exchange_rates = self._fetch_from_exchangerate_api()

        # Если Steam rates успешно загрузился, дополняем недостающие из exchangerate-api
        if steam_rates:
            # Дополняем курсы из exchangerate-api для валют, которых нет в Steam API
            if exchange_rates:
                for currency in ['BYN', 'TRY', 'KZT', 'UAH', 'BRL', 'CNY']:
                    # Если в Steam rates это статическое значение, заменяем на exchangerate
                    if currency in exchange_rates:
                        # Проверяем - если это статический fallback, то заменяем
                        static_fallback = {'TRY': 34.0, 'BYN': 3.2}
                        if currency in static_fallback:
                            if abs(steam_rates.get(currency, 0) - static_fallback[currency]) < 0.01:
                                steam_rates[currency] = exchange_rates[currency]

                logger.info(f"Enhanced Steam rates with exchangerate-api data")
            return steam_rates

        # Если Steam rates не сработал, используем exchangerate-api
        if exchange_rates:
            return exchange_rates

        # Источник 3: ЦБ РФ API (для RUB) - последний fallback
        cbr_rates = self._fetch_from_cbr()
        if cbr_rates:
            return cbr_rates

        return None

    def _fetch_from_steam_rates(self) -> Optional[Dict[str, float]]:
        """
        Получить курсы с Steam rates API (официальные курсы Steam).

        API возвращает курсы между парами валют.
        """
        try:
            url = "https://steam-rates.playwallet.bot/latest-rate/"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list):
                logger.warning(f"Steam rates API returned unexpected format: {type(data)}")
                return None

            # Строим словарь курсов относительно USD
            rates = {'USD': 1.0}

            # Парсим ВСЕ пары валют из API
            usd_rates = {}  # Курсы USD -> X
            reverse_rates = {}  # Курсы X -> USD (для обратного расчёта)

            for rate_info in data:
                currency = rate_info.get('currency_code')
                base_currency = rate_info.get('base_currency_code')
                exchange_rate = rate_info.get('exchange_rate')

                if not currency or not base_currency or not exchange_rate:
                    continue

                # USD -> Currency
                if base_currency == 'USD':
                    usd_rates[currency] = exchange_rate
                # Currency -> USD (для обратного расчёта)
                elif currency == 'USD':
                    reverse_rates[base_currency] = exchange_rate

            # Для каждой валюты пробуем найти прямой или обратный курс
            for curr in ['RUB', 'EUR', 'UAH', 'TRY', 'BRL', 'CNY', 'BYN', 'KZT']:
                if curr in usd_rates:
                    rates[curr] = usd_rates[curr]
                elif curr in reverse_rates:
                    rates[curr] = 1.0 / reverse_rates[curr]

            # Проверяем что есть хотя бы RUB (основная валюта)
            if 'RUB' not in rates:
                logger.warning("Steam rates API: USD->RUB rate not found")
                return None

            # Дополняем статическими курсами для валют, которых нет в API
            static_fallback = {
                'UAH': 41.0,
                'TRY': 34.0,
                'BRL': 5.0,
                'CNY': 7.2,
                'BYN': 3.2,
                'KZT': 480.0,
            }

            for curr, fallback_rate in static_fallback.items():
                if curr not in rates:
                    rates[curr] = fallback_rate

            logger.info(f"Fetched rates from Steam rates API: {rates}")
            return rates

        except Exception as e:
            logger.error(f"Failed to fetch from Steam rates API: {e}")
            return None

    def _fetch_from_exchangerate_api(self) -> Optional[Dict[str, float]]:
        """
        Получить курсы с exchangerate-api.com.

        API возвращает курсы относительно USD.
        """
        try:
            url = "https://open.er-api.com/v6/latest/USD"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('result') != 'success':
                logger.warning(f"exchangerate-api returned error: {data}")
                return None

            conversion_rates = data.get('rates', {})

            # Извлекаем нужные валюты
            rates = {}
            for currency_code in ['RUB', 'EUR', 'UAH', 'TRY', 'BRL', 'CNY', 'BYN', 'KZT']:
                if currency_code in conversion_rates:
                    rates[currency_code] = conversion_rates[currency_code]

            # USD = 1.0
            rates['USD'] = 1.0

            logger.info(f"Fetched rates from exchangerate-api: {rates}")
            return rates

        except Exception as e:
            logger.error(f"Failed to fetch from exchangerate-api: {e}")
            return None

    def _fetch_from_cbr(self) -> Optional[Dict[str, float]]:
        """
        Получить курсы с ЦБ РФ (для RUB).

        Дополняет данными из статических курсов.
        """
        try:
            url = "https://www.cbr-xml-daily.ru/daily_json.js"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            valute = data.get('Valute', {})

            # USD -> RUB
            usd_data = valute.get('USD', {})
            usd_to_rub = usd_data.get('Value', 95.0)

            # EUR -> RUB
            eur_data = valute.get('EUR', {})
            eur_to_rub = eur_data.get('Value', 103.0)

            # Рассчитываем курсы относительно USD
            rates = {
                'USD': 1.0,
                'RUB': usd_to_rub,
                'EUR': eur_to_rub / usd_to_rub,  # EUR в USD
                'UAH': 41.0,  # Статический
                'TRY': 34.0,  # Статический
                'BRL': 5.0,   # Статический
                'CNY': 7.2,   # Статический
                'BYN': 3.2,   # Статический
                'KZT': 480.0, # Статический
            }

            logger.info(f"Fetched rates from CBR: RUB={usd_to_rub:.2f}")
            return rates

        except Exception as e:
            logger.error(f"Failed to fetch from CBR: {e}")
            return None

    def _get_fallback_rates(self) -> Dict[str, float]:
        """
        Статические курсы (fallback).

        Используется если все API недоступны.
        """
        return {
            'USD': 1.0,
            'EUR': 0.92,
            'RUB': 95.0,
            'UAH': 41.0,
            'TRY': 34.0,
            'BRL': 5.0,
            'CNY': 7.2,
            'BYN': 3.2,
            'KZT': 480.0,
        }

    def convert_rub_to_currency(self, amount_rub: float, currency_code: str) -> float:
        """
        Конвертировать рубли в другую валюту.

        Args:
            amount_rub: Сумма в рублях
            currency_code: Код валюты Steam (1=USD, 3=EUR, 5=RUB, etc.)

        Returns:
            Сумма в целевой валюте
        """
        # Получаем название валюты
        currency_name = self.STEAM_CURRENCIES.get(int(currency_code), 'USD')

        # Для рублей возвращаем как есть
        if currency_name == 'RUB':
            return amount_rub

        # Получаем актуальные курсы
        rates = self.get_rates()

        # RUB -> USD -> Target Currency
        rub_to_usd = 1.0 / rates.get('RUB', 95.0)
        amount_usd = amount_rub * rub_to_usd

        usd_to_target = rates.get(currency_name, 1.0)
        amount_target = amount_usd * usd_to_target

        logger.debug(
            f"Converted {amount_rub:.2f} RUB -> {amount_target:.2f} {currency_name} "
            f"(via USD, rates: RUB={rates.get('RUB'):.2f}, {currency_name}={usd_to_target:.2f})"
        )

        return amount_target

    def convert_to_rub(self, amount: float, currency_code: str) -> float:
        """
        Конвертировать из любой валюты в рубли.

        Args:
            amount: Сумма в исходной валюте
            currency_code: Код валюты ('USD', 'EUR', 'RUB', etc.)

        Returns:
            Сумма в рублях
        """
        # Для рублей возвращаем как есть
        if currency_code == 'RUB':
            return amount

        # Получаем актуальные курсы
        rates = self.get_rates()

        # Source Currency -> USD -> RUB
        source_to_usd = 1.0 / rates.get(currency_code, 1.0)
        amount_usd = amount * source_to_usd

        usd_to_rub = rates.get('RUB', 95.0)
        amount_rub = amount_usd * usd_to_rub

        logger.debug(
            f"Converted {amount:.2f} {currency_code} -> {amount_rub:.2f} RUB "
            f"(via USD, rates: {currency_code}={rates.get(currency_code, 1.0):.2f}, RUB={usd_to_rub:.2f})"
        )

        return amount_rub


# Глобальный экземпляр провайдера
_currency_provider: Optional[CurrencyRatesProvider] = None


def get_currency_provider() -> CurrencyRatesProvider:
    """Получить глобальный экземпляр провайдера курсов валют."""
    global _currency_provider
    if _currency_provider is None:
        _currency_provider = CurrencyRatesProvider()
    return _currency_provider


def convert_rub_to_currency(amount_rub: float, steam_currency_code: int) -> float:
    """
    Удобная функция для конвертации рублей в валюту Steam.

    Args:
        amount_rub: Сумма в рублях
        steam_currency_code: Код валюты Steam (1=USD, 3=EUR, 5=RUB, etc.)

    Returns:
        Сумма в целевой валюте
    """
    provider = get_currency_provider()
    return provider.convert_rub_to_currency(amount_rub, steam_currency_code)
