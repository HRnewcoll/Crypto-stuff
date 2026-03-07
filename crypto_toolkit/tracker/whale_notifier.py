"""
Whale notifier – detect and alert on large on-chain transfers.

Monitors the pending mempool (or confirmed blocks) for transfers above a
configurable threshold and fires notifications via:
  - Telegram
  - Console / logging
  - Custom callback
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

from crypto_toolkit.config import (
    RPC_URLS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    WHALE_THRESHOLD_ETH,
)


@dataclass
class WhaleAlert:
    chain: str
    tx_hash: str
    from_address: str
    to_address: str
    value_eth: float
    block_number: int


AlertCallback = Callable[[WhaleAlert], None]


class WhaleNotifier:
    """Monitor a chain for whale-sized transfers.

    Example::

        notifier = WhaleNotifier(threshold_eth=500)
        notifier.on_alert(lambda a: print(f"WHALE: {a.value_eth} ETH"))
        asyncio.run(notifier.start(chain="ethereum"))
    """

    def __init__(self, threshold_eth: Optional[float] = None) -> None:
        self.threshold_eth = threshold_eth or WHALE_THRESHOLD_ETH
        self._callbacks: list[AlertCallback] = []

    def on_alert(self, callback: AlertCallback) -> None:
        """Register a callback invoked on every whale alert."""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Main loop – polls latest blocks
    # ------------------------------------------------------------------

    async def start(
        self,
        chain: str = "ethereum",
        poll_interval: int = 12,
    ) -> None:
        """Poll for new blocks and check transactions.  Runs until cancelled."""
        from web3 import Web3

        rpc = RPC_URLS.get(chain.lower())
        if not rpc:
            raise ValueError(f"No RPC configured for chain '{chain}'.")
        w3 = Web3(Web3.HTTPProvider(rpc))

        last_block = w3.eth.block_number
        while True:
            current = w3.eth.block_number
            for block_num in range(last_block + 1, current + 1):
                block = w3.eth.get_block(block_num, full_transactions=True)
                for tx in block.transactions:  # type: ignore[union-attr]
                    value_eth = w3.from_wei(tx["value"], "ether")
                    if float(value_eth) >= self.threshold_eth:
                        alert = WhaleAlert(
                            chain=chain,
                            tx_hash=tx["hash"].hex(),
                            from_address=tx.get("from", ""),
                            to_address=tx.get("to", "") or "",
                            value_eth=float(value_eth),
                            block_number=block_num,
                        )
                        await self._fire(alert)
            last_block = current
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    async def _fire(self, alert: WhaleAlert) -> None:
        for cb in self._callbacks:
            try:
                cb(alert)
            except Exception as exc:
                print(f"[WhaleNotifier] callback error: {exc}")
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            await self._send_telegram(alert)

    async def _send_telegram(self, alert: WhaleAlert) -> None:
        msg = (
            f"🐳 *Whale Alert* on {alert.chain.upper()}\n"
            f"Value: `{alert.value_eth:.2f}` ETH\n"
            f"From: `{alert.from_address}`\n"
            f"To: `{alert.to_address}`\n"
            f"TX: `{alert.tx_hash}`"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                await client.post(url, json=payload)
            except Exception as exc:
                print(f"[WhaleNotifier] Telegram error: {exc}")
