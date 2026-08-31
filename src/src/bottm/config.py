"""
Configuration for the trading bot.
"""
from enum import Enum
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class Currency(str, Enum):
    RUB = "RUB"
    EUR = "EUR"
    USD = "USD"


# Steam currency codes for API
STEAM_CURRENCY_CODES = {
    Currency.RUB: 5,   # Russian Ruble
    Currency.EUR: 3,   # Euro
    Currency.USD: 1,   # US Dollar
}


class FilterSettings(BaseModel):
    """Settings for item filtering."""
    min_price: float = 1000.0  # Minimum price in selected currency
    max_price: float = 10000.0  # Maximum price in selected currency
    min_sales_7d: int = 50  # Minimum sales per week
    min_sales_30d: int = 100  # Minimum sales per month
    max_price_deviation: float = 15.0  # Max % deviation between 7d and 30d avg
    min_profit_margin: float = 6.0  # Minimum profit margin % (steam order vs market price)


class ProxySettings(BaseModel):
    """Proxy configuration for Steam API."""
    enabled: bool = False
    # Format: "socks5://user:pass@host:port" or "http://user:pass@host:port"
    url: str = ""


class TelegramSettings(BaseModel):
    """Telegram bot configuration."""
    bot_token: str = ""  # Bot API token from @BotFather
    allowed_users: list[int] = []  # List of Telegram user IDs allowed to use the bot
    compact_mode: bool = True  # Show compact output by default


class Config(BaseSettings):
    """Main configuration."""
    currency: Currency = Currency.RUB

    # API endpoints
    csgo_market_base_url: str = "https://market.csgo.com/api/v2"
    steam_market_base_url: str = "https://steamcommunity.com/market"

    # Proxy for Steam (blocked in Russia)
    proxy: ProxySettings = ProxySettings()

    # Filter settings
    filters: FilterSettings = FilterSettings()

    # Telegram bot settings
    telegram: TelegramSettings = TelegramSettings()

    class Config:
        env_prefix = "BOT_"


# Global config instance
config = Config()
