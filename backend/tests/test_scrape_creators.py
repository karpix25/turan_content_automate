import unittest

from app.integrations.scrape_creators import ScrapeCreatorsClient, normalize_tiktok_handle


class ScrapeCreatorsTikTokTests(unittest.TestCase):
    def test_normalize_tiktok_profile_handle(self):
        self.assertEqual(normalize_tiktok_handle("https://www.tiktok.com/@creator"), "creator")
        self.assertEqual(normalize_tiktok_handle("@creator"), "creator")

    def test_get_tiktok_profile_videos_uses_latest_feed_endpoint(self):
        client = ScrapeCreatorsClient("key")
        client._get_json = lambda path, params: {
            "success": True,
            "aweme_list": [{"aweme_id": "1"}, {"aweme_id": "2"}],
        }

        payload = client.get_tiktok_profile_videos("https://www.tiktok.com/@creator")

        self.assertEqual([item["aweme_id"] for item in payload["aweme_list"]], ["1", "2"])

    def test_extracts_no_watermark_url_and_transcript(self):
        client = ScrapeCreatorsClient("test")
        client._get_json = lambda path, params: {
            "success": True,
            "aweme_detail": {
                "desc": "Подпись",
                "author": {"unique_id": "creator"},
                "statistics": {"play_count": 42},
                "video": {
                    "has_watermark": True,
                    "download_no_watermark_addr": {"url_list": ["https://cdn.test/video.mp4"]},
                },
            },
            "transcript": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nПривет",
        }

        result = client.get_tiktok_details("https://www.tiktok.com/@creator/video/1")

        self.assertEqual(result["download_url"], "https://cdn.test/video.mp4")
        self.assertEqual(result["transcript_only_text"], "Привет")
        self.assertEqual(result["creator"], "creator")

    def test_does_not_claim_no_watermark_when_tiktok_only_returns_watermarked_url(self):
        client = ScrapeCreatorsClient("test")
        client._get_json = lambda path, params: {
            "success": True,
            "aweme_detail": {
                "video": {
                    "has_watermark": True,
                    "play_addr": {"url_list": ["https://cdn.test/watermarked.mp4"]},
                }
            },
        }

        result = client.get_tiktok_details("https://www.tiktok.com/@creator/video/1")

        self.assertIsNone(result["download_url"])


if __name__ == "__main__":
    unittest.main()
