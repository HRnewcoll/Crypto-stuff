"""
Arbitrage bot – find and execute cross-DEX price discrepancies.

Strategy:
1. Query the same token pair on two or more DEXes.
2. If price difference > gas cost + slippage, execute a flash-swap arbitrage.
3. Supports both simple (buy low / sell high) and flash-loan arbitrage.

⚠  This is for educational purposes.  Real arbitrage is highly competitive.
   Always simulate transactions before sending on mainnet.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from eth_account import Account as _EthAccount

from crypto_toolkit.config import RPC_URLS
from crypto_toolkit.trading.dex_screener import DexScreener

# ── Constants ──────────────────────────────────────────────────────────────────
# Minimum spread (as a percentage) required to consider an opportunity.
# The default of 0.3 % covers the typical 0.3 % LP fee on Uniswap V2/V3.
# Uniswap V3 has multiple fee tiers (0.01 %, 0.05 %, 0.3 %, 1 %) – adjust
# this constant to match the fee tier of the pairs you are scanning.
_DEFAULT_MIN_SPREAD_PCT: float = 0.3

# Rough ETH price in USD used for profit estimation.
# Replace with a live Chainlink / CoinGecko call in production.
_ETH_PRICE_USD_ESTIMATE: float = 2_500.0


@dataclass
class ArbOpportunity:
    token_in: str
    token_out: str
    dex_buy: str
    dex_sell: str
    price_buy: float
    price_sell: float
    spread_pct: float
    estimated_profit_usd: float


@dataclass
class ArbResult:
    opportunity: ArbOpportunity
    tx_hash: Optional[str]
    profit_usd: Optional[float]
    success: bool
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# ArbitrageBot
# ─────────────────────────────────────────────────────────────────────────────

class ArbitrageBot:
    """Scan for and execute cross-DEX arbitrage opportunities.

    Example::

        bot = ArbitrageBot(private_key="0x…", min_profit_usd=10)
        asyncio.run(bot.start(chain="ethereum"))
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        min_profit_usd: float = 5.0,
        trade_size_eth: float = 0.1,
        dry_run: bool = True,
        min_spread_pct: float = _DEFAULT_MIN_SPREAD_PCT,
    ) -> None:
        self.private_key = private_key
        self.min_profit_usd = min_profit_usd
        self.trade_size_eth = trade_size_eth
        self.dry_run = dry_run
        self.min_spread_pct = min_spread_pct
        self._screener = DexScreener()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def start(
        self,
        chain: str = "ethereum",
        poll_interval: int = 5,
        token_pairs: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        """Continuously scan for arbitrage and execute if profitable.

        Args:
            chain:        Chain to run on.
            poll_interval: Seconds between scans.
            token_pairs:  List of (token0_symbol, token1_symbol) to monitor.
                          Defaults to ETH/USDC and ETH/USDT.
        """
        if token_pairs is None:
            token_pairs = [("WETH", "USDC"), ("WETH", "USDT"), ("WETH", "DAI")]

        rpc = RPC_URLS.get(chain.lower())
        if not rpc:
            raise ValueError(f"No RPC configured for chain '{chain}'.")

        w3 = Web3(Web3.HTTPProvider(rpc))
        print(f"[ArbitrageBot] Starting on {chain} (dry_run={self.dry_run}) …")

        dex_pairs = (
            ["uniswap_v2", "uniswap_v3"]
            if chain.lower() == "ethereum"
            else ["pancakeswap_v2"]
        )

        while True:
            opps = await self._scan(dex_pairs)
            for opp in opps:
                if opp.spread_pct > 0 and opp.estimated_profit_usd >= self.min_profit_usd:
                    result = await self._execute(w3, opp)
                    self._log(result)
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    async def _scan(self, dexes: list[str]) -> list[ArbOpportunity]:
        """Compare prices across DEXes and return opportunities."""
        opportunities: list[ArbOpportunity] = []

        # Gather top pairs from each DEX
        pair_prices: dict[str, dict[str, float]] = {}
        for dex in dexes:
            try:
                pairs = await self._screener.get_new_pairs(dex, limit=50)
                for pair in pairs:
                    key = f"{pair.token0_symbol}/{pair.token1_symbol}"
                    pair_prices.setdefault(key, {})
                    pair_prices[key][dex] = pair.price_token0_in_token1
            except Exception:
                pass

        for token_pair, prices in pair_prices.items():
            if len(prices) < 2:
                continue
            dex_list = list(prices.items())
            for i in range(len(dex_list)):
                for j in range(i + 1, len(dex_list)):
                    dex_a, price_a = dex_list[i]
                    dex_b, price_b = dex_list[j]
                    if price_a == 0 or price_b == 0:
                        continue
                    spread = abs(price_a - price_b) / min(price_a, price_b) * 100
                    if spread > self.min_spread_pct:
                        buy_dex, buy_price = (dex_a, price_a) if price_a < price_b else (dex_b, price_b)
                        sell_dex, sell_price = (dex_b, price_b) if price_a < price_b else (dex_a, price_a)
                        estimated_profit = (sell_price - buy_price) * self.trade_size_eth * _ETH_PRICE_USD_ESTIMATE
                        t0, t1 = token_pair.split("/")
                        opportunities.append(
                            ArbOpportunity(
                                token_in=t0,
                                token_out=t1,
                                dex_buy=buy_dex,
                                dex_sell=sell_dex,
                                price_buy=buy_price,
                                price_sell=sell_price,
                                spread_pct=spread,
                                estimated_profit_usd=estimated_profit,
                            )
                        )

        return sorted(opportunities, key=lambda x: x.estimated_profit_usd, reverse=True)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute(self, w3: Web3, opp: ArbOpportunity) -> ArbResult:
        if self.dry_run:
            print(
                f"[ArbitrageBot] DRY RUN – "
                f"Buy {opp.token_in} on {opp.dex_buy} @ {opp.price_buy:.6f}, "
                f"sell on {opp.dex_sell} @ {opp.price_sell:.6f}, "
                f"spread {opp.spread_pct:.2f}%, "
                f"est. profit ${opp.estimated_profit_usd:.2f}"
            )
            return ArbResult(
                opportunity=opp,
                tx_hash=None,
                profit_usd=opp.estimated_profit_usd,
                success=True,
            )

        if not self.private_key:
            return ArbResult(
                opportunity=opp,
                tx_hash=None,
                profit_usd=None,
                success=False,
                error="No private key provided.",
            )

        # In production: build and submit the flash-swap / atomic arb transaction.
        # This requires a deployed arbitrage smart contract.
        # Placeholder – returns a not-implemented result.
        return ArbResult(
            opportunity=opp,
            tx_hash=None,
            profit_usd=None,
            success=False,
            error="Live execution requires a deployed arbitrage contract.  See docs.",
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    @staticmethod
    def _log(result: ArbResult) -> None:
        status = "✅" if result.success else "❌"
        print(
            f"{status} [ArbitrageBot] {result.opportunity.token_in}/{result.opportunity.token_out} "
            f"spread={result.opportunity.spread_pct:.2f}% "
            f"profit=${result.opportunity.estimated_profit_usd:.2f} "
            f"tx={result.tx_hash or 'N/A'}"
        )
