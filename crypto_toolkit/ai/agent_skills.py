"""
AI agent crypto skills – framework-agnostic tool wrappers.

Each skill is usable with:
  • OpenAI function-calling  (``openai_schema()``)
  • Anthropic tool-use       (``anthropic_schema()``)
  • LangChain                (``to_langchain_tool()``)
  • MCP (Model Context Protocol) (``mcp_schema()``)
  • Any other framework      (``to_dict()`` / plain callable)

Usage with OpenAI::

    from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY, execute_tool
    tools = [t.openai_schema() for t in TOOL_REGISTRY.values()]
    result = await execute_tool("generate_wallet", {"chain": "ethereum"})

Usage with LangChain::

    from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY
    lc_tools = [skill.to_langchain_tool() for skill in TOOL_REGISTRY.values()]

Usage with Anthropic::

    tools = [t.anthropic_schema() for t in TOOL_REGISTRY.values()]
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from pydantic import BaseModel


# ─────────────────────────────────────────────────────────────────────────────
# Base skill class
# ─────────────────────────────────────────────────────────────────────────────

class AgentSkill:
    """Base class for an AI-agent-callable crypto tool.

    Subclasses must set:
        name          – unique snake_case identifier
        description   – human-readable purpose (used in system prompts)
        input_schema  – Pydantic BaseModel class describing the parameters
    """

    name: str = ""
    description: str = ""
    input_schema: type[BaseModel]

    # ── OpenAI function-calling ───────────────────────────────────────────────

    def openai_schema(self) -> dict:
        """Return an OpenAI function-calling tool schema."""
        schema = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    # ── Anthropic tool-use ────────────────────────────────────────────────────

    def anthropic_schema(self) -> dict:
        """Return an Anthropic tool-use schema (Claude API format)."""
        schema = self.input_schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    # ── MCP (Model Context Protocol) ─────────────────────────────────────────

    def mcp_schema(self) -> dict:
        """Return an MCP-compatible tool descriptor."""
        schema = self.input_schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
        }

    # ── LangChain ────────────────────────────────────────────────────────────

    def to_langchain_tool(self):
        """Return a LangChain StructuredTool wrapping this skill.

        Requires ``langchain`` to be installed (``pip install langchain``).
        """
        try:
            from langchain.tools import StructuredTool  # type: ignore
        except ImportError:
            raise ImportError("Install langchain: pip install langchain")

        skill = self

        def _sync_run(**kwargs: Any) -> Any:
            # asyncio.run() works for Python 3.7+ and avoids
            # the deprecated asyncio.get_event_loop() pattern.
            return asyncio.run(skill.execute(**kwargs))

        return StructuredTool.from_function(
            func=_sync_run,
            name=self.name,
            description=self.description,
            args_schema=self.input_schema,
        )

    # ── Generic dict ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a plain dict suitable for any framework."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema.model_json_schema(),
        }

    # ── Execution ─────────────────────────────────────────────────────────────

    async def execute(self, **kwargs: Any) -> Any:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Individual skills
# ─────────────────────────────────────────────────────────────────────────────

class GenerateWalletInput(BaseModel):
    chain: str = "ethereum"
    num_words: int = 12


class GenerateWalletSkill(AgentSkill):
    name = "generate_wallet"
    description = "Generate a new HD wallet (mnemonic + address) for any chain."
    input_schema = GenerateWalletInput

    async def execute(self, chain: str = "ethereum", num_words: int = 12) -> dict:
        from crypto_toolkit.wallet.wallet_generator import WalletGenerator
        gen = WalletGenerator()
        w = gen.create(chain=chain, num_words=num_words)
        return {
            "address": w.address,
            "mnemonic": w.mnemonic,
            "private_key": w.private_key,
            "chain": w.chain,
            "derivation_path": w.derivation_path,
        }


# ──────────────────────────────────────────────────────────────────────────────

class CheckBalanceInput(BaseModel):
    address: str
    chain: str = "ethereum"


class CheckBalanceSkill(AgentSkill):
    name = "check_balance"
    description = "Check the native coin and token balances of a wallet address on any chain."
    input_schema = CheckBalanceInput

    async def execute(self, address: str, chain: str = "ethereum") -> dict:
        from crypto_toolkit.tracker.fund_checker import FundChecker
        checker = FundChecker()
        if chain.lower() == "solana":
            bal = checker.get_solana_balance(address)
        else:
            bal = checker.get_native_balance(address, chain=chain)
        return {"address": bal.address, "balance": bal.balance, "symbol": bal.symbol, "chain": bal.chain}


# ──────────────────────────────────────────────────────────────────────────────

class GetNewPairsInput(BaseModel):
    dex: str = "uniswap_v2"
    limit: int = 10
    min_liquidity_usd: float = 1000.0


class GetNewPairsSkill(AgentSkill):
    name = "get_new_dex_pairs"
    description = "Get the most recently listed token pairs on a DEX."
    input_schema = GetNewPairsInput

    async def execute(self, dex: str = "uniswap_v2", limit: int = 10, min_liquidity_usd: float = 1000.0) -> list[dict]:
        from crypto_toolkit.trading.dex_screener import DexScreener
        screener = DexScreener()
        pairs = await screener.get_new_pairs(dex, limit=limit, min_liquidity_usd=min_liquidity_usd)
        return [
            {
                "pair": f"{p.token0_symbol}/{p.token1_symbol}",
                "address": p.pair_address,
                "liquidity_usd": p.reserve_usd,
                "volume_usd_24h": p.volume_usd_24h,
            }
            for p in pairs
        ]


# ──────────────────────────────────────────────────────────────────────────────

class GetTradingSignalInput(BaseModel):
    token_id: str = "ethereum"


class GetTradingSignalSkill(AgentSkill):
    name = "get_trading_signal"
    description = (
        "Get a self-trained ML buy/sell/hold signal for a token using "
        "local technical analysis (no external API key required)."
    )
    input_schema = GetTradingSignalInput

    async def execute(self, token_id: str = "ethereum") -> dict:
        from crypto_toolkit.trading.self_trained_bot import SelfTrainedBot
        bot = SelfTrainedBot()
        signal = await bot.analyse(token_id)
        return {
            "token": signal.token,
            "action": signal.action,
            "confidence": signal.confidence,
            "price": signal.price,
            "reasoning": signal.reasoning,
        }


# ──────────────────────────────────────────────────────────────────────────────

class GenerateBip39Input(BaseModel):
    num_words: int = 12
    language: str = "english"


class GenerateBip39Skill(AgentSkill):
    name = "generate_bip39_mnemonic"
    description = "Generate a cryptographically secure BIP-39 mnemonic phrase."
    input_schema = GenerateBip39Input

    async def execute(self, num_words: int = 12, language: str = "english") -> dict:
        from crypto_toolkit.wallet.bip39 import BIP39
        b = BIP39(language=language)
        mnemonic = b.generate(num_words)
        return {"mnemonic": mnemonic, "word_count": num_words, "language": language}


# ──────────────────────────────────────────────────────────────────────────────

class FindArbitrageInput(BaseModel):
    chain: str = "ethereum"
    dry_run: bool = True


class FindArbitrageSkill(AgentSkill):
    name = "find_arbitrage"
    description = "Scan for cross-DEX arbitrage opportunities."
    input_schema = FindArbitrageInput

    async def execute(self, chain: str = "ethereum", dry_run: bool = True) -> list[dict]:
        from crypto_toolkit.trading.arbitrage_bot import ArbitrageBot
        bot = ArbitrageBot(dry_run=dry_run)
        dexes = ["uniswap_v2", "uniswap_v3"] if chain == "ethereum" else ["pancakeswap_v2"]
        opps = await bot._scan(dexes)
        return [
            {
                "pair": f"{o.token_in}/{o.token_out}",
                "buy_on": o.dex_buy,
                "sell_on": o.dex_sell,
                "spread_pct": round(o.spread_pct, 3),
                "est_profit_usd": round(o.estimated_profit_usd, 2),
            }
            for o in opps[:5]
        ]


# ──────────────────────────────────────────────────────────────────────────────

class TraceFundsInput(BaseModel):
    address: str
    chain: str = "ethereum"
    depth: int = 3


class TraceFundsSkill(AgentSkill):
    name = "trace_funds"
    description = (
        "Forensically trace the flow of funds from a given address, "
        "following transactions up to *depth* hops.  Useful for tracking "
        "stolen/suspected funds."
    )
    input_schema = TraceFundsInput

    async def execute(self, address: str, chain: str = "ethereum", depth: int = 3) -> dict:
        from crypto_toolkit.tracker.fund_tracer import FundTracer
        tracer = FundTracer()
        report = await tracer.trace(address, chain=chain, max_depth=depth)
        return report.to_dict()


# ──────────────────────────────────────────────────────────────────────────────

class DexBotAnalyseInput(BaseModel):
    token_address: str
    chain: str = "ethereum"


class DexBotAnalyseSkill(AgentSkill):
    name = "dex_bot_analyse"
    description = (
        "Analyse a token using the DEX Bot: checks social media hype, "
        "whale activity, bot/insider trading patterns, market cap, liquidity, "
        "and rug-pull risk score. Returns a buy/sell/avoid recommendation."
    )
    input_schema = DexBotAnalyseInput

    async def execute(self, token_address: str, chain: str = "ethereum") -> dict:
        from crypto_toolkit.trading.dex_bot import DexBot
        bot = DexBot()
        report = await bot.analyse(token_address, chain=chain)
        return report.to_dict()


# ──────────────────────────────────────────────────────────────────────────────

class VanityAddressInput(BaseModel):
    chain: str = "ethereum"
    prefix: str = ""
    suffix: str = ""


class VanityAddressSkill(AgentSkill):
    name = "find_vanity_address"
    description = (
        "Search for a vanity cryptocurrency address (prefix or suffix match) "
        "on any supported chain: ethereum/EVM, bitcoin, solana, tron …"
    )
    input_schema = VanityAddressInput

    async def execute(self, chain: str = "ethereum", prefix: str = "", suffix: str = "") -> dict:
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        gen = VanityAddressGenerator()
        result = gen.find(
            chain=chain,
            prefix=prefix or None,
            suffix=suffix or None,
            workers=1,
            max_attempts_per_worker=100_000,
        )
        if result:
            return {
                "found": True,
                "address": result.address,
                "private_key": result.private_key,
                "chain": result.chain,
                "attempts": result.attempts,
                "elapsed_seconds": result.elapsed_seconds,
            }
        return {"found": False, "message": "Not found within attempt budget."}


# ──────────────────────────────────────────────────────────────────────────────

class AIDexBotAnalyseInput(BaseModel):
    token_address: str
    chain: str = "ethereum"


class AIDexBotAnalyseSkill(AgentSkill):
    name = "ai_dex_bot_analyse"
    description = (
        "Analyse a token using the locally self-trained AI DEX Bot: collects "
        "on-chain metrics, social hype, whale/bot/insider activity, and "
        "rug-pull risk, then applies a Random Forest + Gradient Boosting "
        "ensemble model trained entirely from synthetic data.  Returns a "
        "data-driven buy/sell/avoid/hold recommendation with a feature-"
        "importance narrative.  No external API key or LLM required – the "
        "model trains and runs 100 % locally."
    )
    input_schema = AIDexBotAnalyseInput

    async def execute(
        self,
        token_address: str,
        chain: str = "ethereum",
    ) -> dict:
        from crypto_toolkit.trading.dex_bot import AIDexBot
        bot = AIDexBot()
        report = await bot.analyse(token_address, chain=chain)
        return report.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, AgentSkill] = {
    skill.name: skill
    for skill in [
        GenerateWalletSkill(),
        CheckBalanceSkill(),
        GetNewPairsSkill(),
        GetTradingSignalSkill(),
        GenerateBip39Skill(),
        FindArbitrageSkill(),
        TraceFundsSkill(),
        DexBotAnalyseSkill(),
        AIDexBotAnalyseSkill(),
        VanityAddressSkill(),
    ]
}


async def execute_tool(name: str, arguments: dict) -> Any:
    """Execute a registered tool by name with the given arguments dict."""
    skill = TOOL_REGISTRY.get(name)
    if not skill:
        raise KeyError(f"Unknown tool: '{name}'.  Available: {list(TOOL_REGISTRY)}")
    return await skill.execute(**arguments)


def get_all_schemas(framework: str = "openai") -> list[dict]:
    """Return tool schemas for a specific AI framework.

    Args:
        framework: One of "openai", "anthropic", "mcp", or "generic".

    Returns:
        List of schema dicts ready to pass to the chosen framework's API.
    """
    method = {
        "openai": "openai_schema",
        "anthropic": "anthropic_schema",
        "mcp": "mcp_schema",
        "generic": "to_dict",
    }.get(framework.lower())
    if not method:
        raise ValueError(f"Unknown framework '{framework}'. Choose: openai, anthropic, mcp, generic.")
    return [getattr(skill, method)() for skill in TOOL_REGISTRY.values()]
