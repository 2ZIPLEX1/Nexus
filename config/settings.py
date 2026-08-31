"""
Configuration settings loaded from environment variables.
"""

import sys
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root directory (parent of config/)
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Steam Account ---
    # SecretStr: значение не появляется в repr(settings), в model_dump() и в
    # трейсбеках. В проекте ~45 мест с exc_info=True, и любой кадр стека,
    # держащий Settings, раньше печатал пароль и оба Guard-секрета целиком.
    # Читать значение — только через .get_secret_value().
    steam_username: str = Field(..., description="Steam account username")
    steam_password: SecretStr = Field(..., description="Steam account password")
    steam_api_key: SecretStr = Field(..., description="Steam Web API key")

    # --- Steam Guard Secrets ---
    steam_shared_secret: SecretStr = Field(..., description="Steam Guard shared secret for 2FA")
    steam_identity_secret: SecretStr = Field(..., description="Steam Guard identity secret for confirmations")

    # --- CSGO.TM API ---
    csgotm_api_key: SecretStr = Field(..., description="CSGO.TM API key")

    # --- Telegram Bot ---
    telegram_bot_token: Optional[SecretStr] = Field(None, description="Telegram bot token")
    telegram_chat_id: Optional[str] = Field(None, description="Telegram chat ID for notifications")

    # --- Database Paths ---
    bottm_db_path: Path = Field(Path("./data/main.db"), description="Path to bottm database")
    trades_db_path: Path = Field(Path("./data/my_trades.db"), description="Path to trades database")

    # --- Trading Settings ---
    min_profit_percent: float = Field(15.0, description="Minimum profit % to buy", ge=0)
    max_item_price: float = Field(50.0, description="Maximum item price in USD", gt=0)
    min_item_price: float = Field(0.5, description="Minimum item price in USD", ge=0)
    order_limit_multiplier: int = Field(5, description="Order limit as multiplier of balance", ge=1, le=10)
    buy_check_interval_hours: float = Field(2.0, description="Buy check interval in hours", gt=0)
    sell_check_interval_hours: float = Field(1.0, description="Sell check interval in hours", gt=0)
    price_change_threshold: float = Field(10.0, description="Price change % for order cancellation", ge=0)

    # --- Commission ---
    csgotm_commission: float = Field(0.10, description="CSGO.TM commission (10%)")

    # --- Logging ---
    log_level: str = Field("INFO", description="Logging level")
    log_file: Path = Field(Path("./logs/bot.log"), description="Log file path")

    @property
    def steam_guard(self) -> dict:
        """Return Steam Guard credentials as dict for steampy.

        Разворачивает SecretStr — получившийся dict содержит секреты открытым
        текстом, поэтому его нельзя логировать целиком.
        """
        return {
            "shared_secret": self.steam_shared_secret.get_secret_value(),
            "identity_secret": self.steam_identity_secret.get_secret_value(),
        }

    def calculate_max_orders_value(self, balance: float) -> float:
        """Calculate maximum total value of active orders based on balance."""
        return balance * self.order_limit_multiplier

    def calculate_net_profit(self, buy_price: float, sell_price: float) -> float:
        """Calculate net profit WITHOUT commission."""
        return sell_price - buy_price

    def calculate_profit_percent(self, buy_price: float, sell_price: float) -> float:
        """Calculate profit percentage WITHOUT commission."""
        if buy_price <= 0:
            return 0.0
        net_profit = self.calculate_net_profit(buy_price, sell_price)
        return (net_profit / buy_price) * 100


# Global settings instance
def _create_settings() -> Settings:
    """Create settings instance with helpful error messages."""
    try:
        return Settings()
    except ValidationError as e:
        # Check if .env file exists
        if not ENV_FILE.exists():
            print("\n" + "=" * 60, file=sys.stderr)
            print("ERROR: Configuration file not found!", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            print(f"\nThe .env file is missing: {ENV_FILE}", file=sys.stderr)
            print("\nTo fix this:", file=sys.stderr)
            print(f"  1. Copy the example file: cp {ENV_EXAMPLE} {ENV_FILE}", file=sys.stderr)
            print(f"  2. Edit {ENV_FILE} with your credentials", file=sys.stderr)
            print("\nRequired settings:", file=sys.stderr)
            print("  - STEAM_USERNAME", file=sys.stderr)
            print("  - STEAM_PASSWORD", file=sys.stderr)
            print("  - STEAM_API_KEY", file=sys.stderr)
            print("  - STEAM_SHARED_SECRET", file=sys.stderr)
            print("  - STEAM_IDENTITY_SECRET", file=sys.stderr)
            print("  - CSGOTM_API_KEY", file=sys.stderr)
            print("\n" + "=" * 60 + "\n", file=sys.stderr)
            sys.exit(1)
        else:
            # .env exists but has validation errors
            print("\n" + "=" * 60, file=sys.stderr)
            print("ERROR: Invalid configuration!", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            print(f"\nYour .env file at {ENV_FILE} has errors:\n", file=sys.stderr)
            # Ошибка валидации может процитировать введённое значение — чистим,
            # чтобы креды не осели в консоли и в journald.
            try:
                from src.logger import redact_text
                print(redact_text(str(e)), file=sys.stderr)
            except Exception:
                print(str(e), file=sys.stderr)
            print(f"\nPlease check {ENV_EXAMPLE} for the correct format.", file=sys.stderr)
            print("\n" + "=" * 60 + "\n", file=sys.stderr)
            sys.exit(1)


settings = _create_settings()
