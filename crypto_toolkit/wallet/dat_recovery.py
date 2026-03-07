"""
Bitcoin wallet.dat recovery helper.

This module provides utilities to attempt recovering access to an encrypted
Bitcoin Core ``wallet.dat`` file when the password has been forgotten.

Techniques supported:
1. Dictionary attack       – try words / phrases from a wordlist file.
2. Mask attack             – try all combinations matching a pattern,
                            e.g. ``Pass????2020`` where ``?`` = any digit.
3. Rule-based mutations    – capitalize, leet, append/prepend numbers etc.
4. BIP-39 recovery         – verify if a BIP-39 mnemonic unlocks the wallet.

⚠  LEGAL NOTICE: Only use this tool on wallets you own or have explicit
written permission to recover.  Unauthorized access to others' wallets is
illegal in most jurisdictions.
"""

from __future__ import annotations

import itertools
import string
from pathlib import Path
from typing import Callable, Generator, Iterable, Optional

try:
    import bitcoin
    _BITCOIN_AVAILABLE = True
except ImportError:
    _BITCOIN_AVAILABLE = False

try:
    # pywallet is a community tool for wallet.dat parsing
    # pip install pywallet  (optional dependency)
    import pywallet  # type: ignore
    _PYWALLET_AVAILABLE = True
except ImportError:
    _PYWALLET_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Password generators
# ─────────────────────────────────────────────────────────────────────────────

def dictionary_passwords(wordlist_path: str) -> Generator[str, None, None]:
    """Yield passwords from a wordlist file (one per line)."""
    with open(wordlist_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            yield line.rstrip("\n")


def mask_passwords(mask: str, charset_map: Optional[dict[str, str]] = None) -> Generator[str, None, None]:
    """Yield all passwords that match a mask.

    Default mask characters:
        ?d  – digits (0-9)
        ?l  – lowercase letters
        ?u  – uppercase letters
        ?a  – all printable ASCII
        ?s  – special characters
        ?b  – custom charset (provide via charset_map['b'])

    Example:
        ``Pass?d?d?d?d`` yields Pass0000 … Pass9999
    """
    default_map = {
        "d": string.digits,
        "l": string.ascii_lowercase,
        "u": string.ascii_uppercase,
        "a": string.printable,
        "s": string.punctuation,
    }
    if charset_map:
        default_map.update(charset_map)

    # Parse the mask into literal chars and charset slots
    slots: list[str | list[str]] = []
    i = 0
    while i < len(mask):
        if mask[i] == "?" and i + 1 < len(mask) and mask[i + 1] in default_map:
            slots.append(list(default_map[mask[i + 1]]))
            i += 2
        else:
            slots.append(mask[i])
            i += 1

    for combo in itertools.product(*[s if isinstance(s, list) else [s] for s in slots]):
        yield "".join(combo)


def mutated_passwords(base: str) -> Generator[str, None, None]:
    """Yield common mutations of a base password."""
    variants = {base}
    # Capitalization
    variants.add(base.capitalize())
    variants.add(base.upper())
    variants.add(base.lower())
    # Leet substitutions
    leet_map = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7"}
    leet = "".join(leet_map.get(c.lower(), c) for c in base)
    variants.add(leet)
    # Append / prepend common suffixes
    import datetime
    current_year = datetime.datetime.now().year
    year_suffixes = [str(y) for y in range(current_year - 5, current_year + 1)]
    for suffix in ["1", "12", "123", "1234", "!", "#", "@"] + year_suffixes:
        variants.add(base + suffix)
        variants.add(suffix + base)
    yield from variants


# ─────────────────────────────────────────────────────────────────────────────
# DatRecovery
# ─────────────────────────────────────────────────────────────────────────────

class DatRecovery:
    """Attempt to recover the password for a Bitcoin Core wallet.dat file.

    Usage::

        recovery = DatRecovery("wallet.dat")
        password = recovery.dictionary_attack("rockyou.txt")
        if password:
            print(f"Found password: {password}")
    """

    def __init__(self, wallet_path: str) -> None:
        self.wallet_path = Path(wallet_path)
        if not self.wallet_path.exists():
            raise FileNotFoundError(f"wallet.dat not found: {wallet_path}")

    # ------------------------------------------------------------------
    # High-level attack methods
    # ------------------------------------------------------------------

    def dictionary_attack(
        self,
        wordlist_path: str,
        verbose: bool = False,
    ) -> Optional[str]:
        """Try passwords from a wordlist file.

        Returns the correct password or ``None``.
        """
        return self._try_passwords(
            dictionary_passwords(wordlist_path),
            verbose=verbose,
        )

    def mask_attack(
        self,
        mask: str,
        charset_map: Optional[dict[str, str]] = None,
        verbose: bool = False,
    ) -> Optional[str]:
        """Try all combinations matching a mask pattern.

        Returns the correct password or ``None``.
        """
        return self._try_passwords(
            mask_passwords(mask, charset_map),
            verbose=verbose,
        )

    def mutation_attack(
        self,
        base_passwords: Iterable[str],
        verbose: bool = False,
    ) -> Optional[str]:
        """Apply common mutations to a list of base passwords.

        Returns the correct password or ``None``.
        """
        def gen() -> Generator[str, None, None]:
            for base in base_passwords:
                yield from mutated_passwords(base)

        return self._try_passwords(gen(), verbose=verbose)

    def bip39_recovery(
        self,
        mnemonic: str,
        passphrase: str = "",
    ) -> Optional[str]:
        """Check whether a BIP-39 mnemonic unlocks a wallet.

        This is useful if the wallet was created by a BIP-39-compatible
        application that also wrote a wallet.dat for compatibility.

        Returns the mnemonic if verified, else ``None``.
        """
        from crypto_toolkit.wallet.bip39 import BIP39
        b = BIP39()
        if not b.is_valid(mnemonic):
            return None
        seed_hex = b.to_seed_hex(mnemonic, passphrase)
        # Use seed_hex as the "password" for wallet.dat decryption attempt
        result = self._try_password(seed_hex)
        return mnemonic if result else None

    # ------------------------------------------------------------------
    # Core unlock logic
    # ------------------------------------------------------------------

    def _try_passwords(
        self,
        passwords: Iterable[str],
        verbose: bool = False,
    ) -> Optional[str]:
        for i, pw in enumerate(passwords):
            if verbose and i % 1000 == 0:
                print(f"Tried {i} passwords …")
            if self._try_password(pw):
                return pw
        return None

    def _try_password(self, password: str) -> bool:
        """Return True if *password* successfully decrypts the wallet."""
        if _PYWALLET_AVAILABLE:
            return self._try_via_pywallet(password)
        return self._try_via_bitcoin_lib(password)

    def _try_via_pywallet(self, password: str) -> bool:
        try:
            pywallet.read_wallet(self.wallet_path, password)
            return True
        except Exception:
            return False

    def _try_via_bitcoin_lib(self, password: str) -> bool:
        """
        Fallback: attempt AES-CBC decryption of the wallet master key.

        wallet.dat stores an encrypted master key:
            - salt (8 bytes)
            - nIter (4 bytes)
            - encrypted key (32 bytes)
        The decryption key is derived via EVP_BytesToKey (MD5, 1 round) from
        (password + salt).  If decrypted key looks like a valid secp256k1
        private key the password is correct.
        """
        try:
            from Crypto.Cipher import AES
            from Crypto.Hash import MD5

            # Byte offsets within the mkey record (Berkeley DB wallet.dat format)
            _MKEY_HEADER_LEN = 5
            _ENCRYPTED_KEY_LEN = 48
            _SALT_OFFSET = 48
            _SALT_LEN = 8
            _NITER_OFFSET = 56
            _NITER_LEN = 4
            _DERIVED_KEY_LEN = 32
            _IV_OFFSET = 60
            _IV_LEN = 16
            data = self.wallet_path.read_bytes()
            mkey_idx = data.find(b"\x04mkey")
            if mkey_idx == -1:
                return False

            # Rough extraction – skip the mkey record header (5 bytes typical)
            offset = mkey_idx + _MKEY_HEADER_LEN
            encrypted_key = data[offset: offset + _ENCRYPTED_KEY_LEN]
            salt = data[offset + _SALT_OFFSET: offset + _SALT_OFFSET + _SALT_LEN]
            n_iter = int.from_bytes(data[offset + _NITER_OFFSET: offset + _NITER_OFFSET + _NITER_LEN], "little")

            # Derive decryption key using EVP_BytesToKey
            dk = b""
            prev = b""
            while len(dk) < _DERIVED_KEY_LEN:
                prev = MD5.new(prev + password.encode() + salt).digest()
                dk += prev
            dk = dk[:_DERIVED_KEY_LEN]
            iv = data[offset + _IV_OFFSET: offset + _IV_OFFSET + _IV_LEN] if len(data) > offset + _IV_OFFSET + _IV_LEN else b"\x00" * _IV_LEN

            cipher = AES.new(dk, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted_key[:32])

            # A valid secp256k1 private key is 32 non-zero bytes < curve order
            key_int = int.from_bytes(decrypted, "big")
            _CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
            return 0 < key_int < _CURVE_ORDER
        except Exception:
            return False
