import json
import unittest

from app.services.carousel_copy import (
    build_reference_rewrite_prompt,
    build_template_package,
    build_template_package_prompt,
    parse_template_package,
    template_package_text,
)


TEMPLATES = {
    "cover": {
        "height": 1350,
        "variables": {"headlineAccent": {}, "headlineMain": {}, "аватар": {}, "author": {}},
    },
    "content": {
        "variables": {"Заголовок": {}, "подзаголовок": {}, "аватара": {}, "автор": {}},
    },
    "cta": {"variables": {"CTA": {}, "аватар": {}, "author": {}}},
}


def _package():
    return {
        "slide_count": 4,
        "cover": {
            "headlineAccent": "Верните себе контроль",
            "headlineMain": "Начните с медленного дыхания",
            "аватар": "лишнее",
            "author": "лишнее",
        },
        "main": [
            {
                "Заголовок": "Удлините выдох",
                "подзаголовок": "Так тело быстрее замечает безопасность",
                "аватара": "лишнее",
                "автор": "лишнее",
            },
            {
                "Заголовок": "Расслабьте лицо",
                "подзаголовок": "Это снижает телесное напряжение",
                "аватара": "лишнее",
                "автор": "лишнее",
            },
        ],
        "cta": {"CTA": "не тот призыв", "аватар": "лишнее", "author": "лишнее"},
    }


class _Llm:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def _complete(self, messages, temperature):
        self.calls.append((messages, temperature))
        return next(self.responses)


class CarouselCopyTests(unittest.TestCase):
    def test_reference_prompt_requires_media_text_analysis(self):
        prompt = build_reference_rewrite_prompt(
            [{"content_kind": "post", "title": "нет", "caption": "нет", "body": "нет", "image_urls": ["https://example.com/post.png"]}],
            None,
        )
        self.assertIn("прочитай видимый текст", prompt[1]["content"][0]["text"])
        self.assertEqual(prompt[1]["content"][1]["image_url"]["url"], "https://example.com/post.png")

    def test_prompt_uses_exact_saved_template_variables(self):
        text = build_template_package_prompt("Русский исходный текст.", "vk", TEMPLATES, 4, "Подпишись")[1]["content"]
        self.assertIn('"slide_count": 4', text)
        self.assertIn('"headlineAccent"', text)
        self.assertIn('"подзаголовок"', text)
        self.assertIn("Количество слайдов — ровно 4", text)

    def test_parses_exact_package_and_protects_runtime_values(self):
        result = parse_template_package(json.dumps(_package(), ensure_ascii=False), TEMPLATES, 4, "Подпишись")
        self.assertEqual(result["slide_count"], 4)
        self.assertEqual(len(result["main"]), 2)
        self.assertEqual(result["cover"]["author"], "")
        self.assertEqual(result["main"][0]["аватара"], "")
        self.assertEqual(result["cta"]["CTA"], "Подпишись")

    def test_retries_invalid_json_once(self):
        invalid = _package()
        invalid["main"][0]["Заголовок"] = "### Версия 1"
        llm = _Llm([
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(_package(), ensure_ascii=False),
        ])
        result = build_template_package(llm, "Исходный текст.", "vk", TEMPLATES, 4, "Подпишись")
        self.assertEqual(result["slide_count"], 4)
        self.assertEqual(len(llm.calls), 2)

    def test_invalid_json_fails_before_rendering(self):
        llm = _Llm(["не JSON", "снова не JSON"])
        with self.assertRaisesRegex(ValueError, "Не удалось получить JSON"):
            build_template_package(llm, "Исходный текст.", "vk", TEMPLATES, 4, "Подпишись")

    def test_builds_publication_text_from_slide_variables(self):
        text = template_package_text(_package())
        self.assertIn("Верните себе контроль Начните с медленного дыхания", text)
        self.assertIn("Удлините выдох Так тело быстрее замечает безопасность", text)
        self.assertNotIn("не тот призыв", text)


if __name__ == "__main__":
    unittest.main()
