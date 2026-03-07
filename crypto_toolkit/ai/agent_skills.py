"""
AI agent crypto skills – tool wrappers for LLM agents.

This module exposes each crypto capability as a structured "tool" that an
LLM agent (OpenAI function-calling, LangChain, AutoGPT, CrewAI, etc.) can
call.  Each tool has:
  - A name and description (used in the system prompt).
  - A typed input schema (Pydantic model).
  - An ``execute()`` method that runs the underlying logic.

Usage with OpenAI function-calling::

    from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY, execute_tool

    # Build the tools list for the chat completion
    tools = [t.openai_schema() for t in TOOL_REGISTRY.values()]

    # When the model returns a tool_call:
    result = await execute_tool(tool_name, arguments_dict)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

from pydantic import BaseModel


# ─────────────────────────────────────────────────────────────────────────────
# Base skill class
# ─────────────────────────────────────────────────────────────────────────────

class AgentSkill:
    """Base class for an AI-agent-callable crypto tool."""

    name: str = ""
    description: str = ""
    input_schema: type[BaseModel]

    def openai_schema(self) -> dict:
        """Return the OpenAI function-calling schema for this tool."""
        schema = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

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
    description = "Check the native coin balance of any wallet address."
    input_schema = CheckBalanceInput

    async def execute(self, address: str, chain: str = "ethereum") -> dict:
        from crypto_toolkit.tracker.fund_checker import FundChecker
        checker = FundChecker()
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

    async def execute(
        self,
        dex: str = "uniswap_v2",
        limit: int = 10,
        min_liquidity_usd: float = 1000.0,
    ) -> list[dict]:
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
    use_llm: bool = False


class GetTradingSignalSkill(AgentSkill):
    name = "get_trading_signal"
    description = "Get an AI-generated buy/sell/hold signal for a token."
    input_schema = GetTradingSignalInput

    async def execute(self, token_id: str = "ethereum", use_llm: bool = False) -> dict:
        from crypto_toolkit.trading.ai_trading_bot import (
            fetch_ohlcv,
            MLSignalGenerator,
            LLMSignalGenerator,
        )
        candles = await fetch_ohlcv(token_id, days=90)
        if use_llm:
            gen = LLMSignalGenerator()
            signal = await gen.predict(candles, token=token_id.upper())
        else:
            ml = MLSignalGenerator()
            ml.train(candles)
            signal = ml.predict(candles)
            signal.token = token_id.upper()
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
    ]
}


async def execute_tool(name: str, arguments: dict) -> Any:
    """Execute a registered tool by name with the given arguments."""
    skill = TOOL_REGISTRY.get(name)
    if not skill:
        raise KeyError(f"Unknown tool: '{name}'.")
    return await skill.execute(**arguments)
