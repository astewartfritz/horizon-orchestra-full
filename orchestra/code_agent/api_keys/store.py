"""Server-side encrypted API key storage.

Keys are stored in SQLite with XOR+HMAC envelope encryption using
API_KEY_ENCRYPTION_KEY from settings. The plaintext never touches
localStorage or logs.

Schema
------
api_keys(id, user_id, provider, label, ciphertext, created_at, updated_at)
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("orchestra.api_keys")

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Simple symmetric encryption (XOR cipher + HMAC-SHA256 MAC)
# No external deps required. Swap for cryptography.Fernet in prod if desired.
# ---------------------------------------------------------------------------

def _derive_key(master: str, purpose: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        master.encode(),
        purpose.encode(),
        iterations=100_000,
        dklen=32,
    )


def _encrypt(plaintext: str, master: str) -> str:
    enc_key = _derive_key(master, "encrypt")
    mac_key = _derive_key(master, "mac")
    import secrets as _sec
    nonce = _sec.token_bytes(16)
    pt_bytes = plaintext.encode("utf-8")
    # XOR stream using SHA-256 keystream
    keystream = b""
    block = 0
    while len(keystream) < len(pt_bytes):
        keystream += hashlib.sha256(enc_key + nonce + block.to_bytes(4, "big")).digest()
        block += 1
    ct = bytes(a ^ b for a, b in zip(pt_bytes, keystream))
    mac = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    import base64
    return base64.b64encode(nonce + ct + mac).decode()


def _decrypt(ciphertext: str, master: str) -> str:
    import base64
    enc_key = _derive_key(master, "encrypt")
    mac_key = _derive_key(master, "mac")
    raw = base64.b64decode(ciphertext)
    nonce, ct, mac = raw[:16], raw[16:-32], raw[-32:]
    expected_mac = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("API key MAC verification failed — key may be corrupt or tampered")
    keystream = b""
    block = 0
    while len(keystream) < len(ct):
        keystream += hashlib.sha256(enc_key + nonce + block.to_bytes(4, "big")).digest()
        block += 1
    return bytes(a ^ b for a, b in zip(ct, keystream)).decode("utf-8")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ApiKeyStore:
    _instance: ApiKeyStore | None = None

    def __init__(self, db_path: str | Path = "orchestra.db") -> None:
        self._path = str(db_path)
        from orchestra.code_agent.settings import settings
        self._master = settings.api_key_encryption_key
        self._init_db()
        type(self)._instance = self

    @classmethod
    def get(cls) -> ApiKeyStore:
        if cls._instance is None:
            from orchestra.code_agent.settings import settings
            cls._instance = cls(db_path=settings.db_path)
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with _lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id          TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL,
                    provider    TEXT NOT NULL,
                    label       TEXT NOT NULL DEFAULT '',
                    ciphertext  TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON api_keys(user_id, provider);
            """)

    # ── CRUD ──────────────────────────────────────────────────────────────

    def upsert(self, user_id: str, provider: str, plaintext_key: str,
               label: str = "") -> dict[str, Any]:
        now = time.time()
        with _lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM api_keys WHERE user_id=? AND provider=?",
                (user_id, provider),
            ).fetchone()
            ct = _encrypt(plaintext_key, self._master)
            if existing:
                conn.execute(
                    "UPDATE api_keys SET ciphertext=?, label=?, updated_at=? WHERE id=?",
                    (ct, label or provider, now, existing["id"]),
                )
                return self.get_meta(user_id, provider) or {}
            key_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO api_keys(id, user_id, provider, label, ciphertext, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (key_id, user_id, provider, label or provider, ct, now, now),
            )
        return self.get_meta(user_id, provider) or {}

    def reveal(self, user_id: str, provider: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT ciphertext FROM api_keys WHERE user_id=? AND provider=?",
                (user_id, provider),
            ).fetchone()
        if not row:
            return None
        try:
            return _decrypt(row["ciphertext"], self._master)
        except Exception:
            log.error("Failed to decrypt API key for user=%s provider=%s", user_id, provider)
            return None

    def get_meta(self, user_id: str, provider: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, user_id, provider, label, created_at, updated_at "
                "FROM api_keys WHERE user_id=? AND provider=?",
                (user_id, provider),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["has_key"] = True
        return d

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, provider, label, created_at, updated_at "
                "FROM api_keys WHERE user_id=? ORDER BY provider",
                (user_id,),
            ).fetchall()
        return [dict(r) | {"has_key": True} for r in rows]

    def delete(self, user_id: str, provider: str) -> bool:
        with _lock, self._conn() as conn:
            c = conn.execute(
                "DELETE FROM api_keys WHERE user_id=? AND provider=?",
                (user_id, provider),
            )
        return c.rowcount > 0

    def providers_for_user(self, user_id: str) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT provider FROM api_keys WHERE user_id=?", (user_id,)
            ).fetchall()
        return {r["provider"] for r in rows}
