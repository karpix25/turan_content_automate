import unittest

from app.services.carousel_copy import (
    build_platform_unique_prompt,
    build_reference_rewrite_prompt,
    build_platform_texts,
)


class _Llm:
    def __init__(self):
        self.calls = []

    def _complete(self, messages, temperature):
        self.calls.append((messages, temperature))
        return "Этот результат отражает привычный образ себя и его можно изменить."


class CarouselCopyTests(unittest.TestCase):
    def test_reference_prompt_requires_media_text_analysis(self):
        prompt = build_reference_rewrite_prompt(
            [{"content_kind": "post", "title": "нет", "caption": "нет", "body": "нет", "image_urls": ["https://example.com/post.png"]}],
            None,
        )
        self.assertIn("прочитай видимый текст", prompt[1]["content"][0]["text"])
        self.assertEqual(prompt[1]["content"][1]["image_url"]["url"], "https://example.com/post.png")

    def test_platform_prompt_requires_unique_russian_copy_without_cta(self):
        text = build_platform_unique_prompt("Результат отражает образ себя.", "vk")[1]["content"]
        self.assertIn("отдельную уникальную версию", text)
        self.assertIn("Не добавляй CTA", text)
        self.assertIn("Площадка: vk", text)

    def test_platform_texts_are_generated_for_each_platform(self):
        llm = _Llm()
        result = build_platform_texts(llm, "Исходный русский текст.", ["vk", "instagram", "vk"])
        self.assertEqual(set(result), {"vk", "instagram"})
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(all(value for value in result.values()))


if __name__ == "__main__":
    unittest.main()
