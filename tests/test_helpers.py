"""Unit tests for utility helpers."""

import pytest

from crypto_toolkit.utils.helpers import (
    is_valid_evm_address,
    wei_to_eth,
    eth_to_wei,
    unix_to_iso,
    truncate_address,
    RateLimiter,
)
import time


class TestIsValidEvmAddress:
    def test_valid_lowercase(self):
        assert is_valid_evm_address("0xabcdef1234567890abcdef1234567890abcdef12")

    def test_valid_uppercase(self):
        assert is_valid_evm_address("0xABCDEF1234567890ABCDEF1234567890ABCDEF12")

    def test_valid_checksum(self):
        assert is_valid_evm_address("0xdAC17F958D2ee523a2206206994597C13D831ec7")

    def test_too_short(self):
        assert not is_valid_evm_address("0x1234")

    def test_no_prefix(self):
        assert not is_valid_evm_address("abcdef1234567890abcdef1234567890abcdef12")

    def test_invalid_chars(self):
        assert not is_valid_evm_address("0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG")


class TestWeiEthConversions:
    def test_wei_to_eth(self):
        assert wei_to_eth(1_000_000_000_000_000_000) == pytest.approx(1.0)

    def test_eth_to_wei(self):
        assert eth_to_wei(1.0) == 1_000_000_000_000_000_000

    def test_round_trip(self):
        original = 1.5
        assert wei_to_eth(eth_to_wei(original)) == pytest.approx(original)

    def test_small_value(self):
        assert wei_to_eth(1) == pytest.approx(1e-18)


class TestUnixToIso:
    def test_known_timestamp(self):
        result = unix_to_iso(0)
        assert result == "1970-01-01T00:00:00Z"

    def test_returns_string(self):
        assert isinstance(unix_to_iso(1_700_000_000), str)


class TestTruncateAddress:
    def test_truncates_long_address(self):
        addr = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        result = truncate_address(addr)
        assert "…" in result
        assert len(result) < len(addr)

    def test_short_address_unchanged(self):
        short = "0x1234"
        assert truncate_address(short) == short


class TestRateLimiter:
    def test_rate_limiting(self):
        limiter = RateLimiter(calls_per_second=10)
        start = time.monotonic()
        for _ in range(3):
            limiter.wait()
        elapsed = time.monotonic() - start
        # 3 calls at 10/s should take ~0.2s (2 intervals of 0.1s)
        assert elapsed >= 0.1
