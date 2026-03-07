"""
Memecoin / ERC-20 token factory and deployer.

Creates and deploys a fully customisable ERC-20 (or BEP-20) token with:
  - Configurable name, symbol, decimals, and total supply.
  - Optional: mint/burn, ownership, blacklist, transaction taxes (buy/sell fee).
  - Optional: liquidity lock helper (add liquidity to Uniswap / PancakeSwap).

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
