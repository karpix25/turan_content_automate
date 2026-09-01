import datetime
import unittest
from types import SimpleNamespace

from app import models
from app.carousel_publication_service import _targets, schedule_carousel_publications


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

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
