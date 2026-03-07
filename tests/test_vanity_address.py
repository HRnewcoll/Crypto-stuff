"""Unit tests for vanity address generator."""

import re
import pytest

from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator, _evm_worker


class TestEvmWorker:
    """Test the worker function directly (no subprocess overhead)."""

    def test_finds_matching_address(self):
        # Use a very short prefix to keep test fast
        result = _evm_worker(r"^0x[0-9]", case_sensitive=False, max_attempts=100_000)
        assert result is not None
        assert re.match(r"^0x[0-9]", result["address"], re.IGNORECASE)
        assert result["private_key"]

    def test_returns_none_when_not_found(self):
        # Pattern that is essentially impossible to find in few attempts
        result = _evm_worker(r"^0xDEADBEEFDEADBEEF", case_sensitive=True, max_attempts=10)
        assert result is None


class TestVanityAddressGenerator:
    def setup_method(self):
        self.gen = VanityAddressGenerator()

    def test_requires_at_least_one_criterion(self):
        with pytest.raises(ValueError):
            self.gen.find()

    def test_unsupported_chain_raises(self):
        with pytest.raises(NotImplementedError):
            self.gen.find(chain="bitcoin", prefix="1ABC")

    def test_find_short_prefix(self):
        # Very short prefix (1 hex char after 0x) should be found quickly
        result = self.gen.find(chain="ethereum", prefix="0x0", workers=1)
        assert result is not None
        assert result.address.lower().startswith("0x0")
        assert result.attempts > 0
        assert result.elapsed_seconds >= 0

    def test_find_short_suffix(self):
        result = self.gen.find(chain="ethereum", suffix="f", workers=1)
        assert result is not None
        assert result.address.lower().endswith("f")

    def test_find_via_regex(self):
        result = self.gen.find(chain="ethereum", regex=r"^0x[aAbB]", workers=1)
        assert result is not None
        assert re.match(r"^0x[aAbB]", result.address, re.IGNORECASE)

    def test_result_has_valid_private_key(self):
        result = self.gen.find(chain="ethereum", prefix="0x", workers=1)
        assert result is not None
        assert len(result.private_key) == 64
