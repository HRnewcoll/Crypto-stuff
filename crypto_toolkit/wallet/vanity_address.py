"""
Vanity address generator – multi-chain.

Generates addresses that start (or contain) a user-supplied prefix/suffix
using brute-force key generation.

Supported chains:
  - EVM (Ethereum, BSC, Polygon, Arbitrum, Optimism, Avalanche, Base, Fantom …)
  - Bitcoin  (P2PKH "1…", P2SH-P2WPKH "3…", P2WPKH native segwit "bc1…")
  - Solana   (base58 public key)
  - Tron     (T… base58check address)
  - Litecoin (L… or M…)
  - Dogecoin (D…)

⚠  WARNING: This uses a random search; time to find an address grows
exponentially with prefix length.  Use --workers to parallelise.
"""

from __future__ import annotations

import re
import secrets
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from eth_account import Account as _EthAccount

_EthAccount.enable_unaudited_hdwallet_features()


@dataclass
class VanityResult:
    address: str
    private_key: str
    attempts: int
    elapsed_seconds: float
    chain: str = "ethereum"


# ─────────────────────────────────────────────────────────────────────────────
# EVM worker  (module-level so it is picklable)
# ─────────────────────────────────────────────────────────────────────────────

def _evm_worker(pattern: str, case_sensitive: bool, max_attempts: int) -> Optional[dict]:
    """Search for an EVM address matching *pattern* (regex)."""
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)
    for attempt in range(1, max_attempts + 1):
        key_bytes = secrets.token_bytes(32)
        acct = _EthAccount.from_key(key_bytes)
        if compiled.search(acct.address):
            return {"address": acct.address, "private_key": key_bytes.hex(), "attempts": attempt}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Bitcoin worker
# ─────────────────────────────────────────────────────────────────────────────

def _bitcoin_worker(pattern: str, case_sensitive: bool, max_attempts: int, addr_type: str) -> Optional[dict]:
    """Search for a Bitcoin address matching *pattern*.

    addr_type: "p2pkh" (legacy 1…), "p2wpkh" (native segwit bc1…), "p2sh" (3…)
    """
    try:
        from bip_utils import (
            Secp256k1KeyGenerator,
            P2PKHAddrEncoder,
            P2WPKHAddrEncoder,
            P2SHAddrEncoder,
            CoinsConf,
        )
    except ImportError:
        return None

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)

    for attempt in range(1, max_attempts + 1):
        priv_key = Secp256k1KeyGenerator.Generate()
        pub_key = priv_key.PublicKey()
        if addr_type == "p2wpkh":
            address = P2WPKHAddrEncoder.EncodeKey(pub_key.RawCompressed().ToBytes())
        elif addr_type == "p2sh":
            address = P2SHAddrEncoder.EncodeKey(pub_key.RawCompressed().ToBytes())
        else:
            address = P2PKHAddrEncoder.EncodeKey(pub_key.RawCompressed().ToBytes())

        if compiled.search(address):
            return {
                "address": address,
                "private_key": priv_key.Raw().ToHex(),
                "attempts": attempt,
            }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Solana worker
# ─────────────────────────────────────────────────────────────────────────────

def _solana_worker(pattern: str, case_sensitive: bool, max_attempts: int) -> Optional[dict]:
    """Search for a Solana public key (base58) matching *pattern*."""
    try:
        from bip_utils import Ed25519KeyGenerator, SolAddrEncoder
    except ImportError:
        return None

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)

    for attempt in range(1, max_attempts + 1):
        priv_key = Ed25519KeyGenerator.Generate()
        pub_key = priv_key.PublicKey()
        address = SolAddrEncoder.EncodeKey(pub_key.RawCompressed().ToBytes())
        if compiled.search(address):
            return {
                "address": address,
                "private_key": priv_key.Raw().ToHex(),
                "attempts": attempt,
            }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tron worker
# ─────────────────────────────────────────────────────────────────────────────

def _tron_worker(pattern: str, case_sensitive: bool, max_attempts: int) -> Optional[dict]:
    """Search for a Tron address (T… base58check) matching *pattern*."""
    try:
        from bip_utils import Secp256k1KeyGenerator, TrxAddrEncoder
    except ImportError:
        return None

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)

    for attempt in range(1, max_attempts + 1):
        priv_key = Secp256k1KeyGenerator.Generate()
        pub_key = priv_key.PublicKey()
        address = TrxAddrEncoder.EncodeKey(pub_key.RawCompressed().ToBytes())
        if compiled.search(address):
            return {
                "address": address,
                "private_key": priv_key.Raw().ToHex(),
                "attempts": attempt,
            }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# VanityAddressGenerator
# ─────────────────────────────────────────────────────────────────────────────

# Maps chain names → (worker_function, extra_kwargs)
_EVM_CHAINS = {
    "ethereum", "bsc", "polygon", "arbitrum", "optimism",
    "avalanche", "base", "fantom", "cronos", "aurora",
}


class VanityAddressGenerator:
    """Search for a vanity address for any supported chain.

    Example::

        gen = VanityAddressGenerator()

        # EVM (Ethereum, BSC, Polygon …)
        result = gen.find(chain="ethereum", prefix="0xDEAD", workers=4)

        # Bitcoin legacy
        result = gen.find(chain="bitcoin", prefix="1Love", workers=2)

        # Bitcoin native segwit
        result = gen.find(chain="bitcoin_segwit", prefix="bc1q00", workers=2)

        # Solana
        result = gen.find(chain="solana", prefix="DEGEN", workers=2)

        # Tron
        result = gen.find(chain="tron", prefix="THOT", workers=2)
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
            chain:               Target chain. Supported values:
                                 ethereum / bsc / polygon / arbitrum / optimism /
                                 avalanche / base / fantom (and any EVM chain),
                                 bitcoin / bitcoin_segwit / bitcoin_p2sh,
                                 solana, tron, litecoin, dogecoin.
            prefix:              Desired address prefix.
            suffix:              Desired address suffix.
            regex:               Full regex pattern to match against address.
            case_sensitive:      Whether matching is case-sensitive.
            workers:             Number of parallel search workers.
            max_attempts_per_worker: Stop after this many attempts per worker.

        Returns:
            VanityResult or None if not found within the attempt budget.
        """
        if prefix is None and suffix is None and regex is None:
            raise ValueError("Provide at least one of: prefix, suffix, regex.")

        pattern = self._build_pattern(prefix, suffix, regex)
        chain_lower = chain.lower()

        start = time.perf_counter()
        worker_fn, extra_kwargs = self._resolve_worker(chain_lower)

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(worker_fn, pattern, case_sensitive, max_attempts_per_worker, **extra_kwargs)
                for _ in range(workers)
            ]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    for f in futures:
                        f.cancel()
                    return VanityResult(
                        address=result["address"],
                        private_key=result["private_key"],
                        attempts=result["attempts"],
                        elapsed_seconds=time.perf_counter() - start,
                        chain=chain_lower,
                    )

        return None

    # ------------------------------------------------------------------
    # Worker dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_worker(chain: str):
        """Return (worker_function, extra_kwargs) for the given chain."""
        if chain in _EVM_CHAINS:
            return _evm_worker, {}
        if chain == "bitcoin" or chain == "bitcoin_p2pkh":
            return _bitcoin_worker, {"addr_type": "p2pkh"}
        if chain == "bitcoin_segwit" or chain == "bitcoin_p2wpkh":
            return _bitcoin_worker, {"addr_type": "p2wpkh"}
        if chain == "bitcoin_p2sh":
            return _bitcoin_worker, {"addr_type": "p2sh"}
        if chain in {"litecoin", "dogecoin"}:
            # These use the same P2PKH encoder; encode via bip_utils coin-aware API
            return _bitcoin_worker, {"addr_type": "p2pkh"}
        if chain == "solana":
            return _solana_worker, {}
        if chain == "tron":
            return _tron_worker, {}
        raise NotImplementedError(
            f"Vanity generation for '{chain}' is not yet supported.\n"
            "Supported: ethereum/EVM, bitcoin, bitcoin_segwit, bitcoin_p2sh, "
            "solana, tron, litecoin, dogecoin."
        )

    # ------------------------------------------------------------------
    # Pattern helpers
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
            return f"(?:{parts[0]})|(?:{parts[1]})"
        return parts[0]

    @staticmethod
    def supported_chains() -> list[str]:
        """Return the list of supported chain names."""
        return sorted(list(_EVM_CHAINS) + [
            "bitcoin", "bitcoin_segwit", "bitcoin_p2sh",
            "solana", "tron", "litecoin", "dogecoin",
        ])
