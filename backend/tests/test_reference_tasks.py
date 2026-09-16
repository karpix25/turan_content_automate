import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import models
from app.services.reference_analysis import analyze_reference_post
from app.services.reference_selection import pick_latest_unused_posts
from app.services.reference_sources import extract_reference_post, prepare_reference_item


class _Scraper:
    def get_instagram_details(self, _url):
        return {
            "caption": "Подпись из media",
            "image_urls": ["https://example.com/actual.png"],
            "download_url": None,
        }

    def get_youtube_details(self, _url):
        return {"caption": "Описание", "transcript_only_text": "Текст из видео", "download_url": None}

    def get_tiktok_details(self, _url):
        return {
            "caption": "Описание TikTok",
            "transcript_only_text": "Текст из парсера",
            "download_url": "https://example.com/tiktok.mp4",
        }


class ReferenceSelectionTests(unittest.TestCase):
    def test_prepare_item_uses_nested_publication_identity(self):
        channel = models.ReferenceChannel(id=10, platform="youtube", source_url="https://youtube.com/@channel")
        post = prepare_reference_item(channel, {
            "id": "channel-id",
            "video": {"videoId": "abcdefghijk", "title": "Новая тема"},
        })

        self.assertEqual(post["external_id"], "abcdefghijk")
        self.assertEqual(post["url"], "https://www.youtube.com/watch?v=abcdefghijk")

        profile_url_item = prepare_reference_item(channel, {
            "url": "https://youtube.com/@channel",
            "videoId": "lmnopqrstuv",
        })
        self.assertEqual(profile_url_item["url"], "https://www.youtube.com/watch?v=lmnopqrstuv")

    def test_tiktok_does_not_use_profile_url_as_publication_id(self):
        channel = models.ReferenceChannel(id=11, platform="tiktok", source_url="https://www.tiktok.com/@creator")
        first = prepare_reference_item(channel, {"id": "video-1", "caption": "Первая тема"})
        second = prepare_reference_item(channel, {"id": "video-2", "caption": "Вторая тема"})

        self.assertEqual(first["external_id"], "video-1")
        self.assertEqual(second["external_id"], "video-2")
        self.assertNotEqual(first["external_id"], second["external_id"])

    def test_tiktok_profile_item_keeps_create_time_and_views(self):
        channel = models.ReferenceChannel(id=12, platform="tiktok", source_url="https://www.tiktok.com/@creator")
        post = extract_reference_post(channel, prepare_reference_item(channel, {
            "aweme_id": "video-3",
            "desc": "Свежая тема",
            "create_time": 1739470683,
            "statistics": {"play_count": 42},
            "url": "https://www.tiktok.com/@creator/video/video-3",
        }))

        self.assertEqual(post["external_id"], "video-3")
        self.assertEqual(post["view_count"], 42)
        self.assertIsNotNone(post["published_at"])

    def test_picks_latest_unused_post_per_profile_and_limits_to_three(self):
        posts = [
            SimpleNamespace(id=1, channel_id=10, published_at=datetime.datetime(2026, 8, 1), created_at=None, view_count=999),
            SimpleNamespace(id=2, channel_id=10, published_at=datetime.datetime(2026, 8, 2), created_at=None, view_count=1),
            SimpleNamespace(id=3, channel_id=20, published_at=datetime.datetime(2026, 8, 3), created_at=None, view_count=1),
            SimpleNamespace(id=4, channel_id=30, published_at=datetime.datetime(2026, 8, 4), created_at=None, view_count=1),
            SimpleNamespace(id=5, channel_id=40, published_at=datetime.datetime(2026, 8, 5), created_at=None, view_count=1),
        ]

        selected = pick_latest_unused_posts(posts, used_post_ids={2})

        self.assertEqual([post.id for post in selected], [5, 4, 3])

    def test_analysis_uses_media_details_and_image_urls(self):
        post = models.ReferencePost(
            source_url="https://www.instagram.com/p/ABC123/",
            title="Старая подпись",
            body="Старая подпись",
            raw={"media": {"id": "ABC123", "caption": "Старая подпись"}},
        )
        payload = analyze_reference_post(_Scraper(), post)
        self.assertEqual(payload["caption"], "Подпись из media")
        self.assertEqual(payload["image_urls"], ["https://example.com/actual.png"])

    def test_analysis_uses_video_transcript_before_description(self):
        post = models.ReferencePost(
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
            title="Описание",
            body="Описание",
            raw={"video_versions": [{"url": "https://example.com/video.mp4"}]},
        )
        with patch("app.services.reference_analysis._download_transcript") as transcribe:
            payload = analyze_reference_post(_Scraper(), post)
        self.assertEqual(payload["transcript"], "Текст из видео")
        transcribe.assert_not_called()

    @patch("app.services.reference_analysis._download_transcript", return_value="Текст из Deepgram")
    def test_instagram_and_tiktok_use_deepgram_transcription(self, transcribe):
        for source_url in (
            "https://www.instagram.com/reel/ABC123/",
            "https://www.tiktok.com/@creator/video/123",
        ):
            post = models.ReferencePost(
                source_url=source_url,
                title="Описание",
                body="Описание",
                raw={"video_versions": [{"url": "https://example.com/video.mp4"}]},
            )
            payload = analyze_reference_post(_Scraper(), post)
            self.assertEqual(payload["transcript"], "Текст из Deepgram")

        self.assertEqual(transcribe.call_count, 2)


if __name__ == "__main__":
    unittest.main()
