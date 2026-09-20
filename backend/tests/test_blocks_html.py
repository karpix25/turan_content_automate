import unittest

from app.services.blocks_html import DEFAULT_THEME, build_slide_html


CTA = "Подпишись на канал"


def _deck() -> list[dict]:
    return [
        {"type": "cover", "kicker": "Разбор", "title": "Три ошибки в закупках",
         "subtitle": "Почему заявки отклоняют на первом этапе"},
        {"type": "checklist", "title": "Что проверить",
         "items": ["Наименование объекта закупки", "Сроки поставки", "Обеспечение заявки"]},
        {"type": "table", "title": "Форматы", "columns": ["Карусель", "Сторис"],
         "rows": [["до 30 слов", "до 12 слов"], ["4:5", "9:16"]]},
        {"type": "cta", "cta": ""},
    ]


class BlocksHtmlTests(unittest.TestCase):
    def test_escapes_user_text(self):
        deck = _deck()
        deck[0]["title"] = "<script>alert('x')</script> Заголовок"
        html = build_slide_html(deck, 0, width=1080, height=1350)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_cta_slide_uses_backend_cta_and_author(self):
        html = build_slide_html(_deck(), 3, width=1080, height=1350,
                                author="@turan", avatar_url="https://example.com/a.png", cta=CTA)
        self.assertIn(CTA, html)
        self.assertIn("@turan", html)
        self.assertIn("https://example.com/a.png", html)

    def test_cta_slide_prefers_deck_cta_over_default(self):
        deck = _deck()
        deck[3]["cta"] = "Своя фраза"
        html = build_slide_html(deck, 3, width=1080, height=1350, cta=CTA)
        self.assertIn("Своя фраза", html)
        self.assertNotIn(f">{CTA}<", html)

    def test_page_counter_and_slide_types(self):
        for index, expected in ((0, "1 / 4"), (1, "2 / 4"), (2, "3 / 4"), (3, "4 / 4")):
            html = build_slide_html(_deck(), index, width=1080, height=1350)
            self.assertIn(expected, html)
            self.assertIn(f'type-{_deck()[index]["type"]}', html)

    def test_theme_override(self):
        theme = dict(DEFAULT_THEME, accent="#123456")
        html = build_slide_html(_deck(), 0, width=1080, height=1350, theme=theme)
        self.assertIn("--accent: #123456", html)

    def test_story_canvas_size(self):
        html = build_slide_html(_deck(), 1, width=1080, height=1920)
        self.assertIn("height: 1920px", html)
        self.assertIn("width: 1080px", html)

    def test_index_out_of_deck_raises(self):
        with self.assertRaises(ValueError):
            build_slide_html(_deck(), 9, width=1080, height=1350)


if __name__ == "__main__":
    unittest.main()
