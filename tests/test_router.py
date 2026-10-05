import tempfile
import unittest
from pathlib import Path

from sticky_route.router import Router
from sticky_route.session_tracker import SessionTracker


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        tracker = SessionTracker(Path(self.temporary_directory.name) / "sessions.json")
        self.router = Router(tracker=tracker)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_medium_warm_tier_stays_for_four_light_queries_then_downscales(self):
        medium = self.router.route("SELECT region, SUM(amount) FROM sales GROUP BY region", now=100)
        self.assertEqual(medium.tier, "medium")

        for timestamp in range(101, 105):
            decision = self.router.route("SELECT id FROM users LIMIT 1", now=timestamp)
            self.assertEqual(decision.tier, "medium")
            self.assertEqual(decision.reason, "light_streak_hysteresis")

        decision = self.router.route("SELECT id FROM users LIMIT 1", now=105)
        self.assertEqual(decision.tier, "light")
        self.assertEqual(decision.reason, "light_streak_met")

    def test_escalation_requires_savings_above_switch_penalty(self):
        self.router.route("SELECT id FROM users LIMIT 1", now=100)
        medium = self.router.route("SELECT region, SUM(amount) FROM sales GROUP BY region", now=101)
        heavy = self.router.route("SELECT * FROM events CROSS JOIN users", now=102)

        self.assertEqual(medium.tier, "light")
        self.assertEqual(medium.reason, "escalation_below_penalty")
        self.assertEqual(heavy.tier, "heavy")
        self.assertEqual(heavy.reason, "estimated_savings_exceed_penalty")

    def test_databricks_policy_selects_backend_warehouse(self):
        decision = self.router.route("SELECT id FROM users LIMIT 1", backend="databricks", now=100)
        self.assertEqual(decision.warehouse, "2X-Small")


if __name__ == "__main__":
    unittest.main()