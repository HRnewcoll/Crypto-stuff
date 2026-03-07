"""
Vanity address generator – multi-chain.

Generates addresses that start (or contain) a user-supplied prefix/suffix
using brute-force key generation.

⚠  WARNING: This uses a random search; time to find an address grows
exponentially with prefix length.  Use --workers to parallelize.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional

from eth_account import Account as _EthAccount

_EthAccount.enable_unaudited_hdwallet_features()


@dataclass
class VanityResult:
    address: str
    private_key: str
    attempts: int
    elapsed_seconds: float


# ─────────────────────────────────────────────────────────────────────────────
# EVM vanity search (worker function – must be picklable, so module-level)
# ─────────────────────────────────────────────────────────────────────────────

def _evm_worker(pattern: str, case_sensitive: bool, max_attempts: int) -> Optional[dict]:
    """Search for an EVM address matching *pattern* (regex).

    Called in a subprocess.  Returns a dict or None.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)
    for attempt in range(1, max_attempts + 1):
        key_bytes = secrets.token_bytes(32)
        acct = _EthAccount.from_key(key_bytes)
        if compiled.search(acct.address):
            return {
                "address": acct.address,
                "private_key": key_bytes.hex(),
                "attempts": attempt,
            }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# VanityAddressGenerator
# ─────────────────────────────────────────────────────────────────────────────

class VanityAddressGenerator:
    """Search for a vanity address for a given chain.

    Currently supports EVM-compatible chains (Ethereum, BSC, Polygon, …).
    Bitcoin and Solana hooks are provided but require additional libraries.

    Example:
        gen = VanityAddressGenerator()
        result = gen.find(chain="ethereum", prefix="0xDEAD", workers=4)
    """

    def find(
        self,
        chain: str = "ethereum",
        prefix: Optional[str] = None,
        suffix: Optional[str] = None,
        regex: Optional[str] = None,
        case_sensitive: bool = False,
        workers: int = 2,
        max_attempts_per_worker: int = 1_000_000,
    ) -> Optional[VanityResult]:
        """Search for a vanity address.

        Provide one of *prefix*, *suffix*, or a full *regex* pattern.

        Args:
            chain:               Target chain (only EVM supported for now).
            prefix:              Desired address prefix (e.g. ``"0xDEAD"``).
            suffix:              Desired address suffix.
            regex:               Full regex pattern to match against address.
            case_sensitive:      Whether matching is case-sensitive.
            workers:             Number of parallel search workers.
            max_attempts_per_worker: Stop after this many attempts per worker.

        Returns:
            VanityResult or None if not found within max_attempts.
        """
        if prefix is None and suffix is None and regex is None:
            raise ValueError("Provide at least one of: prefix, suffix, regex.")

        pattern = self._build_pattern(prefix, suffix, regex)

        chain_lower = chain.lower()
        if chain_lower not in {
            "ethereum", "bsc", "polygon", "arbitrum", "optimism",
            "avalanche", "base", "fantom",
        }:
            raise NotImplementedError(
                f"Vanity generation for '{chain}' is not yet supported. "
                "EVM chains are supported."
            )

        start = time.perf_counter()
        total_attempts = 0

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_evm_worker, pattern, case_sensitive, max_attempts_per_worker)
                for _ in range(workers)
            ]
            for future in as_completed(futures):
                result = future.result()
                total_attempts += max_attempts_per_worker
                if result:
                    # Cancel remaining workers
                    for f in futures:
                        f.cancel()
                    return VanityResult(
                        address=result["address"],
                        private_key=result["private_key"],
                        attempts=result["attempts"],
                        elapsed_seconds=time.perf_counter() - start,
                    )

        return None  # not found within budget

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pattern(
        prefix: Optional[str],
        suffix: Optional[str],
        regex: Optional[str],
    ) -> str:
        if regex:
            return regex
        parts: list[str] = []
        if prefix:
            parts.append(f"^{re.escape(prefix)}")
        if suffix:
            parts.append(f"{re.escape(suffix)}$")
        if len(parts) == 2:
            # Both prefix and suffix – must match start and end separately
            return f"(?:{parts[0]})|(?:{parts[1]})"
        return parts[0]
