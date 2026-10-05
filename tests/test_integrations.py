import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sticky_route.router import Router, route_connection
from sticky_route.session_tracker import SessionTracker


class FakeCursor:
    def __init__(self, statements):
        self.statements = statements

    def execute(self, sql, *args, **kwargs):
        self.statements.append(sql)
        return self

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.statements = []

    def cursor(self, *args, **kwargs):
        return FakeCursor(self.statements)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary_directory.name) / "sessions.json"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_connection_switches_warehouse_once(self):
        connection = FakeConnection()
        tracker = SessionTracker(self.state_path)
        routed = route_connection(connection, router=Router(tracker=tracker))

        routed.cursor().execute("SELECT id FROM users LIMIT 1")
        routed.cursor().execute("SELECT id FROM users LIMIT 1")

        self.assertEqual(len(connection.statements), 3)
        self.assertEqual(connection.statements[0], 'USE WAREHOUSE "WH_DEV_XS"')
        self.assertTrue(connection.statements[1].startswith("SELECT"))
        self.assertTrue(connection.statements[2].startswith("SELECT"))

    def test_claude_hook_sets_warehouse_and_preserves_other_input(self):
        hook = Path(__file__).parents[1] / "hooks" / "pretooluse.py"
        environment = os.environ.copy()
        environment["STICKY_ROUTE_STATE"] = str(self.state_path)
        event = {
            "session_id": "hook-test",
            "tool_name": "mcp__warehouse__query",
            "tool_input": {"sql": "SELECT id FROM users LIMIT 1", "timeout": 10},
        }
        result = subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=environment,
            check=True,
        )

        output = json.loads(result.stdout)
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["timeout"], 10)
        self.assertTrue(updated["sql"].startswith('USE WAREHOUSE "WH_DEV_XS";'))


if __name__ == "__main__":
    unittest.main()