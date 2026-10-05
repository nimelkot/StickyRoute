from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from sticky_route.router import Router
from sticky_route.scorer import score_query


def main() -> None:
    parser = argparse.ArgumentParser(prog="sticky-route")
    commands = parser.add_subparsers(dest="command", required=True)
    for command_name in ("score", "route"):
        command = commands.add_parser(command_name)
        command.add_argument("sql", help="one SQL statement")
        command.add_argument("--backend", choices=("snowflake", "databricks"), default="snowflake")
        if command_name == "route":
            command.add_argument("--session", default="default")
    arguments = parser.parse_args()

    if arguments.command == "score":
        result = asdict(score_query(arguments.sql))
    else:
        decision = Router().route(
            arguments.sql,
            backend=arguments.backend,
            session_id=arguments.session,
        )
        result = asdict(decision)
    print(json.dumps(result, default=str, indent=2))