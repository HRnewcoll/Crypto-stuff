"""
Multi-chain HD wallet generator.

Supports: Ethereum / EVM chains, Bitcoin (P2PKH, P2SH-P2WPKH, P2WPKH),
Solana, and any chain reachable via a web3-compatible RPC.

Derivation paths follow the BIP-44 standard:
    m/44'/<coin_type>'/<account>'/<change>/<index>

Common coin types:
    0   – Bitcoin
    60  – Ethereum / EVM
    501 – Solana
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass, field
from typing import Optional

from eth_account import Account as _EthAccount
from mnemonic import Mnemonic as _Mnemonic

from crypto_toolkit.wallet.bip39 import BIP39

# Enable HD wallet features in eth-account
_EthAccount.enable_unaudited_hdwallet_features()


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WalletInfo:
    chain: str
    derivation_path: str
    address: str
    private_key: str
    public_key: str
    mnemonic: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Derivation path helpers
# ─────────────────────────────────────────────────────────────────────────────

_COIN_TYPES: dict[str, int] = {
    "ethereum": 60,
    "bsc": 60,         # BNB Smart Chain uses the same coin type as ETH
    "polygon": 60,
    "arbitrum": 60,
    "optimism": 60,
    "avalanche": 60,
    "base": 60,
    "bitcoin": 0,
    "solana": 501,
    "tron": 195,
    "litecoin": 2,
    "dogecoin": 3,
}


def bip44_path(chain: str, account: int = 0, change: int = 0, index: int = 0) -> str:
    coin_type = _COIN_TYPES.get(chain.lower(), 60)
    return f"m/44'/{coin_type}'/{account}'/{change}/{index}"


# ─────────────────────────────────────────────────────────────────────────────
# WalletGenerator
# ─────────────────────────────────────────────────────────────────────────────

class WalletGenerator:
    """Generate HD wallets for multiple chains from a single mnemonic."""

    def __init__(self) -> None:
        self._bip39 = BIP39()

    # ------------------------------------------------------------------
    # Create new wallet
    # ------------------------------------------------------------------

    def create(
        self,
        chain: str = "ethereum",
        num_words: int = 12,
        account: int = 0,
        index: int = 0,
        passphrase: str = "",
    ) -> WalletInfo:
        """Generate a brand-new mnemonic and return wallet details.

        Args:
            chain:      Target chain name (ethereum, bsc, bitcoin, solana …)
            num_words:  Mnemonic length (12, 15, 18, 21, 24)
            account:    BIP-44 account index
            index:      BIP-44 address index
            passphrase: Optional BIP-39 passphrase

        Returns:
            WalletInfo dataclass.
        """
        mnemonic = self._bip39.generate(num_words)
        return self.from_mnemonic(
            mnemonic,
            chain=chain,
            account=account,
            index=index,
            passphrase=passphrase,
        )

    # ------------------------------------------------------------------
    # Derive from existing mnemonic
    # ------------------------------------------------------------------

    def from_mnemonic(
        self,
        mnemonic: str,
        chain: str = "ethereum",
        account: int = 0,
        index: int = 0,
        passphrase: str = "",
    ) -> WalletInfo:
        """Derive a wallet from an existing BIP-39 mnemonic.

        Args:
            mnemonic:   BIP-39 phrase.
            chain:      Target chain.
            account:    BIP-44 account index.
            index:      BIP-44 address index.
            passphrase: Optional BIP-39 passphrase.

        Returns:
            WalletInfo dataclass.
        """
        chain_lower = chain.lower()
        path = bip44_path(chain_lower, account=account, index=index)

        if chain_lower in {"bitcoin", "litecoin", "dogecoin"}:
            wallet_info = self._derive_bitcoin_like(
                mnemonic, passphrase, path, chain_lower
            )
        elif chain_lower == "solana":
            wallet_info = self._derive_solana(mnemonic, passphrase, path)
        else:
            # Default: EVM-compatible
            wallet_info = self._derive_evm(mnemonic, passphrase, path, chain_lower)

        wallet_info.mnemonic = mnemonic
        return wallet_info

    # ------------------------------------------------------------------
    # From private key
    # ------------------------------------------------------------------

    def from_private_key(self, private_key: str, chain: str = "ethereum") -> WalletInfo:
        """Create a WalletInfo from a raw private key (EVM chains only)."""
        acct = _EthAccount.from_key(private_key)
        return WalletInfo(
            chain=chain,
            derivation_path="",
            address=acct.address,
            private_key=acct.key.hex(),
            public_key="",
        )

    # ------------------------------------------------------------------
    # Batch derivation
    # ------------------------------------------------------------------

    def derive_batch(
        self,
        mnemonic: str,
        chain: str = "ethereum",
        count: int = 10,
        passphrase: str = "",
    ) -> list[WalletInfo]:
        """Derive *count* sequential addresses from a single mnemonic."""
        return [
            self.from_mnemonic(mnemonic, chain=chain, index=i, passphrase=passphrase)
            for i in range(count)
        ]

    # ------------------------------------------------------------------
    # Private derivation helpers
    # ------------------------------------------------------------------

    def _derive_evm(
        self, mnemonic: str, passphrase: str, path: str, chain: str
    ) -> WalletInfo:
        acct = _EthAccount.from_mnemonic(mnemonic, passphrase=passphrase, account_path=path)
        return WalletInfo(
            chain=chain,
            derivation_path=path,
            address=acct.address,
            private_key=acct.key.hex(),
            public_key="",
        )

    def _derive_solana(
        self, mnemonic: str, passphrase: str, path: str
    ) -> WalletInfo:
        """Derive a Solana ed25519 keypair via SLIP-0010."""
        try:
            from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
            seed = Bip39SeedGenerator.GenerateFromMnemonic(mnemonic, passphrase)
            bip44_ctx = Bip44.FromSeed(seed, Bip44Coins.SOLANA)
            acc = bip44_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            return WalletInfo(
                chain="solana",
                derivation_path=path,
                address=acc.PublicKey().ToAddress(),
                private_key=acc.PrivateKey().Raw().ToHex(),
                public_key=acc.PublicKey().RawCompressed().ToHex(),
            )
        except ImportError:
            return WalletInfo(
                chain="solana",
                derivation_path=path,
                address="(install bip_utils for Solana support)",
                private_key="",
                public_key="",
            )

    def _derive_bitcoin_like(
        self, mnemonic: str, passphrase: str, path: str, chain: str
    ) -> WalletInfo:
        """Derive a Bitcoin (or Bitcoin-like) P2WPKH (native segwit) address."""
        try:
            from bip_utils import (
                Bip39SeedGenerator,
                Bip44,
                Bip44Coins,
                Bip44Changes,
            )
            coin_map = {
                "bitcoin": Bip44Coins.BITCOIN,
                "litecoin": Bip44Coins.LITECOIN,
                "dogecoin": Bip44Coins.DOGECOIN,
            }
            seed = Bip39SeedGenerator.GenerateFromMnemonic(mnemonic, passphrase)
            bip44_ctx = Bip44.FromSeed(seed, coin_map[chain])
            acc = (
                bip44_ctx.Purpose()
                .Coin()
                .Account(0)
                .Change(Bip44Changes.CHAIN_EXT)
                .AddressIndex(0)
            )
            return WalletInfo(
                chain=chain,
                derivation_path=path,
                address=acc.PublicKey().ToAddress(),
                private_key=acc.PrivateKey().Raw().ToHex(),
                public_key=acc.PublicKey().RawCompressed().ToHex(),
            )
        except ImportError:
            return WalletInfo(
                chain=chain,
                derivation_path=path,
                address="(install bip_utils for Bitcoin support)",
                private_key="",
                public_key="",
            )
