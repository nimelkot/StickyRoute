import unittest

from sticky_route.scorer import QueryClass, score_query


class ScoreQueryTests(unittest.TestCase):
    def test_limited_lookup_is_light(self):
        metrics = score_query("SELECT id FROM users WHERE id = 7 LIMIT 1")
        self.assertEqual(metrics.query_class, QueryClass.LIGHT)
        self.assertEqual(metrics.table_count, 1)
        self.assertFalse(metrics.unbounded_scan)

    def test_grouped_join_is_medium(self):
        metrics = score_query(
            "SELECT region, SUM(amount) FROM sales JOIN stores USING (store_id) GROUP BY region"
        )
        self.assertEqual(metrics.query_class, QueryClass.MEDIUM)
        self.assertEqual(metrics.table_count, 2)
        self.assertEqual(metrics.join_count, 1)
        self.assertEqual(metrics.aggregate_depth, 1)

    def test_unbounded_multi_table_scan_is_heavy(self):
        metrics = score_query("SELECT * FROM events CROSS JOIN users")
        self.assertEqual(metrics.query_class, QueryClass.HEAVY)
        self.assertTrue(metrics.unbounded_scan)
        self.assertTrue(metrics.has_cross_join)

    def test_unbounded_single_table_scan_is_heavy(self):
        metrics = score_query("SELECT * FROM events")
        self.assertEqual(metrics.query_class, QueryClass.HEAVY)
        self.assertTrue(metrics.unbounded_scan)

    def test_rejects_multiple_statements(self):
        with self.assertRaises(ValueError):
            score_query("SELECT 1; SELECT 2")


if __name__ == "__main__":
    unittest.main()