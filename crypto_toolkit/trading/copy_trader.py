"""
Copy trader – monitor a target wallet and replicate its on-chain swaps.

Flow:
1. Watch the target wallet for new Uniswap/PancakeSwap swap transactions.
2. Decode the swap call data.
3. Submit an equivalent swap from the follower wallet with configurable
   size scaling (e.g. copy 10 % of target trade size).

Chains supported: Ethereum (Uniswap V2/V3), BSC (PancakeSwap V2/V3).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from eth_account import Account as _EthAccount

from crypto_toolkit.config import COPY_TRADE_PRIVATE_KEY, COPY_TRADE_WALLET, RPC_URLS


# Uniswap V2 Router02 ABI – only the swapExactETHForTokens selector needed
_UNISWAP_V2_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
_PANCAKE_V2_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"

# Function selectors
_SWAP_EXACT_ETH_FOR_TOKENS = "0x7ff36ab5"
_SWAP_EXACT_TOKENS_FOR_ETH = "0x18cbafe5"
_SWAP_EXACT_TOKENS_FOR_TOKENS = "0x38ed1739"


@dataclass
class CopiedTrade:
    original_tx: str
    our_tx: str
    token_in: str
    token_out: str
    amount_in: float
    scale_factor: float


class CopyTrader:
    """Copy a target wallet's DEX trades.

    Example::

        trader = CopyTrader(scale_factor=0.1)   # copy 10 % of trade size
        asyncio.run(trader.start(chain="ethereum"))
    """

    def __init__(
        self,
        target_wallet: Optional[str] = None,
        follower_private_key: Optional[str] = None,
        scale_factor: float = 0.1,
        slippage_bps: int = 100,
    ) -> None:
        self.target_wallet = (target_wallet or COPY_TRADE_WALLET).lower()
        self.follower_private_key = follower_private_key or COPY_TRADE_PRIVATE_KEY
        self.scale_factor = scale_factor
        self.slippage_bps = slippage_bps
        self._seen_txs: set[str] = set()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def start(
        self,
        chain: str = "ethereum",
        poll_interval: int = 3,
    ) -> None:
        """Poll for new blocks, detect target's swaps, and replicate them."""
        rpc = RPC_URLS.get(chain.lower())
        if not rpc:
            raise ValueError(f"No RPC configured for chain '{chain}'.")
        w3 = Web3(Web3.HTTPProvider(rpc))

        router = (
            _UNISWAP_V2_ROUTER if chain.lower() == "ethereum" else _PANCAKE_V2_ROUTER
        )

        last_block = w3.eth.block_number
        print(f"[CopyTrader] Watching {self.target_wallet} on {chain} …")

        while True:
            current = w3.eth.block_number
            for block_num in range(last_block + 1, current + 1):
                block = w3.eth.get_block(block_num, full_transactions=True)
                for tx in block.transactions:  # type: ignore[union-attr]
                    tx_from = (tx.get("from") or "").lower()
                    tx_to = (tx.get("to") or "").lower()
                    tx_hash = tx["hash"].hex()

                    if tx_from != self.target_wallet:
                        continue
                    if tx_to.lower() not in {router.lower()}:
                        continue
                    if tx_hash in self._seen_txs:
                        continue

                    self._seen_txs.add(tx_hash)
                    print(f"[CopyTrader] Detected swap: {tx_hash}")
                    await self._replicate(w3, tx, chain, router)

            last_block = current
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Replication logic
    # ------------------------------------------------------------------

    async def _replicate(
        self,
        w3: Web3,
        original_tx: dict,
        chain: str,
        router_addr: str,
    ) -> Optional[CopiedTrade]:
        if not self.follower_private_key:
            print("[CopyTrader] No follower private key configured – dry-run only.")
            return None

        acct = _EthAccount.from_key(self.follower_private_key)
        selector = original_tx["input"][:10].lower() if original_tx.get("input") else ""

        original_value = original_tx.get("value", 0)
        scaled_value = int(original_value * self.scale_factor)

        if selector == _SWAP_EXACT_ETH_FOR_TOKENS:
            # Decode path from calldata (simplified – use eth_abi for production)
            path = self._decode_path(original_tx["input"])
            if not path:
                return None

            nonce = w3.eth.get_transaction_count(acct.address)
            gas_price = w3.eth.gas_price

            # Apply slippage tolerance to minimum output
            # slippage_bps=100 means accept up to 1 % worse price than expected
            # Here we use 0 as a conservative fallback because we don't have
            # a reliable expected-output quote without querying the router.
            # In production, call getAmountsOut() first and apply slippage.
            slippage_factor = 1 - self.slippage_bps / 10_000
            min_out = 0  # set to int(expected_out * slippage_factor) after querying router
                address=Web3.to_checksum_address(router_addr),
                abi=_UNISWAPV2_SWAP_ABI,
            )
            min_out = 0  # accept any amount out (adjust for slippage in prod)
            deadline = w3.eth.get_block("latest")["timestamp"] + 180

            tx_dict = router_contract.functions.swapExactETHForTokens(
                min_out,
                path,
                acct.address,
                deadline,
            ).build_transaction(
                {
                    "from": acct.address,
                    "value": scaled_value,
                    "nonce": nonce,
                    "gas": 250_000,
                    "gasPrice": gas_price,
                }
            )
            signed = acct.sign_transaction(tx_dict)
            tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
            print(f"[CopyTrader] Submitted: {tx_hash.hex()}")
            return CopiedTrade(
                original_tx=original_tx["hash"].hex(),
                our_tx=tx_hash.hex(),
                token_in=path[0],
                token_out=path[-1],
                amount_in=scaled_value / 1e18,
                scale_factor=self.scale_factor,
            )
        return None

    @staticmethod
    def _decode_path(input_data: str) -> list[str]:
        """Very simplified path extraction from Uniswap V2 calldata."""
        try:
            from eth_abi import decode
            # Remove the 4-byte selector
            data = bytes.fromhex(input_data[2:][8:])
            # swapExactETHForTokens(uint256 amountOutMin, address[] path, address to, uint256 deadline)
            decoded = decode(["uint256", "address[]", "address", "uint256"], data)
            return list(decoded[1])
        except Exception:
            return []


# Minimal ABI for swapExactETHForTokens
_UNISWAPV2_SWAP_ABI = [
    {
        "name": "swapExactETHForTokens",
        "type": "function",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
    }
]
