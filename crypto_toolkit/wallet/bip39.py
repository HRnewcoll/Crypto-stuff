"""
BIP-39 mnemonic generation and seed derivation.

Supports any word count from the BIP-39 standard (12, 15, 18, 21, 24 words)
and any BIP-39 language (default: english).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from typing import Sequence

from mnemonic import Mnemonic as _Mnemonic


SUPPORTED_LANGUAGES = [
    "english",
    "chinese_simplified",
    "chinese_traditional",
    "french",
    "italian",
    "japanese",
    "korean",
    "spanish",
]

# Allowed mnemonic strengths (bits of entropy → word count)
_STRENGTH_MAP: dict[int, int] = {
    128: 12,
    160: 15,
    192: 18,
    224: 21,
    256: 24,
}


class BIP39:
    """Generate and verify BIP-39 mnemonics and derive BIP-32 seeds."""

    def __init__(self, language: str = "english") -> None:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. "
                f"Choose from: {SUPPORTED_LANGUAGES}"
            )
        self._mnemo = _Mnemonic(language)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, num_words: int = 12) -> str:
        """Return a new BIP-39 mnemonic phrase.

        Args:
            num_words: 12 | 15 | 18 | 21 | 24  (default 12)

        Returns:
            Space-separated mnemonic string.
        """
        strength = self._words_to_strength(num_words)
        return self._mnemo.generate(strength=strength)

    def generate_from_entropy(self, entropy_hex: str) -> str:
        """Generate a mnemonic from a custom hex entropy string."""
        entropy_bytes = bytes.fromhex(entropy_hex)
        if len(entropy_bytes) * 8 not in _STRENGTH_MAP:
            raise ValueError(
                "Entropy must be 128/160/192/224/256 bits "
                f"(got {len(entropy_bytes)*8} bits)."
            )
        return self._mnemo.to_mnemonic(entropy_bytes)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def is_valid(self, mnemonic: str) -> bool:
        """Return True if the mnemonic is a valid BIP-39 phrase."""
        return self._mnemo.check(mnemonic)

    # ------------------------------------------------------------------
    # Seed derivation
    # ------------------------------------------------------------------

    def to_seed(self, mnemonic: str, passphrase: str = "") -> bytes:
        """Derive the 64-byte BIP-39 seed from a mnemonic phrase.

        Args:
            mnemonic:   Valid BIP-39 phrase.
            passphrase: Optional BIP-39 passphrase (25th word).

        Returns:
            64 raw seed bytes.
        """
        if not self.is_valid(mnemonic):
            raise ValueError("Invalid mnemonic phrase.")
        return _Mnemonic.to_seed(mnemonic, passphrase)

    def to_seed_hex(self, mnemonic: str, passphrase: str = "") -> str:
        """Return seed as a hex string."""
        return self.to_seed(mnemonic, passphrase).hex()

    # ------------------------------------------------------------------
    # BIP-32 master key derivation
    # ------------------------------------------------------------------

    def to_master_key(self, mnemonic: str, passphrase: str = "") -> dict[str, str]:
        """Derive BIP-32 master private key + chain code from a mnemonic.

        Returns:
            dict with keys 'master_private_key' and 'chain_code' (hex strings).
        """
        seed = self.to_seed(mnemonic, passphrase)
        key, chain_code = self._derive_master_key(seed)
        return {
            "master_private_key": key.hex(),
            "chain_code": chain_code.hex(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _words_to_strength(num_words: int) -> int:
        reverse = {v: k for k, v in _STRENGTH_MAP.items()}
        if num_words not in reverse:
            raise ValueError(
                f"num_words must be one of {sorted(reverse.keys())}, got {num_words}"
            )
        return reverse[num_words]

    @staticmethod
    def _derive_master_key(seed: bytes) -> tuple[bytes, bytes]:
        """HMAC-SHA512 master key derivation per BIP-32."""
        I = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
        return I[:32], I[32:]

    def get_wordlist(self) -> list[str]:
        """Return the full wordlist for the current language."""
        return self._mnemo.wordlist
