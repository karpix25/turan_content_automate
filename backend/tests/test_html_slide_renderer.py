import os
import tempfile
import unittest

from app.integrations.html_slide_renderer import HtmlSlideRenderer, find_chromium_executable
from app.services.blocks_html import build_slide_html

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
