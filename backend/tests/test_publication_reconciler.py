import datetime
import unittest
from types import SimpleNamespace

from app.publication_reconciler import reconcile_scheduled_publications


UTC = datetime.timezone.utc


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    def query(self, _model):
        return FakeQuery(self.rows)

    def commit(self):
        self.commits += 1


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.deleted = []

    def get_publication(self, publication_id, account_ids=None):
        payload = self.payloads[publication_id]
        if isinstance(payload, Exception):
            raise payload
        return payload

    def delete_publication(self, publication_id, account_ids):
        self.deleted.append((publication_id, account_ids))


class PublicationReconcilerTests(unittest.TestCase):
    def task(self, task_id, post_id, publish_at):
        return SimpleNamespace(
            id=task_id,
            user_id=1,
            target_account_id=10,
            vizard_project_id=123,
            postmypost_id=post_id,
            publish_at=publish_at,
            publishing_status="scheduled",
            preview_url="preview",
            script_meta={},
        )

    def test_releases_unconfirmed_and_invalid_slots_keeps_valid(self):
        publish_at = datetime.datetime.now() + datetime.timedelta(days=2)
        publish_at = publish_at.replace(hour=12, minute=47, second=0, microsecond=0)
        missing_id = self.task(1, None, publish_at)
        invalid = self.task(2, 200, publish_at)
        valid = self.task(3, 300, publish_at)
        client = FakeClient(
            {
                200: {"post_at": publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")},
                300: {
                    "publication_status": 5,
                    "post_at": publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }
        )

        result = reconcile_scheduled_publications(
            FakeDb([missing_id, invalid, valid]),
            SimpleNamespace(id=1),
            [10],
            lane="vizard",
            client=client,
        )

        self.assertEqual(result["released"], 2)
        self.assertEqual(result["retained"], 1)
        self.assertEqual(missing_id.publishing_status, "not_published")
        self.assertIsNone(missing_id.publish_at)
        self.assertIsNone(invalid.postmypost_id)
        self.assertEqual(client.deleted, [(200, [10])])
        self.assertEqual(valid.postmypost_id, 300)


if __name__ == "__main__":
    unittest.main()
