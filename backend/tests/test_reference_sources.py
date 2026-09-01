import unittest

from app import models
from app.services.reference_sources import resolve_project_account_handles


class _Pmp:
    calls = 0

    def get_accounts(self, project_id):
        type(self).calls += 1
        self.project_id = project_id
        return [
            {"id": 11, "login": "@turan_vk"},
            {"id": 12, "name": "Turan VK"},
        ]


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


class ReferenceSourcesTests(unittest.TestCase):
    def setUp(self):
        _Pmp.calls = 0

    def test_account_login_is_preferred_and_training_source_is_fallback(self):
        pmp = _Pmp()
        result = resolve_project_account_handles(
            7,
            pmp,
            {"vk": [11, 12]},
            fallback_source="https://youtube.com/@turantender",
        )
        self.assertEqual(result, {"vk": {11: "@turan_vk", 12: "@turantender"}})

    def test_handle_is_saved_and_postmypost_is_not_called_again(self):
        row = models.UserPublishChannel(
            user_id=1,
            postmypost_project_id=7,
            account_id=11,
        )
        db = _Db([row])
        pmp = _Pmp()
        accounts = {"vk": [11]}

        first = resolve_project_account_handles(7, pmp, accounts, db=db, user_id=1)
        second = resolve_project_account_handles(7, pmp, accounts, db=db, user_id=1)

        self.assertEqual(first, {"vk": {11: "@turan_vk"}})
        self.assertEqual(second, first)
        self.assertEqual(row.account_handle, "@turan_vk")
        self.assertEqual(_Pmp.calls, 1)
        self.assertEqual(db.commits, 1)


if __name__ == "__main__":
    unittest.main()
