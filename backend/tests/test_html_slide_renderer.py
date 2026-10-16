import os
import tempfile
import unittest

from app.integrations.html_slide_renderer import HtmlSlideRenderer, find_chromium_executable
from app.services.blocks_html import build_slide_html
from app.services.carousel_blocks import validate_deck

try:
    import playwright  # noqa: F401

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

CHROMIUM_AVAILABLE = find_chromium_executable() is not None


def _short_deck() -> list[dict]:
    return [
        {"type": "cover", "kicker": "Разбор", "title": "Три ошибки в закупках",
         "subtitle": "Почему заявки отклоняют на первом этапе"},
        {"type": "cta", "cta": "Подпишись"},
    ]


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE and CHROMIUM_AVAILABLE, "playwright/chromium недоступен")
class HtmlSlideRendererTests(unittest.TestCase):
    def test_all_content_types_render_at_both_production_sizes(self):
        content_slides = [
            {'type': 'text', 'title': 'Смысловой абзац', 'paragraphs': ['Первый самостоятельный тезис.', 'Второе пояснение с примером.']},
            {'type': 'checklist', 'title': 'Что проверить', 'items': ['Сверьте условия', 'Проверьте сроки']},
            {'type': 'steps', 'title': 'Последовательность действий', 'items': ['Изучите источник', 'Выделите главное', 'Проверьте результат']},
            {'type': 'table', 'title': 'Числовые значения', 'columns': ['Карты', 'Значение'], 'rows': [['От 2 до 6', '+1'], ['От 7 до 9', '0']]},
            {'type': 'comparison', 'title': 'Сравнение вариантов', 'left_title': 'Первый', 'right_title': 'Второй',
             'left_items': ['Вероятность 50%', 'Одна попытка'], 'right_items': ['Вероятность 1 к 1 000 000', 'Много повторений']},
            {'type': 'stat', 'title': 'Основное число', 'value': '50%', 'caption': 'вероятность одной попытки'},
            {'type': 'quote', 'text': 'Главное — сохранять смысл источника.', 'author': 'Редактор'},
            {'type': 'qa', 'title': 'Вопрос и ответ', 'pairs': [{'q': 'Что проверить?', 'a': 'Факты и исходные числа.'}]},
        ]
        with tempfile.TemporaryDirectory() as tmp, HtmlSlideRenderer() as renderer:
            for content in content_slides:
                deck, _ = validate_deck({'frame': 'insight', 'slides': [
                    {'type': 'cover', 'title': 'Проверка формата'}, content, {'type': 'cta'},
                ]}, 'Сохраните')
                for width, height in ((1080, 1350), (1080, 1920)):
                    with self.subTest(slide_type=content['type'], height=height):
                        path = os.path.join(tmp, f"{content['type']}-{height}.png")
                        markup = build_slide_html(deck, 1, width=width, height=height)
                        renderer.render_html(markup, path, width, height)
                        with open(path, 'rb') as handle:
                            header = handle.read(24)
                        self.assertEqual((int.from_bytes(header[16:20], 'big'), int.from_bytes(header[20:24], 'big')), (width, height))

    def _render(self, deck: list[dict], index: int, width: int = 1080, height: int = 1350) -> str:
        html = build_slide_html(deck, index, width=width, height=height)
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        os.unlink(path)
        with HtmlSlideRenderer() as renderer:
            renderer.render_html(html, path, width, height)
        return path

    def test_renders_png_of_exact_canvas(self):
        path = self._render(_short_deck(), 0)
        self.assertTrue(os.path.isfile(path))
        with open(path, "rb") as fh:
            content = fh.read()
        self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        self.assertEqual((width, height), (1080, 1350))
        os.unlink(path)

    def test_auto_fit_saves_moderately_overflowing_slide(self):
        deck = [
            {"type": "text", "title": "Плотный слайд",
             "body": " ".join(["Наполненный абзац с конкретикой"] * 12)},
        ]
        deck = [{"type": "cover", "title": "Обложка"}, *deck, {"type": "cta", "cta": "Подпишись"}]
        path = self._render(deck, 1)
        self.assertTrue(os.path.isfile(path))
        os.unlink(path)

    def test_unbreakable_word_is_rejected_instead_of_split_or_cropped(self):
        deck = [{"type": "text", "title": "Тема", "body": "Оченьдлинноеслово" * 30}]
        markup = build_slide_html(deck, 0, width=1080, height=1350)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'never.png')
            with HtmlSlideRenderer() as renderer:
                with self.assertRaisesRegex(RuntimeError, 'не помещается'):
                    renderer.render_html(markup, path, 1080, 1350)
            self.assertFalse(os.path.exists(path))

    def test_unfitting_slide_raises_instead_of_cropping(self):
        deck = [
            {"type": "text", "title": "Переполненный слайд",
             "body": " ".join(["совершенно непомещающееся слово"] * 1500)},
        ]
        deck = [{"type": "cover", "title": "Обложка"}, *deck, {"type": "cta", "cta": "Подпишись"}]
        html = build_slide_html(deck, 1, width=1080, height=1350)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "never.png")
            with HtmlSlideRenderer() as renderer:
                with self.assertRaisesRegex(RuntimeError, "не помещается"):
                    renderer.render_html(html, path, 1080, 1350)
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
