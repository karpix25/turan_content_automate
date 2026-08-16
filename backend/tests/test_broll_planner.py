import unittest

from app.services.broll_planner import BrollCandidate, build_broll_plan


class BrollPlannerTests(unittest.TestCase):
    def candidates(self, count: int = 8):
        return [BrollCandidate(index, f"clip-{index}.mp4", 8.0) for index in range(1, count + 1)]

    def test_plan_is_deterministic_and_respects_rules(self):
        plan = build_broll_plan(
            main_duration=28.0,
            candidates=self.candidates(),
            seed=42,
        )
        same_plan = build_broll_plan(
            main_duration=28.0,
            candidates=list(reversed(self.candidates())),
            seed=42,
        )
        self.assertEqual([item.as_dict() for item in plan], [item.as_dict() for item in same_plan])

        broll = [item for item in plan if item.kind == "broll"]
        self.assertEqual(len({item.asset_id for item in broll}), len(broll))
        for item in broll:
            self.assertGreaterEqual(item.duration, 4.0)
            self.assertLessEqual(item.duration, 6.0)
            self.assertGreaterEqual(item.source_start, 0.0)
            self.assertLessEqual(item.source_start + item.duration, 8.0 + 1e-6)

        for index, segment in enumerate(plan):
            if segment.kind != "broll":
                continue
            previous = plan[index - 1]
            following = plan[index + 1]
            self.assertEqual(previous.kind, "main")
            self.assertGreaterEqual(previous.duration, 3.0)
            self.assertLessEqual(previous.duration, 5.0)
            self.assertEqual(following.kind, "main")
            self.assertGreaterEqual(following.duration, 3.0)

    def test_short_assets_are_not_selected(self):
        plan = build_broll_plan(
            main_duration=12.0,
            candidates=[BrollCandidate(1, "too-short.mp4", 3.9)],
            seed=1,
        )
        self.assertFalse(any(item.kind == "broll" for item in plan))
        self.assertEqual(sum(item.duration for item in plan), 12.0)

    def test_library_exhaustion_stops_without_repeating(self):
        plan = build_broll_plan(
            main_duration=60.0,
            candidates=[BrollCandidate(1, "only.mp4", 8.0)],
            seed=5,
        )
        broll = [item for item in plan if item.kind == "broll"]
        self.assertEqual(len(broll), 1)
        self.assertEqual(sum(item.duration for item in plan), 60.0)


if __name__ == "__main__":
    unittest.main()
