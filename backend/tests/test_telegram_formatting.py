import datetime
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.utils.telegram_formatting import escape_markdown_v2, markdown_v2_code_block
from app.integrations.telegram_carousel import (
    resolve_telegram_chat_id,
    send_carousel_ready_to_telegram,
    send_carousel_scheduled_to_telegram,
)


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

    def test_primary_admin_overrides_other_configured_admins(self):
        with patch.dict(os.environ, {
            "TELEGRAM_ADMIN_IDS": "1354492516,38061745",
            "TELEGRAM_PRIMARY_ADMIN_ID": "1354492516",
        }):
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

    def test_ready_images_are_sent_as_two_media_groups(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"ok": True})
        client = MagicMock()
        client.post.return_value = response
        with tempfile.NamedTemporaryFile(suffix=".png") as carousel_file, \
                tempfile.NamedTemporaryFile(suffix=".png") as story_file, \
                patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_ADMIN_IDS": "1354492516"}), \
                patch("app.integrations.telegram_carousel.httpx.Client") as client_factory:
            client_factory.return_value.__enter__.return_value = client
            draft = SimpleNamespace(
                id=7,
                slides={"vk:1": [carousel_file.name]},
                story_slides={"vk:1": [story_file.name]},
            )
            self.assertTrue(send_carousel_ready_to_telegram(draft))
            self.assertEqual(client.post.call_count, 2)
            for call in client.post.call_args_list:
                self.assertTrue(call.args[0].endswith("/sendMediaGroup"))
                media = json.loads(call.kwargs["data"]["media"])
                self.assertEqual(len(media), 1)
                self.assertEqual(media[0]["type"], "photo")


if __name__ == "__main__":
    unittest.main()
