"""Langfuse 观测边界测试，不连接外部平台。"""

import unittest
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.observability import (
    get_langfuse,
    observation,
    observation_data,
    shutdown_observability,
    summarize,
    update_observation,
)


class FakeObservation:
    def __init__(self):
        self.updates = []

    def update(self, **values):
        self.updates.append(values)


class FakeManager:
    def __init__(self, current):
        self.current = current
        self.closed = False

    def __enter__(self):
        return self.current

    def __exit__(self, *args):
        self.closed = True


class FakeClient:
    def __init__(self):
        self.current = FakeObservation()
        self.manager = FakeManager(self.current)
        self.created = []

    def start_as_current_observation(self, **values):
        self.created.append(values)
        return self.manager


class ObservabilityTest(unittest.TestCase):
    def test_default_mode_keeps_only_structure_and_counts(self):
        settings = Settings(_env_file=None, langfuse_capture_content=False)
        value = {"messages": [{"content": "private interview answer"}], "total": 3}
        result = observation_data(settings, value)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["messages_count"], 1)
        self.assertNotIn("private interview answer", str(result))

    def test_none_remains_unset_for_incremental_sdk_updates(self):
        settings = Settings(_env_file=None, langfuse_capture_content=False)
        self.assertIsNone(observation_data(settings, None))

    def test_content_mode_redacts_secrets_and_bounds_strings(self):
        settings = Settings(_env_file=None, langfuse_capture_content=True)
        result = observation_data(settings, {
            "api_key": "must-not-leak",
            "nested": {"auth_code": "must-not-leak-either"},
            "text": "x" * 17000,
        })
        self.assertEqual(result["api_key"], "[redacted]")
        self.assertEqual(result["nested"]["auth_code"], "[redacted]")
        self.assertLess(len(result["text"]), 17000)

    def test_observation_context_updates_and_closes(self):
        settings = Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-test",
        )
        client = FakeClient()
        with patch("backend.app.observability.get_langfuse", return_value=client):
            with observation(settings, name="agent", as_type="agent", input={"count": 1}) as current:
                update_observation(current, output={"status": "ok"})
        self.assertEqual(client.created[0]["name"], "agent")
        self.assertEqual(client.current.updates[0]["output"], {"status": "ok"})
        self.assertTrue(client.manager.closed)

    def test_client_mask_applies_privacy_policy_to_wrapper_payloads(self):
        settings = Settings(
            _env_file=None,
            langfuse_enabled=True,
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-test",
            langfuse_capture_content=False,
        )
        with patch("backend.app.observability.Langfuse") as constructor:
            constructor.return_value.shutdown.return_value = None
            get_langfuse(settings)
            mask = constructor.call_args.kwargs["mask"]
            masked = mask(data=[{"role": "user", "content": "private interview answer"}])
        shutdown_observability()

        self.assertEqual(masked, {"type": "list", "count": 1})
        self.assertNotIn("private interview answer", str(masked))

    def test_summary_does_not_echo_plain_text(self):
        self.assertEqual(summarize("secret body"), {"type": "text", "characters": 11})


if __name__ == "__main__":
    unittest.main()
