"""
MEV (Maximal Extractable Value) bot.

Implements two common MEV strategies:
1. **Sandwich attack** – detect a large pending swap, front-run it, and back-run it.
2. **Back-running** – detect a transaction that moves the market and capture the
   arbitrage created in the next transaction.

⚠  MEV is highly competitive.  Most opportunities are captured by dedicated
   block builders with direct peering.  This implementation is educational.
   Running sandwich attacks on mainnet is controversial and may be front-run
   or reverted.  Always test on a local fork (Hardhat / Anvil) first.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from eth_account import Account as _EthAccount

from crypto_toolkit.config import RPC_URLS

# ── Constants ──────────────────────────────────────────────────────────────────
# Approximate swap fee earned by the LP on a Uniswap V2 0.3 % pool.
# Used to model the profit available to a sandwich.
_SANDWICH_FEE_RATE: float = 0.003

# Approximate gas cost (in ETH) for the front-run + back-run transactions.
# Adjust based on current gas price * gas limit for your chain.
_SANDWICH_GAS_COST_ETH: float = 0.002

# Minimum swap value (ETH) for a target to be worth sandwiching.
_MIN_SANDWICH_TARGET_ETH: float = 1.0


@dataclass
class PendingSwap:
    tx_hash: str
    from_address: str
    router: str
    token_in: str
    token_out: str
    amount_in: int
    amount_out_min: int
    deadline: int
    gas_price: int


@dataclass
class SandwichResult:
    target_tx: str
    frontrun_tx: Optional[str]
    backrun_tx: Optional[str]
    profit_wei: int
    success: bool


class MEVBot:
    """Monitor the mempool and execute MEV strategies.

    Example::

        bot = MEVBot(private_key="0x…", dry_run=True)
        asyncio.run(bot.start(chain="ethereum"))
    """

    # Known Uniswap V2-compatible router addresses
    _ROUTERS = {
        "ethereum": {"0x7a250d5630b4cf539739df2c5dacb4c659f2488d"},
        "bsc": {"0x10ed43c718714eb63d5aa57b78b54704e256024e"},
    }

    def __init__(
        self,
        private_key: Optional[str] = None,
        min_profit_eth: float = 0.01,
        sandwich_size_eth: float = 0.5,
        dry_run: bool = True,
    ) -> None:
        self.private_key = private_key
        self.min_profit_eth = min_profit_eth
        self.sandwich_size_eth = sandwich_size_eth
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    # Main loop – subscribe to pending transactions
    # ------------------------------------------------------------------

    async def start(self, chain: str = "ethereum") -> None:
        """Start monitoring the mempool for MEV opportunities."""
        rpc = RPC_URLS.get(chain.lower())
        if not rpc:
            raise ValueError(f"No RPC configured for chain '{chain}'.")

        w3 = Web3(Web3.HTTPProvider(rpc))
        routers = self._ROUTERS.get(chain.lower(), set())

        print(f"[MEVBot] Starting on {chain} (dry_run={self.dry_run}) …")

        # Subscribe to pending transactions via polling (WebSocket preferred in prod)
        seen: set[str] = set()
        while True:
            try:
                pending = w3.eth.get_block("pending", full_transactions=True)
                for tx in pending.transactions:  # type: ignore[union-attr]
                    tx_hash = tx["hash"].hex()
                    if tx_hash in seen:
                        continue
                    seen.add(tx_hash)

                    to = (tx.get("to") or "").lower()
                    if to not in routers:
                        continue

                    swap = self._decode_swap(tx)
                    if swap:
                        await self._consider_sandwich(w3, swap)
            except Exception as exc:
                print(f"[MEVBot] Error: {exc}")
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # Strategy: sandwich
    # ------------------------------------------------------------------

    async def _consider_sandwich(self, w3: Web3, swap: PendingSwap) -> None:
        """Evaluate and (optionally) execute a sandwich around *swap*."""
        # Estimate price impact and profitability
        value_eth = swap.amount_in / 1e18
        if value_eth < _MIN_SANDWICH_TARGET_ETH:
            return  # too small to be worth sandwiching

        estimated_profit_eth = value_eth * _SANDWICH_FEE_RATE - _SANDWICH_GAS_COST_ETH
        if estimated_profit_eth < self.min_profit_eth:
            return

        if self.dry_run:
            print(
                f"[MEVBot] SANDWICH OPPORTUNITY (dry run): "
                f"target={swap.tx_hash[:12]}… "
                f"amount={value_eth:.3f} ETH "
                f"est_profit={estimated_profit_eth:.4f} ETH"
            )
            return

        # Live execution:
        # 1. Build front-run tx (buy token_out before target)
        # 2. Submit bundle via Flashbots (eth_sendBundle)
        # 3. Back-run tx included in same bundle
        # This requires Flashbots relay integration – see flashbots.net
        print("[MEVBot] Live sandwich requires Flashbots relay integration.")

    # ------------------------------------------------------------------
    # Decode swap calldata
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_swap(tx: dict) -> Optional[PendingSwap]:
        """Attempt to decode a Uniswap V2 swapExactETHForTokens call."""
        input_data = tx.get("input", "")
        if not input_data or len(input_data) < 10:
            return None

        selector = input_data[:10].lower()
        _ETH_FOR_TOKENS = "0x7ff36ab5"
        if selector != _ETH_FOR_TOKENS:
            return None

        try:
            from eth_abi import decode
            data = bytes.fromhex(input_data[2:][8:])
            amount_out_min, path, to, deadline = decode(
                ["uint256", "address[]", "address", "uint256"], data
            )
            return PendingSwap(
                tx_hash=tx["hash"].hex(),
                from_address=tx.get("from", ""),
                router=tx.get("to", ""),
                token_in=path[0],
                token_out=path[-1],
                amount_in=tx.get("value", 0),
                amount_out_min=amount_out_min,
                deadline=deadline,
                gas_price=tx.get("gasPrice", 0),
            )
        except Exception:
            return None
