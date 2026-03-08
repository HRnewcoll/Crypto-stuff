"""
Fund tracer – follow-the-money forensic analysis.

This module helps law enforcement officers and fraud victims trace the flow of
funds across blockchain networks by following transactions hop-by-hop.

Features:
  • Multi-hop transaction graph traversal (BFS / DFS)
  • Known-exchange address tagging (Binance, Coinbase, Kraken …)
  • Mixer / tumbler detection heuristics (equal-amount splits, Tornado Cash)
  • High-velocity wallet detection (many small txns in a short window)
  • Risk scoring per address
  • Human-readable text and structured JSON reports

Supported chains: any EVM chain with a block-explorer API
                  (Ethereum, BSC, Polygon …) + Solana.

⚠  For lawful use only.  Tracing someone else's funds without legal
   authority may violate privacy laws in some jurisdictions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import httpx

from crypto_toolkit.config import EXPLORER_API_KEYS, EXPLORER_API_URLS


# ─────────────────────────────────────────────────────────────────────────────
# Known exchange / service address database
# ─────────────────────────────────────────────────────────────────────────────

# A non-exhaustive list of well-known exchange hot wallets (Ethereum mainnet)
_KNOWN_LABELS: dict[str, str] = {
    # Binance
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "Binance",
    "0xd551234ae421e3bcba99a0da6d736074f22192ff": "Binance",
    "0x564286362092d8e7936f0549571a803b203aaced": "Binance",
    # Coinbase
    "0xa090e606e30bd747d4e6245a1517ebe430f0057e": "Coinbase",
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase",
    # Kraken
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": "Kraken",
    "0x0a869d79a7052c7f1b55a8ebabbea3420f0d1e13": "Kraken",
    # Tornado Cash (ETH mainnet) – mixer
    "0x722122df12d4e14e13ac3b6895a86e84145b6967": "Tornado Cash (mixer)",
    "0xdd4c48c0b24039969fc16d1cdf626eab821d3384": "Tornado Cash (mixer)",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b": "Tornado Cash (mixer)",
    "0xd96f2b1c14db8458374d9aca76e26c3950113464": "Tornado Cash (mixer)",
    "0x4736dcf1b7a3d580672cce6e7c65cd5cc9cfba9d": "Tornado Cash (mixer)",
    # OKX
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX",
    # Huobi
    "0x1b3cb81e51011b549d78bf720b0d924ac763a7c2": "Huobi",
    # Uniswap Router V2 (DEX)
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router",
    # Uniswap V3
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 Router",
}

# Regex patterns for Tornado Cash note amounts (0.1, 1, 10, 100 ETH)
_TORNADO_AMOUNTS_ETH = {0.1, 1.0, 10.0, 100.0}


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Hop:
    """A single transaction in the trace path."""
    hop_number: int
    tx_hash: str
    from_address: str
    to_address: str
    value_eth: float
    timestamp: int
    block_number: int
    label_from: Optional[str] = None
    label_to: Optional[str] = None
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class AddressProfile:
    """Aggregated profile for an address encountered during tracing."""
    address: str
    label: Optional[str] = None
    total_received_eth: float = 0.0
    total_sent_eth: float = 0.0
    tx_count: int = 0
    risk_score: float = 0.0  # 0–10
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class TraceReport:
    """Full fund-trace report."""
    seed_address: str
    chain: str
    hops: list[Hop] = field(default_factory=list)
    addresses: dict[str, AddressProfile] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "seed_address": self.seed_address,
            "chain": self.chain,
            "hop_count": len(self.hops),
            "addresses_visited": len(self.addresses),
            "summary": self.summary,
            "hops": [
                {
                    "hop": h.hop_number,
                    "tx": h.tx_hash,
                    "from": h.from_address,
                    "to": h.to_address,
                    "value_eth": h.value_eth,
                    "label_from": h.label_from,
                    "label_to": h.label_to,
                    "risk_flags": h.risk_flags,
                }
                for h in self.hops
            ],
            "address_profiles": {
                addr: {
                    "label": p.label,
                    "received_eth": p.total_received_eth,
                    "sent_eth": p.total_sent_eth,
                    "tx_count": p.tx_count,
                    "risk_score": p.risk_score,
                    "risk_flags": p.risk_flags,
                }
                for addr, p in self.addresses.items()
            },
        }

    def to_text(self) -> str:
        """Return a human-readable report."""
        lines = [
            f"=== Fund Trace Report ===",
            f"Seed address : {self.seed_address}",
            f"Chain        : {self.chain}",
            f"Hops traced  : {len(self.hops)}",
            f"Addresses    : {len(self.addresses)}",
            "",
            "--- Transaction Path ---",
        ]
        for h in self.hops:
            flags = f"  ⚠ {', '.join(h.risk_flags)}" if h.risk_flags else ""
            frm = h.label_from or h.from_address[:12] + "…"
            to = h.label_to or h.to_address[:12] + "…"
            lines.append(
                f"[{h.hop_number:02d}] {frm} → {to}  {h.value_eth:.4f} ETH  "
                f"(tx: {h.tx_hash[:12]}…){flags}"
            )
        lines += ["", "--- Address Profiles ---"]
        for addr, p in self.addresses.items():
            flags = f"  ⚠ {', '.join(p.risk_flags)}" if p.risk_flags else ""
            label = f" [{p.label}]" if p.label else ""
            lines.append(
                f"{addr[:14]}…{label}  risk={p.risk_score:.1f}/10  "
                f"txns={p.tx_count}  recv={p.total_received_eth:.4f}{flags}"
            )
        if self.summary:
            lines += ["", "--- Summary ---", self.summary]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# FundTracer
# ─────────────────────────────────────────────────────────────────────────────

class FundTracer:
    """Forensic fund tracer for EVM chains.

    Example::

        tracer = FundTracer()
        report = asyncio.run(tracer.trace("0xSUSPECT…", chain="ethereum", max_depth=4))
        print(report.to_text())
        data = report.to_dict()  # JSON-serialisable
    """

    def __init__(self, min_value_eth: float = 0.0001) -> None:
        """
        Args:
            min_value_eth: Ignore outgoing transactions below this value (dust).
        """
        self.min_value_eth = min_value_eth

    async def trace(
        self,
        address: str,
        chain: str = "ethereum",
        max_depth: int = 3,
        max_branches: int = 5,
    ) -> TraceReport:
        """Trace funds from *address* up to *max_depth* hops.

        Args:
            address:      Seed address to start tracing from.
            chain:        Chain name (ethereum, bsc, polygon …).
            max_depth:    Maximum number of hops to follow.
            max_branches: Maximum outgoing branches to follow per address
                          (avoids explosion on exchange wallets).

        Returns:
            TraceReport with hops, address profiles, and a summary.
        """
        report = TraceReport(seed_address=address.lower(), chain=chain)
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(address.lower(), 0)]

        while queue:
            current_addr, depth = queue.pop(0)
            if current_addr in visited or depth > max_depth:
                continue
            visited.add(current_addr)

            txs = await self._fetch_txs(current_addr, chain)
            profile = self._build_profile(current_addr, txs)
            report.addresses[current_addr] = profile

            # Only follow outgoing transactions
            outgoing = [
                tx for tx in txs
                if tx.get("from", "").lower() == current_addr
                and float(tx.get("value", 0)) / 1e18 >= self.min_value_eth
            ]
            # Sort by value descending, take top N branches
            outgoing.sort(key=lambda t: int(t.get("value", 0)), reverse=True)
            outgoing = outgoing[:max_branches]

            for i, tx in enumerate(outgoing):
                hop_num = len(report.hops) + 1
                value_eth = int(tx.get("value", 0)) / 1e18
                to_addr = (tx.get("to") or "").lower()
                label_from = self._label(current_addr)
                label_to = self._label(to_addr)
                risk_flags = self._risk_flags(tx, value_eth)

                hop = Hop(
                    hop_number=hop_num,
                    tx_hash=tx.get("hash", ""),
                    from_address=current_addr,
                    to_address=to_addr,
                    value_eth=value_eth,
                    timestamp=int(tx.get("timeStamp", 0)),
                    block_number=int(tx.get("blockNumber", 0)),
                    label_from=label_from,
                    label_to=label_to,
                    risk_flags=risk_flags,
                )
                report.hops.append(hop)

                # Don't follow known exchange sinks (dead ends)
                if to_addr and to_addr not in visited and not self._is_exchange_sink(to_addr):
                    queue.append((to_addr, depth + 1))

        report.summary = self._generate_summary(report)
        return report

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    async def _fetch_txs(self, address: str, chain: str) -> list[dict]:
        """Fetch transaction list for an address from a block explorer."""
        api_url = EXPLORER_API_URLS.get(chain.lower())
        api_key = EXPLORER_API_KEYS.get(chain.lower(), "")
        if not api_url:
            return []

        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "sort": "desc",
            "apikey": api_key,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(api_url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "1":
                    return data.get("result", [])
            except Exception:
                pass
        return []

    # ------------------------------------------------------------------
    # Profiling
    # ------------------------------------------------------------------

    def _build_profile(self, address: str, txs: list[dict]) -> AddressProfile:
        addr_lower = address.lower()
        received = sum(
            int(t.get("value", 0)) / 1e18
            for t in txs
            if (t.get("to") or "").lower() == addr_lower
        )
        sent = sum(
            int(t.get("value", 0)) / 1e18
            for t in txs
            if (t.get("from") or "").lower() == addr_lower
        )
        profile = AddressProfile(
            address=addr_lower,
            label=self._label(addr_lower),
            total_received_eth=received,
            total_sent_eth=sent,
            tx_count=len(txs),
        )
        profile.risk_score, profile.risk_flags = self._score_address(addr_lower, txs, profile)
        return profile

    def _score_address(
        self,
        address: str,
        txs: list[dict],
        profile: AddressProfile,
    ) -> tuple[float, list[str]]:
        score = 0.0
        flags: list[str] = []

        # Known mixer
        label = self._label(address)
        if label and "mixer" in label.lower():
            score += 9.0
            flags.append("known_mixer")
            return score, flags

        # High-velocity (many txns in a short window)
        if len(txs) > 50:
            timestamps = sorted(int(t.get("timeStamp", 0)) for t in txs[:50])
            if timestamps[-1] - timestamps[0] < 3600:  # 50 txns in 1 hour
                score += 3.0
                flags.append("high_velocity")

        # Equal-amount splitting (mixer-like)
        values = [int(t.get("value", 0)) for t in txs if int(t.get("value", 0)) > 0]
        if len(values) > 3:
            most_common = max(set(values), key=values.count)
            if values.count(most_common) / len(values) > 0.6:
                score += 2.0
                flags.append("equal_amount_splitting")

        # Tornado Cash deposit amounts
        for tx in txs:
            val_eth = int(tx.get("value", 0)) / 1e18
            if val_eth in _TORNADO_AMOUNTS_ETH:
                score += 1.5
                flags.append("tornado_cash_denomination")
                break

        # New wallet (< 10 txns)
        if len(txs) < 10:
            score += 0.5
            flags.append("new_wallet")

        return min(score, 10.0), flags

    # ------------------------------------------------------------------
    # Labelling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _label(address: str) -> Optional[str]:
        return _KNOWN_LABELS.get(address.lower())

    @staticmethod
    def _is_exchange_sink(address: str) -> bool:
        label = _KNOWN_LABELS.get(address.lower(), "")
        if not label:
            return False
        lower = label.lower()
        return "mixer" not in lower and any(
            x in lower for x in ["binance", "coinbase", "kraken", "okx", "huobi", "exchange"]
        )

    # ------------------------------------------------------------------
    # Risk flags per transaction
    # ------------------------------------------------------------------

    def _risk_flags(self, tx: dict, value_eth: float) -> list[str]:
        flags: list[str] = []
        to_addr = (tx.get("to") or "").lower()
        label = self._label(to_addr)
        if label and "mixer" in label.lower():
            flags.append("mixer_destination")
        if value_eth in _TORNADO_AMOUNTS_ETH:
            flags.append("tornado_denomination")
        return flags

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_summary(report: TraceReport) -> str:
        lines: list[str] = []
        mixer_hops = [h for h in report.hops if "mixer_destination" in h.risk_flags]
        high_risk = [
            addr for addr, p in report.addresses.items() if p.risk_score >= 5
        ]
        exchange_addresses = [
            p.label for p in report.addresses.values()
            if p.label and "mixer" not in (p.label or "").lower()
            and p.label not in (None, "")
        ]

        if mixer_hops:
            lines.append(
                f"⚠  {len(mixer_hops)} transaction(s) directed to known mixers "
                f"(e.g. {mixer_hops[0].label_to})."
            )
        if high_risk:
            lines.append(f"⚠  {len(high_risk)} high-risk address(es) detected.")
        if exchange_addresses:
            unique_exchanges = list(set(exchange_addresses))
            lines.append(
                f"ℹ  Funds reached the following known service(s): "
                f"{', '.join(unique_exchanges)}.  This may help with account freezing."
            )
        if not lines:
            lines.append("No major risk indicators found in this trace.")
        return "  ".join(lines)
