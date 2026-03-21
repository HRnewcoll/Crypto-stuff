"""
Shared utility helpers used across the crypto_toolkit package.
"""

from __future__ import annotations

import re
import time
from typing import Any


def is_valid_evm_address(address: str) -> bool:
    """Return True if *address* looks like a valid EVM hex address."""
    return bool(re.match(r"^0x[0-9a-fA-F]{40}$", address))


def wei_to_eth(wei: int) -> float:
    """Convert wei (int) to ETH (float)."""
    return wei / 1e18


def eth_to_wei(eth: float) -> int:
    """Convert ETH (float) to wei (int)."""
    return int(eth * 1e18)


def unix_to_iso(ts: int) -> str:
    """Convert a Unix timestamp to an ISO-8601 string."""
    import datetime
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat().replace("+00:00", "Z")


def truncate_address(address: str, chars: int = 6) -> str:
    """Return a truncated address like ``0x1234…abcd``."""
    if len(address) <= chars * 2 + 2:
        return address
    return f"{address[:chars + 2]}…{address[-chars:]}"


class RateLimiter:
    """Simple in-memory token-bucket rate limiter."""

    def __init__(self, calls_per_second: float = 1.0) -> None:
        self._interval = 1.0 / calls_per_second
        self._last_call = 0.0

    def wait(self) -> None:
        """Block until the next allowed call."""
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_call = time.monotonic()
