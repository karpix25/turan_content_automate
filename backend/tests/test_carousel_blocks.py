import unittest

from app.services.carousel_blocks import (
    build_fallback_deck,
    build_deck_prompt,
    deck_to_text,
    parse_deck,
    polish_text,
    validate_deck,
)


CTA = "Подпишись"


def _deck() -> dict:
    return {
        "slides": [
            {"type": "cover", "kicker": "Разбор", "title": "Три ошибки в закупках",
             "subtitle": "Почему заявки отклоняют на первом этапе"},
            {"type": "stat", "title": "Сколько теряют поставщики",
             "value": "72%", "caption": "заявок отклоняют из-за описания объекта закупки"},
            {"type": "checklist", "title": "Что проверить перед подачей",
             "items": ["Наименование объекта закупки", "Сроки поставки по графику", "Обеспечение заявки"],
             },
            {"type": "cta", "cta": "лишний текст"},
        ]
    }


class CarouselBlocksTests(unittest.TestCase):
    def test_valid_deck_passes_and_cta_is_forced(self):
        slides = validate_deck(_deck(), CTA)
        self.assertEqual(slides[0]["type"], "cover")
        self.assertEqual(slides[-1]["type"], "cta")
        self.assertEqual(slides[-1]["cta"], CTA)

    def test_rejects_missing_cover_first(self):
        deck = _deck()
        deck["slides"][0] = {"type": "text", "title": "Т", "body": "Б"}
        with self.assertRaisesRegex(ValueError, "обложкой"):
            validate_deck(deck, CTA)

    def test_rejects_cta_not_last(self):
        deck = _deck()
        deck["slides"].append({"type": "text", "title": "Т", "body": "Б"})
        with self.assertRaisesRegex(ValueError, "CTA"):
            validate_deck(deck, CTA)

    def test_rejects_unknown_type(self):
        deck = _deck()
        deck["slides"][1]["type"] = "meme"
        with self.assertRaisesRegex(ValueError, "неизвестный тип"):
            validate_deck(deck, CTA)

    def test_rejects_latin(self):
        deck = _deck()
        deck["slides"][2]["items"][0] = "Best offer for you"
        with self.assertRaisesRegex(ValueError, "не русский"):
            validate_deck(deck, CTA)

    def test_rejects_word_limit(self):
        deck = _deck()
        deck["slides"][1]["caption"] = " ".join(["слово"] * 20)
        with self.assertRaisesRegex(ValueError, "caption"):
            validate_deck(deck, CTA)

    def test_rejects_table_row_width_mismatch(self):
        deck = {
            "slides": [
                {"type": "cover", "title": "Сравнение форматов"},
                {"type": "table", "title": "Форматы", "columns": ["Карусель", "Сторис"],
                 "rows": [["до 30 слов", "до 12 слов"], ["4:5", "9:16", "лишняя ячейка"]]},
                {"type": "cta", "cta": ""},
            ]
        }
        with self.assertRaisesRegex(ValueError, "ячеек"):
            validate_deck(deck, CTA)

    def test_requires_two_different_content_blocks(self):
        deck = {
            "slides": [
                {"type": "cover", "title": "Мысль"},
                {"type": "text", "title": "Раз", "body": "Первый тезис"},
                {"type": "text", "title": "Два", "body": "Второй тезис"},
                {"type": "cta", "cta": ""},
            ]
        }
        with self.assertRaisesRegex(ValueError, "минимум два разных"):
            validate_deck(deck, CTA)

    def test_parse_deck_strips_code_fence(self):
        import json

        raw = "```json\n" + json.dumps(_deck(), ensure_ascii=False) + "\n```"
        slides = parse_deck(raw, CTA)
        self.assertEqual(len(slides), 4)

    def test_polish_text_typography(self):
        self.assertEqual(polish_text('он сказал "привет"  миру'), "он сказал «привет» миру")
        self.assertEqual(polish_text("цифра - это факт"), "цифра — это факт")
        self.assertEqual(polish_text("ждал... и дождался"), "ждал… и дождался")
        self.assertEqual(polish_text("**жирный** текст"), "жирный текст")
        self.assertEqual(polish_text("Чек-лист из-за плана"), "Чек-лист из-за плана")

    def test_fallback_deck_is_structurally_sound(self):
        master = (
            "Тендерная практика меняется быстрее, чем успевают поставщики. "
            "Заказчики стали чаще отказывать на первом этапе. "
            "Причина простая: описание объекта закупки читают буквально. "
            "• Проверяйте наименование объекта закупки "
            "• Сверяйте сроки поставки с графиком "
            "• Готовьте обеспечение заявки заранее"
        )
        slides = build_fallback_deck(master, 5, CTA)
        self.assertEqual(slides[0]["type"], "cover")
        self.assertEqual(slides[-1]["type"], "cta")
        self.assertLessEqual(len(slides), 7)
        self.assertTrue(all("type" in slide for slide in slides))

    def test_deck_prompt_contains_limits_and_platform(self):
        prompt = build_deck_prompt("Исходный текст", "instagram", 5, CTA)
        text = prompt[1]["content"]
        self.assertIn("ровно 5", text)
        self.assertIn("instagram", text)
        self.assertIn("checklist", text)

    def test_deck_to_text_skips_cta_and_duplicates(self):
        text = deck_to_text(_deck())
        self.assertIn("Три ошибки в закупках", text)
        self.assertNotIn("Подпишись", text)


if __name__ == "__main__":
    unittest.main()
