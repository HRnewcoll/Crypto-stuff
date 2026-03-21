"""Unit tests for BIP-39 mnemonic generation and seed derivation."""

import pytest

from crypto_toolkit.wallet.bip39 import BIP39, SUPPORTED_LANGUAGES


class TestBIP39:
    def setup_method(self):
        self.bip39 = BIP39()

    # ── Generation ────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("num_words", [12, 15, 18, 21, 24])
    def test_generate_word_counts(self, num_words):
        mnemonic = self.bip39.generate(num_words)
        words = mnemonic.strip().split()
        assert len(words) == num_words

    def test_generate_default_12_words(self):
        mnemonic = self.bip39.generate()
        assert len(mnemonic.split()) == 12

    def test_generate_invalid_word_count(self):
        with pytest.raises(ValueError):
            self.bip39.generate(11)

    def test_generate_uniqueness(self):
        m1 = self.bip39.generate()
        m2 = self.bip39.generate()
        assert m1 != m2

    # ── Validation ────────────────────────────────────────────────────────────

    def test_valid_mnemonic(self):
        mnemonic = self.bip39.generate()
        assert self.bip39.is_valid(mnemonic)

    def test_invalid_mnemonic(self):
        assert not self.bip39.is_valid("this is not a valid bip39 mnemonic phrase at all")

    # ── Seed derivation ───────────────────────────────────────────────────────

    def test_seed_length(self):
        mnemonic = self.bip39.generate()
        seed = self.bip39.to_seed(mnemonic)
        assert len(seed) == 64

    def test_seed_determinism(self):
        mnemonic = self.bip39.generate()
        s1 = self.bip39.to_seed(mnemonic)
        s2 = self.bip39.to_seed(mnemonic)
        assert s1 == s2

    def test_seed_differs_with_passphrase(self):
        mnemonic = self.bip39.generate()
        s1 = self.bip39.to_seed(mnemonic, passphrase="")
        s2 = self.bip39.to_seed(mnemonic, passphrase="secret")
        assert s1 != s2

    def test_seed_hex_is_string(self):
        mnemonic = self.bip39.generate()
        seed_hex = self.bip39.to_seed_hex(mnemonic)
        assert isinstance(seed_hex, str)
        assert len(seed_hex) == 128

    def test_invalid_mnemonic_raises_on_seed(self):
        with pytest.raises(ValueError):
            self.bip39.to_seed("invalid mnemonic")

    # ── Master key ────────────────────────────────────────────────────────────

    def test_master_key_structure(self):
        mnemonic = self.bip39.generate()
        keys = self.bip39.to_master_key(mnemonic)
        assert "master_private_key" in keys
        assert "chain_code" in keys
        assert len(keys["master_private_key"]) == 64
        assert len(keys["chain_code"]) == 64

    # ── Entropy generation ───────────────────────────────────────────────────

    def test_generate_from_entropy(self):
        entropy = "a" * 32  # 16 bytes = 128 bits
        mnemonic = self.bip39.generate_from_entropy(entropy)
        assert self.bip39.is_valid(mnemonic)
        assert len(mnemonic.split()) == 12

    def test_generate_from_entropy_invalid_length(self):
        with pytest.raises(ValueError):
            self.bip39.generate_from_entropy("aabb")  # too short

    # ── Languages ────────────────────────────────────────────────────────────

    def test_supported_languages(self):
        for lang in SUPPORTED_LANGUAGES:
            b = BIP39(language=lang)
            mnemonic = b.generate()
            assert b.is_valid(mnemonic)

    def test_unsupported_language(self):
        with pytest.raises(ValueError):
            BIP39(language="klingon")

    # ── Wordlist ─────────────────────────────────────────────────────────────

    def test_wordlist_length(self):
        wordlist = self.bip39.get_wordlist()
        assert len(wordlist) == 2048
