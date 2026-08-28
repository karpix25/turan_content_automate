import os
import unittest
from unittest.mock import patch

from app.utils.telegram_formatting import escape_markdown_v2, markdown_v2_code_block
from app.integrations.telegram_carousel import resolve_telegram_chat_id


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


if __name__ == "__main__":
    unittest.main()
