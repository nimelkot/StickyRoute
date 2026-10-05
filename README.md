# Sticky Route

Sticky Route is a deterministic SQL compute router for Snowflake and Databricks. It parses each statement locally with SQLGlot, classifies its structural complexity, and applies session affinity and hysteresis without an `EXPLAIN` roundtrip.

## Install

```bash
python -m pip install -e .
```

To run the MCP server as well:

```bash
python -m pip install -e '.[mcp]'
```

The optional MCP server is exposed as `sticky-route-mcp` and is configured for Claude Code by the root `.mcp.json`. The Claude Code plugin hook is registered in `.claude-plugin/plugin.json` and `hooks/hooks.json`.

## Use

```bash
sticky-route score 'SELECT user_id FROM events WHERE user_id = 42 LIMIT 1'
sticky-route route --backend snowflake --session analyst-1 'SELECT region, SUM(amount) FROM sales GROUP BY region'
```

Python callers can wrap a Snowflake connection:

```python
from sticky_route import route_connection
import snowflake.connector

conn = route_connection(snowflake.connector.connect(...), session_id="analyst-1")
conn.cursor().execute("SELECT COUNT(*) FROM raw_events GROUP BY user_id")
```

The wrapper issues `USE WAREHOUSE` before the first query routed to a target warehouse. The Snowflake user needs permission to use every configured warehouse. Databricks SQL connections do not support switching SQL warehouses with a `USE` statement; provide `warehouse_switcher(connection, backend, warehouse)` to `route_connection` to implement switching or reconnection for your connector setup.

The MCP `route_query` tool returns a decision for a client to apply; it does not execute SQL. The Claude `PreToolUse` hook updates a recognized warehouse input field when one exists. For SQL-only Snowflake tools it prefixes `USE WAREHOUSE` to the statement, so use it only with tools that accept multi-statement SQL. For Databricks, the hook only updates tools that expose a recognized warehouse input field. Set `STICKY_ROUTE_BACKEND=databricks` to select Databricks policy targets. Set `STICKY_ROUTE_STATE` to change the local state JSON path.

## Policy

The packaged defaults are in [`src/sticky_route/policy.yaml`](src/sticky_route/policy.yaml). They map light, medium, and heavy classes to backend warehouses. Adjust the identifiers for your account before use. The router escalates only when the class's configured estimated speedup is greater than `escalation_min_savings_seconds`; it waits for `downgrade_threshold_queries` consecutive light queries before downscaling.

Session state is written atomically to `~/.cache/sticky-route/sessions.json` by default. Supply a `SessionTracker(path=...)` to use another local file. Each application/session should use a distinct session ID.

## Classification

- Light: point lookups, limited reads, and simple single-table queries.
- Medium: joins, grouped aggregates, and window functions.
- Heavy: cross joins, five or more joins, or large unbounded multi-table scans.

These are structural heuristics, not table-size statistics or a query optimizer. Review and tune the policy against representative workloads before enabling automatic switching in production.

## Tests

```bash
python -m unittest discover -s tests -v
```