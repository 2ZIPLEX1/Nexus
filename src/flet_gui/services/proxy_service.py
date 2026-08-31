"""
Proxy service - integrates ProxyManager with GUI.
"""

from pathlib import Path
from typing import Optional, List
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.proxy_manager import ProxyManager
from flet_gui.state.app_state import AppState
from src.logger import get_logger

logger = get_logger(__name__)


class ProxyService:
    """Service for managing proxies in GUI."""

    def __init__(self, state: AppState, proxy_file: str = "proxies.txt"):
        """Initialize proxy service."""
        self.state = state
        self.proxy_file = proxy_file
        self.proxy_manager: Optional[ProxyManager] = None
        self._load_proxies()

    def _load_proxies(self):
        """Load proxies from file."""
        try:
            proxies = self._read_proxy_file(self.proxy_file)
            if proxies:
                config = self.state.config
                self.proxy_manager = ProxyManager(
                    proxies=proxies,
                    max_requests_per_proxy=config.get('proxy_max_requests', 15),
                    blacklist_duration_minutes=config.get('proxy_blacklist_duration', 30),
                    cooldown_seconds=config.get('proxy_cooldown', 60)
                )
                self.state.add_log(f"[SUCCESS] Loaded {len(proxies)} proxies from {self.proxy_file}")
            else:
                self.state.add_log(f"[WARNING] No proxies loaded from {self.proxy_file}")
        except Exception as e:
            logger.error(f"Failed to load proxies: {e}")
            self.state.add_log(f"[ERROR] Failed to load proxies: {str(e)}")

    def _read_proxy_file(self, proxy_file: str) -> List[str]:
        """Read proxies from file."""
        proxies = []
        proxy_path = Path(proxy_file)

        if not proxy_path.exists():
            logger.warning(f"Proxy file not found: {proxy_file}")
            return proxies

        try:
            with open(proxy_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Support various formats
                        if not line.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
                            # Assume http:// if no protocol
                            line = f"http://{line}"
                        proxies.append(line)

            logger.info(f"Loaded {len(proxies)} proxies from {proxy_file}")
            return proxies

        except Exception as e:
            logger.error(f"Error reading proxy file: {e}")
            return []

    def reload_proxies(self):
        """Reload proxies from file."""
        self._load_proxies()

    def get_next_proxy(self) -> Optional[str]:
        """Get next available proxy."""
        if not self.proxy_manager:
            return None
        return self.proxy_manager.get_next_proxy()

    def report_success(self, proxy: str):
        """Report successful request with proxy."""
        if self.proxy_manager:
            self.proxy_manager.report_success(proxy)

    def report_error(self, proxy: str, is_rate_limit: bool = False):
        """Report error with proxy."""
        if self.proxy_manager:
            self.proxy_manager.report_error(proxy, is_rate_limit=is_rate_limit)

    def get_stats(self) -> List[dict]:
        """Get statistics for all proxies."""
        if not self.proxy_manager:
            return []

        stats = []
        for proxy_url, proxy_stats in self.proxy_manager.stats.items():
            stats.append({
                'proxy': proxy_url,
                'requests': proxy_stats.requests_count,
                'success': proxy_stats.success_count,
                'errors': proxy_stats.error_count,
                'rate_limits': proxy_stats.rate_limit_count,
                'success_rate': f"{proxy_stats.success_rate:.1f}%",
                'healthy': proxy_stats.is_healthy,
                'blacklisted': proxy_stats.is_blacklisted,
            })
        return stats

    def get_healthy_count(self) -> int:
        """Get count of healthy proxies."""
        if not self.proxy_manager:
            return 0
        return sum(1 for s in self.proxy_manager.stats.values() if s.is_healthy)

    def get_total_count(self) -> int:
        """Get total proxy count."""
        if not self.proxy_manager:
            return 0
        return len(self.proxy_manager.proxies)

    def blacklist_proxy(self, proxy: str, duration_minutes: int = 30):
        """Manually blacklist a proxy."""
        if self.proxy_manager and proxy in self.proxy_manager.stats:
            from datetime import datetime, timedelta
            stats = self.proxy_manager.stats[proxy]
            stats.is_blacklisted = True
            stats.blacklist_until = datetime.now() + timedelta(minutes=duration_minutes)
            self.state.add_log(f"[INFO] Blacklisted proxy for {duration_minutes} minutes: {proxy}")

    def unblacklist_proxy(self, proxy: str):
        """Remove proxy from blacklist."""
        if self.proxy_manager and proxy in self.proxy_manager.stats:
            stats = self.proxy_manager.stats[proxy]
            stats.is_blacklisted = False
            stats.blacklist_until = None
            self.state.add_log(f"[INFO] Removed proxy from blacklist: {proxy}")

    def reset_stats(self):
        """Reset all proxy statistics."""
        if self.proxy_manager:
            for stats in self.proxy_manager.stats.values():
                stats.requests_count = 0
                stats.success_count = 0
                stats.error_count = 0
                stats.rate_limit_count = 0
                stats.is_blacklisted = False
                stats.blacklist_until = None
            self.state.add_log("[INFO] Proxy statistics reset")
