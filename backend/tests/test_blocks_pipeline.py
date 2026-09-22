import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.blocks_pipeline import generate_blocks_outputs
from app.integrations.html_slide_renderer import SlideLayoutError
from app.services.carousel_blocks import parse_deck


CTA = "Подпишись"


def _deck_json() -> str:
    import json

    return json.dumps({
        "frame": "insight",
        "slides": [
            {"type": "cover", "kicker": "Разбор", "title": "Три ошибки в закупках",
             "subtitle": "Почему заявки отклоняют"},
            {"type": "stat", "title": "Отказы", "value": "72%",
             "caption": "заявок отклоняют на первом этапе"},
            {"type": "checklist", "title": "Проверить перед подачей",
             "items": ["Наименование объекта", "Сроки поставки", "Обеспечение заявки"]},
            {"type": "cta", "cta": ""},
        ]
    }, ensure_ascii=False)


class _FakeLlm:
    def __init__(self, payload: str):
        self.payload = payload

    def _complete(self, messages, temperature=0.7, response_format=None):
        return self.payload


class _FakeRenderer:
    calls: list[tuple] = []
    fail_once: bool = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def render_html(self, html: str, output_path: str, width: int, height: int) -> None:
        _FakeRenderer.calls.append((output_path, width, height))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\nfake")


class BlocksPipelineTests(unittest.TestCase):
    def setUp(self):
        _FakeRenderer.calls = []
        _FakeRenderer.fail_once = False
        self.temp = tempfile.TemporaryDirectory()
        deck, frame = parse_deck(_deck_json(), CTA)
        frame = dict(frame, editorial_plan={"promise": "Тема", "beats": []}, editorial_review={"approved": True})
        self.initial = patch('app.blocks_pipeline.build_platform_deck', return_value=(deck, frame)).start()
        repaired = [deck[0], {"type": "text", "title": "Пояснение", "body": "Исправлено моделью"}, deck[-1]]
        self.repair = patch('app.blocks_pipeline.compose_reviewed_deck', return_value=(repaired, frame)).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.temp.cleanup()

    def test_generates_both_formats_per_account(self):
        carousel, story, texts = generate_blocks_outputs(
            _FakeLlm(_deck_json()),
            "Исходный текст про закупки",
            {"instagram": [1], "tiktok": [2, 3]},
            {"instagram": {1: "@acc"}, "tiktok": {2: "@two", 3: "@three"}},
            {1: "", 2: "", 3: ""},
            {"instagram": CTA, "tiktok": CTA},
            Path(self.temp.name),
            renderer_factory=_FakeRenderer,
        )
        # instagram: 1 variant; tiktok: 2 variants (per-account keys)
        self.assertIn("instagram", carousel)
        self.assertIn("tiktok:2", carousel)
        self.assertIn("tiktok:3", carousel)
        self.assertEqual(set(story), set(carousel))
        self.assertEqual(len(carousel["instagram"]), 4)
        self.assertEqual(texts["instagram"]["carousel"]["slides"][0]["type"], "cover")
        self.assertIn("frame", texts["instagram"]["carousel"])
        # caption builder input shape
        self.assertEqual(texts["instagram"]["carousel"]["slides"][-1]["cta"], CTA)

    def test_llm_repairs_deck_after_overflow(self):
        calls = {"n": 0}
        original = _FakeRenderer.render_html

        def flaky(self, html, output_path, width, height):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SlideLayoutError("Слайд 2: текст не помещается")
            return original(self, html, output_path, width, height)

        _FakeRenderer.render_html = flaky
        try:
            carousel, _, texts = generate_blocks_outputs(
                _FakeLlm(_deck_json()),
                "Исходный текст про закупки",
                {"instagram": [1]},
                {"instagram": {1: "@acc"}},
                {1: ""},
                {"instagram": CTA},
                Path(self.temp.name),
                renderer_factory=_FakeRenderer,
            )
            # First layout failed; the LLM-edited deck is rendered in every format.
            self.assertGreaterEqual(calls["n"], 2)
            self.assertEqual(len(carousel["instagram"]), 3)
            self.assertTrue(carousel["instagram"][-1].endswith(".png"))
            self.assertEqual(texts["instagram"]["carousel"]["slides"][0]["type"], "cover")
        finally:
            _FakeRenderer.render_html = original

    def test_story_overflow_rebuilds_previously_rendered_carousels(self):
        original = _FakeRenderer.render_html
        failed = []
        def flaky(renderer, html, output_path, width, height):
            if height == 1920 and not failed:
                failed.append(True)
                raise SlideLayoutError("Слайд не помещается")
            return original(renderer, html, output_path, width, height)
        with patch.object(_FakeRenderer, "render_html", flaky):
            carousel, story, texts = generate_blocks_outputs(
                _FakeLlm(_deck_json()), "Исходный текст про закупки",
                {"vk": [1, 2]}, {}, {}, {"vk": CTA}, Path(self.temp.name),
                renderer_factory=_FakeRenderer,
            )
        for key in ("vk:1", "vk:2"):
            self.assertEqual(len(carousel[key]), 3)
            self.assertEqual(len(story[key]), 3)
        self.assertIn("editorial_plan", texts["vk"]["carousel"])
        self.repair.assert_called_once()
        self.assertEqual(texts["vk"]["carousel"], texts["vk"]["story"])

    def test_story_cta_is_preserved_separately(self):
        _, _, texts = generate_blocks_outputs(
            _FakeLlm(_deck_json()), "Исходный текст про закупки",
            {"vk": [1]}, {}, {}, {"vk": CTA}, Path(self.temp.name),
            renderer_factory=_FakeRenderer, story_ctas={"vk": "Открой ссылку"},
        )
        self.assertEqual(texts["vk"]["carousel"]["slides"][-1]["cta"], CTA)
        self.assertEqual(texts["vk"]["story"]["slides"][-1]["cta"], "Открой ссылку")

    def test_browser_failure_does_not_rewrite_content(self):
        with patch.object(_FakeRenderer, "render_html", side_effect=RuntimeError("Browser closed")):
            with self.assertRaisesRegex(RuntimeError, "Browser closed"):
                generate_blocks_outputs(_FakeLlm(_deck_json()), "Текст", {"vk": [1]}, {}, {},
                                        {"vk": CTA}, Path(self.temp.name), renderer_factory=_FakeRenderer)
        self.repair.assert_not_called()

    def test_second_overflow_fails_task(self):
        calls = {"n": 0}
        original = _FakeRenderer.render_html

        def broken(self, html, output_path, width, height):
            calls["n"] += 1
            raise SlideLayoutError("Слайд 1: текст не помещается")

        _FakeRenderer.render_html = broken
        try:
            with self.assertRaises(RuntimeError):
                generate_blocks_outputs(
                    _FakeLlm(_deck_json()),
                    "Исходный текст",
                    {"instagram": [1]},
                    {"instagram": {1: "@acc"}},
                    {1: ""},
                    {"instagram": CTA},
                    Path(self.temp.name),
                    renderer_factory=_FakeRenderer,
                )
            self.assertEqual(calls["n"], 2)
        finally:
            _FakeRenderer.render_html = original


if __name__ == "__main__":
    unittest.main()
