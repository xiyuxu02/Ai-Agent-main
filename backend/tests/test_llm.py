import os
import unittest
from unittest.mock import patch

from app.llm import LLMManager, LLMSettings


class LLMSettingsTests(unittest.TestCase):
    def setUp(self):
        self.valid_environment = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "test-model",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
            "TEMPERATURE": "0.25",
            "MAX_TOKENS": "4096",
        }

    def test_temperature_and_max_tokens_are_loaded_and_forwarded(self):
        with patch.dict(os.environ, self.valid_environment, clear=True):
            with patch("app.llm.ChatOpenAI") as chat_open_ai:
                manager = LLMManager()

        self.assertEqual(manager.temperature, 0.25)
        self.assertEqual(manager.max_tokens, 4096)
        chat_open_ai.assert_called_once_with(
            model="test-model",
            temperature=0.25,
            api_key="test-key",
            base_url="https://example.invalid/v1",
            max_tokens=4096,
            streaming=True,
            callbacks=[],
        )

    def test_invalid_temperatures_fail_fast(self):
        for value in ("", "not-a-number", "nan", "inf", "-0.1", "2.1"):
            environment = {**self.valid_environment, "TEMPERATURE": value}
            with self.subTest(value=value), patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValueError, "TEMPERATURE"):
                    LLMSettings.from_env()

    def test_invalid_max_tokens_fail_fast(self):
        for value in ("", "0", "-1", "1.5", "10 tokens"):
            environment = {**self.valid_environment, "MAX_TOKENS": value}
            with self.subTest(value=value), patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValueError, "MAX_TOKENS"):
                    LLMSettings.from_env()

    def test_explicit_values_override_environment(self):
        environment = {
            **self.valid_environment,
            "TEMPERATURE": "invalid",
            "MAX_TOKENS": "invalid",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = LLMSettings.from_env(temperature=0.4, max_tokens=1024)

        self.assertEqual(settings.temperature, 0.4)
        self.assertEqual(settings.max_tokens, 1024)

    def test_missing_api_key_fails_fast(self):
        environment = {
            key: value
            for key, value in self.valid_environment.items()
            if key != "OPENAI_API_KEY"
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                LLMSettings.from_env()


if __name__ == "__main__":
    unittest.main()
