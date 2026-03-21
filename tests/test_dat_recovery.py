"""Unit tests for dat_recovery password generators."""

import pytest

from crypto_toolkit.wallet.dat_recovery import (
    dictionary_passwords,
    mask_passwords,
    mutated_passwords,
)
import tempfile
import os


class TestDictionaryPasswords:
    def test_yields_all_lines(self, tmp_path):
        wordlist = tmp_path / "words.txt"
        wordlist.write_text("hello\nworld\npassword\n")
        result = list(dictionary_passwords(str(wordlist)))
        assert result == ["hello", "world", "password"]

    def test_strips_newlines(self, tmp_path):
        wordlist = tmp_path / "words.txt"
        wordlist.write_text("abc\ndef\n")
        result = list(dictionary_passwords(str(wordlist)))
        assert all("\n" not in pw for pw in result)


class TestMaskPasswords:
    def test_digit_mask(self):
        results = list(mask_passwords("?d?d"))
        assert len(results) == 100  # 10^2
        assert "00" in results
        assert "99" in results

    def test_literal_chars(self):
        results = list(mask_passwords("Pass?d"))
        assert "Pass0" in results
        assert "Pass9" in results
        assert all(r.startswith("Pass") for r in results)

    def test_combined_mask(self):
        results = list(mask_passwords("?u?l"))
        assert len(results) == 26 * 26
        assert "Aa" in results

    def test_empty_mask(self):
        results = list(mask_passwords(""))
        assert results == [""]


class TestMutatedPasswords:
    def test_contains_original(self):
        mutations = set(mutated_passwords("hello"))
        assert "hello" in mutations

    def test_contains_uppercase(self):
        mutations = set(mutated_passwords("hello"))
        assert "HELLO" in mutations

    def test_contains_capitalized(self):
        mutations = set(mutated_passwords("hello"))
        assert "Hello" in mutations

    def test_contains_numeric_suffix(self):
        mutations = set(mutated_passwords("hello"))
        assert "hello1" in mutations
        assert "hello123" in mutations

    def test_leet_substitution(self):
        mutations = set(mutated_passwords("hello"))
        # h→h, e→3, l→l, l→l, o→0 → h3ll0
        assert "h3ll0" in mutations

    def test_returns_multiple_variants(self):
        mutations = list(mutated_passwords("test"))
        assert len(mutations) > 5
