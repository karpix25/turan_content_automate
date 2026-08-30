import datetime
import unittest
from types import SimpleNamespace

from app.services.reference_selection import pick_latest_unused_posts


class ReferenceSelectionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
