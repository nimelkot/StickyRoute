from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class QueryClass(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


@dataclass(frozen=True)
class QueryMetrics:
    table_count: int
    join_count: int
    aggregate_depth: int
    unbounded_scan: bool
    has_limit: bool
    has_window: bool
    has_cross_join: bool
    query_class: QueryClass


def score_query(sql: str, dialect: str | None = None) -> QueryMetrics:
    """Classify one SQL statement using its parsed syntax tree."""
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except ParseError as error:
        raise ValueError(f"Unable to parse SQL: {error}") from error

    statements = [statement for statement in statements if statement is not None]
    if len(statements) != 1:
        raise ValueError("Expected exactly one SQL statement")

    tree = statements[0]
    cte_names = {
        cte.alias_or_name.casefold()
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    }
    table_refs = [
        table
        for table in tree.find_all(exp.Table)
        if table.name.casefold() not in cte_names
    ]
    joins = list(tree.find_all(exp.Join))
    aggregate_depth = _aggregate_depth(tree)
    has_limit = any(select.args.get("limit") is not None for select in tree.find_all(exp.Select))
    has_window = any(tree.find_all(exp.Window))
    unbounded_scan = any(_select_scans_without_bound(select) for select in tree.find_all(exp.Select))
    has_cross_join = any(join.args.get("kind", "").upper() == "CROSS" for join in joins)

    query_class = _classify(
        table_count=len(table_refs),
        join_count=len(joins),
        aggregate_depth=aggregate_depth,
        unbounded_scan=unbounded_scan,
        has_window=has_window,
        has_cross_join=has_cross_join,
    )
    return QueryMetrics(
        table_count=len(table_refs),
        join_count=len(joins),
        aggregate_depth=aggregate_depth,
        unbounded_scan=unbounded_scan,
        has_limit=has_limit,
        has_window=has_window,
        has_cross_join=has_cross_join,
        query_class=query_class,
    )


def _aggregate_depth(tree: exp.Expression) -> int:
    depth = 1 if any(select.args.get("group") is not None for select in tree.find_all(exp.Select)) else 0
    for aggregate in tree.find_all(exp.AggFunc):
        nested = 1
        parent = aggregate.parent
        while parent is not None:
            if isinstance(parent, exp.AggFunc):
                nested += 1
            parent = parent.parent
        depth = max(depth, nested)
    return depth


def _select_scans_without_bound(select: exp.Select) -> bool:
    if select.args.get("where") is not None or select.args.get("limit") is not None:
        return False
    source = select.args.get("from_")
    return source is not None and any(source.find_all(exp.Table))


def _classify(
    *,
    table_count: int,
    join_count: int,
    aggregate_depth: int,
    unbounded_scan: bool,
    has_window: bool,
    has_cross_join: bool,
) -> QueryClass:
    if has_cross_join or join_count >= 5 or (
        unbounded_scan
        and table_count >= 1
        and (
            (table_count == 1 and aggregate_depth == 0)
            or (table_count >= 2 and (join_count >= 3 or aggregate_depth == 0))
        )
    ):
        return QueryClass.HEAVY
    if join_count > 0 or aggregate_depth > 0 or has_window:
        return QueryClass.MEDIUM
    return QueryClass.LIGHT