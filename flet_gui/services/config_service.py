"""
Config service - manages bot_config.json for GUI settings.
"""

import json
from pathlib import Path
from typing import Optional, Any
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from flet_gui.state.app_state import AppState
from src.logger import get_logger

logger = get_logger(__name__)


class ConfigService:
    """Service for managing bot configuration."""

    def __init__(self, state: AppState, config_file: str = "bot_config.json"):
        """Initialize config service."""
        self.state = state
        self.config_file = Path(config_file)
        self.load_config()

    def load_config(self) -> dict:
        """Load configuration from file."""
        try:
            if not self.config_file.exists():
                self.state.add_log(f"[WARNING] Config file not found: {self.config_file}")
                # Create default config
                default_config = self._get_default_config()
                self.save_config(default_config)
                return default_config

            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            self.state.config = config
            self.state.add_log(f"[INFO] Configuration loaded from {self.config_file}")
            logger.info(f"Configuration loaded: {len(config)} settings")

            return config

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.state.add_log(f"[ERROR] Failed to load config: {str(e)}")
            return {}

    def save_config(self, config: Optional[dict] = None) -> bool:
        """Save configuration to file."""
        try:
            if config is None:
                config = self.state.config

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

            self.state.config = config
            self.state.add_log(f"[SUCCESS] Configuration saved to {self.config_file}")
            logger.info("Configuration saved successfully")

            return True

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            self.state.add_log(f"[ERROR] Failed to save config: {str(e)}")
            return False

    def update_setting(self, key: str, value: Any) -> bool:
        """Update a single configuration setting."""
        try:
            config = self.state.config.copy()
            config[key] = value
            return self.save_config(config)

        except Exception as e:
            logger.error(f"Failed to update setting: {e}")
            self.state.add_log(f"[ERROR] Failed to update setting: {str(e)}")
            return False

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a single configuration setting."""
        return self.state.config.get(key, default)

    def _get_default_config(self) -> dict:
        """Get default configuration."""
        return {
            # Bot settings
            "cycle_interval_minutes": 5,
            "max_items_per_cycle": 10,
            "min_profit_percent": 5.0,
            "max_price_rub": 1000,

            # Scanner settings
            "scan_interval_minutes": 30,
            "scan_max_items": 100,
            "scanner_min_profit": -5.0,
            "scanner_min_price": 1000.0,
            "scanner_max_price": 10000.0,
            "min_sales_7d": 50,
            "csgo_commission": 10.0,

            # Trading limits
            "max_daily_trades": 50,
            "max_hold_time_hours": 168,  # 7 days
            "check_orders_min_profit": 5.0,  # Min profit % for order profitability check

            # Proxy settings
            "use_proxy": False,
            "proxy_rotation_enabled": False,
            "proxy_rotation_interval_minutes": 60,
            "requests_per_proxy": 50,

            # Logging
            "log_level": "INFO",
            "log_to_file": True,

            # Currency
            "default_currency": "RUB",

            # Steam settings
            "steam_api_key": "",
            "trade_hold_days": 7,

            # CSGO.TM settings
            "csgotm_api_key": "",

            # Price monitoring settings
            "auto_update_prices": False,  # True = автоматически обновлять, False = уведомления в Telegram
            "price_check_threshold_percent": 10.0,  # Порог для уведомления (если цена выше на X%)
            "price_update_to_top1": True,  # Обновлять до топ-1 (рыночная - 1₽)
            "csgotm_min_balance": 100,

            # Notifications
            "enable_notifications": False,
            "notification_webhook": "",
        }

    def reset_to_defaults(self) -> bool:
        """Reset configuration to default values."""
        try:
            self.state.add_log("[INFO] Resetting configuration to defaults...")
            default_config = self._get_default_config()
            success = self.save_config(default_config)

            if success:
                self.state.add_log("[SUCCESS] Configuration reset to defaults")

            return success

        except Exception as e:
            logger.error(f"Failed to reset config: {e}")
            self.state.add_log(f"[ERROR] Failed to reset config: {str(e)}")
            return False

    def validate_config(self) -> tuple[bool, list[str]]:
        """Validate current configuration."""
        errors = []
        config = self.state.config

        # Validate cycle interval
        if config.get('cycle_interval_minutes', 0) < 1:
            errors.append("cycle_interval_minutes must be at least 1")

        # Validate profit threshold
        if config.get('min_profit_percent', 0) < 0:
            errors.append("min_profit_percent cannot be negative")

        # Validate max price
        if config.get('max_price_rub', 0) <= 0:
            errors.append("max_price_rub must be positive")

        # Validate scan interval
        if config.get('scan_interval_minutes', 0) < 5:
            errors.append("scan_interval_minutes must be at least 5")

        is_valid = len(errors) == 0
        return is_valid, errors
