import datetime
import unittest

from app.integrations.postmypost_carousel import build_carousel_payload
from app.services.carousel_pipeline import build_slide_prompts, split_master_text
from app.services.project_cta_settings import normalize_ctas
from app.services.reference_sources import extract_reference_post
from app import models


class CarouselPipelineTests(unittest.TestCase):
    def test_one_master_text_becomes_platform_specific_final_cta(self):
        text = "Первый тезис. Второй тезис. Третий тезис."
        prompts = build_slide_prompts(text, 3, "instagram", "Подпишись")
        self.assertEqual(len(prompts), 3)
        self.assertNotIn("Подпишись", prompts[0])
        self.assertIn("Подпишись", prompts[-1])

    def test_split_text_respects_safe_slide_limit(self):
        slides = split_master_text("Один. Два. Три. Четыре.", 20)
        self.assertLessEqual(len(slides), 10)
        self.assertTrue(all(slides))

    def test_story_prompt_has_story_format_and_word_limit(self):
        prompts = build_slide_prompts("раз два три четыре пять шесть семь восемь девять десять", 2, "instagram", "Смотри подробнее", "story")
        self.assertIn("1080x1920", prompts[0])
        self.assertIn("не больше 12 слов", prompts[0])

    def test_payload_keeps_one_caption_and_many_files(self):
        payload = build_carousel_payload(
            project_id=7,
            account_ids=[12, 12, 13],
            post_at=datetime.datetime(2026, 8, 23, 12, tzinfo=datetime.timezone.utc),
            file_ids=[101, 102, 103],
            content="Единый текст",
        )
        self.assertEqual(payload["account_ids"], [12, 13])
        self.assertEqual(payload["details"][0]["file_ids"], [101, 102, 103])
        self.assertEqual(payload["details"][0]["content"], "Единый текст")

    def test_cta_settings_ignore_unsupported_platforms(self):
        self.assertEqual(normalize_ctas({"instagram": "Ок", "youtube": "Нет"}), {"instagram": "Ок"})

    def test_reference_post_normalization_keeps_fresh_metadata(self):
        channel = models.ReferenceChannel(
            id=4,
            user_id=1,
            project_id=2,
            platform="youtube",
            source_url="https://youtube.com/@author",
        )
        post = extract_reference_post(channel, {
            "videoId": "abcdefghijk",
            "title": "Новый смысл",
            "publishedAt": "2026-08-23T10:00:00Z",
            "viewCount": 42,
        })
        self.assertEqual(post["source_url"], "https://youtube.com/@author")
        self.assertEqual(post["view_count"], 42)
        self.assertIsNotNone(post["published_at"])


if __name__ == "__main__":
    unittest.main()
