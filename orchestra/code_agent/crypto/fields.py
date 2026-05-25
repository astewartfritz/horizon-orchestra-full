"""
Field-level encryption for sensitive database columns.

PHI (patient name, DOB, SSN, diagnosis), PII (emails in some contexts),
and financial identifiers are encrypted at rest using AES-128-CBC + HMAC
(Fernet) derived from the API_KEY_ENCRYPTION_KEY environment variable.

Format stored in DB:  enc:v1:<fernet_token>
Plaintext fields are stored as-is (no prefix) for backwards compatibility.

Usage::

    from orchestra.code_agent.crypto.fields import encrypt, decrypt, EncryptedField

    # Encrypt before INSERT
    row["ssn"] = encrypt(ssn)

    # Decrypt after SELECT
    ssn = decrypt(row["ssn"])

    # Transparent wrapper for dataclass fields
    @dataclass
    class Patient:
        name: str = field(metadata={"encrypted": True})
"""
from __future__ import annotations

import base64
import hashlib
import os
import threading
from functools import lru_cache
from typing import Any

_PREFIX = b"enc:v1:"
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _fernet():
    """Return a cached Fernet instance derived from the encryption key."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    raw_key = os.environ.get("API_KEY_ENCRYPTION_KEY", "")
    if not raw_key:
        # Dev fallback: deterministic key from a fixed salt — NOT for production
        raw_key = "orchestra_dev_key_not_for_production"

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"orchestra_field_enc_v1",  # static salt — key itself provides entropy
        iterations=100_000,
    )
    key_bytes = kdf.derive(raw_key.encode())
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt(value: str | None) -> str | None:
    """Encrypt a plaintext string. Returns None if value is None/empty."""
    if not value:
        return value
    token = _fernet().encrypt(value.encode("utf-8"))
    return (_PREFIX + token).decode("ascii")


def decrypt(value: str | None) -> str | None:
    """Decrypt an encrypted field. Passes through plaintext transparently."""
    if not value:
        return value
    encoded = value.encode("ascii") if isinstance(value, str) else value
    if not encoded.startswith(_PREFIX):
        return value  # already plaintext (pre-migration or non-sensitive)
    token = encoded[len(_PREFIX):]
    return _fernet().decrypt(token).decode("utf-8")


def is_encrypted(value: str | None) -> bool:
    if not value:
        return False
    return value.encode("ascii", errors="replace").startswith(_PREFIX)


def deterministic_hash(value: str | None) -> str | None:
    """
    One-way searchable hash for encrypted fields that need equality lookup
    (e.g., searching by SSN or email without decrypting all rows).

    Uses HMAC-SHA256 keyed by the encryption key so the hash is not
    reversible without the key.
    """
    if not value:
        return value
    import hmac
    key = os.environ.get("API_KEY_ENCRYPTION_KEY", "orchestra_dev_key_not_for_production")
    return hmac.new(key.encode(), value.lower().encode(), hashlib.sha256).hexdigest()


# ── Batch helpers ─────────────────────────────────────────────────────────────

def encrypt_row(row: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    """Return a copy of row with specified fields encrypted."""
    return {k: (encrypt(v) if k in fields and isinstance(v, str) else v) for k, v in row.items()}


def decrypt_row(row: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    """Return a copy of row with specified fields decrypted."""
    return {k: (decrypt(v) if k in fields and isinstance(v, str) else v) for k, v in row.items()}


# ── Field sets per vertical ───────────────────────────────────────────────────

HEALTHCARE_ENCRYPTED = frozenset({
    "name", "date_of_birth", "ssn", "phone", "address",
    "diagnosis_codes", "notes", "allergies", "medications",
})

LEGAL_ENCRYPTED = frozenset({
    "name", "phone", "address", "email", "notes",
    "opposing_party", "confidential_notes",
})

FINANCE_ENCRYPTED = frozenset({
    "account_number", "routing_number", "tax_id", "notes",
})

USER_ENCRYPTED = frozenset({
    # email is stored plaintext for login lookup but phone/address are encrypted
    "phone", "address",
})
