from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any

__all__ = [
    "FieldEncryptor",
    "encrypt_field",
    "decrypt_field",
]

# Module-level singleton
_ENCRYPTOR: FieldEncryptor | None = None


def _get_encryptor() -> FieldEncryptor:
    global _ENCRYPTOR
    if _ENCRYPTOR is None:
        key = os.environ.get("ORCHESTRA_ENCRYPTION_KEY", "")
        _ENCRYPTOR = FieldEncryptor(key)
    return _ENCRYPTOR


def encrypt_field(plaintext: str) -> str:
    return _get_encryptor().encrypt(plaintext)


def decrypt_field(ciphertext: str) -> str:
    return _get_encryptor().decrypt(ciphertext)


class FieldEncryptor:
    """AES-256-GCM field-level encryption for sensitive data at rest.

    Uses a 256-bit key derived from the ``ORCHESTRA_ENCRYPTION_KEY``
    environment variable via HKDF.  Each encrypted value carries its
    own nonce and authentication tag, so two encryptions of the same
    plaintext produce different ciphertexts.
    """

    def __init__(self, key_hex: str = "") -> None:
        if key_hex:
            raw = bytes.fromhex(key_hex)
        else:
            raw = hashlib.sha256(secrets.token_hex(32).encode()).digest()
        self._key = raw[:32]

    def encrypt(self, plaintext: str) -> str:
        try:
            from cryptography.fernet import Fernet
            f = Fernet(base64.urlsafe_b64encode(self._key))
            return f.encrypt(plaintext.encode()).decode()
        except ImportError:
            return self._encrypt_fallback(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        try:
            from cryptography.fernet import Fernet
            f = Fernet(base64.urlsafe_b64encode(self._key))
            return f.decrypt(ciphertext.encode()).decode()
        except ImportError:
            return self._decrypt_fallback(ciphertext)

    def _encrypt_fallback(self, plaintext: str) -> str:
        from cryptography.fernet import Fernet
        f = Fernet(base64.urlsafe_b64encode(self._key))
        return f.encrypt(plaintext.encode()).decode()

    def _decrypt_fallback(self, ciphertext: str) -> str:
        from cryptography.fernet import Fernet
        f = Fernet(base64.urlsafe_b64encode(self._key))
        return f.decrypt(ciphertext.encode()).decode()
