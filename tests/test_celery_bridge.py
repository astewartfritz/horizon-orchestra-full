from __future__ import annotations

"""Unit tests for orchestra.queue.celery_bridge (no live Redis required)."""

import time
import unittest
from unittest.mock import MagicMock, patch


class TestSubmitDataJob(unittest.TestCase):
    """submit_data_job() returns a Job with the Celery task ID."""

    def _make_async_result(self, task_id: str) -> MagicMock:
        ar = MagicMock()
        ar.id = task_id
        return ar

    @patch("orchestra.queue.celery_bridge._celery_app")
    def test_returns_pending_job(self, mock_app_factory):
        app = MagicMock()
        task_id = "abc-123"
        app.send_task.return_value = self._make_async_result(task_id)
        mock_app_factory.return_value = app

        from orchestra.queue.celery_bridge import submit_data_job

        job = submit_data_job(
            "embed_documents",
            {"documents": [{"id": "1", "text": "hello"}]},
        )

        self.assertEqual(job.id, task_id)
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.name, "embed_documents")

    @patch("orchestra.queue.celery_bridge._celery_app")
    def test_uses_known_task_name(self, mock_app_factory):
        app = MagicMock()
        app.send_task.return_value = self._make_async_result("x")
        mock_app_factory.return_value = app

        from orchestra.queue.celery_bridge import submit_data_job

        submit_data_job("embed_documents", {})

        call_args = app.send_task.call_args
        self.assertEqual(
            call_args[0][0],
            "orchestra.queue.tasks.embed_documents",
        )

    @patch("orchestra.queue.celery_bridge._celery_app")
    def test_unknown_name_passes_through(self, mock_app_factory):
        app = MagicMock()
        app.send_task.return_value = self._make_async_result("y")
        mock_app_factory.return_value = app

        from orchestra.queue.celery_bridge import submit_data_job

        submit_data_job("my_custom_task", {})

        call_args = app.send_task.call_args
        self.assertEqual(call_args[0][0], "my_custom_task")


class TestGetDataJobStatus(unittest.TestCase):
    """get_data_job_status() maps Celery states to Job status values."""

    # Inject fake celery stubs once for the whole class so every test can
    # import orchestra.queue.celery_bridge cleanly without celery installed.
    _orig_sys_modules: dict

    @classmethod
    def setUpClass(cls):
        import sys
        import types

        cls._orig_sys_modules = {}
        for key in ("celery", "celery.result"):
            cls._orig_sys_modules[key] = sys.modules.get(key)

        fake_ar_cls = MagicMock()
        fake_result_mod = types.ModuleType("celery.result")
        fake_result_mod.AsyncResult = fake_ar_cls  # type: ignore[attr-defined]

        fake_celery_mod = types.ModuleType("celery")
        fake_celery_mod.result = fake_result_mod  # type: ignore[attr-defined]
        fake_celery_mod.Celery = MagicMock()       # satisfies celery_app.py import

        sys.modules["celery"] = fake_celery_mod
        sys.modules["celery.result"] = fake_result_mod
        cls._fake_ar_cls = fake_ar_cls

    @classmethod
    def tearDownClass(cls):
        import sys

        for key, val in cls._orig_sys_modules.items():
            if val is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = val

    def _mock_async_result(self, state: str, result=None):
        ar = MagicMock()
        ar.state = state
        ar.result = result
        return ar

    def _call(self, state: str, result=None):
        import orchestra.queue.celery_bridge as bridge_mod

        fake_ar_instance = self._mock_async_result(state, result)
        self._fake_ar_cls.return_value = fake_ar_instance

        with patch.object(bridge_mod, "_celery_app", return_value=MagicMock()):
            return bridge_mod.get_data_job_status("some-task-id")

    def test_pending_state(self):
        job = self._call("PENDING")
        self.assertEqual(job.status, "pending")
        self.assertIsNone(job.result)
        self.assertIsNone(job.error)

    def test_started_state(self):
        job = self._call("STARTED")
        self.assertEqual(job.status, "running")

    def test_success_state(self):
        job = self._call("SUCCESS", {"embedded": 10})
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, {"embedded": 10})
        self.assertIsNone(job.error)

    def test_failure_state(self):
        job = self._call("FAILURE", ValueError("oops"))
        self.assertEqual(job.status, "failed")
        self.assertIsNone(job.result)
        self.assertIn("oops", job.error)

    def test_revoked_state(self):
        job = self._call("REVOKED")
        self.assertEqual(job.status, "dead")

    def test_retry_state(self):
        job = self._call("RETRY")
        self.assertEqual(job.status, "pending")


class TestRevoke(unittest.TestCase):
    @patch("orchestra.queue.celery_bridge._celery_app")
    def test_revoke_calls_control(self, mock_app_factory):
        app = MagicMock()
        mock_app_factory.return_value = app

        from orchestra.queue.celery_bridge import revoke_data_job

        revoke_data_job("tid-42", terminate=True)

        app.control.revoke.assert_called_once_with("tid-42", terminate=True)
