import unittest

from app.integrations.scrape_creators import ScrapeCreatorsClient


class ScrapeCreatorsTikTokTests(unittest.TestCase):
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
