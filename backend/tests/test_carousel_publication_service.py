import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import models
from app.carousel_publication_service import _publication_content, _targets, schedule_carousel_publications


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class FakeDb:
    def __init__(self):
        self.project_rows = [SimpleNamespace(publish_limit_per_day=6, vizard_limit_per_day=3, other_formats_limit_per_day=3)]
        self.carousel_rows = []

    def query(self, model):
        if model is models.PostMyPostProjectSetting:
            return FakeQuery(self.project_rows)
        if model is models.CarouselPublication:
            return FakeQuery(self.carousel_rows)
        return FakeQuery([])

    def add(self, row):
        if isinstance(row, models.CarouselPublication) and row not in self.carousel_rows:
            self.carousel_rows.append(row)

    def commit(self):
        return None


class FakeClient:
    def __init__(self):
        self.next_id = 100
        self.requests = []
        self.publications = {}

    def upload_local_file(self, _project_id, path):
        return abs(hash(path)) % 10000

    def _request(self, _method, _path, **kwargs):
        payload = kwargs["json"]
        publication_id = self.next_id
        self.next_id += 1
        self.requests.append(payload)
        self.publications[publication_id] = payload
        return {"data": {"id": publication_id}}

    @staticmethod
    def _unwrap_data(payload):
        return payload["data"]

    def get_publication(self, publication_id, account_ids=None):
        payload = self.publications[publication_id]
        return {
            "publication_status": 5,
            "post_at": payload["post_at"],
        }

    def delete_publication(self, publication_id, account_ids):
        self.publications.pop(publication_id, None)


class CarouselPublicationServiceTests(unittest.TestCase):
    def test_repeated_account_ids_do_not_create_duplicate_publications(self):
        draft = models.CarouselDraft(id=106, platform_accounts={'vk': [11, '11', 11]},
                                     slides={'vk': ['c.png']}, story_slides={'vk': ['s.png']})
        self.assertEqual(len(_targets(draft)), 2)

    def test_repeated_scheduling_reuses_existing_provider_publications(self):
        draft = models.CarouselDraft(id=106, user_id=1, project_id=7, master_text='Текст', status='ready',
                                     platform_accounts={'vk': [11]}, slides={'vk': ['c.png']}, story_slides={})
        db, client = FakeDb(), FakeClient()
        user = SimpleNamespace(id=1)
        when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        with patch('app.integrations.telegram_carousel.send_carousel_scheduled_to_telegram'):
            first = schedule_carousel_publications(db, user, draft, client, manual_post_at=when)
            second = schedule_carousel_publications(db, user, draft, client, manual_post_at=when)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(first[0].postmypost_id, second[0].postmypost_id)

    def test_upload_failure_does_not_create_publication_and_can_be_retried(self):
        draft = models.CarouselDraft(id=106, user_id=1, project_id=7, master_text='Текст', status='ready',
                                     platform_accounts={'vk': [11]}, slides={'vk': ['c.png']}, story_slides={})
        db, client = FakeDb(), FakeClient()
        when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        with patch.object(client, 'upload_local_file', side_effect=RuntimeError('Upload failed')):
            with self.assertRaisesRegex(RuntimeError, 'Upload failed'):
                schedule_carousel_publications(db, SimpleNamespace(id=1), draft, client, manual_post_at=when)
        self.assertEqual(client.requests, [])
        self.assertEqual(db.carousel_rows[0].publishing_status, 'failed')
        with patch('app.integrations.telegram_carousel.send_carousel_scheduled_to_telegram'):
            result = schedule_carousel_publications(db, SimpleNamespace(id=1), draft, client, manual_post_at=when)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(result[0].publishing_status, 'scheduled')

    def test_partial_failure_retries_only_unscheduled_target(self):
        draft = models.CarouselDraft(id=106, user_id=1, project_id=7, master_text='Текст', status='ready',
                                     platform_accounts={'vk': [11, 12]},
                                     slides={'vk:11': ['c11.png'], 'vk:12': ['c12.png']}, story_slides={})
        db, client = FakeDb(), FakeClient()
        when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        original = client.upload_local_file
        def upload(project, path):
            if path == 'c12.png':
                raise RuntimeError('Upload failed')
            return original(project, path)
        with patch.object(client, 'upload_local_file', side_effect=upload):
            with self.assertRaisesRegex(RuntimeError, 'Upload failed'):
                schedule_carousel_publications(db, SimpleNamespace(id=1), draft, client, manual_post_at=when)
        self.assertEqual(len(client.requests), 1)
        with patch('app.integrations.telegram_carousel.send_carousel_scheduled_to_telegram'):
            schedule_carousel_publications(db, SimpleNamespace(id=1), draft, client, manual_post_at=when)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual([r['account_ids'] for r in client.requests], [[11], [12]])

    def test_uses_format_json_as_publication_text(self):
        draft = SimpleNamespace(
            master_text="Запасной текст",
            approved_text=None,
            platform_texts={
                "vk": {
                    "carousel": {
                        "cover": {"headlineAccent": "Главный хук", "headlineMain": "Про дыхание"},
                        "main": [{"Заголовок": "Длинный выдох", "подзаголовок": "Помогает успокоиться"}],
                        "cta": {"CTA": "Подпишись"},
                    },
                    "story": {
                        "cover": {"хук заголовок": "Дышите медленнее", "описание": "Верните контроль"},
                        "main": [],
                        "cta": {"CTA": "Подпишись"},
                    },
                },
            },
        )
        self.assertEqual(
            _publication_content(draft, "vk", "carousel"),
            "Главный хук Про дыхание\n\nДлинный выдох Помогает успокоиться",
        )
        self.assertEqual(_publication_content(draft, "vk", "story"), "Дышите медленнее Верните контроль")

    def test_duplicate_platform_accounts_use_account_specific_variants(self):
        draft = models.CarouselDraft(
            id=2,
            platform_accounts={"instagram": [11, 12]},
            slides={"instagram:11": ["ig-11"], "instagram:12": ["ig-12"]},
            story_slides={"instagram:11": ["story-11"], "instagram:12": ["story-12"]},
        )
        targets = _targets(draft)
        self.assertEqual(len(targets), 4)
        self.assertEqual(
            {(item["account_id"], item["format"], item["paths"][0]) for item in targets},
            {
                (11, "carousel", "ig-11"),
                (12, "carousel", "ig-12"),
                (11, "story", "story-11"),
                (12, "story", "story-12"),
            },
        )

    def test_current_settings_skip_existing_telegram_story_images(self):
        db = FakeDb()
        db.project_rows[0].carousel_formats = {"telegram": {"carousel": True, "story": False}}
        draft = models.CarouselDraft(
            id=3, user_id=1, project_id=7, master_text="Текст", status="ready",
            platform_accounts={"telegram": [11, 12]},
            slides={"telegram:11": ["c11"], "telegram:12": ["c12"]},
            story_slides={"telegram:11": ["s11"], "telegram:12": ["s12"]},
        )
        client = FakeClient()
        result = schedule_carousel_publications(
            db, SimpleNamespace(id=1), draft, client,
            manual_post_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(row.media_format == "carousel" for row in result))
        self.assertEqual([r["details"][0]["publication_type"] for r in client.requests], [1, 1])

    def test_story_only_can_be_scheduled(self):
        db = FakeDb()
        db.project_rows[0].carousel_formats = {"telegram": {"carousel": False, "story": True}}
        draft = models.CarouselDraft(
            id=4, user_id=1, project_id=7, master_text="Текст", status="ready",
            platform_accounts={"telegram": [11]}, slides={}, story_slides={"telegram": ["s11"]},
        )
        client = FakeClient()
        result = schedule_carousel_publications(
            db, SimpleNamespace(id=1), draft, client,
            manual_post_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
        )
        self.assertEqual([row.media_format for row in result], ["story"])
        self.assertEqual(client.requests[0]["details"][0]["publication_type"], 2)

    def test_schedules_supported_formats_per_account_and_reuses_package_files(self):
        draft = models.CarouselDraft(
            id=1,
            user_id=1,
            project_id=7,
            master_text="Текст",
            approved_text="Одобренный текст",
            platform_texts={"instagram": "Текст для Instagram", "tiktok": "Текст для TikTok", "vk": "Текст для VK"},
            status="ready",
            platform_accounts={"instagram": [11], "tiktok": [12], "vk": [13]},
            slides={"instagram": ["ig-1", "ig-final"], "tiktok": ["tt-1", "tt-final"], "vk": ["vk-1"]},
            story_slides={"instagram": ["igs-1", "igs-final"], "tiktok": ["tts-1"], "vk": ["vks-1", "vks-final"]},
        )
        client = FakeClient()
        result = schedule_carousel_publications(
            FakeDb(),
            SimpleNamespace(id=1, publish_window_start_msk="10:00:00", publish_window_end_msk="22:00:00"),
            draft,
            client,
        )

        self.assertEqual(len(result), 5)
        self.assertEqual(
            [request["details"][0]["publication_type"] for request in client.requests],
            [1, 2, 1, 1, 2],
        )
        self.assertEqual(draft.status, "scheduled")
        self.assertTrue(all(row.postmypost_id for row in result))
        self.assertEqual(
            [request["details"][0]["content"] for request in client.requests],
            ["Текст для Instagram", "Текст для Instagram", "Текст для TikTok", "Текст для VK", "Текст для VK"],
        )
        self.assertTrue(all(row.post_at > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) for row in result))


if __name__ == "__main__":
    unittest.main()
