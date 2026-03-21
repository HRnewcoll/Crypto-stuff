"""
DEX screener – monitor decentralised exchanges for new pairs, price feeds,
and trading volume in real time.

Supported DEXes (via public subgraph APIs):
  - Uniswap V2 / V3 (Ethereum)
  - PancakeSwap V2 / V3 (BSC)
  - QuickSwap (Polygon)
  - Any The-Graph-compatible subgraph endpoint
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


# ─────────────────────────────────────────────────────────────────────────────
# Subgraph endpoints
# ─────────────────────────────────────────────────────────────────────────────

_SUBGRAPHS: dict[str, str] = {
    "uniswap_v2": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2",
    "uniswap_v3": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3",
    "pancakeswap_v2": "https://api.thegraph.com/subgraphs/name/pancakeswap/exchange-v2",
    "quickswap": "https://api.thegraph.com/subgraphs/name/sameepsi/quickswap06",
}


@dataclass
class Pair:
    dex: str
    pair_address: str
    token0_symbol: str
    token1_symbol: str
    token0_address: str
    token1_address: str
    reserve_usd: float
    volume_usd_24h: float
    created_at_timestamp: int
    price_token0_in_token1: float = 0.0


@dataclass
class PriceUpdate:
    dex: str
    pair_address: str
    token0_symbol: str
    token1_symbol: str
    price: float
    volume_usd: float
    timestamp: int


# ─────────────────────────────────────────────────────────────────────────────
# DexScreener
# ─────────────────────────────────────────────────────────────────────────────

class DexScreener:
    """Screen DEXes for new pairs and price movements.

    Example::

        screener = DexScreener()
        new_pairs = await screener.get_new_pairs("uniswap_v2", limit=20)
        price = await screener.get_price("uniswap_v2", "0xPAIR_ADDRESS")
    """

    def __init__(self, custom_subgraphs: Optional[dict[str, str]] = None) -> None:
        self._subgraphs = {**_SUBGRAPHS, **(custom_subgraphs or {})}

    # ------------------------------------------------------------------
    # New-pair discovery
    # ------------------------------------------------------------------

    async def get_new_pairs(
        self,
        dex: str = "uniswap_v2",
        limit: int = 20,
        min_liquidity_usd: float = 1_000,
    ) -> list[Pair]:
        """Return recently created pairs ordered by creation time (newest first)."""
        endpoint = self._subgraphs.get(dex)
        if not endpoint:
            raise ValueError(f"Unknown DEX '{dex}'. Available: {list(self._subgraphs)}")

        query = """
        {
          pairs(
            first: %d
            orderBy: createdAtTimestamp
            orderDirection: desc
          ) {
            id
            token0 { id symbol }
            token1 { id symbol }
            reserveUSD
            volumeUSD
            createdAtTimestamp
            token0Price
          }
        }
        """ % limit

        data = await self._query(endpoint, query)
        pairs = []
        for raw in data.get("data", {}).get("pairs", []):
            reserve = float(raw.get("reserveUSD", 0))
            if reserve < min_liquidity_usd:
                continue
            pairs.append(
                Pair(
                    dex=dex,
                    pair_address=raw["id"],
                    token0_symbol=raw["token0"]["symbol"],
                    token1_symbol=raw["token1"]["symbol"],
                    token0_address=raw["token0"]["id"],
                    token1_address=raw["token1"]["id"],
                    reserve_usd=reserve,
                    volume_usd_24h=float(raw.get("volumeUSD", 0)),
                    created_at_timestamp=int(raw.get("createdAtTimestamp", 0)),
                    price_token0_in_token1=float(raw.get("token0Price", 0)),
                )
            )
        return pairs

    # ------------------------------------------------------------------
    # Price feed
    # ------------------------------------------------------------------

    async def get_price(
        self,
        dex: str,
        pair_address: str,
    ) -> Optional[PriceUpdate]:
        """Return the latest price for a specific pair address."""
        endpoint = self._subgraphs.get(dex)
        if not endpoint:
            raise ValueError(f"Unknown DEX '{dex}'.")

        query = """
        {
          pair(id: "%s") {
            token0 { symbol }
            token1 { symbol }
            token0Price
            volumeUSD
          }
        }
        """ % pair_address.lower()

        data = await self._query(endpoint, query)
        raw = data.get("data", {}).get("pair")
        if not raw:
            return None
        return PriceUpdate(
            dex=dex,
            pair_address=pair_address,
            token0_symbol=raw["token0"]["symbol"],
            token1_symbol=raw["token1"]["symbol"],
            price=float(raw.get("token0Price", 0)),
            volume_usd=float(raw.get("volumeUSD", 0)),
            timestamp=int(time.time()),
        )

    # ------------------------------------------------------------------
    # Continuous monitor
    # ------------------------------------------------------------------

    async def monitor_new_pairs(
        self,
        dex: str = "uniswap_v2",
        poll_interval: int = 30,
        callback=None,
    ) -> None:
        """Poll for new pairs and invoke *callback(Pair)* for each new one."""
        seen: set[str] = set()
        while True:
            try:
                pairs = await self.get_new_pairs(dex)
                for pair in pairs:
                    if pair.pair_address not in seen:
                        seen.add(pair.pair_address)
                        if callback:
                            callback(pair)
                        else:
                            print(
                                f"[DexScreener] New pair on {dex}: "
                                f"{pair.token0_symbol}/{pair.token1_symbol} "
                                f"(${pair.reserve_usd:,.0f} liquidity)"
                            )
            except Exception as exc:
                print(f"[DexScreener] Error: {exc}")
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _query(self, endpoint: str, query: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(endpoint, json={"query": query})
            resp.raise_for_status()
            return resp.json()
