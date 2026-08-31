"""
Steam Mobile Confirmations handler.

Тонкая ASYNC-обёртка над aiosteampy ConfirmationMixin. Подтверждения выполняются через
identity_secret, установленный на клиенте (из maFile). Для аккаунтов БЕЗ identity_secret
подтверждение делается вручную в Steam Mobile Guard (см. manual_confirmation.py).

ВАЖНО: раньше этот модуль вызывал методы steampy/python-steam
(get_confirmations(identity_secret, steamid), confirm_market_transaction, ...),
которых НЕТ у aiosteampy-клиента → все вызовы молча падали в except и возвращали 0.
Теперь используется нативный aiosteampy API: get_confirmations() / allow_all_confirmations()
/ allow_confirmation().
"""

import asyncio
from typing import List

from src.logger import get_logger

logger = get_logger(__name__)

# Типы подтверждений — значения из aiosteampy.constants.ConfirmationType
CONF_TYPE_UNKNOWN = 1
CONF_TYPE_TRADE = 2
CONF_TYPE_LISTING = 3
CONF_TYPE_API_KEY = 4
CONF_TYPE_PURCHASE = 12

# Всё, что относится к маркету (листинг на продажу + покупка/ордер)
MARKET_CONF_TYPES = {CONF_TYPE_LISTING, CONF_TYPE_PURCHASE}


class ConfirmationHandler:
    """
    Обёртка над aiosteampy для работы с Steam Mobile Confirmations.

    Принимает SteamClientAio (обёртку); реальный aiosteampy-клиент — в `steam_client._client`.
    """

    def __init__(self, steam_client):
        """
        Args:
            steam_client: SteamClientAio (обёртка над aiosteampy)
        """
        self._wrapper = steam_client

    def _get_client(self):
        """Достать залогиненный aiosteampy-клиент с identity_secret или бросить понятную ошибку."""
        client = getattr(self._wrapper, "_client", None)
        if client is None:
            raise RuntimeError("aiosteampy client не инициализирован (не залогинен?)")
        if not getattr(client, "_identity_secret", None):
            raise RuntimeError(
                "identity_secret не задан — авто-подтверждение через maFile невозможно "
                "(нужно подтверждать вручную в Steam Mobile Guard)"
            )
        return client

    @staticmethod
    def _conf_type_value(conf) -> int:
        """Вернуть int-значение типа подтверждения из aiosteampy Confirmation."""
        t = getattr(conf, "type", None)
        return getattr(t, "value", t) if t is not None else CONF_TYPE_UNKNOWN

    async def get_confirmations(self) -> List:
        """Получить все ожидающие подтверждения (список aiosteampy Confirmation)."""
        client = self._get_client()
        # create_task — чтобы aiohttp timeout корректно работал в этом event loop
        confs = await asyncio.create_task(client.get_confirmations())
        logger.info(f"Found {len(confs)} pending confirmations")
        return confs

    async def allow(self, conf) -> bool:
        """Подтвердить (allow) одно подтверждение."""
        client = self._get_client()
        try:
            await asyncio.create_task(client.allow_confirmation(conf))
            logger.info(f"Confirmed: type={self._conf_type_value(conf)} id={getattr(conf, 'id', '?')}")
            return True
        except Exception as e:
            logger.error(f"Failed to allow confirmation {getattr(conf, 'id', conf)}: {e}")
            return False

    async def confirm_all(self) -> int:
        """
        Подтвердить ВСЕ ожидающие подтверждения одним запросом (allow_all_confirmations).

        Returns:
            Количество подтверждённых
        """
        client = self._get_client()
        try:
            confs = await asyncio.create_task(client.allow_all_confirmations())
            n = len(confs or [])
            logger.info(f"Allowed {n} confirmations (bulk)")
            return n
        except Exception as e:
            logger.error(f"Failed to allow all confirmations: {e}")
            return 0

    async def confirm_all_market_listings(self) -> int:
        """Подтвердить все маркет-подтверждения (листинги на продажу + покупки/ордера)."""
        return await self._confirm_by_types(MARKET_CONF_TYPES)

    async def confirm_all_trades(self) -> int:
        """Подтвердить все трейд-офферы."""
        return await self._confirm_by_types({CONF_TYPE_TRADE})

    async def _confirm_by_types(self, types: set) -> int:
        """Получить подтверждения, отфильтровать по типам и подтвердить по одному."""
        try:
            confs = await self.get_confirmations()
        except Exception as e:
            logger.error(f"Failed to fetch confirmations: {e}")
            return 0

        target = [c for c in confs if self._conf_type_value(c) in types]
        if not target:
            logger.debug(f"No confirmations to allow for types {types}")
            return 0

        confirmed = 0
        for conf in target:
            if await self.allow(conf):
                confirmed += 1
            await asyncio.sleep(1)  # rate limiting

        logger.info(f"Confirmed {confirmed}/{len(target)} confirmations (types={types})")
        return confirmed


def create_confirmation_handler(steam_client) -> ConfirmationHandler:
    """Factory function to create confirmation handler."""
    return ConfirmationHandler(steam_client)
