"""
DNS-совместимость для aiohttp на Windows.

Проблема: если установлен пакет `aiodns`, aiohttp по умолчанию использует AsyncResolver
(c-ares/pycares). На части Windows-конфигураций (в т.ч. Python 3.14) c-ares не может
прочитать список DNS-серверов и падает с ошибкой:

    Cannot connect to host steamcommunity.com:443 ssl:default [Could not contact DNS servers]

При этом обычный OS-резолвер (getaddrinfo) работает нормально. С socks5-прокси проблема
не проявлялась, т.к. хост резолвится удалённо на прокси; без прокси — прямое подключение
падает на этапе резолва DNS (ещё до HTTP-запроса, headers ни при чём).

Решение: заставить aiohttp использовать ThreadedResolver (OS getaddrinfo). Патч применяется
глобально и один раз; вызывать нужно ДО создания любых ClientSession.
"""

from src.logger import get_logger

logger = get_logger(__name__)

_applied = False


def apply_dns_compat() -> bool:
    """
    Переключить дефолтный резолвер aiohttp на ThreadedResolver (OS DNS).

    Returns:
        True если патч применён (или уже был применён), False при ошибке.
    """
    global _applied
    if _applied:
        return True

    try:
        import aiohttp.resolver as _resolver
        import aiohttp.connector as _connector
        from aiohttp.resolver import ThreadedResolver

        current = getattr(_resolver, "DefaultResolver", None)
        if current is ThreadedResolver:
            _applied = True
            return True

        # aiohttp читает DefaultResolver из обоих namespace при создании коннектора
        _resolver.DefaultResolver = ThreadedResolver
        _connector.DefaultResolver = ThreadedResolver
        _applied = True
        logger.info(
            "DNS compat: aiohttp переключён на ThreadedResolver (OS DNS) вместо aiodns/c-ares"
        )
        return True
    except Exception as e:
        logger.warning(f"DNS compat: не удалось применить фикс резолвера: {e}")
        return False


# Применяем сразу при импорте модуля
apply_dns_compat()
