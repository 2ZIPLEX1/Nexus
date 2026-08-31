"""
Вспомогательные функции для создания HTTP сессий с proxy и стандартными headers.
Централизует логику создания сессий, чтобы избежать дублирования кода.
"""
import requests
from typing import Optional
from src.logger import get_logger

logger = get_logger(__name__)

# Стандартные браузерные headers для имитации реального браузера
DEFAULT_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}


def create_session_with_proxy(
    proxy_url: Optional[str] = None,
    add_browser_headers: bool = True
) -> requests.Session:
    """
    Создать requests.Session с proxy и стандартными headers.

    Args:
        proxy_url: URL прокси (например: 'http://user:pass@ip:port')
        add_browser_headers: Добавить ли стандартные браузерные headers

    Returns:
        Настроенная requests.Session
    """
    session = requests.Session()

    # Настройка proxy
    if proxy_url:
        session.proxies = {
            'http': proxy_url,
            'https': proxy_url,
        }
        logger.debug(f"Session created with proxy: {proxy_url}")
    else:
        logger.debug("Session created without proxy")

    # Добавляем браузерные headers
    if add_browser_headers:
        session.headers.update(DEFAULT_BROWSER_HEADERS)

    return session


def get_browser_headers() -> dict:
    """
    Получить стандартные браузерные headers.

    Returns:
        Словарь с headers
    """
    return DEFAULT_BROWSER_HEADERS.copy()
