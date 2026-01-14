"""
Парсинг баланса Steam через торговую площадку (Community Market)
Это часто работает лучше, чем store.steampowered.com
"""

import re
import json
import requests
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup


class SteamMarketScraper:
    """Скрапер баланса с торговой площадки Steam"""

    # Валюты Steam
    CURRENCIES = {
        '₽': 'RUB', 'pуб': 'RUB', 'руб': 'RUB',
        '$': 'USD', 'USD': 'USD',
        '€': 'EUR', 'EUR': 'EUR',
        '£': 'GBP', 'GBP': 'GBP',
        '¥': 'JPY', 'JPY': 'JPY',
        'CDN$': 'CAD', 'A$': 'AUD', 'R$': 'BRL',
        '₴': 'UAH', 'kr': 'SEK', 'zł': 'PLN',
        '₹': 'INR', 'CHF': 'CHF', '元': 'CNY',
        '฿': 'THB', '₩': 'KRW',
    }

    def __init__(self, cookies: Dict[str, str], proxy: Optional[str] = None):
        """
        Инициализация

        Args:
            cookies: Словарь с cookies (sessionid и/или steamLoginSecure)
            proxy: Прокси сервер
        """
        self.session = requests.Session()

        # Устанавливаем cookies
        for name, value in cookies.items():
            # Устанавливаем для разных доменов
            self.session.cookies.set(name, value, domain='.steampowered.com')
            self.session.cookies.set(name, value, domain='.steamcommunity.com')

        if proxy:
            self.session.proxies = {
                'http': proxy,
                'https': proxy
            }

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        })

    def get_balance(self) -> Dict:
        """
        Получает баланс с торговой площадки

        Returns:
            Dict с результатом
        """
        # Пробуем разные методы
        methods = [
            self._from_market_home,
            self._from_market_listings,
            self._from_inventory,
            self._from_wallet_api,
        ]

        for method in methods:
            result = method()
            if result['success']:
                return result

        return {
            'success': False,
            'error': 'Could not get balance from market'
        }

    def _from_market_home(self) -> Dict:
        """Парсит с главной страницы торговой площадки"""
        try:
            url = 'https://steamcommunity.com/market/'
            response = self.session.get(url, timeout=15)

            if 'login' in response.url.lower():
                return {'success': False, 'error': 'Not authorized'}

            # Метод 1: JavaScript переменная g_rgWalletInfo
            wallet_match = re.search(r'g_rgWalletInfo\s*=\s*({[^}]+})', response.text)
            if wallet_match:
                try:
                    # Очищаем JS объект и парсим как JSON
                    wallet_str = wallet_match.group(1)
                    # Заменяем одинарные кавычки на двойные
                    wallet_str = wallet_str.replace("'", '"')
                    wallet_data = json.loads(wallet_str)

                    if 'wallet_balance' in wallet_data:
                        balance_cents = int(wallet_data['wallet_balance'])
                        currency_code = wallet_data.get('wallet_currency', 1)

                        # Конвертируем центы в основную валюту
                        balance = balance_cents / 100.0

                        # Определяем валюту по коду
                        currency = self._currency_code_to_name(currency_code)

                        return {
                            'success': True,
                            'balance': balance,
                            'currency': currency,
                            'raw_balance': f'{balance} {currency}',
                            'method': 'market_home_js_var'
                        }
                except Exception as e:
                    print(f"Error parsing g_rgWalletInfo: {e}")

            # Метод 2: HTML элемент с балансом
            soup = BeautifulSoup(response.text, 'html.parser')

            # Ищем элемент с балансом
            balance_elem = soup.find('span', {'id': 'marketWalletBalanceAmount'})
            if balance_elem:
                balance_text = balance_elem.get_text(strip=True)
                balance, currency = self._parse_balance_string(balance_text)

                return {
                    'success': True,
                    'balance': balance,
                    'currency': currency,
                    'raw_balance': balance_text,
                    'method': 'market_home_html'
                }

            # Метод 3: Ищем любое упоминание кошелька
            wallet_patterns = [
                r'wallet.*?balance.*?([0-9\s,.]+)\s*([₽$€£¥])',
                r'([₽$€£¥])\s*([0-9\s,.]+)',
                r'balance.*?([0-9\s,.]+)\s*([A-Z]{3})',
            ]

            for pattern in wallet_patterns:
                matches = re.findall(pattern, response.text, re.IGNORECASE)
                if matches:
                    for match in matches:
                        if len(match) >= 2:
                            # Пытаемся распарсить
                            balance_str = f"{match[0]} {match[1]}"
                            balance, currency = self._parse_balance_string(balance_str)
                            if currency != 'UNKNOWN':
                                return {
                                    'success': True,
                                    'balance': balance,
                                    'currency': currency,
                                    'raw_balance': balance_str,
                                    'method': 'market_home_regex'
                                }

        except Exception as e:
            print(f"Market home error: {e}")

        return {'success': False}

    def _from_market_listings(self) -> Dict:
        """Парсит со страницы листингов"""
        try:
            # Берем любой популярный предмет для примера
            url = 'https://steamcommunity.com/market/listings/730/AK-47%20|%20Redline%20(Field-Tested)'
            response = self.session.get(url, timeout=15)

            if 'login' not in response.url.lower():
                # Ищем баланс на странице
                balance_match = re.search(r'wallet_balance["\']?\s*:\s*(\d+)', response.text)
                currency_match = re.search(r'wallet_currency["\']?\s*:\s*(\d+)', response.text)

                if balance_match:
                    balance_cents = int(balance_match.group(1))
                    balance = balance_cents / 100.0

                    currency_code = int(currency_match.group(1)) if currency_match else 1
                    currency = self._currency_code_to_name(currency_code)

                    return {
                        'success': True,
                        'balance': balance,
                        'currency': currency,
                        'raw_balance': f'{balance} {currency}',
                        'method': 'market_listings'
                    }

        except Exception as e:
            print(f"Market listings error: {e}")

        return {'success': False}

    def _from_inventory(self) -> Dict:
        """Парсит из инвентаря"""
        try:
            url = 'https://steamcommunity.com/my/inventory/'
            response = self.session.get(url, timeout=15)

            if 'login' not in response.url.lower():
                # Ищем g_rgWalletInfo
                wallet_match = re.search(r'g_rgWalletInfo\s*=\s*({[^}]+})', response.text)
                if wallet_match:
                    wallet_str = wallet_match.group(1).replace("'", '"')
                    try:
                        wallet_data = json.loads(wallet_str)
                        balance_cents = int(wallet_data.get('wallet_balance', 0))
                        balance = balance_cents / 100.0
                        currency_code = wallet_data.get('wallet_currency', 1)
                        currency = self._currency_code_to_name(currency_code)

                        return {
                            'success': True,
                            'balance': balance,
                            'currency': currency,
                            'raw_balance': f'{balance} {currency}',
                            'method': 'inventory'
                        }
                    except:
                        pass

        except Exception as e:
            print(f"Inventory error: {e}")

        return {'success': False}

    def _from_wallet_api(self) -> Dict:
        """Пробует через внутренний API кошелька"""
        try:
            url = 'https://steamcommunity.com/my/ajaxgetwalletinfo'
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if 'wallet_balance' in data:
                    balance_cents = int(data['wallet_balance'])
                    balance = balance_cents / 100.0
                    currency_code = data.get('wallet_currency', 1)
                    currency = self._currency_code_to_name(currency_code)

                    return {
                        'success': True,
                        'balance': balance,
                        'currency': currency,
                        'raw_balance': f'{balance} {currency}',
                        'method': 'wallet_api'
                    }

        except Exception as e:
            print(f"Wallet API error: {e}")

        return {'success': False}

    def _parse_balance_string(self, balance_str: str) -> Tuple[float, str]:
        """Парсит строку баланса"""
        if not balance_str:
            return 0.0, 'UNKNOWN'

        # Определяем валюту
        currency = 'UNKNOWN'
        for symbol, code in self.CURRENCIES.items():
            if symbol in balance_str:
                currency = code
                break

        # Извлекаем число
        cleaned = balance_str
        for symbol in self.CURRENCIES.keys():
            cleaned = cleaned.replace(symbol, '')

        cleaned = re.sub(r'[^\d.,\-]', '', cleaned)

        if ',' in cleaned:
            parts = cleaned.split(',')
            if len(parts) == 2 and len(parts[1]) <= 2:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')

        cleaned = cleaned.replace(' ', '').replace('\xa0', '')

        try:
            balance = float(cleaned)
            return balance, currency
        except ValueError:
            return 0.0, currency

    def _currency_code_to_name(self, code: int) -> str:
        """Конвертирует код валюты Steam в название"""
        currency_map = {
            1: 'USD', 2: 'GBP', 3: 'EUR', 4: 'CHF', 5: 'RUB',
            6: 'PLN', 7: 'BRL', 8: 'JPY', 9: 'SEK', 10: 'IDR',
            11: 'MYR', 12: 'PHP', 13: 'SGD', 14: 'THB', 15: 'VND',
            16: 'KRW', 17: 'TRY', 18: 'UAH', 19: 'MXN', 20: 'CAD',
            21: 'AUD', 22: 'NZD', 23: 'CNY', 24: 'INR', 25: 'CLP',
            26: 'PEN', 27: 'COP', 28: 'ZAR', 29: 'HKD', 30: 'TWD',
        }
        return currency_map.get(code, 'USD')


def test_market_scraper():
    """Тест скрапера с торговой площадки"""
    print("=" * 70)
    print("ТЕСТ: Парсинг баланса с торговой площадки Steam")
    print("=" * 70)
    print()

    # Загружаем cookies
    cookies_files = ['steam_cookies_full.json', 'steam_cookies.json']
    cookies = None

    for filename in cookies_files:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
                print(f"[OK] Загружены cookies из {filename}")
                break
        except FileNotFoundError:
            print(f"  Файл {filename} не найден")
            continue
        except Exception as e:
            print(f"  Ошибка чтения {filename}: {e}")
            continue

    if not cookies:
        print("[X] Файл с cookies не найден!")
        print("  Создайте steam_cookies.json с sessionid")
        return

    # Получаем прокси
    proxy = None
    try:
        with open('accounts.json', 'r') as f:
            accounts = json.load(f)
            proxy = accounts[0].get('proxy')
    except:
        pass

    print()
    print("-" * 70)
    print()

    # Создаем скрапер
    scraper = SteamMarketScraper(cookies, proxy)

    print("Получение баланса с торговой площадки...")
    result = scraper.get_balance()

    print()
    print("=" * 70)
    print("РЕЗУЛЬТАТ")
    print("=" * 70)
    print()

    if result['success']:
        print("[SUCCESS]")
        print()
        print(f"  Balance:    {result['balance']} {result['currency']}")
        print(f"  Raw:        {result['raw_balance']}")
        print(f"  Method:     {result['method']}")
        print()
        print("Parsing from market works!")
    else:
        print("[ERROR]")
        print(f"  {result.get('error')}")

    print()
    print("=" * 70)


if __name__ == '__main__':
    test_market_scraper()
