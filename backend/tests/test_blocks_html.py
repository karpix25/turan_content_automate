import unittest

from app.services.blocks_html import DEFAULT_THEME, build_slide_html, _copy


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
                                author="@turan", cta=CTA)
        self.assertIn(CTA, html.replace("\u00a0", " "))
        self.assertIn("@turan", html)
        self.assertIn("data:image/png;base64,", html)

    def test_logo_replaces_avatar_in_footer_and_cta(self):
        for index in (0, 3):
            html = build_slide_html(_deck(), index, width=1080, height=1350,
                                    author="@turan", avatar_url="https://example.com/a.png", cta=CTA)
            self.assertIn("data:image/png;base64,", html)
            self.assertNotIn("https://example.com/a.png", html)

    def test_cta_slide_prefers_deck_cta_over_default(self):
        deck = _deck()
        deck[3]["cta"] = "Своя фраза"
        html = build_slide_html(deck, 3, width=1080, height=1350, cta=CTA)
        self.assertIn("Своя фраза", html.replace("\u00a0", " "))
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

    def test_typography_keeps_short_links_and_numbers_together(self):
        text = _copy('В жизни — 5 приёмов и 10 % результата')
        self.assertIn('В\u00a0жизни\u00a0—', text)
        self.assertIn('5\u00a0приёмов', text)
        self.assertIn('и\u00a010\u00a0%', text)
        self.assertNotIn('\x01', text)

    def test_renderer_uses_model_paragraph_boundaries(self):
        deck = [{"type": "text", "title": "Тема", "body": "Первое. Второе. Третье.",
                 "paragraphs": ["Первое.", "Второе. Третье."]}]
        markup = build_slide_html(deck, 0, width=1080, height=1350)
        self.assertIn('<p>Первое.</p><p>Второе. Третье.</p>', markup.replace('\u00a0', ' '))
        deck[0].pop('paragraphs')
        markup = build_slide_html(deck, 0, width=1080, height=1350)
        self.assertIn('<p>Первое. Второе. Третье.</p>', markup.replace('\u00a0', ' '))

    def test_model_title_lines_render_without_word_splitting(self):
        deck = [{"type": "cover", "title": "Пять приёмов разговора", "title_lines": ["Пять приёмов", "разговора"]}]
        markup = build_slide_html(deck, 0, width=1080, height=1350)
        self.assertIn('Пять приёмов<br>разговора', markup.replace('\u00a0', ' '))
        self.assertIn('word-break: normal; hyphens: none', markup)
        self.assertNotIn('overflow-wrap: anywhere', markup)

    def test_numbered_checklist_uses_single_marker(self):
        deck = [{"type": "checklist", "title": "Приёмы", "items": ["3. Первый приём", "4. Второй приём"]}]
        markup = build_slide_html(deck, 0, width=1080, height=1350)
        self.assertIn('<span class="badge">3</span>', markup)
        self.assertIn('<span class="badge">4</span>', markup)
        self.assertNotIn('<span class="badge">✓</span>', markup)
        self.assertNotIn('<p>3.', markup)

    def test_short_final_word_stays_with_preceding_word(self):
        self.assertTrue(_copy('Чтобы показать интерес.').endswith('показать\u00a0интерес.'))

    def test_index_out_of_deck_raises(self):
        with self.assertRaises(ValueError):
            build_slide_html(_deck(), 9, width=1080, height=1350)


if __name__ == "__main__":
    unittest.main()
