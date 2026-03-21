"""
Fund / balance checker – query native coin and ERC-20 token balances.

Supports any EVM chain and Solana.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from crypto_toolkit.config import EXPLORER_API_KEYS, EXPLORER_API_URLS, RPC_URLS

# Minimal ERC-20 ABI for balanceOf + decimals + symbol
_ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


@dataclass
class Balance:
    chain: str
    address: str
    symbol: str
    balance: float
    token_contract: Optional[str] = None


class FundChecker:
    """Check native coin and ERC-20 token balances.

    Example::

        checker = FundChecker()
        bal = checker.get_native_balance("0xABC…", chain="ethereum")
        print(f"{bal.balance} {bal.symbol}")

        tokens = checker.get_token_balances("0xABC…", chain="bsc")
    """

    # ------------------------------------------------------------------
    # Native balance
    # ------------------------------------------------------------------

    def get_native_balance(self, address: str, chain: str = "ethereum") -> Balance:
        """Return the native coin balance of an address.

        Uses the JSON-RPC ``eth_getBalance`` call.
        """
        from web3 import Web3

        rpc = RPC_URLS.get(chain.lower())
        if not rpc:
            raise ValueError(f"No RPC URL configured for chain '{chain}'.")

        w3 = Web3(Web3.HTTPProvider(rpc))
        checksum = Web3.to_checksum_address(address)
        raw = w3.eth.get_balance(checksum)
        eth_value = w3.from_wei(raw, "ether")

        symbol_map = {
            "ethereum": "ETH",
            "bsc": "BNB",
            "polygon": "MATIC",
            "arbitrum": "ETH",
            "optimism": "ETH",
            "avalanche": "AVAX",
            "base": "ETH",
        }
        symbol = symbol_map.get(chain.lower(), "ETH")

        return Balance(
            chain=chain,
            address=address,
            symbol=symbol,
            balance=float(eth_value),
        )

    # ------------------------------------------------------------------
    # ERC-20 balances via block-explorer API
    # ------------------------------------------------------------------

    def get_token_balances(
        self,
        address: str,
        chain: str = "ethereum",
    ) -> list[Balance]:
        """Return ERC-20 token balances via the block-explorer tokenlist API."""
        api_url = EXPLORER_API_URLS.get(chain.lower())
        api_key = EXPLORER_API_KEYS.get(chain.lower(), "")
        if not api_url:
            raise ValueError(f"No explorer API configured for chain '{chain}'.")

        params = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "sort": "desc",
            "apikey": api_key,
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "1":
            return []

        # Aggregate unique tokens
        seen: dict[str, Balance] = {}
        for tx in data.get("result", []):
            contract = tx.get("contractAddress", "").lower()
            symbol = tx.get("tokenSymbol", "")
            decimals = int(tx.get("tokenDecimal", 18))
            if contract in seen:
                continue
            # Query exact balance via RPC
            bal = self._erc20_balance(address, contract, chain, symbol, decimals)
            seen[contract] = bal

        return list(seen.values())

    def _erc20_balance(
        self,
        owner: str,
        contract: str,
        chain: str,
        symbol: str,
        decimals: int,
    ) -> Balance:
        from web3 import Web3

        rpc = RPC_URLS.get(chain.lower(), "")
        w3 = Web3(Web3.HTTPProvider(rpc))
        token = w3.eth.contract(
            address=Web3.to_checksum_address(contract),
            abi=_ERC20_ABI,
        )
        raw = token.functions.balanceOf(Web3.to_checksum_address(owner)).call()
        balance = raw / (10 ** decimals)
        return Balance(
            chain=chain,
            address=owner,
            symbol=symbol,
            balance=balance,
            token_contract=contract,
        )

    # ------------------------------------------------------------------
    # Solana balance
    # ------------------------------------------------------------------

    def get_solana_balance(self, pubkey: str) -> Balance:
        """Return the SOL balance of a Solana public key."""
        from crypto_toolkit.config import SOLANA_RPC_URL

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey],
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(SOLANA_RPC_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        lamports = data.get("result", {}).get("value", 0)
        return Balance(
            chain="solana",
            address=pubkey,
            symbol="SOL",
            balance=lamports / 1e9,
        )
