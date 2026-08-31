"""
Proxy parsing helpers.
"""

from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks4", "socks5"}


def normalize_proxy_url(raw_proxy: str) -> str | None:
    """Return a connector-ready proxy URL, or None if the row is invalid."""
    proxy = raw_proxy.strip()
    if not proxy or proxy.startswith("#"):
        return None

    if "://" not in proxy:
        proxy = f"http://{proxy}"

    parsed = urlparse(proxy)
    if parsed.scheme.lower() not in SUPPORTED_PROXY_SCHEMES:
        return None

    try:
        port = parsed.port
    except ValueError:
        return None

    if not parsed.hostname or port is None:
        return None

    return proxy


def normalize_proxy_list(raw_proxies: Iterable[str]) -> tuple[list[str], int]:
    """Normalize proxy rows and return (valid_proxies, skipped_count)."""
    proxies = []
    skipped = 0

    for raw_proxy in raw_proxies:
        raw_proxy = raw_proxy.strip()
        if not raw_proxy or raw_proxy.startswith("#"):
            continue

        proxy = normalize_proxy_url(raw_proxy)
        if proxy:
            proxies.append(proxy)
        else:
            skipped += 1

    return proxies, skipped


def load_proxy_file(proxy_file: str | Path) -> tuple[list[str], int]:
    """Read a proxy file and skip blank/comment/malformed rows."""
    proxy_path = Path(proxy_file)
    if not proxy_path.exists():
        return [], 0

    with open(proxy_path, "r", encoding="utf-8") as f:
        return normalize_proxy_list(f)
