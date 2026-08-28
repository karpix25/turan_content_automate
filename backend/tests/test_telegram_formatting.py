import unittest

from app.utils.telegram_formatting import escape_markdown_v2, markdown_v2_code_block


class TelegramFormattingTests(unittest.TestCase):
    def test_code_block_preserves_text_and_escapes_only_code_delimiters(self):
        value = "Цена *важна*\\путь `пример`"
        self.assertEqual(markdown_v2_code_block(value), "```text\nЦена *важна*\\\\путь \\`пример\\`\n```")

    def test_markdown_v2_escapes_regular_message_text(self):
        self.assertEqual(escape_markdown_v2("Текст #1: [готово]!"), "Текст \\#1: \\[готово\\]\\!")


if __name__ == "__main__":
    unittest.main()
