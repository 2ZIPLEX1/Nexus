"""
Scanner for finding profitable items.

Strategy: Buy on Steam via buy order -> Sell on market.csgo.com
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from src.bottm.config import Currency, config, FilterSettings
from src.bottm.api.steam_market import SteamMarketAPI, PriceHistory
from src.bottm.api.csgo_market import CSGOMarketAPI, ItemMarketPrice, ItemPriceStats, detect_item_type, ItemType
from src.database import TradesDatabase

logger = logging.getLogger(__name__)

# market.csgo.com commission
CSGO_MARKET_FEE_PCT = 7.0


@dataclass
class ProfitableItem:
    """Item with calculated profit potential."""
    market_hash_name: str
    item_type: ItemType

    # CSGO Market data
    csgo_price: float  # Min sell price on market.csgo.com
    csgo_buy_order: float  # Max buy order (instant sell)
    csgo_avg_price: float
    csgo_popularity_7d: int
    csgo_sales_7d: Optional[int] = None
    csgo_sales_30d: Optional[int] = None
    csgo_avg_7d: Optional[float] = None
    csgo_avg_30d: Optional[float] = None

    # Steam Market data
    steam_buy_order: Optional[float] = None  # Current highest buy order
    steam_lowest_sell: Optional[float] = None  # Current lowest sell listing
    steam_median: Optional[float] = None
    steam_volume_24h: Optional[int] = None

    # Steam spread analysis
    steam_spread: Optional[float] = None  # Difference between lowest_sell and buy_order
    steam_spread_pct: Optional[float] = None  # Spread as percentage

    # Calculated profit (sell at csgo price, buy at steam buy order)
    profit: Optional[float] = None  # Profit amount
    profit_pct: Optional[float] = None  # Profit percentage

    # Steam price history (for smarter buy orders)
    # Note: Steam history is in USD, convert to currency for comparison
    steam_history_min: Optional[float] = None  # Historical minimum
    steam_history_avg: Optional[float] = None  # Historical average
    steam_history_p20: Optional[float] = None  # 20th percentile (20% sold below)
    steam_history_p25: Optional[float] = None  # 25th percentile (25% sold below)
    steam_history_sales: Optional[int] = None  # Number of sales analyzed

    # Recommended buy order (based on history - place below current but likely to fill)
    recommended_buy_order: Optional[float] = None  # Based on 20th percentile
    recommended_profit: Optional[float] = None  # Profit at recommended price
    recommended_profit_pct: Optional[float] = None  # Profit percentage at recommended price
    orders_above_recommended: Optional[int] = None  # Orders that need to fill before yours

    # Price stability
    price_deviation_pct: Optional[float] = None

    def get_csgo_market_url(self) -> str:
        """Get URL to item on market.csgo.com"""
        encoded = quote(self.market_hash_name)
        return f"https://market.csgo.com/ru/{encoded}"

    def get_steam_market_url(self) -> str:
        """Get URL to item on Steam Market"""
        encoded = quote(self.market_hash_name)
        return f"https://steamcommunity.com/market/listings/730/{encoded}"


def validate_item_data(
    steam_buy_order: Optional[float],
    steam_lowest_sell: Optional[float],
    csgo_price: float,
    csgo_buy_order: float,
    steam_history_avg: Optional[float]
) -> tuple[bool, str]:
    """
    Validate item data for correctness.
    Returns (is_valid, error_message).
    """
    # Check 1: All critical fields must be filled
    if steam_buy_order is None:
        return False, "Missing steam_buy_order"
    if steam_lowest_sell is None:
        return False, "Missing steam_lowest_sell"

    # Check 2: All prices must be > 0
    if steam_buy_order <= 0:
        return False, f"Invalid steam_buy_order: {steam_buy_order}"
    if steam_lowest_sell <= 0:
        return False, f"Invalid steam_lowest_sell: {steam_lowest_sell}"
    if csgo_price <= 0:
        return False, f"Invalid csgo_price: {csgo_price}"

    # Check 3: buy_order MUST be less than lowest_sell (otherwise fake profit)
    if steam_buy_order >= steam_lowest_sell:
        return False, f"Fake profit: buy_order ({steam_buy_order:.0f}) >= lowest_sell ({steam_lowest_sell:.0f})"

    return True, ""


class ItemScanner:
    """Scanner for finding profitable trading opportunities."""

    def __init__(
        self,
        database: TradesDatabase,
        currency: Currency = Currency.RUB,
        proxy_url: Optional[str] = None,
        proxy_list: Optional[list[str]] = None,
        requests_per_proxy: int = 15,
        filters: Optional[FilterSettings] = None,
    ):
        self.database = database
        self.currency = currency
        self.filters = filters or config.filters

        self.csgo_api = CSGOMarketAPI(currency=currency)
        self.steam_api = SteamMarketAPI(
            currency=currency,
            proxy_url=proxy_url,
            proxy_list=proxy_list,
            requests_per_proxy=requests_per_proxy,
        )

        self._candidates: list[ItemMarketPrice] = []

    async def close(self):
        """Close API sessions."""
        # Give pending requests time to complete
        await asyncio.sleep(0.1)
        await self.csgo_api.close()
        await self.steam_api.close()
        # Final sleep to ensure cleanup
        await asyncio.sleep(0.1)

    async def load_data(self):
        """Load all necessary data from APIs."""
        logger.info("Loading CSGO Market prices...")
        await self.csgo_api.load_prices_with_buy_orders()

        logger.info("Loading CSGO Market names dictionary...")
        await self.csgo_api.load_names_dictionary()

        logger.info("Data loaded!")

    def filter_candidates(self) -> list[ItemMarketPrice]:
        """
        Filter items by basic criteria (price range, type).

        This is a fast pre-filter before checking Steam prices.
        """
        candidates = []

        logger.info(f"Starting filter_candidates, cache has {len(self.csgo_api._prices_cache)} items")
        logger.info(f"Filters: min_price={self.filters.min_price}, max_price={self.filters.max_price}, "
                   f"min_sales_7d={self.filters.min_sales_7d}")

        for name, price_data in self.csgo_api._prices_cache.items():
            # Check item type (only weapon skins and agents)
            item_type = detect_item_type(name)
            if item_type not in [ItemType.WEAPON_SKIN, ItemType.AGENT]:
                continue

            # Check price range (using csgo market price)
            if price_data.price < self.filters.min_price:
                continue
            if price_data.price > self.filters.max_price:
                continue

            # Check popularity (sales)
            if price_data.popularity_7d < self.filters.min_sales_7d:
                continue

            # Must have buy_order for instant sell
            if price_data.buy_order <= 0:
                continue

            candidates.append(price_data)

        # Sort by popularity (most sales first)
        candidates.sort(key=lambda x: x.popularity_7d, reverse=True)

        self._candidates = candidates
        logger.info(f"Found {len(candidates)} candidates after basic filtering (sorted by popularity)")
        return candidates

    async def analyze_item(self, price_data: ItemMarketPrice) -> Optional[ProfitableItem]:
        """
        Analyze a single item for profitability.

        Returns ProfitableItem if profitable, None otherwise.
        """
        name = price_data.market_hash_name
        item_type = detect_item_type(name)

        # Get Steam market data
        steam_info = await self.steam_api.get_full_market_info(name)

        price_overview = steam_info.get("price_overview")
        buy_orders = steam_info.get("buy_orders")

        # Need Steam buy order to calculate profit
        steam_buy_order = None
        if buy_orders and buy_orders.success:
            steam_buy_order = buy_orders.highest_buy_order

        if not steam_buy_order:
            logger.info(f"  No Steam buy order data")
            return None

        logger.info(f"  Steam buy: {steam_buy_order:.0f} | CSGO sell: {price_data.price:.0f} / buy_order: {price_data.buy_order:.0f}")

        # Get history for sales stats and price stability
        history = await self.csgo_api.get_item_history_by_name(name)

        csgo_sales_7d = None
        csgo_sales_30d = None
        csgo_avg_7d = None
        csgo_avg_30d = None
        price_deviation_pct = None

        if history:
            currency_key = self.currency.value
            csgo_sales_7d = history.sales_7d.get(currency_key)
            csgo_sales_30d = history.sales_30d.get(currency_key)
            csgo_avg_7d = history.average_7d.get(currency_key)
            csgo_avg_30d = history.average_30d.get(currency_key)

            # Check sales requirements
            if csgo_sales_7d and csgo_sales_7d < self.filters.min_sales_7d:
                return None
            if csgo_sales_30d and csgo_sales_30d < self.filters.min_sales_30d:
                return None

            # Calculate price stability
            if csgo_avg_7d and csgo_avg_30d and csgo_avg_7d > 0 and csgo_avg_30d > 0:
                price_deviation_pct = abs(csgo_avg_7d - csgo_avg_30d) / max(csgo_avg_7d, csgo_avg_30d) * 100
                if price_deviation_pct > self.filters.max_price_deviation:
                    return None

        # Get Steam lowest sell price
        steam_lowest_sell = None
        if price_overview and price_overview.success:
            steam_lowest_sell = price_overview.lowest_price

        # Get Steam price history for validation and smarter buy order recommendations
        # Use last 7 days for recent/relevant prices
        # History is in USD, we need to convert to target currency
        steam_history = await self.steam_api.get_price_history(name, days=7)
        steam_history_avg = steam_history.avg_price if steam_history and steam_history.success else None

        # IMPORTANT: Comprehensive data validation
        is_valid, error_msg = validate_item_data(
            steam_buy_order=steam_buy_order,
            steam_lowest_sell=steam_lowest_sell,
            csgo_price=price_data.price,
            csgo_buy_order=price_data.buy_order,
            steam_history_avg=steam_history_avg
        )

        if not is_valid:
            logger.warning(f"  ❌ Invalid data: {error_msg}")
            return None

        # Calculate Steam spread (gap between sell and buy)
        steam_spread = None
        steam_spread_pct = None

        if steam_lowest_sell and steam_buy_order:
            steam_spread = steam_lowest_sell - steam_buy_order
            steam_spread_pct = (steam_spread / steam_lowest_sell) * 100

        # Process Steam price history for recommended buy order
        steam_history_min = None
        steam_history_avg = None
        steam_history_p20 = None
        steam_history_p25 = None
        steam_history_sales = None
        recommended_buy_order = None

        if steam_history and steam_history.success:
            steam_history_sales = steam_history.total_sales

            # Estimate USD to currency conversion rate using current prices
            # If we have both steam_buy_order (in currency) and history avg (in USD)
            # we can estimate the rate
            if steam_history.avg_price and steam_history.avg_price > 0:
                # This is approximate - using average as reference
                usd_to_currency = steam_buy_order / steam_history.avg_price

                steam_history_min = steam_history.min_price * usd_to_currency
                steam_history_avg = steam_history.avg_price * usd_to_currency
                steam_history_p20 = steam_history.percentile_20 * usd_to_currency
                steam_history_p25 = steam_history.percentile_25 * usd_to_currency

                # Recommended buy order: 20th percentile (20% of sales were at this price or lower)
                # This gives a good chance to fill while saving money
                recommended_buy_order = steam_history_p20

                # Make sure recommended is below current buy order (otherwise no point)
                if recommended_buy_order >= steam_buy_order:
                    recommended_buy_order = None  # Not worth it

                logger.info(f"  History: min={steam_history_min:.0f}, p20={steam_history_p20:.0f}, p25={steam_history_p25:.0f}, avg={steam_history_avg:.0f}")
                if recommended_buy_order:
                    savings_pct = ((steam_buy_order - recommended_buy_order) / steam_buy_order) * 100
                    logger.info(f"  Recommended buy order: {recommended_buy_order:.0f} (save {savings_pct:.1f}%)")

        # Count orders above recommended price (how many need to fill before yours)
        orders_above_recommended = None
        if recommended_buy_order and buy_orders and buy_orders.buy_order_graph:
            orders_above_recommended = buy_orders.count_orders_above_price(recommended_buy_order)
            if orders_above_recommended > 0:
                logger.info(f"  Orders above {recommended_buy_order:.0f}: {orders_above_recommended}")
                if orders_above_recommended > 200:
                    logger.info(f"  WARNING: Too many orders ({orders_above_recommended}), will take long to fill!")

        # Calculate profit at CURRENT buy order (without fee - user pays fee separately)
        # Profit = Sell on CSGO.TM - Buy on Steam
        csgo_sell_price = price_data.price
        profit = csgo_sell_price - steam_buy_order
        profit_pct = (profit / steam_buy_order) * 100

        logger.info(f"  Profit calc: CSGO sell={csgo_sell_price:.0f}, Steam buy={steam_buy_order:.0f}, profit={profit:.0f} ({profit_pct:.1f}%)")

        # Calculate profit at RECOMMENDED buy order (based on history)
        recommended_profit = None
        recommended_profit_pct = None

        if recommended_buy_order:
            recommended_profit = csgo_sell_price - recommended_buy_order
            recommended_profit_pct = (recommended_profit / recommended_buy_order) * 100

        # Check minimum profit margin - use BEST case (recommended or current)
        best_profit_pct = profit_pct
        if recommended_profit_pct is not None:
            best_profit_pct = max(best_profit_pct, recommended_profit_pct)

        # Show ALL items regardless of profit (goal is to withdraw with minimal loss)
        logger.info(f"  FOUND: profit={profit_pct:.1f}%")
        if recommended_profit_pct is not None:
            logger.info(f"  @ Recommended: profit={recommended_profit_pct:.1f}%")
        if steam_spread_pct:
            logger.info(f"  Steam spread: {steam_spread:.0f} ({steam_spread_pct:.1f}%)")

        # Build result
        item = ProfitableItem(
            market_hash_name=name,
            item_type=item_type,
            csgo_price=price_data.price,
            csgo_buy_order=price_data.buy_order,
            csgo_avg_price=price_data.avg_price,
            csgo_popularity_7d=price_data.popularity_7d,
            csgo_sales_7d=csgo_sales_7d,
            csgo_sales_30d=csgo_sales_30d,
            csgo_avg_7d=csgo_avg_7d,
            csgo_avg_30d=csgo_avg_30d,
            steam_buy_order=steam_buy_order,
            steam_lowest_sell=steam_lowest_sell,
            steam_median=price_overview.median_price if price_overview and price_overview.success else None,
            steam_volume_24h=price_overview.volume if price_overview and price_overview.success else None,
            steam_spread=steam_spread,
            steam_spread_pct=steam_spread_pct,
            profit=profit,
            profit_pct=profit_pct,
            # Steam price history
            steam_history_min=steam_history_min,
            steam_history_avg=steam_history_avg,
            steam_history_p20=steam_history_p20,
            steam_history_p25=steam_history_p25,
            steam_history_sales=steam_history_sales,
            # Recommended buy order (based on history)
            recommended_buy_order=recommended_buy_order,
            recommended_profit=recommended_profit,
            recommended_profit_pct=recommended_profit_pct,
            orders_above_recommended=orders_above_recommended,
            price_deviation_pct=price_deviation_pct,
        )

        return item

    async def scan(
        self,
        max_items: int = 100,
        delay_between_items: float = 1.5,
        parallel: int = 1,
    ) -> list[ProfitableItem]:
        """
        Scan for profitable items.

        Args:
            max_items: Maximum items to check (Steam has rate limits)
            delay_between_items: Delay between Steam API calls
            parallel: Number of parallel workers (use number of proxies)

        Returns:
            List of profitable items sorted by profit potential
        """
        # Load data if not loaded
        if not self.csgo_api._prices_cache:
            await self.load_data()

        # Get candidates
        logger.info("Filtering candidates from CSGO Market data...")
        candidates = self.filter_candidates()
        logger.info(f"Found {len(candidates)} candidates after filtering")

        if not candidates:
            logger.warning("No candidates found matching filter criteria!")
            return []

        # Sort by popularity (more trades = more reliable)
        candidates.sort(key=lambda x: x.popularity_7d, reverse=True)

        # Limit to max_items
        candidates = candidates[:max_items]
        logger.info(f"Limited to {len(candidates)} items for analysis")

        logger.info(f"Starting analysis of {len(candidates)} items (parallel workers: {parallel})...")

        profitable_items = []
        semaphore = asyncio.Semaphore(parallel)
        counter = {"done": 0, "total": len(candidates)}
        lock = asyncio.Lock()

        async def process_item(candidate):
            async with semaphore:
                try:
                    async with lock:
                        counter["done"] += 1
                        idx = counter["done"]

                    logger.info(f"[{idx}/{counter['total']}] Checking: {candidate.market_hash_name}")

                    item = await self.analyze_item(candidate)

                    if item:
                        async with lock:
                            profitable_items.append(item)
                            # Save to database - convert ProfitableItem to dict
                            item_data = {
                                'market_hash_name': item.market_hash_name,
                                'item_type': item.item_type.value if hasattr(item.item_type, 'value') else str(item.item_type),
                                'steam_buy_order': item.steam_buy_order,
                                'recommended_buy_order': item.recommended_buy_order,
                                'csgo_price': item.csgo_price,
                                'csgo_buy_order': item.csgo_buy_order,
                                'profit_pct': item.profit_pct,
                                'recommended_profit_pct': item.recommended_profit_pct,
                                'orders_above': item.orders_above_recommended,
                            }
                            is_new = self.database.add_or_update_profitable_item(item_data)
                            if is_new:
                                logger.info(f"  -> FOUND! (added to DB)")
                            else:
                                logger.info(f"  -> FOUND! (updated in DB)")

                except Exception as e:
                    logger.error(f"Error analyzing {candidate.market_hash_name}: {e}")

                # Small delay to avoid hammering
                await asyncio.sleep(delay_between_items)

        # Run all tasks
        tasks = [process_item(c) for c in candidates]
        await asyncio.gather(*tasks)

        # Sort by profit (best first)
        profitable_items.sort(key=lambda x: x.profit_pct or -999, reverse=True)

        logger.info(f"Found {len(profitable_items)} profitable items!")

        return profitable_items


def print_profitable_item(item: ProfitableItem, currency: str = "RUB"):
    """Pretty print a profitable item."""
    print(f"\n{'='*70}")
    print(f"{item.market_hash_name}")
    print(f"Type: {item.item_type.value}")
    print("="*70)

    print(f"\n[market.csgo.com]")
    print(f"  Sell price:     {item.csgo_price:.2f} {currency}")
    print(f"  Buy order:      {item.csgo_buy_order:.2f} {currency}")
    if item.csgo_sales_7d:
        print(f"  Sales 7d/30d:   {item.csgo_sales_7d}/{item.csgo_sales_30d}")

    print(f"\n[Steam Market]")
    print(f"  Highest buy:    {item.steam_buy_order:.2f} {currency}")
    if item.steam_lowest_sell:
        print(f"  Lowest sell:    {item.steam_lowest_sell:.2f} {currency}")
    if item.steam_spread:
        print(f"  Spread:         {item.steam_spread:.2f} ({item.steam_spread_pct:.1f}%)")
    if item.steam_volume_24h:
        print(f"  Volume 24h:     {item.steam_volume_24h}")

    print(f"\n[Profit @ Current Buy Order: {item.steam_buy_order:.2f}]")
    if item.price_deviation_pct is not None:
        stable = "STABLE" if item.price_deviation_pct < 15 else "UNSTABLE"
        print(f"  Price stability: {stable} ({item.price_deviation_pct:.1f}%)")

    icon = "+" if item.profit_pct and item.profit_pct > 0 else "-"
    print(f"  Profit:         {item.profit:.2f} ({icon}{abs(item.profit_pct):.1f}%)")

    # Show history-based recommended order (lower than current, based on 20th percentile)
    if item.steam_history_p20:
        print(f"\n[Steam Price History (7d)]")
        print(f"  Min:        {item.steam_history_min:.2f} {currency}")
        print(f"  20th pctl:  {item.steam_history_p20:.2f} {currency}  <- 20% sold below this")
        print(f"  25th pctl:  {item.steam_history_p25:.2f} {currency}  <- 25% sold below this")
        print(f"  Average:    {item.steam_history_avg:.2f} {currency}")
        if item.steam_history_sales:
            print(f"  Sales:      {item.steam_history_sales}")

    if item.recommended_buy_order:
        savings = item.steam_buy_order - item.recommended_buy_order
        savings_pct = (savings / item.steam_buy_order) * 100
        print(f"\n[>>> RECOMMENDED Buy Order: {item.recommended_buy_order:.2f} <<<] (save {savings_pct:.1f}%)")
        print(f"  Based on 20th percentile - 20% of sales happen at this price or lower")
        if item.recommended_profit_pct is not None:
            icon = "+" if item.recommended_profit_pct > 0 else "-"
            print(f"  Profit:         {item.recommended_profit:.2f} ({icon}{abs(item.recommended_profit_pct):.1f}%)")

        # Show orders above recommended price
        if item.orders_above_recommended is not None:
            if item.orders_above_recommended > 200:
                print(f"  !!! ORDERS ABOVE: {item.orders_above_recommended} - TOO MANY, WILL TAKE LONG !!!")
            elif item.orders_above_recommended > 100:
                print(f"  !! Orders above: {item.orders_above_recommended} - might take a while")
            elif item.orders_above_recommended > 0:
                print(f"  Orders above: {item.orders_above_recommended}")
            else:
                print(f"  Orders above: 0 - will fill quickly!")

    print(f"\n[Links]")
    print(f"  CSGO: {item.get_csgo_market_url()}")
    print(f"  Steam: {item.get_steam_market_url()}")

    if item.recommended_buy_order and item.recommended_profit_pct and item.recommended_profit_pct > 5:
        print(f"\n  >>> RECOMMENDED: Place buy order at {item.recommended_buy_order:.0f} for better profit! <<<")
    elif item.profit_pct and item.profit_pct > 0:
        print(f"\n  >>> PROFITABLE! <<<")


def format_item_compact(item: ProfitableItem, currency: str = "RUB") -> str:
    """Format item in compact mode for Telegram."""
    # Use recommended or current prices
    buy_price = item.recommended_buy_order or item.steam_buy_order
    sell_price = item.csgo_price
    profit_pct = item.recommended_profit_pct or item.profit_pct or 0

    # Profit icon
    if profit_pct > 5:
        icon = "🟢"
    elif profit_pct > 0:
        icon = "🟡"
    else:
        icon = "🔴"

    # Orders warning
    orders_warn = ""
    if item.orders_above_recommended is not None:
        if item.orders_above_recommended > 200:
            orders_warn = " ⚠️ SLOW"
        elif item.orders_above_recommended > 100:
            orders_warn = " ⏳"

    lines = [
        f"{icon} <b>{item.market_hash_name}</b>{orders_warn}",
        f"",
        f"💰 Steam: <code>{buy_price:.0f}</code> {currency}",
        f"💵 Market: <code>{sell_price:.0f}</code> {currency}",
        f"📈 Profit: <code>{profit_pct:+.1f}%</code>",
        f"",
        f"🛒 <a href=\"{item.get_steam_market_url()}\">Steam</a> | <a href=\"{item.get_csgo_market_url()}\">Market</a>",
    ]

    return "\n".join(lines)


def format_item_full(item: ProfitableItem, currency: str = "RUB") -> str:
    """Format item in full mode for Telegram."""
    buy_price = item.recommended_buy_order or item.steam_buy_order
    profit_pct = item.recommended_profit_pct or item.profit_pct or 0

    if profit_pct > 5:
        icon = "🟢"
    elif profit_pct > 0:
        icon = "🟡"
    else:
        icon = "🔴"

    lines = [
        f"{icon} <b>{item.market_hash_name}</b>",
        f"Type: {item.item_type.value}",
        f"",
        f"<b>[market.csgo.com]</b>",
        f"  Sell: <code>{item.csgo_price:.0f}</code> {currency}",
        f"  Buy order: <code>{item.csgo_buy_order:.0f}</code> {currency}",
    ]

    if item.csgo_sales_7d:
        lines.append(f"  Sales 7d/30d: {item.csgo_sales_7d}/{item.csgo_sales_30d}")

    lines.extend([
        f"",
        f"<b>[Steam]</b>",
        f"  Buy order: <code>{item.steam_buy_order:.0f}</code> {currency}",
    ])

    if item.steam_lowest_sell:
        lines.append(f"  Lowest sell: <code>{item.steam_lowest_sell:.0f}</code> {currency}")

    if item.steam_history_p20:
        lines.extend([
            f"",
            f"<b>[History]</b>",
            f"  Min: {item.steam_history_min:.0f} | P20: {item.steam_history_p20:.0f} | Avg: {item.steam_history_avg:.0f}",
        ])

    if item.recommended_buy_order:
        savings_pct = ((item.steam_buy_order - item.recommended_buy_order) / item.steam_buy_order) * 100
        lines.extend([
            f"",
            f"<b>✅ Recommended: {item.recommended_buy_order:.0f}</b> (save {savings_pct:.1f}%)",
            f"  Profit: {profit_pct:+.1f}%",
        ])

        if item.orders_above_recommended is not None:
            if item.orders_above_recommended > 200:
                lines.append(f"  ⚠️ Orders above: {item.orders_above_recommended} - SLOW!")
            elif item.orders_above_recommended > 0:
                lines.append(f"  Orders above: {item.orders_above_recommended}")

    lines.extend([
        f"",
        f"🛒 <a href=\"{item.get_steam_market_url()}\">Steam</a> | <a href=\"{item.get_csgo_market_url()}\">Market</a>",
    ])

    return "\n".join(lines)
