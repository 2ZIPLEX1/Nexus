"""
market.csgo.com API client.

Provides methods to fetch:
- Item dictionary (names and IDs)
- Full history of item sales
- Price statistics
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

import aiohttp

from src.bottm.config import Currency, config

logger = logging.getLogger(__name__)


class ItemType(str, Enum):
    """CS:GO/CS2 item types."""
    WEAPON_SKIN = "weapon_skin"
    AGENT = "agent"
    KNIFE = "knife"
    GLOVES = "gloves"
    STICKER = "sticker"
    CASE = "case"
    KEY = "key"
    OTHER = "other"


@dataclass
class ItemPriceStats:
    """Price statistics for an item."""
    item_id: int
    market_hash_name: str
    min_price: dict[str, float] = field(default_factory=dict)
    max_price: dict[str, float] = field(default_factory=dict)
    average: dict[str, float] = field(default_factory=dict)
    average_7d: dict[str, float] = field(default_factory=dict)
    average_30d: dict[str, float] = field(default_factory=dict)
    sales_7d: dict[str, int] = field(default_factory=dict)
    sales_30d: dict[str, int] = field(default_factory=dict)
    history: list[tuple] = field(default_factory=list)  # [(timestamp, rub, usd, eur), ...]
    last_updated: int = 0


@dataclass
class ItemMarketPrice:
    """Current market prices for an item from prices/class_instance API."""
    class_instance: str  # e.g., "1434515088_0"
    market_hash_name: str
    price: float  # Current lowest sell price
    buy_order: float  # Highest buy order (instant sell price)
    avg_price: float  # Average price
    popularity_7d: int  # Sales in last 7 days


@dataclass
class ItemInfo:
    """Basic item information."""
    item_id: int
    market_hash_name: str
    item_type: ItemType = ItemType.OTHER


def detect_item_type(market_hash_name: str) -> ItemType:
    """Detect item type from market hash name."""
    name_lower = market_hash_name.lower()

    # Agents
    agent_keywords = [
        "agent", "operator", "guerrilla", "professional",
        "ground rebel", "elite crew", "seal frogman",
        "swat", "gendarmerie", "ksk", "sas", "fbi",
        "cmdr.", "lt. commander", "special agent",
        "the elite mr. muhlik", "vypa sista",
        "chem-haz capitaine", "chef d'escadron",
        "aspirant", "sous-lieutenant", "officer",
        "sir bloody", "street soldier", "safecracker",
        "enforcer", "slingshot", "dragomir", "rezan",
        "'the doctor'", "buckshot", "little kev",
        "getaway sally", "number k", "sir bloody",
        "1st lieutenant", "john 'van heansen'",
        "bio-haz specialist", "cbrn"
    ]
    if any(kw in name_lower for kw in agent_keywords):
        return ItemType.AGENT

    # Knives
    knife_keywords = [
        "knife", "karambit", "bayonet", "flip knife",
        "gut knife", "huntsman", "butterfly", "falchion",
        "bowie", "shadow daggers", "navaja", "stiletto",
        "talon", "ursus", "classic knife", "paracord",
        "survival knife", "nomad knife", "skeleton knife",
        "kukri"
    ]
    if any(kw in name_lower for kw in knife_keywords):
        return ItemType.KNIFE

    # Gloves
    glove_keywords = [
        "gloves", "hand wraps", "driver gloves",
        "moto gloves", "specialist gloves", "sport gloves",
        "hydra gloves", "bloodhound gloves"
    ]
    if any(kw in name_lower for kw in glove_keywords):
        return ItemType.GLOVES

    # Stickers
    if "sticker |" in name_lower:
        return ItemType.STICKER

    # Cases
    if "case" in name_lower and "hardened" not in name_lower:
        return ItemType.CASE

    # Keys
    if "key" in name_lower:
        return ItemType.KEY

    # Weapon skins - check for common weapon names
    weapon_keywords = [
        "ak-47", "m4a4", "m4a1-s", "awp", "usp-s", "glock-18",
        "desert eagle", "p250", "five-seven", "cz75", "tec-9",
        "dual berettas", "r8 revolver", "p2000", "mac-10",
        "mp9", "mp7", "mp5-sd", "ump-45", "pp-bizon", "p90",
        "famas", "galil ar", "aug", "sg 553", "ssg 08",
        "g3sg1", "scar-20", "nova", "xm1014", "mag-7",
        "sawed-off", "m249", "negev", "zeus"
    ]
    if any(kw in name_lower for kw in weapon_keywords):
        return ItemType.WEAPON_SKIN

    return ItemType.OTHER


class CSGOMarketAPI:
    """market.csgo.com API client."""

    BASE_URL = "https://market.csgo.com/api/v2"

    def __init__(self, currency: Currency = Currency.RUB, proxy: Optional[str] = None):
        self.currency = currency
        self.proxy = proxy  # Прокси в формате "socks5://user:pass@host:port"
        self._session: Optional[aiohttp.ClientSession] = None
        self._names_cache: dict[int, str] = {}  # item_id -> market_hash_name
        self._reverse_names_cache: dict[str, int] = {}  # market_hash_name -> item_id
        self._prices_cache: dict[str, ItemMarketPrice] = {}  # market_hash_name -> ItemMarketPrice
        self._session_lock = asyncio.Lock()  # Lock for thread-safe session operations

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                # Создаем connector с поддержкой прокси
                connector = None
                if self.proxy:
                    # Только host:port. Срез [:20] показывал начало user:pass —
                    # маскирующий фильтр логов такой обрезок уже не распознаёт.
                    logger.debug(f"Creating session with proxy: {self.proxy.split('@')[-1]}")
                    from aiohttp_socks import ProxyConnector
                    try:
                        connector = ProxyConnector.from_url(self.proxy)
                    except Exception as e:
                        logger.warning(f"Failed to create proxy connector: {e}, using direct connection")

                self._session = aiohttp.ClientSession(
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    },
                    connector=connector,
                    # Без явного таймаута aiohttp ждёт 5 минут: один зависший
                    # прокси из proxies.txt стопорил весь цикл сканирования.
                    timeout=aiohttp.ClientTimeout(total=30, connect=10),
                )
            return self._session

    async def close(self):
        """Close the session and wait for proper cleanup."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Wait for underlying connections to close
            await asyncio.sleep(0.25)

    async def load_names_dictionary(self) -> dict[int, str]:
        """
        Load the item names dictionary.

        Returns:
            Dict mapping item_id to market_hash_name
        """
        if self._names_cache:
            return self._names_cache

        session = await self._get_session()
        url = f"{self.BASE_URL}/dictionary/names.json"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to load names dictionary: {response.status}")
                    return {}

                response_data = await response.json()

                # Response format: {"success": true, "items": [{"id": "123", "hash_name": "..."}]}
                if not response_data.get("success"):
                    logger.error("API returned success=false")
                    return {}

                items = response_data.get("items", [])
                for item in items:
                    item_id = int(item["id"])
                    name = item["hash_name"]
                    self._names_cache[item_id] = name
                    self._reverse_names_cache[name] = item_id

                logger.info(f"Loaded {len(self._names_cache)} item names")
                return self._names_cache

        except Exception as e:
            logger.error(f"Failed to load names dictionary: {e}")
            return {}

    async def load_prices_with_buy_orders(self, force_reload: bool = False) -> dict[str, ItemMarketPrice]:
        """
        Load all item prices including buy orders from prices/class_instance API.

        This is the best source for:
        - Current sell price (price)
        - Instant sell price (buy_order) - highest buy order on market.csgo.com
        - Average price (avg_price)
        - Weekly popularity (popularity_7d)

        Returns:
            Dict mapping market_hash_name to ItemMarketPrice
        """
        if self._prices_cache and not force_reload:
            return self._prices_cache

        session = await self._get_session()
        url = f"{self.BASE_URL}/prices/class_instance/{self.currency.value}.json"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to load prices: {response.status}")
                    return {}

                response_data = await response.json()

                if not response_data.get("success"):
                    logger.error("Prices API returned success=false")
                    return {}

                items = response_data.get("items", {})

                # Same item can have multiple class_instances (different stickers, floats)
                # We need to aggregate: take lowest price, highest buy_order, sum popularity
                aggregated: dict[str, dict] = {}

                for class_instance, item_data in items.items():
                    try:
                        market_hash_name = item_data.get("market_hash_name", "")
                        if not market_hash_name:
                            continue

                        price = float(item_data.get("price", 0) or 0)
                        buy_order = float(item_data.get("buy_order", 0) or 0)
                        avg_price = float(item_data.get("avg_price", 0) or 0)
                        popularity = int(item_data.get("popularity_7d", 0) or 0)

                        if market_hash_name not in aggregated:
                            aggregated[market_hash_name] = {
                                "class_instance": class_instance,
                                "min_price": price if price > 0 else float('inf'),
                                "max_buy_order": buy_order,
                                "avg_price": avg_price,
                                "total_popularity": popularity,
                                "count": 1,
                            }
                        else:
                            agg = aggregated[market_hash_name]
                            # Take minimum sell price (best for buyer)
                            if price > 0 and price < agg["min_price"]:
                                agg["min_price"] = price
                                agg["class_instance"] = class_instance
                            # Take maximum buy order (best for instant sell)
                            if buy_order > agg["max_buy_order"]:
                                agg["max_buy_order"] = buy_order
                            # Sum popularity
                            agg["total_popularity"] += popularity
                            # Keep avg_price if we don't have one yet
                            if agg["avg_price"] == 0 and avg_price > 0:
                                agg["avg_price"] = avg_price
                            agg["count"] += 1

                    except (ValueError, TypeError) as e:
                        logger.debug(f"Skipping item {class_instance}: {e}")
                        continue

                # Convert aggregated data to ItemMarketPrice
                for market_hash_name, agg in aggregated.items():
                    self._prices_cache[market_hash_name] = ItemMarketPrice(
                        class_instance=agg["class_instance"],
                        market_hash_name=market_hash_name,
                        price=agg["min_price"] if agg["min_price"] != float('inf') else 0,
                        buy_order=agg["max_buy_order"],
                        avg_price=agg["avg_price"],
                        popularity_7d=agg["total_popularity"],
                    )

                logger.info(f"Loaded {len(self._prices_cache)} unique items from {len(items)} listings")
                return self._prices_cache

        except Exception as e:
            logger.error(f"Failed to load prices: {e}")
            return {}

    def get_item_price(self, market_hash_name: str) -> Optional[ItemMarketPrice]:
        """Get cached price data for an item."""
        return self._prices_cache.get(market_hash_name)

    async def get_item_history(self, item_id: int) -> Optional[ItemPriceStats]:
        """
        Get full price history for an item.

        Args:
            item_id: Item ID from names dictionary

        Returns:
            ItemPriceStats with all price data
        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/full-history/{item_id}.json"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to get history for item {item_id}: {response.status}")
                    return None

                result = await response.json()
                data = result.get("data", {})

                market_hash_name = self._names_cache.get(item_id, f"Unknown_{item_id}")

                return ItemPriceStats(
                    item_id=item_id,
                    market_hash_name=market_hash_name,
                    min_price=data.get("min", {}),
                    max_price=data.get("max", {}),
                    average=data.get("average", {}),
                    average_7d=data.get("average7d", {}),
                    average_30d=data.get("average30d", {}),
                    sales_7d=data.get("sales7d", {}),
                    sales_30d=data.get("sales30d", {}),
                    history=data.get("history", []),
                    last_updated=result.get("time", 0),
                )

        except Exception as e:
            logger.error(f"Failed to get history for item {item_id}: {e}")
            return None

    async def get_item_history_by_name(self, market_hash_name: str) -> Optional[ItemPriceStats]:
        """Get item history by market hash name."""
        if not self._reverse_names_cache:
            await self.load_names_dictionary()

        item_id = self._reverse_names_cache.get(market_hash_name)
        if item_id is None:
            logger.warning(f"Item not found: {market_hash_name}")
            return None

        return await self.get_item_history(item_id)

    def get_price_for_currency(self, stats: ItemPriceStats, field: str) -> Optional[float]:
        """Get price value for current currency."""
        currency_key = self.currency.value
        data = getattr(stats, field, {})
        return data.get(currency_key)

    def filter_items_by_criteria(
        self,
        items: list[ItemPriceStats],
        min_price: float = None,
        max_price: float = None,
        min_sales_7d: int = None,
        min_sales_30d: int = None,
        max_price_deviation: float = None,
        item_types: list[ItemType] = None,
    ) -> list[ItemPriceStats]:
        """
        Filter items by given criteria.

        Args:
            items: List of ItemPriceStats to filter
            min_price: Minimum average price
            max_price: Maximum average price
            min_sales_7d: Minimum sales in 7 days
            min_sales_30d: Minimum sales in 30 days
            max_price_deviation: Maximum % difference between 7d and 30d avg
            item_types: List of allowed item types

        Returns:
            Filtered list of items
        """
        currency_key = self.currency.value
        filtered = []

        for item in items:
            # Check item type
            if item_types:
                item_type = detect_item_type(item.market_hash_name)
                if item_type not in item_types:
                    continue

            # Check price range
            avg_price = item.average.get(currency_key, 0)
            if min_price and avg_price < min_price:
                continue
            if max_price and avg_price > max_price:
                continue

            # Check sales volume
            sales_7d = item.sales_7d.get(currency_key, 0)
            sales_30d = item.sales_30d.get(currency_key, 0)

            if min_sales_7d and sales_7d < min_sales_7d:
                continue
            if min_sales_30d and sales_30d < min_sales_30d:
                continue

            # Check price stability (deviation between 7d and 30d avg)
            if max_price_deviation:
                avg_7d = item.average_7d.get(currency_key, 0)
                avg_30d = item.average_30d.get(currency_key, 0)

                if avg_7d > 0 and avg_30d > 0:
                    deviation = abs(avg_7d - avg_30d) / max(avg_7d, avg_30d) * 100
                    if deviation > max_price_deviation:
                        continue

            filtered.append(item)

        return filtered

    async def get_all_items_list(self) -> list[int]:
        """
        Get list of all item IDs from full-history/all.json.

        Note: This endpoint may be heavy, use with caution.
        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/full-history/all.json"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to get all items: {response.status}")
                    return []

                data = await response.json()
                # Return list of item IDs
                return list(data.get("data", {}).keys())

        except Exception as e:
            logger.error(f"Failed to get all items list: {e}")
            return []


# Convenience function for testing
async def test_csgo_market_api():
    """Test CSGO Market API."""
    api = CSGOMarketAPI(currency=Currency.RUB)

    try:
        # Load names dictionary
        print("Loading item names dictionary...")
        names = await api.load_names_dictionary()
        print(f"Loaded {len(names)} items")

        # Test with a specific item
        test_items = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Field-Tested)",
        ]

        for item_name in test_items:
            print(f"\n{'='*60}")
            print(f"Item: {item_name}")
            print("="*60)

            stats = await api.get_item_history_by_name(item_name)

            if stats:
                print(f"\nItem ID: {stats.item_id}")
                print(f"Type: {detect_item_type(item_name).value}")

                print(f"\nPrices (RUB):")
                print(f"  Average: {stats.average.get('RUB', 'N/A')}")
                print(f"  Average 7d: {stats.average_7d.get('RUB', 'N/A')}")
                print(f"  Average 30d: {stats.average_30d.get('RUB', 'N/A')}")
                print(f"  Min: {stats.min_price.get('RUB', 'N/A')}")
                print(f"  Max: {stats.max_price.get('RUB', 'N/A')}")

                print(f"\nSales (RUB):")
                print(f"  7 days: {stats.sales_7d.get('RUB', 'N/A')}")
                print(f"  30 days: {stats.sales_30d.get('RUB', 'N/A')}")

                # Calculate price stability
                avg_7d = stats.average_7d.get('RUB', 0)
                avg_30d = stats.average_30d.get('RUB', 0)
                if avg_7d > 0 and avg_30d > 0:
                    deviation = abs(avg_7d - avg_30d) / max(avg_7d, avg_30d) * 100
                    print(f"\nPrice deviation (7d vs 30d): {deviation:.2f}%")

                print(f"\nHistory entries: {len(stats.history)}")
            else:
                print("Item not found!")

            await asyncio.sleep(0.5)  # Rate limiting

    finally:
        await api.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_csgo_market_api())
