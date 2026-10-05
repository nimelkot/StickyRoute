from __future__ import annotations

from dataclasses import asdict
import json

from mcp.server.fastmcp import FastMCP

from sticky_route.router import Router


server = FastMCP("sticky-route")
router = Router()


@server.tool()
def route_query(
    sql: str,
    session_id: str = "mcp-default",
    backend: str = "snowflake",
) -> dict[str, object]:
    """Classify a SQL statement and return its deterministic compute target."""
    decision = router.route(sql, session_id=session_id, backend=backend)
    return json.loads(json.dumps(asdict(decision), default=str))


def main() -> None:
    server.run(transport="stdio")