"""Unit tests for multi-chain wallet generation."""

import pytest

from crypto_toolkit.wallet.wallet_generator import WalletGenerator, bip44_path, WalletInfo


class TestBip44Path:
    def test_ethereum_path(self):
        assert bip44_path("ethereum") == "m/44'/60'/0'/0/0"

    def test_bitcoin_path(self):
        assert bip44_path("bitcoin") == "m/44'/0'/0'/0/0"

    def test_solana_path(self):
        assert bip44_path("solana") == "m/44'/501'/0'/0/0"

    def test_account_and_index(self):
        path = bip44_path("ethereum", account=2, index=5)
        assert path == "m/44'/60'/2'/0/5"


class TestWalletGenerator:
    def setup_method(self):
        self.gen = WalletGenerator()

    # ── EVM wallet creation ───────────────────────────────────────────────────

    @pytest.mark.parametrize("chain", ["ethereum", "bsc", "polygon", "arbitrum"])
    def test_create_evm_chain(self, chain):
        w = self.gen.create(chain=chain)
        assert w.address.startswith("0x")
        assert len(w.address) == 42
        assert w.private_key
        assert w.chain == chain
        assert w.mnemonic is not None
        assert len(w.mnemonic.split()) == 12

    def test_create_24_words(self):
        w = self.gen.create(num_words=24)
        assert w.mnemonic and len(w.mnemonic.split()) == 24

    def test_create_uniqueness(self):
        w1 = self.gen.create()
        w2 = self.gen.create()
        assert w1.address != w2.address
        assert w1.mnemonic != w2.mnemonic

    # ── From mnemonic ────────────────────────────────────────────────────────

    def test_from_mnemonic_determinism(self):
        w1 = self.gen.create()
        w2 = self.gen.from_mnemonic(w1.mnemonic or "", chain=w1.chain)
        assert w1.address == w2.address

    def test_from_mnemonic_different_index(self):
        w = self.gen.create()
        mnemonic = w.mnemonic or ""
        w0 = self.gen.from_mnemonic(mnemonic, index=0)
        w1 = self.gen.from_mnemonic(mnemonic, index=1)
        assert w0.address != w1.address

    def test_from_mnemonic_with_passphrase(self):
        w = self.gen.create()
        mnemonic = w.mnemonic or ""
        wa = self.gen.from_mnemonic(mnemonic, passphrase="")
        wb = self.gen.from_mnemonic(mnemonic, passphrase="secret")
        assert wa.address != wb.address

    # ── From private key ─────────────────────────────────────────────────────

    def test_from_private_key(self):
        original = self.gen.create()
        recovered = self.gen.from_private_key(original.private_key, chain=original.chain)
        assert recovered.address == original.address

    # ── Batch derivation ─────────────────────────────────────────────────────

    def test_derive_batch_count(self):
        w = self.gen.create()
        batch = self.gen.derive_batch(w.mnemonic or "", count=5)
        assert len(batch) == 5

    def test_derive_batch_addresses_unique(self):
        w = self.gen.create()
        batch = self.gen.derive_batch(w.mnemonic or "", count=5)
        addresses = [b.address for b in batch]
        assert len(set(addresses)) == 5

    def test_derive_batch_first_matches_single(self):
        w = self.gen.create()
        batch = self.gen.derive_batch(w.mnemonic or "", count=1)
        single = self.gen.from_mnemonic(w.mnemonic or "", index=0)
        assert batch[0].address == single.address

    # ── Wallet info fields ────────────────────────────────────────────────────

    def test_wallet_info_has_all_fields(self):
        w = self.gen.create()
        assert isinstance(w, WalletInfo)
        assert w.address
        assert w.private_key
        assert w.chain
        assert w.derivation_path
        assert w.mnemonic
