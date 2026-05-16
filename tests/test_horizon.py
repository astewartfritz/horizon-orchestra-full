import io
import json
from pathlib import Path
import types
import unittest
from unittest import mock

import horizon


class DetectAgentsTests(unittest.TestCase):
    def test_code_task_routes_through_code_pipeline(self):
        self.assertEqual(
            horizon.detect_agents("Build an API and add tests"),
            ["planner", "coder", "tester", "reviewer"],
        )

    def test_research_and_docs_task_includes_writer(self):
        self.assertEqual(
            horizon.detect_agents("Research the API and write docs"),
            ["planner", "researcher", "writer"],
        )


class ConfigHelpersTests(unittest.TestCase):
    def test_redact_config_hides_secret_like_values(self):
        config = {
            "OPENAI_API_KEY": "secret-value",
            "provider": "openai",
            "default_model": "gpt-4o",
        }

        redacted = horizon.redact_config(config)

        self.assertEqual(redacted["OPENAI_API_KEY"], "***REDACTED***")
        self.assertEqual(redacted["provider"], "openai")


class HorizonCliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(self._testMethodName)
        self.tempdir.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup_tempdir)

    def _cleanup_tempdir(self):
        for child in sorted(self.tempdir.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        if self.tempdir.exists():
            self.tempdir.rmdir()

    def build_cli(self):
        with mock.patch("horizon.Path.home", return_value=self.tempdir):
            return horizon.HorizonCLI()

    def test_config_round_trip(self):
        cli = self.build_cli()
        cli.config["provider"] = "ollama"
        cli.save_config()

        reloaded = self.build_cli()
        self.assertEqual(reloaded.config["provider"], "ollama")

    def test_openai_compatible_requires_key(self):
        cli = self.build_cli()
        result = cli._call_api("gpt-4o", [{"role": "user", "content": "hello"}])
        self.assertIn("error", result)
        self.assertIn("Openai", result["error"])

    def test_model_listing_contains_groq(self):
        cli = self.build_cli()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stream:
            cli.show_models()
        output = stream.getvalue()
        self.assertIn("groq-llama4-scout", output)

    def test_config_command_redacts_secret_output(self):
        cli = self.build_cli()
        cli.config = {"OPENAI_API_KEY": "top-secret", "provider": "openai"}

        with mock.patch("sys.stdout", new_callable=io.StringIO) as stream:
            exit_code = cli.handle_config_command([])

        output = stream.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("***REDACTED***", output)
        self.assertNotIn("top-secret", output)

    def test_request_json_extracts_response(self):
        cli = self.build_cli()
        payload = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "ready",
                        }
                    }
                ],
                "model": "gpt-4o",
            }
        ).encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return payload

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            req = types.SimpleNamespace()
            result = cli._request_json(req, cli._extract_openai_response)
        self.assertEqual(result["content"], "ready")

    def test_save_state_ignores_write_failures(self):
        cli = self.build_cli()

        with mock.patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            cli.save_state({"current_model": "gpt-4o"})


if __name__ == "__main__":
    unittest.main()
