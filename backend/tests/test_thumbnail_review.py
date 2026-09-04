import unittest

from app.services.thumbnail_review import should_request_thumbnail_review


class ThumbnailReviewTests(unittest.TestCase):
    def test_auto_approve_skips_telegram_review(self):
        self.assertFalse(
            should_request_thumbnail_review(
                review_enabled=True,
                auto_approve_enabled=True,
                telegram_chat_id="123",
            )
        )

    def test_manual_review_requires_enabled_review_and_chat(self):
        self.assertTrue(
            should_request_thumbnail_review(
                review_enabled=True,
                auto_approve_enabled=False,
                telegram_chat_id="123",
            )
        )
        self.assertFalse(
            should_request_thumbnail_review(
                review_enabled=True,
                auto_approve_enabled=False,
                telegram_chat_id="",
            )
        )


if __name__ == "__main__":
    unittest.main()
