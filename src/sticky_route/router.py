from __future__ import annotations

import importlib.resources
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from sticky_route.scorer import QueryMetrics, score_query
from sticky_route.session_tracker import SessionState, SessionTracker


_TIERS = ("light", "medium", "heavy")


@dataclass(frozen=True)
class RouteDecision:
    tier: str
    warehouse: str
    query_class: str
    metrics: QueryMetrics
    switched: bool
    reason: str
    idle_seconds_remaining: int


class Router:
    def __init__(
        self,
        policy_path: str | Path | None = None,
        tracker: SessionTracker | None = None,
    ):
        if policy_path is None:
            policy_text = importlib.resources.files("sticky_route").joinpath("policy.yaml").read_text()
            self.policy = yaml.safe_load(policy_text)
        else:
            with Path(policy_path).open(encoding="utf-8") as policy_file:
                self.policy = yaml.safe_load(policy_file)
        self._validate_policy()
        self.tracker = tracker or SessionTracker()

    def route(
        self,
        sql: str,
        *,
        session_id: str = "default",
        backend: str = "snowflake",
        now: float | None = None,
    ) -> RouteDecision:
        backend = backend.casefold()
        if backend not in {"snowflake", "databricks"}:
            raise ValueError("backend must be 'snowflake' or 'databricks'")

        current_time = time.time() if now is None else now
        metrics = score_query(sql)
        desired_tier = metrics.query_class.value
        current = self.tracker.get(session_id)
        rules = self.policy["switching_rules"]
        light_streak = (current.light_streak if current else 0) + 1 if desired_tier == "light" else 0
        tier = desired_tier
        reason = "query_class"

        if current is not None:
            current_rank = _TIERS.index(current.tier)
            desired_rank = _TIERS.index(desired_tier)
            warm = current_time - current.last_query_at <= rules["idle_window_seconds"]

            if desired_rank < current_rank:
                if desired_tier == "light" and light_streak < rules["downgrade_threshold_queries"]:
                    tier, reason = current.tier, "light_streak_hysteresis"
                elif desired_tier != "light" and rules["prefer_warm"] and warm:
                    tier, reason = current.tier, "warm_state_affinity"
                else:
                    reason = "light_streak_met" if desired_tier == "light" else "idle_downgrade"
            elif desired_rank > current_rank:
                savings = rules["estimated_speedup_seconds"].get(desired_tier, 0)
                if savings <= rules["escalation_min_savings_seconds"]:
                    tier, reason = current.tier, "escalation_below_penalty"
                else:
                    reason = "estimated_savings_exceed_penalty"

        warehouse = self.policy["tiers"][tier][backend]
        switched = current is None or current.tier != tier or current.warehouse != warehouse
        state = SessionState(
            tier=tier,
            warehouse=warehouse,
            last_query_at=current_time,
            light_streak=light_streak,
        )
        self.tracker.put(session_id, state)
        return RouteDecision(
            tier=tier,
            warehouse=warehouse,
            query_class=desired_tier,
            metrics=metrics,
            switched=switched,
            reason=reason,
            idle_seconds_remaining=state.idle_seconds_remaining(
                current_time, rules["idle_window_seconds"]
            ),
        )

    def _validate_policy(self) -> None:
        if not isinstance(self.policy, dict) or not isinstance(self.policy.get("tiers"), dict):
            raise ValueError("Policy must define a tiers mapping")
        for tier in _TIERS:
            if tier not in self.policy["tiers"]:
                raise ValueError(f"Policy is missing the {tier!r} tier")
            for backend in ("snowflake", "databricks"):
                if not self.policy["tiers"][tier].get(backend):
                    raise ValueError(f"Policy is missing {backend!r} for tier {tier!r}")
        rules = self.policy.get("switching_rules")
        if not isinstance(rules, dict):
            raise ValueError("Policy must define switching_rules")
        for setting in (
            "prefer_warm",
            "idle_window_seconds",
            "downgrade_threshold_queries",
            "escalation_min_savings_seconds",
            "estimated_speedup_seconds",
        ):
            if setting not in rules:
                raise ValueError(f"Policy is missing switching rule {setting!r}")


class RoutedConnection:
    def __init__(
        self,
        connection: Any,
        router: Router,
        session_id: str,
        backend: str,
        warehouse_switcher: Callable[[Any, str, str], None] | None,
    ):
        self._connection = connection
        self._router = router
        self._session_id = session_id
        self._backend = backend
        self._warehouse_switcher = warehouse_switcher or _switch_warehouse
        self._active_warehouse: str | None = None

    def cursor(self, *args: Any, **kwargs: Any) -> RoutedCursor:
        return RoutedCursor(self, self._connection.cursor(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class RoutedCursor:
    def __init__(self, connection: RoutedConnection, cursor: Any):
        self._connection = connection
        self._cursor = cursor

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        decision = self._connection._router.route(
            sql,
            session_id=self._connection._session_id,
            backend=self._connection._backend,
        )
        if decision.warehouse != self._connection._active_warehouse:
            self._connection._warehouse_switcher(
                self._connection._connection,
                self._connection._backend,
                decision.warehouse,
            )
            self._connection._active_warehouse = decision.warehouse
        return self._cursor.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


def route_connection(
    connection: Any,
    *,
    router: Router | None = None,
    session_id: str = "default",
    backend: str = "snowflake",
    warehouse_switcher: Callable[[Any, str, str], None] | None = None,
) -> RoutedConnection:
    """Wrap a connection and select its compute tier before each execute call."""
    return RoutedConnection(
        connection,
        router or Router(),
        session_id,
        backend.casefold(),
        warehouse_switcher,
    )


def _switch_warehouse(connection: Any, backend: str, warehouse: str) -> None:
    if backend != "snowflake":
        raise RuntimeError(
            "Databricks warehouse switching requires a warehouse_switcher callback"
        )
    if not warehouse.replace("_", "").replace("$", "").isalnum():
        raise ValueError(f"Unsafe Snowflake warehouse identifier: {warehouse!r}")
    cursor = connection.cursor()
    try:
        cursor.execute(f'USE WAREHOUSE "{warehouse.replace(chr(34), chr(34) * 2)}"')
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()