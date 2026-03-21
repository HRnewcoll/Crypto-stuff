"""
Wallet tracker – monitor multiple addresses across EVM chains.

Polls block explorers for new transactions and fires callbacks.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from crypto_toolkit.config import EXPLORER_API_KEYS, EXPLORER_API_URLS


@dataclass
class Transaction:
    chain: str
    tx_hash: str
    block_number: int
    from_address: str
    to_address: str
    value_eth: float
    timestamp: int
    gas_used: Optional[int] = None
    token_symbol: Optional[str] = None


TransactionCallback = Callable[[Transaction], None]


class WalletTracker:
    """Track one or more wallet addresses for new transactions.

    Example::

        tracker = WalletTracker()
        tracker.add_wallet("0xABC…", chain="ethereum")
        tracker.on_transaction(lambda tx: print(tx))
        asyncio.run(tracker.start(poll_interval=15))
    """

    def __init__(self) -> None:
        self._wallets: dict[str, list[str]] = {}   # chain → [addresses]
        self._seen_txs: set[str] = set()
        self._callbacks: list[TransactionCallback] = []
        self._last_blocks: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_wallet(self, address: str, chain: str = "ethereum") -> None:
        """Add a wallet address to track."""
        chain = chain.lower()
        self._wallets.setdefault(chain, [])
        if address not in self._wallets[chain]:
            self._wallets[chain].append(address)

    def remove_wallet(self, address: str, chain: str = "ethereum") -> None:
        chain = chain.lower()
        if chain in self._wallets:
            self._wallets[chain] = [a for a in self._wallets[chain] if a != address]

    def on_transaction(self, callback: TransactionCallback) -> None:
        """Register a callback invoked for every new transaction."""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def start(self, poll_interval: int = 15) -> None:
        """Start the tracking loop (runs until cancelled)."""
        while True:
            for chain, addresses in self._wallets.items():
                for address in addresses:
                    await self._check_address(chain, address)
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _check_address(self, chain: str, address: str) -> None:
        if chain not in EXPLORER_API_URLS:
            return
        api_url = EXPLORER_API_URLS[chain]
        api_key = EXPLORER_API_KEYS.get(chain, "")
        start_block = self._last_blocks.get(f"{chain}:{address}", 0)

        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block,
            "endblock": 99999999,
            "sort": "asc",
            "apikey": api_key,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(api_url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                return

        if data.get("status") != "1":
            return

        txs: list[dict] = data.get("result", [])
        for raw in txs:
            tx_hash = raw.get("hash", "")
            if tx_hash in self._seen_txs:
                continue
            self._seen_txs.add(tx_hash)
            tx = Transaction(
                chain=chain,
                tx_hash=tx_hash,
                block_number=int(raw.get("blockNumber", 0)),
                from_address=raw.get("from", ""),
                to_address=raw.get("to", ""),
                value_eth=int(raw.get("value", 0)) / 1e18,
                timestamp=int(raw.get("timeStamp", 0)),
                gas_used=int(raw.get("gasUsed", 0)),
            )
            if txs:
                self._last_blocks[f"{chain}:{address}"] = int(txs[-1].get("blockNumber", 0))
            for cb in self._callbacks:
                try:
                    cb(tx)
                except Exception as exc:
                    print(f"[WalletTracker] callback error: {exc}")
