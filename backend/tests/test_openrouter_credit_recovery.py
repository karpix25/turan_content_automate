import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.integrations.llm import LLMClient, OpenRouterInsufficientCreditsError


class OpenRouterCreditRecoveryTests(unittest.TestCase):
    def test_embedded_credit_errors_stop_fallbacks_even_with_http_200(self):
        for payload in ({'error': {'code': 402}}, {'choices': [{'error': {'code': 402}}]}):
            with self.subTest(payload=payload):
                client = MagicMock()
                client.__enter__.return_value = client
                client.post.return_value = httpx.Response(200, json=payload,
                    request=httpx.Request('POST', 'https://openrouter.ai/api/v1/chat/completions'))
                with patch('app.integrations.llm.httpx.Client', return_value=client):
                    with self.assertRaises(OpenRouterInsufficientCreditsError):
                        LLMClient('test-key', 'google/gemini-2.5-pro')._complete([])
                self.assertEqual(client.post.call_count, 1)

    def test_timeout_and_empty_response_fall_back_without_losing_schema(self):
        client = MagicMock()
        client.__enter__.return_value = client
        request = httpx.Request('POST', 'https://openrouter.ai/api/v1/chat/completions')
        client.post.side_effect = [
            httpx.ReadTimeout('Timed out'),
            httpx.Response(200, json={'choices': [{'message': {'content': ''}}]}, request=request),
            httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}}]}, request=request),
        ]
        schema = {'type': 'json_object'}
        with patch('app.integrations.llm.httpx.Client', return_value=client):
            result = LLMClient('test-key', 'google/gemini-2.5-pro')._complete([], response_format=schema)
        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(client.post.call_count, 3)
        self.assertTrue(all(call.kwargs['json']['response_format'] == schema for call in client.post.call_args_list))

    def test_total_provider_outage_has_a_bounded_request_budget(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.side_effect = httpx.ConnectError('Offline')
        with patch('app.integrations.llm.httpx.Client', return_value=client):
            self.assertIsNone(LLMClient('test-key', 'google/gemini-2.5-pro')._complete([]))
        self.assertEqual(client.post.call_count, 3)

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
