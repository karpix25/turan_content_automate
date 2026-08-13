import unittest

from app.services.video_uniqueizer import build_unique_seed, get_duplicate_platform_account_ids


class VideoUniqueizerTests(unittest.TestCase):
    def test_account_id_changes_render_seed(self):
        first = build_unique_seed(project_id=266646, clip_index=1, account_id=101, slot_index=1)
        second = build_unique_seed(project_id=266646, clip_index=1, account_id=202, slot_index=2)
        self.assertNotEqual(first, second)

    def test_duplicate_platform_accounts_are_detected(self):
        duplicates = get_duplicate_platform_account_ids(
            [101, 202, 303],
            {101: "instagram", 202: "instagram", 303: "youtube"},
        )
        self.assertEqual(duplicates, {101, 202})


if __name__ == "__main__":
    unittest.main()
