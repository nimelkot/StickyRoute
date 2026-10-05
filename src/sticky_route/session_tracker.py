from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionState:
    tier: str
    warehouse: str
    last_query_at: float
    light_streak: int = 0

    def idle_seconds_remaining(self, now: float, idle_window_seconds: int) -> int:
        elapsed = max(0.0, now - self.last_query_at)
        return max(0, int(idle_window_seconds - elapsed))


class SessionTracker:
    """Small atomic JSON store for per-session routing affinity."""

    _lock = threading.RLock()

    def __init__(self, path: str | Path | None = None):
        default_path = os.environ.get("STICKY_ROUTE_STATE")
        self.path = Path(path or default_path or Path.home() / ".cache/sticky-route/sessions.json")

    def get(self, session_id: str) -> SessionState | None:
        with self._lock:
            sessions = self._read_all()
        state = sessions.get(session_id)
        if state is None:
            return None
        return SessionState(
            tier=state["tier"],
            warehouse=state["warehouse"],
            last_query_at=float(state["last_query_at"]),
            light_streak=int(state.get("light_streak", 0)),
        )

    def put(self, session_id: str, state: SessionState) -> None:
        with self._lock:
            sessions = self._read_all()
            sessions[session_id] = asdict(state)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=f"{self.path.name}.", dir=self.path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
                    json.dump(sessions, temporary_file, separators=(",", ":"))
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary_path, self.path)
            finally:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)

    def _read_all(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open(encoding="utf-8") as session_file:
                sessions = json.load(session_file)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read session state at {self.path}: {error}") from error
        if not isinstance(sessions, dict):
            raise ValueError(f"Invalid session state at {self.path}: expected an object")
        return sessions