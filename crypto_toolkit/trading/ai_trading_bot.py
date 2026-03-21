"""
AI-powered trading bot.

Uses a combination of technical indicators and an LLM/ML model to generate
buy/sell signals, then executes them via a DEX router.

Signal pipeline:
    1. Fetch OHLCV data from CoinGecko / CryptoCompare.
    2. Compute technical indicators (RSI, MACD, Bollinger Bands, ATR).
    3. Feed features to a scikit-learn RandomForest classifier
       (or optionally to an LLM for reasoning-based decisions).
    4. Execute swap if signal confidence exceeds threshold.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import numpy as np
import pandas as pd

from crypto_toolkit.config import OPENAI_API_KEY, OPENAI_BASE_URL, RPC_URLS


@dataclass
class OHLCV:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class TradingSignal:
    token: str
    action: str          # "buy" | "sell" | "hold"
    confidence: float    # 0–1
    price: float
    reasoning: str


# ─────────────────────────────────────────────────────────────────────────────
# Data fetcher
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_ohlcv(
    token_id: str = "ethereum",
    vs_currency: str = "usd",
    days: int = 30,
) -> list[OHLCV]:
    """Fetch OHLCV data from CoinGecko (free tier, no key required)."""
    url = f"https://api.coingecko.com/api/v3/coins/{token_id}/ohlc"
    params = {"vs_currency": vs_currency, "days": days}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        raw = resp.json()
    result = []
    for item in raw:
        ts, o, h, l, c = item
        result.append(OHLCV(timestamp=ts, open=o, high=h, low=l, close=c, volume=0))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering
# ─────────────────────────────────────────────────────────────────────────────

def compute_features(candles: list[OHLCV]) -> pd.DataFrame:
    """Convert OHLCV list to a feature DataFrame with technical indicators."""
    df = pd.DataFrame(
        {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )

    # Simple Moving Averages
    df["sma_7"] = df["close"].rolling(7).mean()
    df["sma_25"] = df["close"].rolling(25).mean()

    # RSI (14-period)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands (20-period)
    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)

    # ATR (14-period)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    return df.dropna()


# ─────────────────────────────────────────────────────────────────────────────
# ML-based signal generator
# ─────────────────────────────────────────────────────────────────────────────

class MLSignalGenerator:
    """Train a RandomForest on historical data and predict the next move."""

    def __init__(self, lookahead_periods: int = 3, threshold_pct: float = 1.0) -> None:
        from sklearn.ensemble import RandomForestClassifier
        self.lookahead = lookahead_periods
        self.threshold = threshold_pct / 100
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self._trained = False

    def _make_labels(self, df: pd.DataFrame) -> pd.Series:
        future_return = df["close"].shift(-self.lookahead) / df["close"] - 1
        return (future_return > self.threshold).astype(int)  # 1 = buy, 0 = hold/sell

    def train(self, candles: list[OHLCV]) -> None:
        df = compute_features(candles)
        feature_cols = ["sma_7", "sma_25", "rsi", "macd", "macd_hist", "bb_pct", "atr"]
        labels = self._make_labels(df).iloc[: len(df) - self.lookahead]
        X = df[feature_cols].iloc[: len(df) - self.lookahead]
        self.model.fit(X, labels)
        self._trained = True

    def predict(self, candles: list[OHLCV]) -> TradingSignal:
        if not self._trained:
            raise RuntimeError("Call train() before predict().")
        df = compute_features(candles)
        feature_cols = ["sma_7", "sma_25", "rsi", "macd", "macd_hist", "bb_pct", "atr"]
        X = df[feature_cols].iloc[-1:]
        proba = self.model.predict_proba(X)[0]
        action = "buy" if proba[1] > 0.6 else ("sell" if proba[1] < 0.4 else "hold")
        return TradingSignal(
            token="",
            action=action,
            confidence=float(max(proba)),
            price=float(df["close"].iloc[-1]),
            reasoning=f"RandomForest: buy_prob={proba[1]:.2f} hold_prob={proba[0]:.2f}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# LLM-based signal generator
# ─────────────────────────────────────────────────────────────────────────────

class LLMSignalGenerator:
    """Use an LLM to reason about market conditions and generate a signal."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    async def predict(self, candles: list[OHLCV], token: str = "ETH") -> TradingSignal:
        if not OPENAI_API_KEY:
            raise RuntimeError("Set OPENAI_API_KEY in your .env file.")

        df = compute_features(candles)
        latest = df.iloc[-1]
        summary = (
            f"Token: {token}\n"
            f"Latest close: {latest['close']:.4f}\n"
            f"RSI(14): {latest['rsi']:.1f}\n"
            f"MACD histogram: {latest['macd_hist']:.4f}\n"
            f"BB %: {latest['bb_pct']:.2f}\n"
            f"SMA7/SMA25: {latest['sma_7']:.2f} / {latest['sma_25']:.2f}\n"
        )
        prompt = (
            "You are an expert crypto trader.  Given the following technical "
            "indicators, output a JSON object with keys: "
            "\"action\" (\"buy\", \"sell\", or \"hold\"), "
            "\"confidence\" (0.0–1.0), and \"reasoning\" (one sentence).\n\n"
            + summary
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

        parsed = json.loads(content)
        return TradingSignal(
            token=token,
            action=parsed.get("action", "hold"),
            confidence=float(parsed.get("confidence", 0.5)),
            price=float(latest["close"]),
            reasoning=parsed.get("reasoning", ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# AITradingBot
# ─────────────────────────────────────────────────────────────────────────────

class AITradingBot:
    """End-to-end AI trading bot.

    Example::

        bot = AITradingBot(private_key="0x…", use_llm=False, dry_run=True)
        asyncio.run(bot.start(token_id="ethereum", chain="ethereum"))
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        use_llm: bool = False,
        min_confidence: float = 0.65,
        trade_size_eth: float = 0.05,
        dry_run: bool = True,
    ) -> None:
        self.private_key = private_key
        self.use_llm = use_llm
        self.min_confidence = min_confidence
        self.trade_size_eth = trade_size_eth
        self.dry_run = dry_run
        self._ml = MLSignalGenerator()

    async def start(
        self,
        token_id: str = "ethereum",
        chain: str = "ethereum",
        poll_interval: int = 300,  # 5 min
    ) -> None:
        """Start the trading loop."""
        print(f"[AITradingBot] Starting for {token_id} on {chain} …")

        # Initial training run
        candles = await fetch_ohlcv(token_id, days=90)
        self._ml.train(candles)

        while True:
            try:
                candles = await fetch_ohlcv(token_id, days=30)
                if self.use_llm:
                    llm = LLMSignalGenerator()
                    signal = await llm.predict(candles, token=token_id.upper())
                else:
                    signal = self._ml.predict(candles)
                    signal.token = token_id.upper()

                print(
                    f"[AITradingBot] Signal: {signal.action.upper()} "
                    f"({signal.confidence:.0%} confidence) – {signal.reasoning}"
                )

                if signal.confidence >= self.min_confidence and signal.action != "hold":
                    await self._execute(chain, signal)
            except Exception as exc:
                print(f"[AITradingBot] Error: {exc}")

            await asyncio.sleep(poll_interval)

    async def _execute(self, chain: str, signal: TradingSignal) -> None:
        if self.dry_run:
            print(
                f"[AITradingBot] DRY RUN – would {signal.action} "
                f"{self.trade_size_eth} ETH worth of {signal.token}"
            )
            return
        # Live execution: call Uniswap/PancakeSwap router
        # Requires a fully set-up Web3 connection and private key
        print("[AITradingBot] Live trading: connect your wallet and DEX router here.")
