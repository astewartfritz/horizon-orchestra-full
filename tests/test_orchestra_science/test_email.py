from __future__ import annotations

import os
import tempfile
import time
import unittest

from orchestra.code_agent.auth.email import (
    EmailService,
    _reset_db,
    _verifications,
    _verified_users,
    create_password_reset,
    create_verification,
    is_email_verified,
    reset_password,
    verify_email,
)
from orchestra.code_agent.auth.password import PasswordHasher
from orchestra.code_agent.auth.user_store import UserStore


class TestEmailService(unittest.TestCase):
    def setUp(self):
        _verifications.clear()
        _verified_users.clear()
        UserStore._reset()

    def test_generate_code_default_length(self):
        svc = EmailService()
        code = svc.generate_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_generate_code_custom_length(self):
        svc = EmailService()
        code = svc.generate_code(8)
        self.assertEqual(len(code), 8)
        self.assertTrue(code.isdigit())

    def test_send_verification_does_not_crash(self):
        svc = EmailService()
        result = svc.send_verification("test@example.com", "123456")
        self.assertTrue(result)

    def test_send_password_reset_does_not_crash(self):
        svc = EmailService()
        result = svc.send_password_reset("test@example.com", "123456")
        self.assertTrue(result)

    def test_env_override_on_init(self):
        try:
            os.environ["SMTP_HOST"] = "smtp.test.com"
            os.environ["SMTP_PORT"] = "465"
            os.environ["SMTP_USER"] = "user"
            os.environ["SMTP_PASS"] = "pass"
            svc = EmailService()
            self.assertEqual(svc.smtp_host, "smtp.test.com")
            self.assertEqual(svc.smtp_port, 465)
            self.assertEqual(svc.smtp_user, "user")
            self.assertEqual(svc.smtp_pass, "pass")
        finally:
            os.environ.pop("SMTP_HOST", None)
            os.environ.pop("SMTP_PORT", None)
            os.environ.pop("SMTP_USER", None)
            os.environ.pop("SMTP_PASS", None)


class TestVerificationFlow(unittest.TestCase):
    def setUp(self):
        _verifications.clear()
        _verified_users.clear()
        UserStore._reset()

    def test_create_verification_returns_code(self):
        code = create_verification("user-1", "test@example.com")
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertIn(code, _verifications)

    def test_create_verification_stores_record(self):
        code = create_verification("user-1", "test@example.com")
        record = _verifications[code]
        self.assertEqual(record["user_id"], "user-1")
        self.assertEqual(record["email"], "test@example.com")
        self.assertFalse(record["verified"])

    def test_verify_email_valid_code(self):
        code = create_verification("user-1", "test@example.com")
        result = verify_email(code)
        self.assertTrue(result)
        self.assertTrue(_verifications[code]["verified"])
        self.assertTrue(is_email_verified("user-1"))

    def test_verify_email_invalid_code(self):
        result = verify_email("000000")
        self.assertFalse(result)

    def test_verify_email_expired_code(self):
        code = create_verification("user-1", "test@example.com")
        _verifications[code]["expires_at"] = time.time() - 1
        result = verify_email(code)
        self.assertFalse(result)
        self.assertFalse(is_email_verified("user-1"))

    def test_is_email_verified_false_for_unknown(self):
        self.assertFalse(is_email_verified("nonexistent"))


class TestPasswordResetFlow(unittest.TestCase):
    _counter = 0

    def setUp(self):
        TestPasswordResetFlow._counter += 1
        _verifications.clear()
        _verified_users.clear()
        self._db = os.path.join(tempfile.gettempdir(), f"test_email_reset_{self._counter}.db")
        self.store = UserStore(self._db)
        UserStore._reset()
        self.store = UserStore(self._db)
        hasher = PasswordHasher()
        self.user = self.store.create_user(
            "reset@test.com", hasher.hash("oldpass"), name="Reset User"
        )
        self.user_id = self.user["id"]

    def tearDown(self):
        self.store.delete_user(self.user_id)
        UserStore._reset()
        if os.path.exists(self._db):
            try:
                os.remove(self._db)
            except PermissionError:
                pass

    def test_create_password_reset_returns_code(self):
        code = create_password_reset(self.user_id, "reset@test.com")
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_reset_password_valid_code(self):
        code = create_password_reset(self.user_id, "reset@test.com")
        result = reset_password(code, "newpass456")
        self.assertTrue(result)
        updated = self.store.get_user_by_id(self.user_id)
        hasher = PasswordHasher()
        self.assertTrue(hasher.verify("newpass456", updated["password_hash"]))

    def test_reset_password_invalid_code(self):
        result = reset_password("000000", "newpass")
        self.assertFalse(result)

    def test_reset_password_expired_code(self):
        code = create_password_reset(self.user_id, "reset@test.com")
        time.sleep(0.01)
        result = reset_password(code, "newpass")
        self.assertTrue(result)

    def test_reset_password_reuse_fails(self):
        code = create_password_reset(self.user_id, "reset@test.com")
        self.assertTrue(reset_password(code, "firstpass"))
        self.assertFalse(reset_password(code, "secondpass"))


if __name__ == "__main__":
    unittest.main()
