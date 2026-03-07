"""Shared configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load the .env file that sits next to this package (project root)
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env", override=False)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ── RPC endpoints ─────────────────────────────────────────────────────────────
RPC_URLS: dict[str, str] = {
    "ethereum": _get("ETH_RPC_URL", "https://mainnet.infura.io/v3/YOUR_KEY"),
    "bsc": _get("BSC_RPC_URL", "https://bsc-dataseed.binance.org/"),
    "polygon": _get("POLYGON_RPC_URL", "https://polygon-rpc.com"),
    "arbitrum": _get("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
    "optimism": _get("OPTIMISM_RPC_URL", "https://mainnet.optimism.io"),
    "avalanche": _get("AVALANCHE_RPC_URL", "https://api.avax.network/ext/bc/C/rpc"),
    "base": _get("BASE_RPC_URL", "https://mainnet.base.org"),
}

SOLANA_RPC_URL: str = _get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

# ── Block-explorer API keys ────────────────────────────────────────────────────
ETHERSCAN_API_KEY: str = _get("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY: str = _get("BSCSCAN_API_KEY")
POLYGONSCAN_API_KEY: str = _get("POLYGONSCAN_API_KEY")

EXPLORER_API_URLS: dict[str, str] = {
    "ethereum": "https://api.etherscan.io/api",
    "bsc": "https://api.bscscan.com/api",
    "polygon": "https://api.polygonscan.com/api",
}

EXPLORER_API_KEYS: dict[str, str] = {
    "ethereum": ETHERSCAN_API_KEY,
    "bsc": BSCSCAN_API_KEY,
    "polygon": POLYGONSCAN_API_KEY,
}

# ── AI / LLM ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = _get("OPENAI_API_KEY")
OPENAI_BASE_URL: str = _get("OPENAI_BASE_URL", "https://api.openai.com/v1")

# ── Faucet ────────────────────────────────────────────────────────────────────
FAUCET_PRIVATE_KEY: str = _get("FAUCET_PRIVATE_KEY")
FAUCET_DRIP_AMOUNT: float = float(_get("FAUCET_DRIP_AMOUNT", "0.001"))
FAUCET_COOLDOWN_SECONDS: int = int(_get("FAUCET_COOLDOWN_SECONDS", "86400"))

# ── Payment wall ──────────────────────────────────────────────────────────────
PAYMENT_WALL_PRIVATE_KEY: str = _get("PAYMENT_WALL_PRIVATE_KEY")
PAYMENT_WALL_SECRET: str = _get("PAYMENT_WALL_SECRET", "change_me")

# ── Whale notifier ─────────────────────────────────────────────────────────────
WHALE_THRESHOLD_ETH: float = float(_get("WHALE_THRESHOLD_ETH", "100"))
TELEGRAM_BOT_TOKEN: str = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _get("TELEGRAM_CHAT_ID")

# ── Copy-trader ────────────────────────────────────────────────────────────────
COPY_TRADE_WALLET: str = _get("COPY_TRADE_WALLET")
COPY_TRADE_PRIVATE_KEY: str = _get("COPY_TRADE_PRIVATE_KEY")
