import datetime
import unittest

from app.publication_guard import PublicationVerificationError, verify_publication_payload
from app.integrations.postmypost_errors import PostMyPostApiError
from app.publication_repair import is_missing_publication_status_error


UTC = datetime.timezone.utc


class PublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 8, 16, 15, 0, tzinfo=UTC)
        self.expected = datetime.datetime(2026, 8, 20, 9, 47)
        self.lead = datetime.timedelta(hours=1)

    def test_accepts_provider_timezone_and_status(self):
        verified = verify_publication_payload(
            {
                "publication_status": 5,
                "post_at": "2026-08-20T12:47:00+03:00",
            },
            expected_post_at=self.expected,
            now_utc=self.now,
            minimum_lead=self.lead,
        )

        self.assertEqual(verified.publication_status, 5)
        self.assertEqual(
            verified.post_at,
            datetime.datetime(2026, 8, 20, 9, 47, tzinfo=UTC),
        )

    def test_rejects_missing_status(self):
        with self.assertRaises(PublicationVerificationError):
            verify_publication_payload(
                {"post_at": "2026-08-20T09:47:00Z"},
                expected_post_at=self.expected,
                now_utc=self.now,
                minimum_lead=self.lead,
            )

    def test_rejects_past_publication(self):
        with self.assertRaises(PublicationVerificationError):
            verify_publication_payload(
                {
                    "publication_status": 5,
                    "post_at": "2026-08-16T15:30:00Z",
                },
                expected_post_at=self.expected,
                now_utc=self.now,
                minimum_lead=self.lead,
            )

    def test_accepts_incomplete_provider_response_as_repairable(self):
        error = PostMyPostApiError(
            "invalid response",
            status_code=422,
            method="GET",
            path="/publications/1",
            response_text="Response validation error: Required property 'account_ids'",
        )
        self.assertTrue(is_missing_publication_status_error(error))


if __name__ == "__main__":
    unittest.main()
