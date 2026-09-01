import unittest

from app import models
from app.services.account_avatars import resolve_account_avatar_url, sync_missing_account_avatars


class _Scraper:
    api_key = "test"

    def __init__(self):
        self.calls = 0

    def get_instagram_profile(self, handle):
        self.calls += 1
        self.handle = handle
        return {"data": {"user": {"profile_pic_url": "https://cdn.test/instagram.jpg"}}}

    def get_tiktok_profile(self, handle=None, user_id=None):
        self.calls += 1
        return {"user": {"avatarLarger": "https://cdn.test/tiktok.jpg"}}

    def get_youtube_channel(self, identifier):
        self.calls += 1
        return {"avatar": {"image": {"sources": [{"url": "https://cdn.test/youtube.jpg"}]}}}

    def get_telegram_channel(self, handle):
        self.calls += 1
        return {"avatar_url": "https://cdn.test/telegram.jpg"}


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    def query(self, model):
        return _Query(self.rows)

    def commit(self):
        self.commits += 1


class AccountAvatarTests(unittest.TestCase):
    def test_postmypost_avatar_field_is_used_first(self):
        result = resolve_account_avatar_url(
            {"id": 11, "avatar": {"image": {"sources": [{"url": "https://cdn.test/pmp.jpg"}]}}},
            "instagram",
        )
        self.assertEqual(result, "https://cdn.test/pmp.jpg")

    def test_supported_profile_sources_return_their_avatar(self):
        scraper = _Scraper()
        cases = (
            ("instagram", {"login": "turan"}, "https://cdn.test/instagram.jpg"),
            ("tiktok", {"login": "turan"}, "https://cdn.test/tiktok.jpg"),
            ("youtube", {"external_id": "UC123"}, "https://cdn.test/youtube.jpg"),
            ("telegram", {"login": "turan"}, "https://cdn.test/telegram.jpg"),
        )
        for platform, account, expected in cases:
            self.assertEqual(resolve_account_avatar_url(account, platform, scraper), expected)

        self.assertEqual(scraper.calls, 4)

    def test_profile_avatar_is_fetched_and_saved_once(self):
        row = models.UserPublishChannel(
            user_id=1,
            postmypost_project_id=7,
            account_id=11,
            enabled=True,
        )
        db = _Db([row])
        scraper = _Scraper()
        accounts = [{"id": 11, "login": "@turan", "chanel_id": 1}]
        channels = {1: {"code": "instagram"}}

        first = sync_missing_account_avatars(db, 1, 7, accounts, channels, scraper)
        second = sync_missing_account_avatars(db, 1, 7, accounts, channels, scraper)

        self.assertEqual(first, {11: "https://cdn.test/instagram.jpg"})
        self.assertEqual(second, first)
        self.assertEqual(row.account_avatar_url, "https://cdn.test/instagram.jpg")
        self.assertEqual(scraper.calls, 1)
        self.assertEqual(db.commits, 1)


if __name__ == "__main__":
    unittest.main()
