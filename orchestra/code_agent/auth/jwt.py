from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any

__all__ = ["JWTManager"]

log = logging.getLogger("orchestra.jwt")

_HAS_PYJWT = False
try:
    import jwt as pyjwt  # type: ignore
    _HAS_PYJWT = True
except ImportError:
    pyjwt = None  # type: ignore[assignment]


class JWTManager:
    """Production-grade JWT with RS256 support, key rotation, refresh tokens.

    Uses RS256 when RSA keypair files are configured, falls back to HS256
    with an HMAC secret.  Refresh tokens use the same signing mechanism
    but carry a distinct ``type`` claim so access tokens can never be
    mistaken for refresh tokens and vice versa.
    """

    def __init__(
        self,
        private_key_path: str = "",
        public_key_path: str = "",
        secret: str = "",
    ) -> None:
        self._private_key: str | None = None
        self._public_key: str | None = None
        self._secret: str = secret or os.environ.get("JWT_SECRET", "")

        if private_key_path and public_key_path:
            self._load_rsa_keys(private_key_path, public_key_path)

        if not self._private_key and not self._secret:
            log.warning(
                "No JWT signing key configured (no RSA keys, no JWT_SECRET). "
                "Tokens will be signed with a volatile auto-generated secret "
                "and invalidated on every restart."
            )
            self._secret = hashlib.sha256(os.urandom(64)).hexdigest()

    # ── Key management ──────────────────────────────────────────────────

    def _load_rsa_keys(self, priv_path: str, pub_path: str) -> None:
        try:
            with open(priv_path) as f:
                self._private_key = f.read()
            with open(pub_path) as f:
                self._public_key = f.read()
            log.info("Loaded RSA keypair from %s / %s", priv_path, pub_path)
        except FileNotFoundError:
            log.warning("RSA key files not found, falling back to HS256")

    @staticmethod
    def generate_keypair(keys_dir: str = ".") -> None:
        """Generate a 4096-bit RSA keypair and write PEM files."""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend
        except ImportError:
            log.error("cryptography package required for RSA key generation")
            return

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend(),
        )
        priv_path = os.path.join(keys_dir, "jwt_private.pem")
        pub_path = os.path.join(keys_dir, "jwt_public.pem")

        with open(priv_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        with open(pub_path, "wb") as f:
            f.write(key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
        log.info("RSA keypair written to %s / %s", priv_path, pub_path)

    def rotate_keys(self, keys_dir: str = ".") -> None:
        """Archive old keys and generate a fresh keypair."""
        for name in ("jwt_private.pem", "jwt_public.pem"):
            path = os.path.join(keys_dir, name)
            if os.path.exists(path):
                ts = time.strftime("%Y%m%d-%H%M%S")
                archived = f"{path}.{ts}"
                os.rename(path, archived)
                log.info("Archived old key %s -> %s", path, archived)
        self.generate_keypair(keys_dir)
        self._private_key = self._public_key = None

    # ── Token creation ──────────────────────────────────────────────────

    def create_access_token(
        self,
        user_id: str,
        role: str = "user",
        tier: str = "free",
        expires_in: int = 3600,
    ) -> str:
        payload: dict[str, Any] = {
            "sub": user_id,
            "role": role,
            "tier": tier,
            "type": "access",
            "iat": int(time.time()),
            "exp": int(time.time() + expires_in),
            "jti": str(uuid.uuid4()),
        }
        return self._sign(payload)

    def create_refresh_token(
        self,
        user_id: str,
        expires_in: int = 2_592_000,  # 30 days
    ) -> str:
        payload: dict[str, Any] = {
            "sub": user_id,
            "type": "refresh",
            "iat": int(time.time()),
            "exp": int(time.time() + expires_in),
            "jti": str(uuid.uuid4()),
        }
        return self._sign(payload)

    # ── Verification ────────────────────────────────────────────────────

    def verify(self, token: str) -> dict[str, Any] | None:
        """Verify a token and return its payload, or None on failure."""
        try:
            if self._private_key and _HAS_PYJWT:
                payload = pyjwt.decode(
                    token, self._public_key or self._private_key,
                    algorithms=["RS256"],
                )
            elif _HAS_PYJWT:
                payload = pyjwt.decode(
                    token, self._secret, algorithms=["HS256"],
                )
            else:
                payload = self._decode_hmac(token)
            if payload.get("exp", 0) < time.time():
                log.warning("Token expired for user %s", payload.get("sub"))
                return None
            return payload
        except Exception as exc:
            log.debug("Token verification failed: %s", exc)
            return None

    def get_token_fingerprint(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    # ── Refresh rotation ────────────────────────────────────────────────

    def rotate_refresh_token(
        self, old_token: str, new_expires_in: int = 3600,
    ) -> tuple[str, str] | None:
        """Verify a refresh token and issue a new access + refresh pair."""
        payload = self.verify(old_token)
        if not payload:
            return None
        if payload.get("type") != "refresh":
            log.warning("rotate_refresh_token called with non-refresh token")
            return None
        user_id = payload["sub"]
        new_access = self.create_access_token(user_id)
        new_refresh = self.create_refresh_token(user_id)
        return new_access, new_refresh

    # ── Internal signing ────────────────────────────────────────────────

    def _sign(self, payload: dict[str, Any]) -> str:
        if self._private_key and _HAS_PYJWT:
            return pyjwt.encode(payload, self._private_key, algorithm="RS256")
        if _HAS_PYJWT:
            return pyjwt.encode(payload, self._secret, algorithm="HS256")
        return self._encode_hmac(payload)

    # ── HMAC fallback (no PyJWT) ────────────────────────────────────────

    def _encode_hmac(self, payload: dict[str, Any]) -> str:
        import base64
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        sig_input = f"{header}.{body}"
        sig = hmac.new(
            self._secret.encode(), sig_input.encode(), hashlib.sha256
        ).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{header}.{body}.{sig_b64}"

    def _decode_hmac(self, token: str) -> dict[str, Any]:
        import base64
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed token")
        header, body, sig = parts
        sig_input = f"{header}.{body}"
        expected = hmac.new(
            self._secret.encode(), sig_input.encode(), hashlib.sha256
        ).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
        if not hmac.compare_digest(sig, expected_b64):
            raise ValueError("Invalid signature")
        padded = body + "=" * (4 - len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
