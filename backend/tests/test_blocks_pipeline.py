import tempfile
import unittest
from pathlib import Path

from app.blocks_pipeline import generate_blocks_outputs


CTA = "Подпишись"


def _deck_json() -> str:
    import json

    return json.dumps({
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
        self.assertEqual(texts["instagram"]["carousel"][0]["type"], "cover")
        # caption builder input shape
        self.assertEqual(texts["instagram"]["carousel"][-1]["cta"], CTA)

    def test_fallback_deck_after_overflow(self):
        calls = {"n": 0}
        original = _FakeRenderer.render_html

        def flaky(self, html, output_path, width, height):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Слайд 2: текст не помещается")
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
            # first attempt failed, then the deterministic deck rendered fully
            self.assertGreaterEqual(calls["n"], 2)
            self.assertEqual(len(carousel["instagram"]), 3)
            self.assertTrue(carousel["instagram"][-1].endswith(".png"))
            self.assertEqual(texts["instagram"]["carousel"][0]["type"], "cover")
        finally:
            _FakeRenderer.render_html = original

    def test_second_overflow_fails_task(self):
        calls = {"n": 0}
        original = _FakeRenderer.render_html

        def broken(self, html, output_path, width, height):
            calls["n"] += 1
            raise RuntimeError("Слайд 1: текст не помещается")

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
