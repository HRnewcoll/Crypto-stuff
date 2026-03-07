"""
Crypto faucet SaaS – FastAPI application.

A faucet drips small amounts of native coins (ETH, BNB, MATIC …) to
registered addresses once per cooldown period.

Run with:
    uvicorn crypto_toolkit.saas.faucet:app --reload --port 8001
"""

from __future__ import annotations

import asyncio
import time
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
)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class DrainRequest(BaseModel):
    address: str
    chain: str = "ethereum"


class DrainResponse(BaseModel):
    success: bool
    tx_hash: Optional[str]
    drip_amount: float
    chain: str
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# In-memory cooldown store  (use Redis / DB in production)
# ─────────────────────────────────────────────────────────────────────────────

_last_drip: dict[str, int] = {}   # address → unix timestamp


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Crypto Faucet",
    description="Multi-chain testnet / mainnet faucet SaaS",
    version="1.0.0",
)


@app.post("/drip", response_model=DrainResponse)
async def drip(body: DrainRequest) -> DrainResponse:
    """Request a drip for the given address."""
    address = body.address.lower()
    chain = body.chain.lower()
    now = int(time.time())

    # Check cooldown
    last = _last_drip.get(f"{chain}:{address}", 0)
    remaining = FAUCET_COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active.  Try again in {remaining} seconds.",
        )

    # Send drip
    try:
        tx_hash = _send_drip(body.address, chain)
        _last_drip[f"{chain}:{address}"] = now
        return DrainResponse(
            success=True,
            tx_hash=tx_hash,
            drip_amount=FAUCET_DRIP_AMOUNT,
            chain=chain,
            message=f"Sent {FAUCET_DRIP_AMOUNT} to {body.address}",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/status")
async def status() -> dict:
    return {
        "drip_amount": FAUCET_DRIP_AMOUNT,
        "cooldown_seconds": FAUCET_COOLDOWN_SECONDS,
        "supported_chains": list(RPC_URLS.keys()),
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Drip logic
# ─────────────────────────────────────────────────────────────────────────────

def _send_drip(to_address: str, chain: str) -> str:
    """Sign and broadcast a native-coin transfer from the faucet wallet."""
    if not FAUCET_PRIVATE_KEY:
        raise RuntimeError(
            "FAUCET_PRIVATE_KEY is not set.  Configure it in your .env file."
        )

    rpc = RPC_URLS.get(chain)
    if not rpc:
        raise ValueError(f"Unsupported chain '{chain}'.")

    w3 = Web3(Web3.HTTPProvider(rpc))
    acct = _EthAccount.from_key(FAUCET_PRIVATE_KEY)
    amount_wei = w3.to_wei(FAUCET_DRIP_AMOUNT, "ether")

    tx = {
        "from": acct.address,
        "to": Web3.to_checksum_address(to_address),
        "value": amount_wei,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 21_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": w3.eth.chain_id,
    }
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    return tx_hash.hex()
