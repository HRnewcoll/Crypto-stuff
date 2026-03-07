# 🔐 Crypto Toolkit

A comprehensive, multi-chain crypto toolkit written in Python.  
Everything you need to build, trade, monitor, and monetise on-chain — in one place.

---

## ⚠️ Legal & Ethical Disclaimer

> This software is provided for **educational and legitimate use only**.
> You are solely responsible for complying with all applicable laws in your jurisdiction.
>
> **Prohibited uses:**
> - Deploying tokens intended to deceive investors (rug pulls, honeypots).
> - Using MEV strategies to harm other users unfairly.
> - Recovering wallets you do not own or lack explicit permission to access.
> - Any activity that constitutes fraud, theft, or market manipulation.
>
> The authors accept no liability for misuse.

---

## 📦 Features

| Module | Feature |
|---|---|
| `wallet/bip39` | BIP-39 mnemonic generation (12–24 words, 9 languages) |
| `wallet/wallet_generator` | Multi-chain HD wallet (Ethereum, BSC, Polygon, Arbitrum, Optimism, Avalanche, Base, Bitcoin, Solana, Litecoin, Dogecoin, TRON …) |
| `wallet/vanity_address` | Vanity address generator – prefix / suffix / regex matching |
| `wallet/dat_recovery` | Bitcoin `wallet.dat` password recovery (dictionary, mask, mutation, BIP-39) |
| `tracker/wallet_tracker` | Real-time wallet tracker – monitors multiple addresses across chains |
| `tracker/fund_checker` | Native coin + ERC-20 token balance checker |
| `tracker/whale_notifier` | Whale alert – detects large transfers and sends Telegram notifications |
| `trading/copy_trader` | Copy trader – mirrors another wallet's DEX swaps |
| `trading/dex_screener` | DEX screener – new-pair discovery and price feeds (Uniswap, PancakeSwap, QuickSwap …) |
| `trading/arbitrage_bot` | Cross-DEX arbitrage bot with dry-run mode |
| `trading/mev_bot` | MEV bot – sandwich / back-run strategy (dry-run by default) |
| `trading/ai_trading_bot` | AI trading bot – ML (RandomForest) + LLM (GPT-4o) signal generation |
| `defi/memecoin_factory` | ERC-20 / BEP-20 token factory – deploy custom tokens with fees and ownership |
| `saas/payment_wall` | Crypto payment-wall SaaS (FastAPI) – invoices, webhooks, multi-chain |
| `saas/faucet` | Crypto faucet SaaS (FastAPI) – cooldown-gated drip, multi-chain |
| `ai/agent_skills` | AI agent skills – OpenAI function-calling wrappers for all tools |
| `cli` | Unified CLI (`crypto-toolkit …`) |

---

## 🚀 Quick Start

### 1 – Install

```bash
git clone https://github.com/HRnewcoll/Crypto-stuff
cd Crypto-stuff
pip install -e .
```

### 2 – Configure

```bash
cp .env.example .env
# Edit .env and fill in your RPC URLs, API keys, etc.
```

### 3 – Use the CLI

```bash
# Generate a wallet
crypto-toolkit wallet create --chain ethereum

# Generate a 24-word mnemonic
crypto-toolkit wallet bip39 --words 24

# Derive 10 addresses from a mnemonic
crypto-toolkit wallet derive "word1 word2 … word12" --chain bsc --count 10

# Check a balance
crypto-toolkit tracker balance 0xdAC17F958D2ee523a2206206994597C13D831ec7 --chain ethereum

# Find a vanity address
crypto-toolkit vanity --prefix 0xDEAD --chain ethereum --workers 4

# Screen new DEX pairs
crypto-toolkit dex --dex uniswap_v2 --limit 20

# Run the arbitrage bot (dry run)
crypto-toolkit bot arb --chain ethereum --dry-run

# Run the AI trading bot (dry run, ML model)
crypto-toolkit bot ai --token ethereum --dry-run

# Run the MEV bot (dry run)
crypto-toolkit bot mev --chain ethereum --dry-run

# Start the payment-wall SaaS
crypto-toolkit saas payment-wall --port 8000

# Start the faucet SaaS
crypto-toolkit saas faucet --port 8001
```

---

## 🔑 Wallet Tools

### BIP-39 Mnemonic Generator

```python
from crypto_toolkit.wallet.bip39 import BIP39

bip39 = BIP39()
mnemonic = bip39.generate(num_words=24)          # 24-word phrase
seed = bip39.to_seed(mnemonic, passphrase="")    # 64-byte seed
seed_hex = bip39.to_seed_hex(mnemonic)           # hex string
master = bip39.to_master_key(mnemonic)           # BIP-32 master key
print(mnemonic)
```

### Multi-Chain HD Wallet

```python
from crypto_toolkit.wallet.wallet_generator import WalletGenerator

gen = WalletGenerator()

# New wallet
wallet = gen.create(chain="ethereum", num_words=12)
print(wallet.address, wallet.mnemonic)

# Derive from existing mnemonic
wallet = gen.from_mnemonic("word1 word2 … word12", chain="bitcoin")
print(wallet.address)

# Batch derivation (10 addresses from one seed)
wallets = gen.derive_batch(mnemonic, chain="polygon", count=10)

# Supported chains: ethereum, bsc, polygon, arbitrum, optimism, avalanche, base,
#                   bitcoin, solana, litecoin, dogecoin, tron
```

### Vanity Address Generator

```python
from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator

gen = VanityAddressGenerator()

# Find address starting with 0xDEAD
result = gen.find(chain="ethereum", prefix="0xDEAD", workers=4)
print(result.address, result.private_key, result.attempts)

# Find by suffix
result = gen.find(chain="ethereum", suffix="cafe")

# Find by regex
result = gen.find(chain="ethereum", regex=r"^0x[dD][eE][aA][dD]")
```

### Wallet.dat Recovery

```python
from crypto_toolkit.wallet.dat_recovery import DatRecovery

recovery = DatRecovery("wallet.dat")

# Dictionary attack
password = recovery.dictionary_attack("rockyou.txt")

# Mask attack (e.g. Pass + 4 digits)
password = recovery.mask_attack("Pass?d?d?d?d")

# Mutation attack
password = recovery.mutation_attack(["mypassword", "bitcoin"])

# BIP-39 check
password = recovery.bip39_recovery("word1 word2 … word12")
```

> **⚠ Only use on wallets you own or have explicit written permission to access.**

---

## 📊 Tracker Tools

### Wallet Tracker

```python
import asyncio
from crypto_toolkit.tracker.wallet_tracker import WalletTracker

tracker = WalletTracker()
tracker.add_wallet("0xdAC17F958D2ee523a2206206994597C13D831ec7", chain="ethereum")
tracker.on_transaction(lambda tx: print(f"New TX: {tx.tx_hash}  {tx.value_eth} ETH"))
asyncio.run(tracker.start(poll_interval=15))
```

### Balance Checker

```python
from crypto_toolkit.tracker.fund_checker import FundChecker

checker = FundChecker()

# Native balance
bal = checker.get_native_balance("0xABC…", chain="ethereum")
print(f"{bal.balance} {bal.symbol}")

# ERC-20 token balances
tokens = checker.get_token_balances("0xABC…", chain="bsc")
for t in tokens:
    print(f"{t.balance} {t.symbol} ({t.token_contract})")

# Solana
sol = checker.get_solana_balance("So11111111111111111111111111111111111111112")
```

### Whale Notifier

```python
import asyncio
from crypto_toolkit.tracker.whale_notifier import WhaleNotifier

notifier = WhaleNotifier(threshold_eth=100)
notifier.on_alert(lambda a: print(f"🐳 {a.value_eth:.0f} ETH from {a.from_address}"))
# Configure TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env for Telegram alerts
asyncio.run(notifier.start(chain="ethereum"))
```

---

## 📈 Trading Bots

### Copy Trader

```python
import asyncio
from crypto_toolkit.trading.copy_trader import CopyTrader

trader = CopyTrader(
    target_wallet="0xTARGET…",
    follower_private_key="0xYOURKEY…",
    scale_factor=0.1,   # copy 10 % of trade size
)
asyncio.run(trader.start(chain="ethereum"))
```

### DEX Screener

```python
import asyncio
from crypto_toolkit.trading.dex_screener import DexScreener

screener = DexScreener()

# New pairs
pairs = asyncio.run(screener.get_new_pairs("uniswap_v2", limit=20))
for p in pairs:
    print(f"{p.token0_symbol}/{p.token1_symbol}  ${p.reserve_usd:,.0f}")

# Price of a specific pair
price = asyncio.run(screener.get_price("uniswap_v2", "0xPAIR_ADDRESS"))

# Continuous monitor
asyncio.run(screener.monitor_new_pairs("pancakeswap_v2", poll_interval=30))
```

### Arbitrage Bot

```python
import asyncio
from crypto_toolkit.trading.arbitrage_bot import ArbitrageBot

bot = ArbitrageBot(
    private_key="0xYOURKEY…",
    min_profit_usd=10,
    trade_size_eth=0.5,
    dry_run=True,         # set False for live trading
)
asyncio.run(bot.start(chain="ethereum"))
```

### MEV Bot

```python
import asyncio
from crypto_toolkit.trading.mev_bot import MEVBot

bot = MEVBot(
    private_key="0xYOURKEY…",
    min_profit_eth=0.01,
    dry_run=True,
)
asyncio.run(bot.start(chain="ethereum"))
# For live sandwiching, integrate with Flashbots relay (flashbots.net)
```

### AI Trading Bot

```python
import asyncio
from crypto_toolkit.trading.ai_trading_bot import AITradingBot

# ML-based (no API key needed)
bot = AITradingBot(dry_run=True)
asyncio.run(bot.start(token_id="ethereum"))

# LLM-based (requires OPENAI_API_KEY in .env)
bot = AITradingBot(use_llm=True, dry_run=True)
asyncio.run(bot.start(token_id="bitcoin"))
```

---

## 🪙 DeFi: Token Factory

```python
from crypto_toolkit.defi.memecoin_factory import MemecoinFactory, TokenConfig

factory = MemecoinFactory(private_key="0xYOURKEY…")

config = TokenConfig(
    name="PepeToken",
    symbol="PEPE",
    decimals=18,
    total_supply=420_690_000_000,
    buy_fee_bps=200,     # 2 % buy tax
    sell_fee_bps=300,    # 3 % sell tax
)

# Generate Solidity source (inspect before deploying)
print(factory.generate_source(config))

# Deploy to BSC (requires py-solc-x: pip install py-solc-x)
deployed = factory.deploy(config, chain="bsc")
print(f"Deployed: {deployed.contract_address}  TX: {deployed.deploy_tx}")

# Add liquidity to PancakeSwap
from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.binance.org/"))
tx = factory.add_liquidity(
    w3,
    token_address=deployed.contract_address,
    token_amount=int(deployed.total_supply * 0.8 * 1e18),
    eth_amount=int(0.5 * 1e18),  # 0.5 BNB
    router_address="0x10ED43C718714eb63d5aA57B78B54704E256024E",
)
```

> **⚠ Only deploy tokens for legitimate projects.  Rug pulls and honeypots are illegal.**

---

## 💳 SaaS: Payment Wall

```python
# Start the server
# uvicorn crypto_toolkit.saas.payment_wall:app --port 8000

# Create an invoice (REST API)
# POST /invoices
# {
#   "amount_usd": 99.99,
#   "chain": "ethereum",
#   "ttl_seconds": 3600,
#   "webhook_url": "https://yoursite.com/webhook"
# }
# Response: { "invoice_id": "…", "pay_address": "0x…", "status": "pending" }

# Check invoice status
# GET /invoices/{invoice_id}
```

Example with `httpx`:

```python
import httpx

resp = httpx.post("http://localhost:8000/invoices", json={
    "amount_usd": 29.99,
    "chain": "polygon",
    "webhook_url": "https://myapp.com/crypto-webhook",
})
invoice = resp.json()
print(f"Pay {invoice['amount_usd']} USD to {invoice['pay_address']} on {invoice['chain']}")
```

---

## 🚰 SaaS: Crypto Faucet

```python
# Start the server
# uvicorn crypto_toolkit.saas.faucet:app --port 8001

# Request a drip
# POST /drip
# { "address": "0xYOUR_ADDRESS", "chain": "ethereum" }
```

Configure in `.env`:
```
FAUCET_PRIVATE_KEY=0xYOUR_HOT_WALLET
FAUCET_DRIP_AMOUNT=0.001
FAUCET_COOLDOWN_SECONDS=86400
```

---

## 🤖 AI Agent Skills

Use the toolkit as tools for LLM agents (OpenAI, LangChain, CrewAI, AutoGPT …):

```python
import asyncio
from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY, execute_tool

# List available tools for OpenAI function-calling
tools = [skill.openai_schema() for skill in TOOL_REGISTRY.values()]

# Execute a tool by name (as called by the model)
result = asyncio.run(execute_tool("generate_wallet", {"chain": "ethereum"}))
result = asyncio.run(execute_tool("check_balance", {"address": "0x…", "chain": "bsc"}))
result = asyncio.run(execute_tool("get_new_dex_pairs", {"dex": "uniswap_v2"}))
result = asyncio.run(execute_tool("get_trading_signal", {"token_id": "bitcoin"}))
result = asyncio.run(execute_tool("find_arbitrage", {"chain": "ethereum"}))
```

Available skills: `generate_wallet`, `check_balance`, `get_new_dex_pairs`,
`get_trading_signal`, `generate_bip39_mnemonic`, `find_arbitrage`.

---

## ⚙️ Configuration (`.env`)

See `.env.example` for all options.  Key variables:

| Variable | Description |
|---|---|
| `ETH_RPC_URL` | Ethereum JSON-RPC (Infura / Alchemy) |
| `BSC_RPC_URL` | BSC JSON-RPC |
| `ETHERSCAN_API_KEY` | Etherscan API key (for balance/tx queries) |
| `OPENAI_API_KEY` | OpenAI key (AI trading bot + agent skills) |
| `FAUCET_PRIVATE_KEY` | Hot wallet private key for the faucet |
| `FAUCET_DRIP_AMOUNT` | Amount to drip per request (e.g. 0.001) |
| `WHALE_THRESHOLD_ETH` | Min ETH value to trigger a whale alert |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications |
| `COPY_TRADE_WALLET` | Target wallet address to copy-trade |

---

## 🧪 Testing

```bash
pytest tests/ -v
```

---

## 📁 Project Structure

```
crypto_toolkit/
├── wallet/
│   ├── bip39.py             # BIP-39 mnemonic generation
│   ├── wallet_generator.py  # Multi-chain HD wallet
│   ├── vanity_address.py    # Vanity address generator
│   └── dat_recovery.py      # wallet.dat password recovery
├── tracker/
│   ├── wallet_tracker.py    # Real-time wallet tracker
│   ├── fund_checker.py      # Balance checker (native + ERC-20)
│   └── whale_notifier.py    # Whale alert monitor
├── trading/
│   ├── copy_trader.py       # Copy trader
│   ├── dex_screener.py      # DEX pair screener
│   ├── arbitrage_bot.py     # Cross-DEX arbitrage
│   ├── mev_bot.py           # MEV / sandwich bot
│   └── ai_trading_bot.py   # ML + LLM trading bot
├── defi/
│   └── memecoin_factory.py  # ERC-20 token factory + deployer
├── saas/
│   ├── payment_wall.py      # Crypto payment-wall (FastAPI)
│   └── faucet.py            # Crypto faucet (FastAPI)
├── ai/
│   └── agent_skills.py      # AI agent tool wrappers
├── utils/
│   └── helpers.py           # Shared utilities
├── config.py                # Environment configuration
└── cli.py                   # Unified CLI entry point
```

---

## 🛣️ Roadmap

- [ ] Solana SPL token support
- [ ] Flashbots bundle submission for live MEV
- [ ] On-chain liquidity lock contract
- [ ] Telegram / Discord bot integration
- [ ] Web UI dashboard (FastAPI + HTMX)
- [ ] Database backend for payment wall and faucet (PostgreSQL)
- [ ] More AI agent skills (token analysis, rug-pull detection)
- [ ] Multi-sig wallet support

---

## 📄 License

MIT License.