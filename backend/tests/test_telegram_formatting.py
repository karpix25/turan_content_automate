import datetime
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.utils.telegram_formatting import escape_markdown_v2, markdown_v2_code_block
from app.integrations.telegram_carousel import resolve_telegram_chat_id, send_carousel_scheduled_to_telegram


class TelegramFormattingTests(unittest.TestCase):
    def test_code_block_preserves_text_and_escapes_only_code_delimiters(self):
        value = "Цена *важна*\\путь `пример`"
        self.assertEqual(markdown_v2_code_block(value), "```text\nЦена *важна*\\\\путь \\`пример\\`\n```")

    def test_markdown_v2_escapes_regular_message_text(self):
        self.assertEqual(escape_markdown_v2("Текст #1: [готово]!"), "Текст \\#1: \\[готово\\]\\!")

    def test_numeric_telegram_chat_id_is_preserved(self):
        self.assertEqual(resolve_telegram_chat_id("1354492516"), "1354492516")

    def test_shared_admin_uses_configured_admin_chat(self):
        with patch.dict(os.environ, {"TELEGRAM_ADMIN_IDS": "1354492516"}):
            self.assertEqual(resolve_telegram_chat_id("shared_admin"), "1354492516")

    def test_scheduling_confirmation_contains_carousel_and_story_dates(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"ok": True})
        client = MagicMock()
        client.post.return_value = response
        rows = [
            SimpleNamespace(media_format="carousel", platform="telegram", account_id=10,
                            post_at=datetime.datetime(2026, 8, 28, 12, 30)),
            SimpleNamespace(media_format="story", platform="instagram", account_id=11,
                            post_at=datetime.datetime(2026, 8, 28, 13, 0)),
        ]
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_ADMIN_IDS": "1354492516"}), \
                patch("app.integrations.telegram_carousel.httpx.Client") as client_factory:
            client_factory.return_value.__enter__.return_value = client
            self.assertTrue(send_carousel_scheduled_to_telegram(SimpleNamespace(id=7), rows))
            message = client.post.call_args.kwargs["json"]["text"]
            self.assertIn("Карусель", message)
            self.assertIn("Stories", message)
            self.assertIn("28.08.2026 12:30 UTC", message)


if __name__ == "__main__":
    unittest.main()
