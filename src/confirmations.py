"""
Steam Mobile Confirmations handler.

Automatically confirms market listings and trade offers using identity_secret.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class ConfirmationType(Enum):
    """Types of confirmations."""
    TRADE = 2  # Trade offer
    MARKET = 3  # Market listing/buy order
    PHONE_VERIFICATION = 1  # Generic confirmation
    UNKNOWN = 0


@dataclass
class ConfirmationInfo:
    """Information about a confirmation."""
    id: str
    key: str  # Nonce/key for confirmation
    conf_type: int  # Type ID (1=generic, 2=trade, 3=market, 12=buy order)
    type_name: str  # Human readable type
    headline: str  # Description
    summary: str  # Additional info


class ConfirmationHandler:
    """
    Handler for Steam Mobile Confirmations.

    Uses identity_secret to automatically accept/deny confirmations
    for market listings and trade offers.
    """

    CHECK_INTERVAL = 10  # Seconds between confirmation checks

    def __init__(self, steam_client):
        """
        Initialize confirmation handler.

        Args:
            steam_client: Logged in SteamClient instance
        """
        self._steam_client = steam_client
        self._identity_secret = getattr(settings, 'steam_identity_secret', None)
        self._steam_id = None

    def _get_steam_id(self) -> str:
        """Get Steam ID from logged in client."""
        if self._steam_id:
            return self._steam_id

        # Get from steam_client attributes
        if hasattr(self._steam_client, 'steamid') and self._steam_client.steamid:
            self._steam_id = str(self._steam_client.steamid)
        elif hasattr(self._steam_client, '_steamid') and self._steam_client._steamid:
            self._steam_id = str(self._steam_client._steamid)

        return self._steam_id

    def get_confirmations(self) -> list[ConfirmationInfo]:
        """
        Get all pending confirmations.

        Returns:
            List of ConfirmationInfo objects
        """
        try:
            self._steam_client.ensure_logged_in()

            # Get identity_secret and steamid
            identity_secret = self._identity_secret or self._steam_client.identity_secret
            steamid = self._get_steam_id() or str(self._steam_client.steamid)

            if not identity_secret:
                logger.error("identity_secret not set, cannot get confirmations")
                return []

            if not steamid:
                logger.error("steamid not set, cannot get confirmations")
                return []

            # Use steam_client's get_confirmations method
            confirmations = self._steam_client.get_confirmations(identity_secret, steamid)

            result = []
            for conf in confirmations:
                conf_type = conf.get('type', 0)
                type_name = conf.get('type_name', 'Unknown')

                result.append(ConfirmationInfo(
                    id=conf['id'],
                    key=conf['key'],
                    conf_type=conf_type,
                    type_name=type_name,
                    headline=conf.get('headline', 'N/A'),
                    summary=conf.get('summary', '')
                ))

            logger.info(f"Found {len(result)} pending confirmations")
            return result

        except Exception as e:
            logger.error(f"Failed to get confirmations: {e}")
            return []

    def confirm(self, confirmation: ConfirmationInfo) -> bool:
        """
        Accept a single confirmation.

        Args:
            confirmation: ConfirmationInfo to accept

        Returns:
            True if confirmed successfully
        """
        try:
            self._steam_client.ensure_logged_in()

            # Get identity_secret and steamid
            identity_secret = self._identity_secret or self._steam_client.identity_secret
            steamid = self._get_steam_id() or str(self._steam_client.steamid)

            if not identity_secret or not steamid:
                logger.error("identity_secret or steamid not set")
                return False

            # Use steam_client's confirm_market_transaction method
            result = self._steam_client.confirm_market_transaction(
                identity_secret, steamid, confirmation.id, confirmation.key
            )

            if result:
                logger.info(f"Confirmed: {confirmation.type_name} ({confirmation.id})")
            else:
                logger.warning(f"Failed to confirm: {confirmation.id}")

            return result

        except Exception as e:
            logger.error(f"Error confirming {confirmation.id}: {e}")
            return False

    def deny(self, confirmation: ConfirmationInfo) -> bool:
        """
        Deny/cancel a confirmation.

        Args:
            confirmation: ConfirmationInfo to deny

        Returns:
            True if denied successfully
        """
        # Note: Steam API doesn't have a dedicated deny endpoint
        # Confirmations expire automatically if not accepted
        logger.warning(f"Deny not implemented - confirmation {confirmation.id} will expire automatically")
        return False

    def confirm_all_market_listings(self) -> int:
        """
        Confirm all pending market listing confirmations.

        Returns:
            Number of confirmations accepted
        """
        try:
            self._steam_client.ensure_logged_in()

            # Get identity_secret and steamid
            identity_secret = self._identity_secret or self._steam_client.identity_secret
            steamid = self._get_steam_id() or str(self._steam_client.steamid)

            if not identity_secret or not steamid:
                logger.error("identity_secret or steamid not set")
                return 0

            # Use steam_client's confirm_all_market_transactions method
            confirmed = self._steam_client.confirm_all_market_transactions(identity_secret, steamid)

            logger.info(f"Confirmed {confirmed} market listings")
            return confirmed

        except Exception as e:
            logger.error(f"Error confirming market listings: {e}")
            return 0

    def confirm_all_trades(self) -> int:
        """
        Confirm all pending trade confirmations.

        Returns:
            Number of confirmations accepted
        """
        confirmations = self.get_confirmations()
        # Type 2 = trade offers
        trade_confs = [c for c in confirmations if c.conf_type == ConfirmationType.TRADE.value]

        confirmed = 0
        for conf in trade_confs:
            if self.confirm(conf):
                confirmed += 1
            time.sleep(1)  # Rate limiting

        logger.info(f"Confirmed {confirmed}/{len(trade_confs)} trades")
        return confirmed

    def confirm_all(self) -> dict:
        """
        Confirm all pending confirmations.

        Returns:
            Dict with counts by type
        """
        confirmations = self.get_confirmations()

        results = {
            "market": 0,
            "trade": 0,
            "other": 0,
            "failed": 0,
        }

        for conf in confirmations:
            success = self.confirm(conf)
            time.sleep(1)  # Rate limiting

            if success:
                # Check type by value
                if conf.conf_type in [3, 12]:  # Market/buy order types
                    results["market"] += 1
                elif conf.conf_type == 2:  # Trade
                    results["trade"] += 1
                else:
                    results["other"] += 1
            else:
                results["failed"] += 1

        total = sum(results.values()) - results["failed"]
        logger.info(f"Confirmed {total} confirmations (failed: {results['failed']})")

        return results

    def auto_confirm_loop(
        self,
        confirm_market: bool = True,
        confirm_trades: bool = True,
        interval: float = None
    ):
        """
        Run continuous confirmation loop.

        Args:
            confirm_market: Auto-confirm market listings
            confirm_trades: Auto-confirm trade offers
            interval: Seconds between checks (default: CHECK_INTERVAL)
        """
        interval = interval or self.CHECK_INTERVAL
        logger.info(f"Starting auto-confirm loop (interval: {interval}s)")

        while True:
            try:
                confirmations = self.get_confirmations()

                for conf in confirmations:
                    should_confirm = False

                    # Check by type value
                    if confirm_market and conf.conf_type in [3, 12]:  # Market/buy order
                        should_confirm = True
                    elif confirm_trades and conf.conf_type == 2:  # Trade
                        should_confirm = True

                    if should_confirm:
                        self.confirm(conf)
                        time.sleep(1)

            except Exception as e:
                logger.error(f"Error in confirm loop: {e}")

            time.sleep(interval)


def create_confirmation_handler(steam_client) -> ConfirmationHandler:
    """Factory function to create confirmation handler."""
    return ConfirmationHandler(steam_client)
