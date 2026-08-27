import datetime
import unittest

from app.integrations.postmypost_carousel import build_carousel_payload
from app.services.carousel_pipeline import build_package_prompts, build_slide_prompts, split_master_text, suggest_package_slide_count
from app.services.carousel_copy import build_reference_rewrite_prompt
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

    def test_package_count_fits_both_formats(self):
        self.assertEqual(suggest_package_slide_count("Один короткий тезис."), 1)
        self.assertEqual(suggest_package_slide_count(" ".join(["слово"] * 30)), 3)

    def test_source_prompt_does_not_allow_style_to_change_topic(self):
        prompt = build_reference_rewrite_prompt(
            [{"content_kind": "video", "title": "А ты?", "caption": "А ты?", "transcript": "Прощать или не прощать?", "body": "А ты?"}],
            "Автор пишет о тендерах и бизнесе",
        )
        text = prompt[1]["content"][0]["text"]
        self.assertIn("единственный источник смысла и фактов", text)
        self.assertIn("не добавляй бизнес", text)
        self.assertIn("Прощать или не прощать?", text)

    def test_package_reuses_body_slides_and_varies_only_final_cta_prompts(self):
        shared, finals = build_package_prompts(
            "Первый тезис. Второй тезис. Третий тезис.",
            3,
            "carousel",
            ["instagram", "vk"],
            {"instagram": "Смотри Instagram", "vk": "Переходи в VK"},
        )
        self.assertEqual(len(shared), 2)
        self.assertEqual(set(finals), {"instagram", "vk"})
        self.assertTrue(all("CTA не добавляй" in prompt for prompt in shared))
        self.assertIn("Смотри Instagram", finals["instagram"])
        self.assertIn("Переходи в VK", finals["vk"])

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

    def test_reference_post_normalization_unwraps_instagram_media(self):
        channel = models.ReferenceChannel(id=5, user_id=1, project_id=2, platform="instagram", source_url="https://instagram.com/author")
        post = extract_reference_post(channel, {
            "media": {
                "id": "123_456",
                "code": "ABC123",
                "url": "https://www.instagram.com/reel/ABC123/",
                "caption": {"text": "Свежий пост"},
                "created_at": "2026-08-27T10:00:00Z",
                "play_count": 99,
            },
        })
        self.assertEqual(post["external_id"], "123_456")
        self.assertEqual(post["title"], "Свежий пост")
        self.assertEqual(post["view_count"], 99)


if __name__ == "__main__":
    unittest.main()
