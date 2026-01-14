"""
Получение баланса Steam
Использует cookies из steam_cookies.json для получения баланса
"""

import os
import json
from src.steam_market_scraper import SteamMarketScraper


def load_account_data(filepath='account.txt'):
    """Загружает данные аккаунта из файла"""
    if not os.path.exists(filepath):
        return None, "Файл account.txt не найден"

    data = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    data[key.strip()] = value.strip()

        username = data.get('STEAM_USERNAME')
        password = data.get('STEAM_PASSWORD')
        shared_secret = data.get('STEAM_SHARED_SECRET')
        proxy = data.get('PROXY')

        if not username or not password:
            return None, "STEAM_USERNAME или STEAM_PASSWORD не найдены в account.txt"

        return {
            'username': username,
            'password': password,
            'shared_secret': shared_secret,
            'proxy': proxy
        }, None

    except Exception as e:
        return None, f"Ошибка чтения файла: {e}"


def load_manual_cookies():
    """Load cookies from steam_cookies.json if exists"""
    import json
    import os

    if os.path.exists('steam_cookies.json'):
        try:
            with open('steam_cookies.json', 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            if cookies and 'sessionid' in cookies:
                return cookies, None
        except Exception as e:
            return None, f"Error reading steam_cookies.json: {e}"

    return None, "steam_cookies.json not found"


def main():
    """Основная функция"""
    print("=" * 70)
    print("STEAM BALANCE CHECKER")
    print("=" * 70)
    print()

    # Load cookies
    print("Loading cookies from steam_cookies.json...")
    cookies, error = load_manual_cookies()

    if error or not cookies:
        print(f"[X] Error: {error or 'No cookies found'}")
        print()
        print("=" * 70)
        print("PLEASE CREATE steam_cookies.json")
        print("=" * 70)
        print()
        print("You need to extract cookies from your browser:")
        print()
        print("1. Login to steamcommunity.com in browser")
        print("2. Press F12 -> Application -> Cookies")
        print("3. Copy 'sessionid' and 'steamLoginSecure' values")
        print("4. Create steam_cookies.json with format:")
        print('   {')
        print('     "sessionid": "your_sessionid",')
        print('     "steamLoginSecure": "your_steamLoginSecure"')
        print('   }')
        print()
        return

    print("[OK] Cookies loaded")
    print(f"  sessionid: {cookies.get('sessionid', 'N/A')[:20]}...")
    print(f"  steamLoginSecure: {'YES' if 'steamLoginSecure' in cookies else 'NO'}")
    print()

    # Load proxy from account.txt if exists
    proxy = None
    account, _ = load_account_data()
    if account and account.get('proxy'):
        proxy = account.get('proxy')
        print(f"Using proxy: {proxy}")
        print()

    # Get balance
    print("-" * 70)
    print("GETTING BALANCE...")
    print("-" * 70)
    print()

    scraper = SteamMarketScraper(cookies, proxy=proxy)
    result = scraper.get_balance()

    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)
    print()

    if result['success']:
        print("SUCCESS!")
        print()
        print(f"  Balance:  {result['balance']} {result['currency']}")
        print(f"  Raw:      {result['raw_balance']}")
        print(f"  Method:   {result['method']}")
    else:
        print("ERROR!")
        print()
        print(f"  Message: {result.get('error')}")
        print()
        print("If you see 'Not authorized' error:")
        print("  - Update cookies from browser")
        print("  - Make sure you're logged in to steamcommunity.com")

    print()
    print("=" * 70)


if __name__ == '__main__':
    main()
