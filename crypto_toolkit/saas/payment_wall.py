"""
Crypto payment-wall SaaS – FastAPI application.

Features:
  • Create invoices (specify amount, currency, chain, expiry).
  • Monitor invoice payments on-chain.
  • Webhook callbacks when payment is confirmed.
  • REST API for integration into any website or SaaS.

Run with:
    uvicorn crypto_toolkit.saas.payment_wall:app --reload
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Header
from pydantic import BaseModel

from crypto_toolkit.config import PAYMENT_WALL_PRIVATE_KEY, PAYMENT_WALL_SECRET, RPC_URLS
from crypto_toolkit.tracker.fund_checker import FundChecker
from crypto_toolkit.wallet.wallet_generator import WalletGenerator

# ── Constants ──────────────────────────────────────────────────────────────────
# Fraction of the invoice amount that may be under-paid and still be accepted
# (e.g. 0.01 = allow up to 1 % shortfall to cover price-feed lag).
# Replace the hardcoded ETH price with a live oracle for production use.
_PAYMENT_TOLERANCE: float = 0.01

# Rough ETH price in USD used for invoice matching.
# Integrate Chainlink / CoinGecko for accurate conversions in production.
_ETH_PRICE_USD_ESTIMATE: float = 2_500.0


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class CreateInvoiceRequest(BaseModel):
    amount_usd: float
    chain: str = "ethereum"
    ttl_seconds: int = 3600
    webhook_url: Optional[str] = None
    metadata: Optional[dict] = None


class InvoiceResponse(BaseModel):
    invoice_id: str
    pay_address: str
    amount_usd: float
    chain: str
    expires_at: int
    status: str
    webhook_url: Optional[str]
    metadata: Optional[dict]


# ─────────────────────────────────────────────────────────────────────────────
# In-memory invoice store (replace with DB in production)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Invoice:
    invoice_id: str
    pay_address: str
    private_key: str
    amount_usd: float
    chain: str
    created_at: int
    expires_at: int
    webhook_url: Optional[str]
    metadata: Optional[dict]
    status: str = "pending"   # pending | paid | expired | overpaid
    paid_amount: float = 0.0
    paid_tx: Optional[str] = None


_invoices: dict[str, Invoice] = {}
_gen = WalletGenerator()
_checker = FundChecker()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Crypto Payment Wall",
    description="Multi-chain crypto payment processing SaaS",
    version="1.0.0",
)


@app.post("/invoices", response_model=InvoiceResponse)
async def create_invoice(
    body: CreateInvoiceRequest,
    background_tasks: BackgroundTasks,
) -> InvoiceResponse:
    """Create a new payment invoice with a unique deposit address."""
    invoice_id = str(uuid.uuid4())
    wallet = _gen.create(chain=body.chain)
    now = int(time.time())

    invoice = Invoice(
        invoice_id=invoice_id,
        pay_address=wallet.address,
        private_key=wallet.private_key,
        amount_usd=body.amount_usd,
        chain=body.chain,
        created_at=now,
        expires_at=now + body.ttl_seconds,
        webhook_url=body.webhook_url,
        metadata=body.metadata,
    )
    _invoices[invoice_id] = invoice

    background_tasks.add_task(_monitor_invoice, invoice_id)

    return _to_response(invoice)


@app.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: str) -> InvoiceResponse:
    """Get the status of an existing invoice."""
    inv = _invoices.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return _to_response(inv)


@app.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices() -> list[InvoiceResponse]:
    """List all invoices (paginate in production)."""
    return [_to_response(inv) for inv in _invoices.values()]


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "invoices": len(_invoices)}


# ─────────────────────────────────────────────────────────────────────────────
# Background payment monitor
# ─────────────────────────────────────────────────────────────────────────────

async def _monitor_invoice(invoice_id: str) -> None:
    """Poll for payment on the invoice's deposit address."""
    invoice = _invoices.get(invoice_id)
    if not invoice:
        return

    while True:
        now = int(time.time())
        if now > invoice.expires_at and invoice.status == "pending":
            invoice.status = "expired"
            await _fire_webhook(invoice)
            return

        if invoice.status != "pending":
            return

        try:
            bal = _checker.get_native_balance(invoice.pay_address, chain=invoice.chain)
            paid_usd = bal.balance * _ETH_PRICE_USD_ESTIMATE

            if paid_usd >= invoice.amount_usd * (1 - _PAYMENT_TOLERANCE):
                invoice.status = "paid"
                invoice.paid_amount = paid_usd
                await _fire_webhook(invoice)
                return
        except Exception:
            pass

        await asyncio.sleep(15)


async def _fire_webhook(invoice: Invoice) -> None:
    """POST to the webhook URL if configured."""
    if not invoice.webhook_url:
        return
    payload = {
        "invoice_id": invoice.invoice_id,
        "status": invoice.status,
        "paid_amount": invoice.paid_amount,
        "chain": invoice.chain,
        "pay_address": invoice.pay_address,
    }
    sig = _sign_payload(payload)
    headers = {"X-Signature": sig, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(invoice.webhook_url, json=payload, headers=headers)
        except Exception as exc:
            print(f"[PaymentWall] Webhook error: {exc}")


def _sign_payload(payload: dict) -> str:
    import json
    raw = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(PAYMENT_WALL_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def _to_response(inv: Invoice) -> InvoiceResponse:
    return InvoiceResponse(
        invoice_id=inv.invoice_id,
        pay_address=inv.pay_address,
        amount_usd=inv.amount_usd,
        chain=inv.chain,
        expires_at=inv.expires_at,
        status=inv.status,
        webhook_url=inv.webhook_url,
        metadata=inv.metadata,
    )
