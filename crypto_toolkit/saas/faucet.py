"""
Crypto faucet SaaS – FastAPI application.

A faucet drips small amounts of:
  • Native coins (ETH, BNB, MATIC, AVAX, SOL …) or
  • ERC-20 / BEP-20 tokens

to registered addresses once per cooldown period.

Per-chain configuration (drip amounts and tokens) can be overridden via
environment variables or the ChainFaucetConfig class.

Run with:
    uvicorn crypto_toolkit.saas.faucet:app --reload --port 8001
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from web3 import Web3
from eth_account import Account as _EthAccount

from crypto_toolkit.config import (
    FAUCET_COOLDOWN_SECONDS,
    FAUCET_DRIP_AMOUNT,
    FAUCET_PRIVATE_KEY,
    RPC_URLS,
    SOLANA_RPC_URL,
)


# ─────────────────────────────────────────────────────────────────────────────
# Per-chain faucet configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChainFaucetConfig:
    """Configuration for one chain's faucet."""
    native_drip_amount: float = FAUCET_DRIP_AMOUNT
    native_symbol: str = "ETH"
    token_contract: Optional[str] = None
    token_symbol: Optional[str] = None
    token_drip_amount: float = 0.0
    token_decimals: int = 18


# Default per-chain configs
_CHAIN_CONFIGS: dict[str, ChainFaucetConfig] = {
    "ethereum":  ChainFaucetConfig(native_drip_amount=0.001, native_symbol="ETH"),
    "bsc":       ChainFaucetConfig(native_drip_amount=0.005, native_symbol="BNB"),
    "polygon":   ChainFaucetConfig(native_drip_amount=1.0,   native_symbol="MATIC"),
    "arbitrum":  ChainFaucetConfig(native_drip_amount=0.001, native_symbol="ETH"),
    "optimism":  ChainFaucetConfig(native_drip_amount=0.001, native_symbol="ETH"),
    "avalanche": ChainFaucetConfig(native_drip_amount=0.05,  native_symbol="AVAX"),
    "base":      ChainFaucetConfig(native_drip_amount=0.001, native_symbol="ETH"),
    "solana":    ChainFaucetConfig(native_drip_amount=0.01,  native_symbol="SOL"),
}

_ERC20_TRANSFER_ABI = [
    {
        "name": "transfer",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
    }
]


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class DrainRequest(BaseModel):
    address: str
    chain: str = "ethereum"
    token_contract: Optional[str] = None


class DrainResponse(BaseModel):
    success: bool
    tx_hash: Optional[str]
    native_tx_hash: Optional[str]
    token_tx_hash: Optional[str]
    drip_amount: float
    symbol: str
    chain: str
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# In-memory cooldown store
# ─────────────────────────────────────────────────────────────────────────────

_last_drip: dict[str, int] = {}


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Crypto Faucet",
    description="Multi-chain, multi-currency faucet SaaS",
    version="2.0.0",
)


@app.post("/drip", response_model=DrainResponse)
async def drip(body: DrainRequest) -> DrainResponse:
    """Request a native coin (and optional token) drip."""
    address = body.address.lower()
    chain = body.chain.lower()
    now = int(time.time())

    key = f"{chain}:{address}"
    last = _last_drip.get(key, 0)
    remaining = FAUCET_COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active.  Try again in {remaining} seconds.",
        )

    cfg = _CHAIN_CONFIGS.get(chain)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"Chain '{chain}' is not supported.")

    native_tx: Optional[str] = None
    token_tx: Optional[str] = None

    try:
        if chain == "solana":
            native_tx = _send_solana_drip(body.address, cfg.native_drip_amount)
        else:
            native_tx = _send_evm_drip(body.address, chain, cfg.native_drip_amount)

        token_contract = body.token_contract or cfg.token_contract
        if token_contract and chain != "solana" and cfg.token_drip_amount > 0:
            token_tx = _send_erc20_drip(
                to_address=body.address,
                chain=chain,
                token_contract=token_contract,
                amount=cfg.token_drip_amount,
                decimals=cfg.token_decimals,
            )

        _last_drip[key] = now
        msg_parts = [f"Sent {cfg.native_drip_amount} {cfg.native_symbol} to {body.address}"]
        if token_tx:
            msg_parts.append(f"Also sent {cfg.token_drip_amount} {cfg.token_symbol or 'tokens'}")

        return DrainResponse(
            success=True,
            tx_hash=native_tx,
            native_tx_hash=native_tx,
            token_tx_hash=token_tx,
            drip_amount=cfg.native_drip_amount,
            symbol=cfg.native_symbol,
            chain=chain,
            message=".  ".join(msg_parts),
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/chains")
async def list_chains() -> dict:
    """List supported chains and their faucet configuration."""
    return {
        chain: {
            "native_symbol": cfg.native_symbol,
            "native_drip_amount": cfg.native_drip_amount,
            "token_contract": cfg.token_contract,
            "token_symbol": cfg.token_symbol,
            "token_drip_amount": cfg.token_drip_amount,
            "cooldown_seconds": FAUCET_COOLDOWN_SECONDS,
        }
        for chain, cfg in _CHAIN_CONFIGS.items()
    }


@app.get("/status")
async def status() -> dict:
    return {
        "cooldown_seconds": FAUCET_COOLDOWN_SECONDS,
        "supported_chains": list(_CHAIN_CONFIGS.keys()),
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Drip helpers
# ─────────────────────────────────────────────────────────────────────────────

def _send_evm_drip(to_address: str, chain: str, amount: float) -> str:
    if not FAUCET_PRIVATE_KEY:
        raise RuntimeError("FAUCET_PRIVATE_KEY is not set.")
    rpc = RPC_URLS.get(chain)
    if not rpc:
        raise ValueError(f"No RPC for chain '{chain}'.")
    w3 = Web3(Web3.HTTPProvider(rpc))
    acct = _EthAccount.from_key(FAUCET_PRIVATE_KEY)
    tx = {
        "from": acct.address,
        "to": Web3.to_checksum_address(to_address),
        "value": w3.to_wei(amount, "ether"),
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 21_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": w3.eth.chain_id,
    }
    signed = acct.sign_transaction(tx)
    return w3.eth.send_raw_transaction(signed.rawTransaction).hex()


def _send_erc20_drip(
    to_address: str,
    chain: str,
    token_contract: str,
    amount: float,
    decimals: int = 18,
) -> str:
    if not FAUCET_PRIVATE_KEY:
        raise RuntimeError("FAUCET_PRIVATE_KEY is not set.")
    rpc = RPC_URLS.get(chain)
    if not rpc:
        raise ValueError(f"No RPC for chain '{chain}'.")
    w3 = Web3(Web3.HTTPProvider(rpc))
    acct = _EthAccount.from_key(FAUCET_PRIVATE_KEY)
    token = w3.eth.contract(
        address=Web3.to_checksum_address(token_contract),
        abi=_ERC20_TRANSFER_ABI,
    )
    raw_amount = int(amount * (10 ** decimals))
    tx = token.functions.transfer(
        Web3.to_checksum_address(to_address),
        raw_amount,
    ).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 80_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": w3.eth.chain_id,
    })
    signed = acct.sign_transaction(tx)
    return w3.eth.send_raw_transaction(signed.rawTransaction).hex()


def _send_solana_drip(to_address: str, amount_sol: float) -> str:
    """Request a SOL airdrop (devnet / testnet only)."""
    import httpx as _httpx
    lamports = int(amount_sol * 1e9)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "requestAirdrop",
        "params": [to_address, lamports],
    }
    resp = _httpx.post(SOLANA_RPC_URL, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    signature = data.get("result", "")
    if not signature:
        raise RuntimeError(f"Solana airdrop failed: {data}")
    return str(signature)
