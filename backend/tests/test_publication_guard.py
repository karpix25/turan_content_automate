import datetime
import unittest

from app.publication_guard import PublicationVerificationError, verify_publication_payload


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


if __name__ == "__main__":
    unittest.main()
