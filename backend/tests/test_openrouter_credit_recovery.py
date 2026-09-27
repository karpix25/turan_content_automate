import unittest
from unittest.mock import patch

import httpx

from app.integrations.llm import LLMClient, OpenRouterInsufficientCreditsError


class OpenRouterCreditRecoveryTests(unittest.TestCase):
    def test_http_402_stops_model_fallbacks_immediately(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(402, request=request)

        class Client:
            calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def post(self, *_args, **_kwargs):
                self.calls += 1
                response.raise_for_status()

        client = Client()
        llm = LLMClient("test-key", model_id="google/gemini-2.5-pro")
        with patch("app.integrations.llm.httpx.Client", return_value=client):
            with self.assertRaises(OpenRouterInsufficientCreditsError):
                llm._complete([{"role": "user", "content": "test"}])
        self.assertEqual(client.calls, 1)

    def test_credit_error_is_safe_and_actionable(self):
        error = OpenRouterInsufficientCreditsError()
        self.assertIn("OpenRouter", str(error))
        self.assertIn("402", str(error))


if __name__ == "__main__":
    unittest.main()
