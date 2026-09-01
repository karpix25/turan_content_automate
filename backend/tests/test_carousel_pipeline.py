import datetime
import unittest

from app import models
from app.integrations.postmypost_carousel import build_carousel_payload
from app.services.carousel_copy import build_reference_rewrite_prompt, is_russian_text, strip_source_cta
from app.services.carousel_pipeline import normalize_master_text, split_master_text, suggest_package_slide_count
from app.services.project_cta_settings import normalize_ctas
from app.services.reference_sources import extract_reference_post, resolve_project_platform_accounts
from app.utils.platform_utils import _normalize_platform_code


class CarouselPipelineTests(unittest.TestCase):
    class _Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *_args):
            return self

        def all(self):
            return list(self.rows)

    class _Db:
        def __init__(self, rows):
            self.rows = rows

        def query(self, _model):
            return CarouselPipelineTests._Query(self.rows)

    class _Pmp:
        def get_accounts(self, project_id):
            return [{"id": 11, "chanel_id": 1}, {"id": 12, "chanel_id": 1}, {"id": 13, "chanel_id": 2}]

        def get_channels(self):
            return [{"id": 1, "code": "instagram"}, {"id": 2, "code": "telegram"}]

    def test_project_accounts_include_only_enabled_accounts_and_telegram(self):
        rows = [
            models.UserPublishChannel(user_id=1, postmypost_project_id=7, account_id=11, enabled=True),
            models.UserPublishChannel(user_id=1, postmypost_project_id=7, account_id=12, enabled=False),
            models.UserPublishChannel(user_id=1, postmypost_project_id=7, account_id=13, enabled=True),
        ]
        self.assertEqual(resolve_project_platform_accounts(7, self._Pmp(), self._Db(rows), 1), {"instagram": [11], "telegram": [13]})

    def test_split_text_keeps_thoughts_and_removes_numbering(self):
        self.assertEqual(
            split_master_text("1. Первая мысль.\n\n2. Вторая мысль.\n\n3. Третья мысль.", 3),
            ["Первая мысль.", "• Вторая мысль.", "• Третья мысль."],
        )
        self.assertEqual(normalize_master_text("1-ое Сириус. 2-ое — Физтехшкола."), "• Сириус. • Физтехшкола.")

    def test_split_text_keeps_bullet_description_together(self):
        text = "Варианты подготовки. 1-ое Сириус. Бесплатная смена в Сочи. 2-ое Физтехшкола. Дистанционные занятия."
        self.assertEqual(split_master_text(text, 3, 20), [
            "Варианты подготовки.",
            "• Сириус. Бесплатная смена в Сочи.",
            "• Физтехшкола. Дистанционные занятия.",
        ])

    def test_source_cta_is_removed_before_slide_composition(self):
        self.assertEqual(strip_source_cta("Первый тезис. Остальные 7 мест у меня в Телеграм. Второй тезис."), "Первый тезис. Второй тезис.")

    def test_russian_copy_rejects_latin_words(self):
        self.assertTrue(is_russian_text("Текст для пяти слайдов 5"))
        self.assertFalse(is_russian_text("Русский text"))

    def test_package_count_fits_both_formats(self):
        self.assertEqual(suggest_package_slide_count("Один короткий тезис."), 1)
        self.assertEqual(suggest_package_slide_count(" ".join(["слово"] * 30)), 3)

    def test_source_rewrite_prompt_uses_media_text_as_facts(self):
        prompt = build_reference_rewrite_prompt(
            [{"content_kind": "video", "title": "А ты?", "caption": "А ты?", "transcript": "Прощать или не прощать?", "body": "А ты?"}],
            "Автор пишет о тендерах и бизнесе",
        )
        text = prompt[1]["content"][0]["text"]
        self.assertIn("единственный источник смысла и фактов", text)
        self.assertIn("Прощать или не прощать?", text)

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

    def test_cta_settings_ignore_unsupported_platforms(self):
        self.assertEqual(normalize_ctas({"instagram": "Ок", "youtube": "Нет"}), {"instagram": "Ок"})

    def test_telegram_channel_code_is_normalized(self):
        self.assertEqual(_normalize_platform_code("telegram_channel"), "telegram")

    def test_reference_post_normalization_keeps_fresh_metadata(self):
        channel = models.ReferenceChannel(id=4, user_id=1, project_id=2, platform="youtube", source_url="https://youtube.com/@author")
        post = extract_reference_post(channel, {"videoId": "abcdefghijk", "title": "Новый смысл", "publishedAt": "2026-08-23T10:00:00Z", "viewCount": 42})
        self.assertEqual(post["source_url"], "https://youtube.com/@author")
        self.assertEqual(post["view_count"], 42)
        self.assertIsNotNone(post["published_at"])


if __name__ == "__main__":
    unittest.main()
