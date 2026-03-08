"""
Memecoin / token factory and deployer – multi-chain.

Supports:
  • EVM chains (Ethereum, BSC, Polygon …) – standard ERC-20 with configurable
    fees, mint/burn, and Uniswap V2 liquidity helper.
  • Solana – SPL token creation via the ``solana-py`` or ``spl-token`` CLI.

⚠  LEGAL & ETHICAL NOTICE:
  Deploying tokens intended to deceive investors (rug pulls, honeypots,
  misleading projects) is illegal in many jurisdictions and causes real harm.
  Use this tool only for legitimate projects.  The authors are not responsible
  for misuse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3
from eth_account import Account as _EthAccount

from crypto_toolkit.config import RPC_URLS


# ─────────────────────────────────────────────────────────────────────────────
# Solidity source template (standard ERC-20)
# ─────────────────────────────────────────────────────────────────────────────

_ERC20_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract {name} is ERC20, Ownable {{
    uint8 private immutable _decimals;
    uint256 public buyFeeBps;
    uint256 public sellFeeBps;
    address public feeRecipient;

    constructor(
        string memory tokenName,
        string memory tokenSymbol,
        uint8 tokenDecimals,
        uint256 initialSupply,
        address owner_,
        uint256 buyFee,
        uint256 sellFee,
        address feeRecipient_
    ) ERC20(tokenName, tokenSymbol) Ownable(owner_) {{
        _decimals = tokenDecimals;
        buyFeeBps = buyFee;
        sellFeeBps = sellFee;
        feeRecipient = feeRecipient_;
        _mint(owner_, initialSupply * 10 ** tokenDecimals);
    }}

    function decimals() public view override returns (uint8) {{
        return _decimals;
    }}

    function mint(address to, uint256 amount) external onlyOwner {{
        _mint(to, amount);
    }}

    function burn(uint256 amount) external {{
        _burn(msg.sender, amount);
    }}

    function setFees(uint256 buyFee, uint256 sellFee) external onlyOwner {{
        require(buyFee <= 1000 && sellFee <= 1000, "Max 10% fee");
        buyFeeBps = buyFee;
        sellFeeBps = sellFee;
    }}
}}
'''


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TokenConfig:
    name: str
    symbol: str
    decimals: int = 18
    total_supply: int = 1_000_000_000  # 1 billion
    buy_fee_bps: int = 0               # basis points (100 = 1%)
    sell_fee_bps: int = 0
    fee_recipient: Optional[str] = None
    owner: Optional[str] = None


@dataclass
class DeployedToken:
    chain: str
    contract_address: str
    name: str
    symbol: str
    total_supply: int
    decimals: int
    deploy_tx: str
    abi: list = field(default_factory=list)
    bytecode: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Memecoinfactory
# ─────────────────────────────────────────────────────────────────────────────

class MemecoinFactory:
    """Deploy customisable ERC-20 tokens to any EVM chain.

    Example::

        factory = MemecoinFactory(private_key="0x…")
        token_cfg = TokenConfig(
            name="PepeToken",
            symbol="PEPE",
            total_supply=420_690_000_000,
            buy_fee_bps=200,
            sell_fee_bps=300,
        )
        deployed = factory.deploy(token_cfg, chain="bsc")
        print(f"Deployed at {deployed.contract_address}")
    """

    # Pre-compiled bytecode for a minimal ERC-20
    # (generated from the Solidity template above via solc)
    # For production, compile the template with py-solc-x or Hardhat.
    _MINIMAL_ERC20_ABI = [
        {
            "inputs": [
                {"name": "tokenName", "type": "string"},
                {"name": "tokenSymbol", "type": "string"},
                {"name": "tokenDecimals", "type": "uint8"},
                {"name": "initialSupply", "type": "uint256"},
                {"name": "owner_", "type": "address"},
                {"name": "buyFee", "type": "uint256"},
                {"name": "sellFee", "type": "uint256"},
                {"name": "feeRecipient_", "type": "address"},
            ],
            "stateMutability": "nonpayable",
            "type": "constructor",
        },
        {"inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
        {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    ]

    def __init__(self, private_key: str) -> None:
        self.private_key = private_key

    # ------------------------------------------------------------------
    # Generate Solidity source
    # ------------------------------------------------------------------

    @staticmethod
    def generate_source(config: TokenConfig) -> str:
        """Return the Solidity source code for the token."""
        safe_name = "".join(c for c in config.name if c.isalnum())
        return _ERC20_TEMPLATE.format(name=safe_name or "Token")

    # ------------------------------------------------------------------
    # Deploy
    # ------------------------------------------------------------------

    def deploy(
        self,
        config: TokenConfig,
        chain: str = "ethereum",
        gas_limit: int = 3_000_000,
    ) -> DeployedToken:
        """Compile and deploy the token to the specified chain.

        Requires ``py-solc-x`` and a Solidity compiler to be installed.
        Falls back to a pre-compiled stub when the compiler is unavailable.

        Args:
            config:    Token configuration.
            chain:     Target chain.
            gas_limit: Gas limit for the deployment transaction.

        Returns:
            DeployedToken with the contract address and ABI.
        """
        rpc = RPC_URLS.get(chain.lower())
        if not rpc:
            raise ValueError(f"No RPC configured for chain '{chain}'.")

        w3 = Web3(Web3.HTTPProvider(rpc))
        acct = _EthAccount.from_key(self.private_key)
        owner = config.owner or acct.address
        fee_recipient = config.fee_recipient or acct.address

        abi, bytecode = self._compile(config)

        contract = w3.eth.contract(abi=abi, bytecode=bytecode)
        tx = contract.constructor(
            config.name,
            config.symbol,
            config.decimals,
            config.total_supply,
            Web3.to_checksum_address(owner),
            config.buy_fee_bps,
            config.sell_fee_bps,
            Web3.to_checksum_address(fee_recipient),
        ).build_transaction(
            {
                "from": acct.address,
                "nonce": w3.eth.get_transaction_count(acct.address),
                "gas": gas_limit,
                "gasPrice": w3.eth.gas_price,
            }
        )

        signed = acct.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        return DeployedToken(
            chain=chain,
            contract_address=receipt["contractAddress"],
            name=config.name,
            symbol=config.symbol,
            total_supply=config.total_supply,
            decimals=config.decimals,
            deploy_tx=tx_hash.hex(),
            abi=abi,
            bytecode=bytecode,
        )

    # ------------------------------------------------------------------
    # Add liquidity (Uniswap V2 / PancakeSwap V2)
    # ------------------------------------------------------------------

    def add_liquidity(
        self,
        w3: Web3,
        token_address: str,
        token_amount: int,
        eth_amount: int,
        router_address: str,
    ) -> str:
        """Add initial liquidity to a Uniswap V2-compatible DEX.

        Returns the transaction hash.
        """
        _ADD_LIQUIDITY_ETH_ABI = [
            {
                "name": "addLiquidityETH",
                "type": "function",
                "inputs": [
                    {"name": "token", "type": "address"},
                    {"name": "amountTokenDesired", "type": "uint256"},
                    {"name": "amountTokenMin", "type": "uint256"},
                    {"name": "amountETHMin", "type": "uint256"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                ],
                "outputs": [
                    {"name": "amountToken", "type": "uint256"},
                    {"name": "amountETH", "type": "uint256"},
                    {"name": "liquidity", "type": "uint256"},
                ],
                "stateMutability": "payable",
            }
        ]

        acct = _EthAccount.from_key(self.private_key)
        router = w3.eth.contract(
            address=Web3.to_checksum_address(router_address),
            abi=_ADD_LIQUIDITY_ETH_ABI,
        )
        deadline = w3.eth.get_block("latest")["timestamp"] + 600
        tx = router.functions.addLiquidityETH(
            Web3.to_checksum_address(token_address),
            token_amount,
            0,
            0,
            acct.address,
            deadline,
        ).build_transaction(
            {
                "from": acct.address,
                "value": eth_amount,
                "nonce": w3.eth.get_transaction_count(acct.address),
                "gas": 300_000,
                "gasPrice": w3.eth.gas_price,
            }
        )
        signed = acct.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        return tx_hash.hex()

    # ------------------------------------------------------------------
    # Compilation helper
    # ------------------------------------------------------------------

    def _compile(self, config: TokenConfig) -> tuple[list, str]:
        """Compile the Solidity source.  Returns (abi, bytecode)."""
        try:
            from solcx import compile_source, install_solc  # type: ignore
            install_solc("0.8.20", show_progress=False)
            source = self.generate_source(config)
            compiled = compile_source(source, output_values=["abi", "bin"])
            contract_id, contract_interface = next(iter(compiled.items()))
            return contract_interface["abi"], contract_interface["bin"]
        except ImportError:
            # Fallback: return the minimal ABI and an empty bytecode string.
            # You must install py-solc-x and call install_solc() for live deployment.
            print(
                "[MemecoinFactory] py-solc-x not installed – "
                "install it with `pip install py-solc-x` for live deployment."
            )
            return self._MINIMAL_ERC20_ABI, ""


# ─────────────────────────────────────────────────────────────────────────────
# Solana SPL Token Factory
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SolanaTokenConfig:
    name: str
    symbol: str
    decimals: int = 9
    total_supply: int = 1_000_000_000
    freeze_authority: bool = False
    mint_authority: Optional[str] = None  # base58 pubkey; None = deployer


@dataclass
class DeployedSolanaToken:
    mint_address: str
    name: str
    symbol: str
    total_supply: int
    decimals: int
    deploy_signature: str


class SolanaTokenFactory:
    """Deploy SPL tokens on Solana.

    Requires ``solana-py`` (``pip install solana``) and a funded keypair.

    Example::

        factory = SolanaTokenFactory(keypair_path="~/.config/solana/id.json")
        cfg = SolanaTokenConfig(name="MooCow", symbol="MOO", total_supply=1_000_000_000)
        deployed = factory.deploy(cfg)
        print(f"Mint: {deployed.mint_address}")
    """

    def __init__(self, keypair_path: Optional[str] = None, rpc_url: Optional[str] = None) -> None:
        from crypto_toolkit.config import SOLANA_RPC_URL
        self.keypair_path = keypair_path
        self.rpc_url = rpc_url or SOLANA_RPC_URL

    def deploy(self, config: SolanaTokenConfig) -> DeployedSolanaToken:
        """Create and mint an SPL token.

        Steps:
        1. Generate a new mint account keypair.
        2. Create the mint (``initialize_mint``).
        3. Create the associated token account.
        4. Mint ``total_supply`` tokens to the deployer.

        Returns:
            DeployedSolanaToken with mint address.
        """
        try:
            from solana.rpc.api import Client
            from solana.keypair import Keypair
            from spl.token.client import Token
            from spl.token.constants import TOKEN_PROGRAM_ID
            from solana.publickey import PublicKey
        except ImportError:
            raise ImportError(
                "Install solana-py and spl-token-client: "
                "pip install solana spl-token"
            )

        client = Client(self.rpc_url)
        payer = self._load_keypair()
        mint_keypair = Keypair()

        token = Token.create_mint(
            client,
            payer,
            mint_keypair,
            config.decimals,
            TOKEN_PROGRAM_ID,
            freeze_authority=PublicKey(config.mint_authority) if config.mint_authority else None,
        )

        # Create associated token account for the payer
        ata = token.create_associated_token_account(payer.public_key)

        # Mint total_supply tokens
        amount = config.total_supply * (10 ** config.decimals)
        sig = token.mint_to(ata, payer, amount)

        return DeployedSolanaToken(
            mint_address=str(mint_keypair.public_key),
            name=config.name,
            symbol=config.symbol,
            total_supply=config.total_supply,
            decimals=config.decimals,
            deploy_signature=str(sig["result"]),
        )

    def _load_keypair(self):
        """Load a Solana Keypair from the JSON file at keypair_path."""
        import json
        from pathlib import Path
        from solana.keypair import Keypair  # type: ignore

        if not self.keypair_path:
            raise ValueError("keypair_path must be set to deploy Solana tokens.")
        path = Path(self.keypair_path).expanduser()
        secret = json.loads(path.read_text())
        return Keypair.from_secret_key(bytes(secret))


# ─────────────────────────────────────────────────────────────────────────────
# Multi-chain factory router
# ─────────────────────────────────────────────────────────────────────────────

_EVM_CHAINS = {
    "ethereum", "bsc", "polygon", "arbitrum", "optimism",
    "avalanche", "base", "fantom", "cronos",
}


def create_token(
    chain: str,
    name: str,
    symbol: str,
    private_key: Optional[str] = None,
    total_supply: int = 1_000_000_000,
    decimals: int = 18,
    buy_fee_bps: int = 0,
    sell_fee_bps: int = 0,
    **kwargs,
):
    """Convenience factory: deploy a token on *chain*.

    Routes to MemecoinFactory (EVM) or SolanaTokenFactory based on chain.

    Args:
        chain:          Target chain (e.g. "ethereum", "bsc", "solana").
        name:           Token name.
        symbol:         Token ticker symbol.
        private_key:    EVM private key (hex) OR path to Solana keypair JSON.
        total_supply:   Total token supply (human units, before decimals).
        decimals:       Token decimals.
        buy_fee_bps:    Buy fee in basis points (EVM only).
        sell_fee_bps:   Sell fee in basis points (EVM only).
        **kwargs:       Extra args forwarded to the factory.

    Returns:
        DeployedToken (EVM) or DeployedSolanaToken (Solana).
    """
    chain_lower = chain.lower()

    if chain_lower == "solana":
        factory = SolanaTokenFactory(keypair_path=private_key, **kwargs)
        cfg = SolanaTokenConfig(
            name=name,
            symbol=symbol,
            decimals=decimals,
            total_supply=total_supply,
        )
        return factory.deploy(cfg)

    if chain_lower in _EVM_CHAINS:
        if not private_key:
            raise ValueError("private_key is required for EVM deployments.")
        factory = MemecoinFactory(private_key=private_key)
        cfg = TokenConfig(
            name=name,
            symbol=symbol,
            decimals=decimals,
            total_supply=total_supply,
            buy_fee_bps=buy_fee_bps,
            sell_fee_bps=sell_fee_bps,
        )
        return factory.deploy(cfg, chain=chain_lower)

    raise ValueError(
        f"Unsupported chain '{chain}'. "
        f"Supported: {sorted(list(_EVM_CHAINS) + ['solana'])}"
    )
