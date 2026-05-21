from __future__ import annotations

import hashlib
import os


class PasswordHasher:
    """Password hashing with bcrypt. Falls back to PBKDF2-SHA256 when bcrypt
    is not installed (PBKDF2 is still FIPS-compliant and resistant to
    rainbow tables — unlike plain SHA256).
    """

    def __init__(self) -> None:
        self._has_bcrypt = False
        try:
            import bcrypt as _bcrypt_mod
            self._bcrypt = _bcrypt_mod
            self._has_bcrypt = True
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._has_bcrypt

    def hash(self, password: str) -> str:
        """Return a portable hash string with algorithm prefix."""
        if self._has_bcrypt:
            pw = password.encode("utf-8")
            salt = self._bcrypt.gensalt(rounds=12)
            return f"bcrypt|{self._bcrypt.hashpw(pw, salt).decode('utf-8')}"
        else:
            salt = os.urandom(32)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
            return f"pbkdf2-sha256|{salt.hex()}.{dk.hex()}"

    def verify(self, password: str, stored: str) -> bool:
        """Verify a password against a stored hash."""
        sep = stored.find("|")
        if sep < 0:
            return False
        scheme = stored[:sep]
        data = stored[sep + 1:]
        if scheme == "bcrypt":
            if not self._has_bcrypt:
                raise RuntimeError("bcrypt required to verify bcrypt hashes")
            pw = password.encode("utf-8")
            return self._bcrypt.checkpw(pw, data.encode("utf-8"))
        elif scheme == "pbkdf2-sha256":
            salt_hex, dk_hex = data.split(".")
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(dk_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, 600_000
            )
            return actual == expected
        return False
