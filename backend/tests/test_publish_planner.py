import datetime
import unittest
from types import SimpleNamespace

from app import models
from app.publish_planner import plan_next_publish_times_for_account_outputs


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, project_rows, task_rows):
        self.project_rows = project_rows
        self.task_rows = task_rows

    def query(self, model):
        rows = self.project_rows if model is models.PostMyPostProjectSetting else self.task_rows
        return FakeQuery(rows)


class PublishPlannerTests(unittest.TestCase):
    def test_project_format_limits_apply_to_each_account(self):
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
                publish_at=datetime.datetime(2026, 8, 20, 8 + index, 0),
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
        minimum_utc = datetime.datetime(2026, 8, 20, 0, 0)

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

        self.assertEqual(vizard_times[0].date(), datetime.date(2026, 8, 21))
        self.assertEqual(vizard_times[1].date(), datetime.date(2026, 8, 20))
        self.assertEqual(other_times[0].date(), datetime.date(2026, 8, 20))


if __name__ == "__main__":
    unittest.main()
