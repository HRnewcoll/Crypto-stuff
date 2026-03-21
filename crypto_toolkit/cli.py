"""
CLI entry point for the crypto toolkit.

Usage:
    crypto-toolkit wallet create --chain ethereum
    crypto-toolkit wallet bip39 --words 24
    crypto-toolkit tracker balance 0xABC… --chain bsc
    crypto-toolkit vanity --prefix 0xDEAD --chain ethereum
    crypto-toolkit bot arb --chain ethereum --dry-run
    crypto-toolkit bot ai --token ethereum --dry-run
    crypto-toolkit saas payment-wall
    crypto-toolkit saas faucet
"""

from __future__ import annotations

import asyncio
import json

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli():
    """🔐 Crypto Toolkit – multi-chain crypto tools, bots, and SaaS."""


# ─────────────────────────────────────────────────────────────────────────────
# wallet commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def wallet():
    """Wallet generation and management commands."""


@wallet.command("create")
@click.option("--chain", default="ethereum", show_default=True, help="Target chain.")
@click.option("--words", default=12, show_default=True, help="Mnemonic word count.")
@click.option("--count", default=1, show_default=True, help="Number of wallets to generate.")
def wallet_create(chain: str, words: int, count: int):
    """Generate new HD wallet(s)."""
    from crypto_toolkit.wallet.wallet_generator import WalletGenerator
    gen = WalletGenerator()
    table = Table(title=f"New {chain.upper()} Wallets")
    table.add_column("Index", style="dim")
    table.add_column("Address", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Mnemonic", style="yellow")

    first_wallet = gen.create(chain=chain, num_words=words)
    if count == 1:
        table.add_row("0", first_wallet.address, first_wallet.derivation_path, first_wallet.mnemonic or "")
    else:
        wallets = gen.derive_batch(first_wallet.mnemonic or "", chain=chain, count=count)
        for i, w in enumerate(wallets):
            table.add_row(str(i), w.address, w.derivation_path, first_wallet.mnemonic or "")

    console.print(table)
    console.print("\n[bold red]⚠  Store your mnemonic safely and NEVER share it![/bold red]")


@wallet.command("bip39")
@click.option("--words", default=12, show_default=True)
@click.option("--language", default="english", show_default=True)
def wallet_bip39(words: int, language: str):
    """Generate a BIP-39 mnemonic phrase."""
    from crypto_toolkit.wallet.bip39 import BIP39
    b = BIP39(language=language)
    mnemonic = b.generate(words)
    console.print(f"\n[bold green]Mnemonic ({words} words):[/bold green]")
    console.print(f"  [yellow]{mnemonic}[/yellow]")
    seed_hex = b.to_seed_hex(mnemonic)
    console.print(f"\n[dim]Seed (hex): {seed_hex[:32]}…[/dim]")
    console.print("\n[bold red]⚠  Store this safely and NEVER share it![/bold red]")


@wallet.command("derive")
@click.argument("mnemonic")
@click.option("--chain", default="ethereum", show_default=True)
@click.option("--count", default=5, show_default=True)
def wallet_derive(mnemonic: str, chain: str, count: int):
    """Derive addresses from an existing mnemonic."""
    from crypto_toolkit.wallet.wallet_generator import WalletGenerator
    gen = WalletGenerator()
    wallets = gen.derive_batch(mnemonic, chain=chain, count=count)
    table = Table(title=f"Derived {chain.upper()} Addresses")
    table.add_column("Index")
    table.add_column("Address", style="cyan")
    table.add_column("Path", style="dim")
    for i, w in enumerate(wallets):
        table.add_row(str(i), w.address, w.derivation_path)
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# tracker commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def tracker():
    """Wallet and balance tracking commands."""


@tracker.command("balance")
@click.argument("address")
@click.option("--chain", default="ethereum", show_default=True)
def tracker_balance(address: str, chain: str):
    """Check the native balance of an address."""
    from crypto_toolkit.tracker.fund_checker import FundChecker
    checker = FundChecker()
    try:
        bal = checker.get_native_balance(address, chain=chain)
        console.print(f"\n[bold]{bal.address}[/bold]")
        console.print(f"Balance: [green]{bal.balance:.8f} {bal.symbol}[/green] ({chain})")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


# ─────────────────────────────────────────────────────────────────────────────
# vanity command
# ─────────────────────────────────────────────────────────────────────────────

@cli.command("vanity")
@click.option("--prefix", default=None, help="Desired address prefix (e.g. 0xDEAD).")
@click.option("--suffix", default=None, help="Desired address suffix.")
@click.option("--chain", default="ethereum", show_default=True)
@click.option("--workers", default=2, show_default=True)
def vanity(prefix, suffix, chain, workers):
    """Search for a vanity address."""
    from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
    if not prefix and not suffix:
        console.print("[red]Provide --prefix or --suffix.[/red]")
        return
    gen = VanityAddressGenerator()
    console.print(f"Searching for vanity address on {chain} …  (Ctrl+C to cancel)")
    result = gen.find(chain=chain, prefix=prefix, suffix=suffix, workers=workers)
    if result:
        console.print(f"\n[bold green]Found![/bold green]")
        console.print(f"Address:     [cyan]{result.address}[/cyan]")
        console.print(f"Private key: [yellow]{result.private_key}[/yellow]")
        console.print(f"Attempts:    {result.attempts}")
        console.print(f"Time:        {result.elapsed_seconds:.1f}s")
    else:
        console.print("[yellow]Not found within attempt budget.[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────
# bot commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def bot():
    """Trading bot commands."""


@bot.command("arb")
@click.option("--chain", default="ethereum", show_default=True)
@click.option("--dry-run/--live", default=True, show_default=True)
@click.option("--min-profit", default=5.0, show_default=True, help="Min profit in USD.")
def bot_arb(chain: str, dry_run: bool, min_profit: float):
    """Run the arbitrage bot."""
    from crypto_toolkit.trading.arbitrage_bot import ArbitrageBot
    bot_instance = ArbitrageBot(min_profit_usd=min_profit, dry_run=dry_run)
    asyncio.run(bot_instance.start(chain=chain))


@bot.command("ai")
@click.option("--token", default="ethereum", show_default=True)
@click.option("--chain", default="ethereum", show_default=True)
@click.option("--dry-run/--live", default=True, show_default=True)
@click.option("--llm/--ml", default=False, help="Use LLM instead of ML model.")
def bot_ai(token: str, chain: str, dry_run: bool, llm: bool):
    """Run the AI trading bot."""
    from crypto_toolkit.trading.ai_trading_bot import AITradingBot
    bot_instance = AITradingBot(use_llm=llm, dry_run=dry_run)
    asyncio.run(bot_instance.start(token_id=token, chain=chain))


@bot.command("mev")
@click.option("--chain", default="ethereum", show_default=True)
@click.option("--dry-run/--live", default=True, show_default=True)
def bot_mev(chain: str, dry_run: bool):
    """Run the MEV bot (monitors mempool for sandwich opportunities)."""
    from crypto_toolkit.trading.mev_bot import MEVBot
    bot_instance = MEVBot(dry_run=dry_run)
    asyncio.run(bot_instance.start(chain=chain))


# ─────────────────────────────────────────────────────────────────────────────
# saas commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.group()
def saas():
    """SaaS service commands."""


@saas.command("payment-wall")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True)
def saas_payment_wall(host: str, port: int):
    """Start the crypto payment-wall SaaS server."""
    import uvicorn
    console.print(f"[bold green]Starting Payment Wall on {host}:{port}[/bold green]")
    uvicorn.run("crypto_toolkit.saas.payment_wall:app", host=host, port=port, reload=False)


@saas.command("faucet")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8001, show_default=True)
def saas_faucet(host: str, port: int):
    """Start the crypto faucet SaaS server."""
    import uvicorn
    console.print(f"[bold green]Starting Faucet on {host}:{port}[/bold green]")
    uvicorn.run("crypto_toolkit.saas.faucet:app", host=host, port=port, reload=False)


# ─────────────────────────────────────────────────────────────────────────────
# dex commands
# ─────────────────────────────────────────────────────────────────────────────

@cli.command("dex")
@click.option("--dex", default="uniswap_v2", show_default=True)
@click.option("--limit", default=20, show_default=True)
@click.option("--min-liquidity", default=1000.0, show_default=True)
def dex_screen(dex: str, limit: int, min_liquidity: float):
    """Fetch recently listed pairs from a DEX."""
    from crypto_toolkit.trading.dex_screener import DexScreener
    screener = DexScreener()
    pairs = asyncio.run(screener.get_new_pairs(dex, limit=limit, min_liquidity_usd=min_liquidity))

    table = Table(title=f"New pairs on {dex}")
    table.add_column("Pair", style="cyan")
    table.add_column("Address", style="dim")
    table.add_column("Liquidity USD", justify="right")
    table.add_column("Volume 24h USD", justify="right")

    for p in pairs:
        table.add_row(
            f"{p.token0_symbol}/{p.token1_symbol}",
            p.pair_address[:12] + "…",
            f"${p.reserve_usd:,.0f}",
            f"${p.volume_usd_24h:,.0f}",
        )
    console.print(table)


if __name__ == "__main__":
    cli()
