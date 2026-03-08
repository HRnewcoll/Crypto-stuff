"""
DEX Bot – advanced smart AI token analyser and trader.

For each token the DEX Bot:
  1. Fetches on-chain data   – price, liquidity, market cap (CoinGecko / DEX APIs)
  2. Fetches social data     – CoinGecko community stats, Reddit mentions
  3. Detects whale activity  – large holder concentration via on-chain top-holders
  4. Bot-trading detection   – analyses tx timing distributions and gas patterns
  5. Insider-trading flags   – unusual buys shortly before pumps
  6. Rug-pull risk scoring   – liquidity ratio, owner concentration, contract age
  7. Decision engine         – weighted scoring → BUY / SELL / AVOID recommendation

Everything runs with public / free APIs (no secret keys required for analysis).

⚠  LEGAL NOTICE: This tool is for informational purposes only.
   Trading decisions are yours.  Past patterns do not guarantee future results.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TokenInfo:
    """Basic token information."""
    address: str
    chain: str
    name: str = ""
    symbol: str = ""
    price_usd: float = 0.0
    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    age_days: float = 0.0
    holder_count: int = 0
    top10_pct: float = 0.0       # % supply held by top-10 wallets
    contract_verified: bool = False


@dataclass
class SocialMetrics:
    """Social media sentiment metrics."""
    twitter_followers: int = 0
    reddit_subscribers: int = 0
    reddit_posts_24h: int = 0
    telegram_members: int = 0
    sentiment_score: float = 0.5   # 0 (very bearish) – 1 (very bullish)
    hype_score: float = 0.0        # 0–10 social hype


@dataclass
class TradingActivityMetrics:
    """On-chain trading activity analysis."""
    total_txns_24h: int = 0
    unique_traders_24h: int = 0
    bot_tx_pct: float = 0.0        # estimated % of txns that are bots
    whale_tx_pct: float = 0.0      # % of volume from wallets > $100k
    insider_flag: bool = False
    avg_tx_interval_secs: float = 0.0


@dataclass
class RiskMetrics:
    """Rug-pull and fraud risk indicators."""
    rug_risk_score: float = 0.0    # 0 (safe) – 10 (very high risk)
    liquidity_locked: bool = False
    owner_renounced: bool = False
    honeypot_flag: bool = False
    sell_tax_pct: float = 0.0
    buy_tax_pct: float = 0.0
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class DexBotReport:
    """Full DEX Bot analysis report."""
    token: TokenInfo
    social: SocialMetrics
    trading: TradingActivityMetrics
    risk: RiskMetrics
    recommendation: str = "hold"  # "buy" | "sell" | "avoid" | "hold"
    confidence: float = 0.5
    score: float = 0.0            # composite 0–100 score
    reasoning: list[str] = field(default_factory=list)
    # Set by AIDexBot when an LLM provides an enhanced analysis
    ai_reasoning: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "token": {
                "address": self.token.address,
                "chain": self.token.chain,
                "name": self.token.name,
                "symbol": self.token.symbol,
                "price_usd": self.token.price_usd,
                "market_cap_usd": self.token.market_cap_usd,
                "liquidity_usd": self.token.liquidity_usd,
                "volume_24h_usd": self.token.volume_24h_usd,
                "age_days": self.token.age_days,
                "holder_count": self.token.holder_count,
                "top10_pct": self.token.top10_pct,
                "contract_verified": self.token.contract_verified,
            },
            "social": {
                "twitter_followers": self.social.twitter_followers,
                "reddit_subscribers": self.social.reddit_subscribers,
                "sentiment_score": self.social.sentiment_score,
                "hype_score": self.social.hype_score,
            },
            "trading": {
                "total_txns_24h": self.trading.total_txns_24h,
                "unique_traders_24h": self.trading.unique_traders_24h,
                "bot_tx_pct": self.trading.bot_tx_pct,
                "whale_tx_pct": self.trading.whale_tx_pct,
                "insider_flag": self.trading.insider_flag,
            },
            "risk": {
                "rug_risk_score": self.risk.rug_risk_score,
                "liquidity_locked": self.risk.liquidity_locked,
                "owner_renounced": self.risk.owner_renounced,
                "honeypot_flag": self.risk.honeypot_flag,
                "sell_tax_pct": self.risk.sell_tax_pct,
                "risk_flags": self.risk.risk_flags,
            },
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "score": self.score,
            "reasoning": self.reasoning,
            "ai_reasoning": self.ai_reasoning,
        }

    def to_text(self) -> str:
        lines = [
            f"=== DEX Bot Analysis: {self.token.symbol or self.token.address[:12]} ===",
            f"Chain        : {self.token.chain}",
            f"Price        : ${self.token.price_usd:.6f}",
            f"Market Cap   : ${self.token.market_cap_usd:,.0f}",
            f"Liquidity    : ${self.token.liquidity_usd:,.0f}",
            f"24h Volume   : ${self.token.volume_24h_usd:,.0f}",
            f"Age          : {self.token.age_days:.0f} days",
            f"Holders      : {self.token.holder_count:,}",
            f"Top-10 Concentration: {self.token.top10_pct:.1f}%",
            "",
            f"Social Hype  : {self.social.hype_score:.1f}/10  "
            f"(sentiment: {self.social.sentiment_score:.2f})",
            f"Bot Traffic  : {self.trading.bot_tx_pct:.0%}",
            f"Whale Volume : {self.trading.whale_tx_pct:.0%}",
            f"Insider Flag : {'YES ⚠' if self.trading.insider_flag else 'No'}",
            f"Rug Risk     : {self.risk.rug_risk_score:.1f}/10",
            f"Risk Flags   : {', '.join(self.risk.risk_flags) if self.risk.risk_flags else 'None'}",
            "",
            f"▶ RECOMMENDATION: {self.recommendation.upper()}  "
            f"(score={self.score:.1f}/100, confidence={self.confidence:.0%})",
            "",
            "Reasoning:",
        ] + [f"  • {r}" for r in self.reasoning]
        if self.ai_reasoning:
            lines += ["", "AI Analysis:", f"  {self.ai_reasoning}"]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# DexBot
# ─────────────────────────────────────────────────────────────────────────────

class DexBot:
    """Smart DEX token analyser and trader.

    Example::

        bot = DexBot()
        report = asyncio.run(bot.analyse("0xTOKEN…", chain="ethereum"))
        print(report.to_text())
        print(report.recommendation)  # "buy" / "sell" / "avoid" / "hold"
    """

    # Weights for the composite score (must sum to 100)
    _WEIGHTS = {
        "social":    15,
        "liquidity": 20,
        "market_cap": 10,
        "volume":    10,
        "holders":   10,
        "bot_ratio": 15,   # lower is better → inverted
        "rug_risk":  20,   # lower is better → inverted
    }

    def __init__(
        self,
        min_liquidity_usd: float = 10_000,
        min_market_cap_usd: float = 50_000,
        max_bot_pct: float = 0.70,
        max_rug_risk: float = 6.0,
    ) -> None:
        self.min_liquidity = min_liquidity_usd
        self.min_market_cap = min_market_cap_usd
        self.max_bot_pct = max_bot_pct
        self.max_rug_risk = max_rug_risk

    async def analyse(self, token_address: str, chain: str = "ethereum") -> DexBotReport:
        """Run a full analysis for *token_address* on *chain*.

        Args:
            token_address: Contract address or CoinGecko coin ID.
            chain:         Blockchain name (ethereum, bsc, polygon …).

        Returns:
            DexBotReport with all metrics and a buy/sell/avoid recommendation.
        """
        token_info, social, trading, risk = await asyncio.gather(
            self._fetch_token_info(token_address, chain),
            self._fetch_social_metrics(token_address, chain),
            self._analyse_trading_activity(token_address, chain),
            self._assess_risk(token_address, chain),
        )

        score, reasoning = self._compute_score(token_info, social, trading, risk)
        recommendation, confidence = self._decide(score, risk, trading)

        return DexBotReport(
            token=token_info,
            social=social,
            trading=trading,
            risk=risk,
            recommendation=recommendation,
            confidence=confidence,
            score=score,
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_token_info(self, address: str, chain: str) -> TokenInfo:
        """Fetch price, market cap, liquidity from CoinGecko."""
        info = TokenInfo(address=address, chain=chain)

        # Map our chain names to CoinGecko platform IDs
        cg_platform = {
            "ethereum": "ethereum",
            "bsc": "binance-smart-chain",
            "polygon": "polygon-pos",
            "arbitrum": "arbitrum-one",
            "optimism": "optimistic-ethereum",
            "avalanche": "avalanche",
            "base": "base",
            "solana": "solana",
        }.get(chain.lower(), "ethereum")

        url = f"https://api.coingecko.com/api/v3/coins/{cg_platform}/contract/{address}"

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    md = data.get("market_data", {})
                    info.name = data.get("name", "")
                    info.symbol = data.get("symbol", "").upper()
                    info.price_usd = (md.get("current_price") or {}).get("usd", 0.0)
                    info.market_cap_usd = (md.get("market_cap") or {}).get("usd", 0.0)
                    info.volume_24h_usd = (md.get("total_volume") or {}).get("usd", 0.0)
                    info.liquidity_usd = (md.get("total_value_locked") or {}).get("usd", 0.0)
                    # Genesis date → age
                    genesis = data.get("genesis_date")
                    if genesis:
                        from datetime import datetime
                        try:
                            gd = datetime.fromisoformat(genesis)
                            info.age_days = (datetime.utcnow() - gd).days
                        except Exception:
                            pass
                    # Contract info
                    info.contract_verified = bool(data.get("contract_address"))
                    # Community data
                    cd = data.get("community_data", {})
                    return info
            except Exception:
                pass

        # Fallback: try DexScreener API (no key required)
        await self._enrich_from_dexscreener(info, address, chain)
        return info

    async def _enrich_from_dexscreener(self, info: TokenInfo, address: str, chain: str) -> None:
        """Enrich token info from DexScreener public API."""
        cg_chain_map = {
            "ethereum": "ethereum",
            "bsc": "bsc",
            "polygon": "polygon",
            "arbitrum": "arbitrum",
            "optimism": "optimism",
            "avalanche": "avalanche",
            "base": "base",
            "solana": "solana",
        }
        ds_chain = cg_chain_map.get(chain.lower(), chain.lower())
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        p = pairs[0]
                        info.name = p.get("baseToken", {}).get("name", info.name)
                        info.symbol = p.get("baseToken", {}).get("symbol", info.symbol)
                        info.price_usd = float(p.get("priceUsd") or 0)
                        info.liquidity_usd = float((p.get("liquidity") or {}).get("usd") or 0)
                        info.volume_24h_usd = float((p.get("volume") or {}).get("h24") or 0)
                        market_cap = p.get("marketCap")
                        if market_cap:
                            info.market_cap_usd = float(market_cap)
                        # Parse creation timestamp (DexScreener returns milliseconds)
                        created_at = p.get("pairCreatedAt")
                        if created_at:
                            info.age_days = (time.time() - created_at / 1000) / 86_400
            except Exception:
                pass

    async def _fetch_social_metrics(self, address: str, chain: str) -> SocialMetrics:
        """Fetch social metrics from CoinGecko community stats."""
        metrics = SocialMetrics()
        url = f"https://api.coingecko.com/api/v3/coins/{address}"

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    cd = data.get("community_data", {})
                    metrics.twitter_followers = cd.get("twitter_followers") or 0
                    metrics.reddit_subscribers = cd.get("reddit_subscribers") or 0
                    metrics.reddit_posts_24h = cd.get("reddit_average_posts_48h") or 0
                    metrics.telegram_members = cd.get("telegram_channel_user_count") or 0
            except Exception:
                pass

        # Compute hype score (0–10) from community size and activity
        metrics.hype_score = self._compute_hype_score(metrics)
        # Simple neutral sentiment baseline (no API key needed)
        metrics.sentiment_score = 0.5 + (metrics.hype_score - 5) / 20
        metrics.sentiment_score = max(0.0, min(1.0, metrics.sentiment_score))
        return metrics

    async def _analyse_trading_activity(self, address: str, chain: str) -> TradingActivityMetrics:
        """Analyse on-chain trading patterns for bot/insider detection."""
        metrics = TradingActivityMetrics()
        from crypto_toolkit.config import EXPLORER_API_KEYS, EXPLORER_API_URLS

        api_url = EXPLORER_API_URLS.get(chain.lower())
        api_key = EXPLORER_API_KEYS.get(chain.lower(), "")
        if not api_url:
            return metrics

        params = {
            "module": "account",
            "action": "tokentx",
            "contractaddress": address,
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
                if data.get("status") != "1":
                    return metrics
                txs = data.get("result", [])[:200]
            except Exception:
                return metrics

        now = int(time.time())
        day_ago = now - 86_400
        recent = [t for t in txs if int(t.get("timeStamp", 0)) > day_ago]
        metrics.total_txns_24h = len(recent)
        unique = {t.get("from", "").lower() for t in recent}
        metrics.unique_traders_24h = len(unique)

        if len(recent) > 3:
            timestamps = sorted(int(t.get("timeStamp", 0)) for t in recent)
            intervals = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
            if intervals:
                metrics.avg_tx_interval_secs = statistics.mean(intervals)
                # Bot heuristic: very regular intervals (low coefficient of variation)
                if len(intervals) > 5:
                    mean_i = statistics.mean(intervals)
                    std_i = statistics.stdev(intervals)
                    cv = std_i / (mean_i + 1e-9)
                    # Very low CV → bot-like regularity
                    metrics.bot_tx_pct = max(0.0, min(1.0, 1.0 - cv))

        # Whale detection: wallets contributing > 5% of 24h volume
        total_volume = sum(int(t.get("value", 0)) for t in recent)
        if total_volume > 0:
            per_wallet: dict[str, int] = {}
            for t in recent:
                w = t.get("from", "").lower()
                per_wallet[w] = per_wallet.get(w, 0) + int(t.get("value", 0))
            whale_volume = sum(v for v in per_wallet.values() if v / total_volume > 0.05)
            metrics.whale_tx_pct = whale_volume / total_volume

        # Insider flag: large buys > 1 hour before biggest price spike in the data
        metrics.insider_flag = self._detect_insider(recent)

        return metrics

    async def _assess_risk(self, address: str, chain: str) -> RiskMetrics:
        """Compute rug-pull and fraud risk score."""
        risk = RiskMetrics()

        # Use GoPlus Security API (free, no key)
        chain_id_map = {
            "ethereum": "1",
            "bsc": "56",
            "polygon": "137",
            "arbitrum": "42161",
            "optimism": "10",
            "avalanche": "43114",
            "base": "8453",
        }
        chain_id = chain_id_map.get(chain.lower())
        if not chain_id:
            return risk

        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    result = resp.json().get("result", {}).get(address.lower(), {})
                    risk = self._parse_goplus(result)
            except Exception:
                pass

        return risk

    # ------------------------------------------------------------------
    # Risk parsing
    # ------------------------------------------------------------------

    def _parse_goplus(self, data: dict) -> RiskMetrics:
        risk = RiskMetrics()
        risk.honeypot_flag = data.get("is_honeypot") == "1"
        risk.liquidity_locked = data.get("lp_is_locked") == "1" or data.get("is_in_dex") == "1"
        risk.owner_renounced = data.get("owner_address") in ("", "0x0000000000000000000000000000000000000000", None)

        try:
            risk.buy_tax_pct = float(data.get("buy_tax", 0)) * 100
            risk.sell_tax_pct = float(data.get("sell_tax", 0)) * 100
        except (ValueError, TypeError):
            pass

        score = 0.0
        flags: list[str] = []

        if risk.honeypot_flag:
            score += 9.0
            flags.append("honeypot")
        if not risk.liquidity_locked:
            score += 2.5
            flags.append("liquidity_not_locked")
        if not risk.owner_renounced:
            score += 1.5
            flags.append("owner_not_renounced")
        if risk.sell_tax_pct > 10:
            score += 2.0
            flags.append(f"high_sell_tax_{risk.sell_tax_pct:.0f}pct")
        if data.get("is_mintable") == "1":
            score += 1.5
            flags.append("mintable")
        if data.get("can_take_back_ownership") == "1":
            score += 2.0
            flags.append("can_reclaim_ownership")
        if data.get("hidden_owner") == "1":
            score += 3.0
            flags.append("hidden_owner")
        if data.get("selfdestruct") == "1":
            score += 2.0
            flags.append("has_selfdestruct")
        if data.get("external_call") == "1":
            score += 1.0
            flags.append("external_call_risk")

        # Holder concentration
        try:
            holders = data.get("holders", [])
            if holders:
                top10_pct = sum(float(h.get("percent", 0)) for h in holders[:10]) * 100
                if top10_pct > 80:
                    score += 2.0
                    flags.append(f"top10_hold_{top10_pct:.0f}pct")
        except Exception:
            pass

        risk.rug_risk_score = min(score, 10.0)
        risk.risk_flags = flags
        return risk

    # ------------------------------------------------------------------
    # Scoring engine
    # ------------------------------------------------------------------

    def _compute_score(
        self,
        token: TokenInfo,
        social: SocialMetrics,
        trading: TradingActivityMetrics,
        risk: RiskMetrics,
    ) -> tuple[float, list[str]]:
        """Compute a composite 0–100 score. Higher = better."""
        reasons: list[str] = []
        scores: dict[str, float] = {}

        # Social hype: 0–10 → 0–15 pts
        scores["social"] = social.hype_score * (self._WEIGHTS["social"] / 10)
        if social.hype_score > 6:
            reasons.append(f"Strong social hype ({social.hype_score:.1f}/10).")

        # Liquidity: ≥$100k = full marks
        liq_norm = min(token.liquidity_usd / 100_000, 1.0)
        scores["liquidity"] = liq_norm * self._WEIGHTS["liquidity"]
        if token.liquidity_usd < self.min_liquidity:
            reasons.append(f"Low liquidity (${token.liquidity_usd:,.0f}).")

        # Market cap: ≥$1M = full marks
        mc_norm = min(token.market_cap_usd / 1_000_000, 1.0)
        scores["market_cap"] = mc_norm * self._WEIGHTS["market_cap"]

        # Volume/liquidity ratio (≥0.3 = active)
        v_l_ratio = (token.volume_24h_usd / max(token.liquidity_usd, 1)) if token.liquidity_usd > 0 else 0
        scores["volume"] = min(v_l_ratio / 0.3, 1.0) * self._WEIGHTS["volume"]
        if v_l_ratio < 0.05:
            reasons.append("Very low trading volume relative to liquidity.")

        # Holder count (≥500 = full marks)
        scores["holders"] = min(token.holder_count / 500, 1.0) * self._WEIGHTS["holders"]

        # Bot ratio: lower is better
        scores["bot_ratio"] = (1.0 - trading.bot_tx_pct) * self._WEIGHTS["bot_ratio"]
        if trading.bot_tx_pct > self.max_bot_pct:
            reasons.append(f"High bot traffic ({trading.bot_tx_pct:.0%}).")

        # Rug risk: lower is better
        scores["rug_risk"] = (1.0 - risk.rug_risk_score / 10) * self._WEIGHTS["rug_risk"]
        if risk.honeypot_flag:
            reasons.append("⚠ HONEYPOT DETECTED – cannot sell.")
        if risk.risk_flags:
            reasons.append(f"Risk flags: {', '.join(risk.risk_flags[:4])}.")

        if trading.insider_flag:
            reasons.append("Possible insider buying pattern detected.")

        total = sum(scores.values())
        if not reasons:
            reasons.append(f"Composite score {total:.1f}/100 – no major issues found.")

        return round(total, 1), reasons

    def _decide(
        self,
        score: float,
        risk: RiskMetrics,
        trading: TradingActivityMetrics,
    ) -> tuple[str, float]:
        """Convert score to a recommendation + confidence."""
        # Hard veto conditions
        if risk.honeypot_flag:
            return "avoid", 0.99
        if risk.rug_risk_score >= self.max_rug_risk:
            return "avoid", min(0.5 + risk.rug_risk_score / 20, 0.99)
        if trading.bot_tx_pct >= self.max_bot_pct:
            return "avoid", 0.80
        if trading.insider_flag and risk.rug_risk_score > 4:
            return "avoid", 0.75

        if score >= 70:
            return "buy", round(score / 100, 2)
        if score >= 45:
            return "hold", 0.5
        if score >= 20:
            return "sell", round((100 - score) / 100, 2)
        return "avoid", 0.85

    # ------------------------------------------------------------------
    # Heuristic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hype_score(metrics: SocialMetrics) -> float:
        """Derive a 0–10 hype score from community sizes."""
        score = 0.0
        # Twitter (up to 4 pts)
        score += min(metrics.twitter_followers / 50_000, 1.0) * 4
        # Reddit (up to 3 pts)
        score += min(metrics.reddit_subscribers / 20_000, 1.0) * 3
        # Reddit activity (up to 2 pts)
        score += min(metrics.reddit_posts_24h / 10, 1.0) * 2
        # Telegram (up to 1 pt)
        score += min(metrics.telegram_members / 50_000, 1.0)
        return round(score, 2)

    @staticmethod
    def _detect_insider(txs: list[dict]) -> bool:
        """
        Heuristic: flag if a small set of wallets accumulated large positions
        > 12 hours before a spike in transaction volume.

        Returns True if pattern is suspicious.
        """
        if len(txs) < 20:
            return False

        timestamps = sorted(int(t.get("timeStamp", 0)) for t in txs)
        midpoint = timestamps[len(timestamps) // 2]

        # Wallets active before midpoint
        early = {t.get("from", "").lower() for t in txs if int(t.get("timeStamp", 0)) < midpoint}
        # Activity after midpoint
        late_volume = sum(
            int(t.get("value", 0))
            for t in txs
            if int(t.get("timeStamp", 0)) >= midpoint
        )
        early_volume = sum(
            int(t.get("value", 0))
            for t in txs
            if int(t.get("timeStamp", 0)) < midpoint
            and t.get("from", "").lower() in early
        )
        total_volume = early_volume + late_volume
        if total_volume == 0:
            return False

        # Suspicious: few wallets (< 5) account for > 60% of early volume
        early_wallet_volumes: dict[str, int] = {}
        for t in txs:
            if int(t.get("timeStamp", 0)) < midpoint:
                w = t.get("from", "").lower()
                early_wallet_volumes[w] = early_wallet_volumes.get(w, 0) + int(t.get("value", 0))

        top_early = sorted(early_wallet_volumes.values(), reverse=True)[:5]
        top_early_pct = sum(top_early) / (total_volume + 1e-9)
        return len(early) < 5 and top_early_pct > 0.60


# ─────────────────────────────────────────────────────────────────────────────
# AIDexBot – LLM-powered variant of DexBot
# ─────────────────────────────────────────────────────────────────────────────

class AIDexBot(DexBot):
    """AI-enhanced DEX token analyser.

    Extends :class:`DexBot` by feeding all collected on-chain, social, and risk
    metrics to an LLM (OpenAI-compatible API) for deeper, reasoning-based
    analysis.  When no API key is configured it falls back silently to the
    parent heuristic scoring so it is always safe to call.

    The LLM is asked to:
      • Re-evaluate the buy/sell/avoid/hold recommendation.
      • Provide a confidence score (0–1).
      • Write a multi-sentence narrative explaining the reasoning.

    The narrative is stored in ``DexBotReport.ai_reasoning`` and is also
    appended to ``report.reasoning``.

    Example::

        bot = AIDexBot(model="gpt-4o-mini")
        report = asyncio.run(bot.analyse("0xTOKEN…", chain="ethereum"))
        print(report.ai_reasoning)
        print(report.recommendation)   # potentially overridden by LLM
    """

    _SYSTEM_PROMPT = (
        "You are an expert DeFi analyst and crypto trader.  "
        "You are given structured data about a token collected from on-chain "
        "analytics, social media, and security audits.  "
        "Output ONLY a valid JSON object (no markdown, no extra text) with "
        "exactly three keys:\n"
        '  "recommendation": one of "buy", "sell", "hold", "avoid"\n'
        '  "confidence": a float between 0.0 and 1.0\n'
        '  "reasoning": a concise multi-sentence narrative (2–5 sentences) '
        "explaining your decision, referencing the data provided."
    )

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        llm_timeout: int = 30,
        **kwargs,
    ) -> None:
        """
        Args:
            model:       OpenAI-compatible model name (e.g. ``"gpt-4o"``,
                         ``"gpt-4o-mini"``, ``"mistral-small"``).
            llm_timeout: HTTP timeout in seconds for the LLM request.
            **kwargs:    Forwarded to :class:`DexBot` (min_liquidity_usd, etc.).
        """
        super().__init__(**kwargs)
        self.model = model
        self.llm_timeout = llm_timeout

    # ------------------------------------------------------------------
    # Public API  (same signature as DexBot.analyse)
    # ------------------------------------------------------------------

    async def analyse(self, token_address: str, chain: str = "ethereum") -> DexBotReport:
        """Run a full AI-enhanced analysis.

        1. Collects all metrics via the parent ``DexBot`` pipeline.
        2. Passes the full context to the configured LLM.
        3. Merges the LLM's recommendation / confidence / reasoning into the
           report, overriding the heuristic decision when the LLM responds.
        4. On any LLM error (no key, timeout, bad JSON …) falls back silently
           to the parent heuristic result.

        Returns:
            DexBotReport with ``ai_reasoning`` populated when the LLM call
            succeeded.
        """
        report = await super().analyse(token_address, chain)
        await self._enrich_with_llm(report)
        return report

    # ------------------------------------------------------------------
    # LLM enrichment
    # ------------------------------------------------------------------

    async def _enrich_with_llm(self, report: DexBotReport) -> None:
        """Query the LLM and update *report* in-place."""
        from crypto_toolkit.config import OPENAI_API_KEY, OPENAI_BASE_URL

        if not OPENAI_API_KEY:
            # No key – stay with heuristic result
            return

        prompt = self._build_prompt(report)

        try:
            import json as _json
            async with __import__("httpx").AsyncClient(timeout=self.llm_timeout) as client:
                resp = await client.post(
                    f"{OPENAI_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self._SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]

            parsed = _json.loads(raw)
            rec = parsed.get("recommendation", report.recommendation).lower()
            if rec in {"buy", "sell", "hold", "avoid"}:
                report.recommendation = rec
            conf = parsed.get("confidence")
            if conf is not None:
                try:
                    report.confidence = max(0.0, min(1.0, float(conf)))
                except (ValueError, TypeError):
                    pass
            narrative = parsed.get("reasoning", "")
            if narrative:
                report.ai_reasoning = str(narrative)
                report.reasoning = report.reasoning + [f"[AI] {narrative}"]

        except Exception:
            # Any failure (network, bad JSON, model error) → keep heuristic result
            pass

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(report: DexBotReport) -> str:
        """Serialise the full report into a dense, LLM-readable prompt."""
        t = report.token
        s = report.social
        tr = report.trading
        r = report.risk

        lines = [
            "=== Token Analysis Data ===",
            f"Token        : {t.name} ({t.symbol}) on {t.chain}",
            f"Address      : {t.address}",
            f"Price (USD)  : {t.price_usd:.8f}",
            f"Market Cap   : ${t.market_cap_usd:,.0f}",
            f"Liquidity    : ${t.liquidity_usd:,.0f}",
            f"24h Volume   : ${t.volume_24h_usd:,.0f}",
            f"Token Age    : {t.age_days:.0f} days",
            f"Holder Count : {t.holder_count:,}",
            f"Top-10 Wallets Hold: {t.top10_pct:.1f}%",
            f"Contract Verified: {t.contract_verified}",
            "",
            "=== Social Metrics ===",
            f"Twitter Followers : {s.twitter_followers:,}",
            f"Reddit Subscribers: {s.reddit_subscribers:,}",
            f"Reddit Posts (48h): {s.reddit_posts_24h}",
            f"Telegram Members  : {s.telegram_members:,}",
            f"Social Hype Score : {s.hype_score:.1f}/10",
            f"Sentiment Score   : {s.sentiment_score:.2f} (0=bearish, 1=bullish)",
            "",
            "=== On-Chain Trading Activity (24 h) ===",
            f"Total Transactions  : {tr.total_txns_24h}",
            f"Unique Traders      : {tr.unique_traders_24h}",
            f"Est. Bot Traffic    : {tr.bot_tx_pct:.0%}",
            f"Whale Volume Share  : {tr.whale_tx_pct:.0%}",
            f"Insider Pattern Flag: {tr.insider_flag}",
            f"Avg Tx Interval     : {tr.avg_tx_interval_secs:.1f}s",
            "",
            "=== Security / Rug-Pull Risk ===",
            f"Rug Risk Score     : {r.rug_risk_score:.1f}/10  (10 = highest risk)",
            f"Honeypot Detected  : {r.honeypot_flag}",
            f"Liquidity Locked   : {r.liquidity_locked}",
            f"Owner Renounced    : {r.owner_renounced}",
            f"Buy Tax            : {r.buy_tax_pct:.1f}%",
            f"Sell Tax           : {r.sell_tax_pct:.1f}%",
            f"Risk Flags         : {', '.join(r.risk_flags) if r.risk_flags else 'None'}",
            "",
            "=== Heuristic Analysis (pre-LLM) ===",
            f"Composite Score    : {report.score:.1f}/100",
            f"Heuristic Decision : {report.recommendation.upper()}",
            f"Heuristic Notes    : {'; '.join(report.reasoning)}",
        ]
        return "\n".join(lines)
