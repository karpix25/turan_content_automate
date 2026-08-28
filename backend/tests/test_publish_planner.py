import datetime
import unittest
from types import SimpleNamespace

from app import models
from app.publish_planner import get_project_format_limits, plan_next_publish_times_for_account_outputs


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, project_rows, task_rows, carousel_rows=None):
        self.project_rows = project_rows
        self.task_rows = task_rows
        self.carousel_rows = carousel_rows or []

    def query(self, model):
        if model is models.PostMyPostProjectSetting:
            rows = self.project_rows
        elif model is models.CarouselPublication:
            rows = self.carousel_rows
        else:
            rows = self.task_rows
        return FakeQuery(rows)


class PublishPlannerTests(unittest.TestCase):
    def test_legacy_project_limits_are_balanced_to_total(self):
        db = FakeDb(
            [SimpleNamespace(publish_limit_per_day=6, vizard_limit_per_day=3, other_formats_limit_per_day=6)],
            [],
        )
        user = SimpleNamespace(id=1, publish_limit_per_day=3)

        self.assertEqual(
            get_project_format_limits(db, user, 266646),
            {"total": 6, "vizard": 3, "other": 3},
        )

    def test_project_format_limits_apply_to_each_account(self):
        base_day = datetime.datetime.now().date() + datetime.timedelta(days=2)
        project_settings = [
            SimpleNamespace(
                publish_limit_per_day=6,
                vizard_limit_per_day=4,
                other_formats_limit_per_day=6,
            ),
        ]
        occupied = [
            SimpleNamespace(
                id=index,
                target_account_id=10,
                vizard_project_id=123,
                postmypost_id=str(index),
                publish_at=datetime.datetime.combine(base_day, datetime.time(8 + index, 0)),
                publishing_status="scheduled",
            )
            for index in range(4)
        ]
        user = SimpleNamespace(
            id=1,
            publish_window_start_msk="10:00:00",
            publish_window_end_msk="22:00:00",
        )
        db = FakeDb(project_settings, occupied)
        minimum_utc = datetime.datetime.combine(base_day, datetime.time(0, 0))

        vizard_times = plan_next_publish_times_for_account_outputs(
            db,
            user,
            [10, 20],
            lane="vizard",
            project_id=266646,
            minimum_utc=minimum_utc,
        )
        other_times = plan_next_publish_times_for_account_outputs(
            db,
            user,
            [10],
            lane="instant",
            project_id=266646,
            minimum_utc=minimum_utc,
        )

        self.assertEqual(vizard_times[0].date(), base_day + datetime.timedelta(days=1))
        self.assertEqual(vizard_times[1].date(), base_day)
        self.assertEqual(other_times[0].date(), base_day)

    def test_carousel_publications_consume_other_formats_limit(self):
        base_day = datetime.datetime.now().date() + datetime.timedelta(days=2)
        carousel_rows = [
            SimpleNamespace(
                id=index,
                account_id=10,
                postmypost_id=str(index),
                post_at=datetime.datetime.combine(base_day, datetime.time(10 + index, 0)),
                publishing_status="scheduled",
            )
            for index in range(3)
        ]
        db = FakeDb(
            [SimpleNamespace(publish_limit_per_day=6, vizard_limit_per_day=3, other_formats_limit_per_day=3)],
            [],
            carousel_rows,
        )
        user = SimpleNamespace(
            id=1,
            publish_window_start_msk="10:00:00",
            publish_window_end_msk="22:00:00",
        )

        planned = plan_next_publish_times_for_account_outputs(
            db,
            user,
            [10],
            lane="instant",
            project_id=266646,
            minimum_utc=datetime.datetime.combine(base_day, datetime.time(0, 0)),
        )

        self.assertEqual(planned[0].date(), base_day + datetime.timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
