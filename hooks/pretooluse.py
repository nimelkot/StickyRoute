from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from sticky_route.router import Router


def main() -> None:
    try:
        event = json.load(sys.stdin)
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return

        sql_key = next(
            (key for key in ("sql", "query", "statement") if isinstance(tool_input.get(key), str)),
            None,
        )
        if sql_key is None:
            return

        sql = tool_input[sql_key]
        if re.match(r"\s*USE\s+WAREHOUSE\b", sql, re.IGNORECASE):
            return
        backend = os.environ.get("STICKY_ROUTE_BACKEND", "snowflake")
        decision = Router().route(
            sql,
            backend=backend,
            session_id=str(event.get("session_id", "claude-code")),
        )

        updated_input = dict(tool_input)
        warehouse_key = next(
            (key for key in ("warehouse", "warehouse_id", "warehouse_name") if key in updated_input),
            None,
        )
        if warehouse_key:
            updated_input[warehouse_key] = decision.warehouse
        elif backend == "snowflake":
            updated_input[sql_key] = f'USE WAREHOUSE "{decision.warehouse}";\n{sql}'
        else:
            return

        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "updatedInput": updated_input,
                    }
                }
            )
        )
    except Exception as error:
        print(f"sticky-route hook skipped routing: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()