"""In-process MCP task store for long-running tool calls.

MCP Tasks (protocol 2025-11-25) let a caller ask the server to run a request in
the background: the server returns a :class:`~mcp_types.Task` immediately and the
real result is fetched later with ``tasks/result`` (progress is polled with
``tasks/get``). The SDK ships the wire types but no server-side task runner, so
this module supplies the stateful core: :class:`TaskStore` creates, tracks,
expires and cancels task records and retains each task's final payload.

Everything lives in memory for the process lifetime. Access is guarded by a lock
because the background tool run happens on a different task from the requests
that poll it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from mcp_types import Task, TaskStatus

#: Terminal states stop a task from progressing further.
_TERMINAL: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

DEFAULT_TTL_MS = 3_600_000


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class TaskRecord:
    """Server-side state for one task."""

    task_id: str
    status: TaskStatus
    created_at: datetime
    last_updated_at: datetime
    ttl_ms: int
    poll_interval_ms: int | None = None
    status_message: str | None = None
    expires_at: float = 0.0
    result: Any = None
    """The original ``CallToolResult`` payload once the task completes."""

    def to_wire(self) -> Task:
        """Render this record as the version-free wire ``Task`` model.

        ``ttl`` is always emitted as a concrete int: the serializer drops
        ``None`` fields, but a task's ``ttl`` is required on the wire.
        """
        return Task(
            task_id=self.task_id,
            status=self.status,
            status_message=self.status_message,
            created_at=self.created_at.isoformat(),
            last_updated_at=self.last_updated_at.isoformat(),
            ttl=self.ttl_ms,
            poll_interval=self.poll_interval_ms,
        )


class TaskStore:
    """Thread-safe, TTL-bounded store of :class:`TaskRecord` objects."""

    def __init__(self, *, default_ttl_ms: int = DEFAULT_TTL_MS) -> None:
        self._lock = Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._default_ttl_ms = default_ttl_ms

    def create(self, *, ttl_ms: int | None = None, poll_interval_ms: int | None = None) -> TaskRecord:
        """Create a fresh ``working`` task and return its record."""
        ttl = ttl_ms if ttl_ms and ttl_ms > 0 else self._default_ttl_ms
        now = _now()
        record = TaskRecord(
            task_id=uuid.uuid4().hex,
            status="working",
            created_at=now,
            last_updated_at=now,
            ttl_ms=ttl,
            poll_interval_ms=poll_interval_ms,
            expires_at=time.monotonic() + ttl / 1000.0,
        )
        with self._lock:
            self._purge_locked()
            self._tasks[record.task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            self._purge_locked()
            return self._tasks.get(task_id)

    def list(self) -> list[TaskRecord]:
        with self._lock:
            self._purge_locked()
            return sorted(self._tasks.values(), key=lambda r: r.created_at)

    def complete(self, task_id: str, result: Any) -> TaskRecord | None:
        return self._finish(task_id, "completed", result=result)

    def fail(self, task_id: str, message: str) -> TaskRecord | None:
        return self._finish(task_id, "failed", status_message=message)

    def cancel(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            self._purge_locked()
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.status not in _TERMINAL:
                record.status = "cancelled"
                record.last_updated_at = _now()
            return record

    def _finish(
        self, task_id: str, status: TaskStatus, *, result: Any = None, status_message: str | None = None
    ) -> TaskRecord | None:
        with self._lock:
            self._purge_locked()
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.status not in _TERMINAL:
                record.status = status
                record.status_message = status_message
                record.result = result
                record.last_updated_at = _now()
            return record

    def _purge_locked(self) -> None:
        """Drop expired tasks. Caller must hold the lock."""
        now = time.monotonic()
        expired = [tid for tid, rec in self._tasks.items() if rec.expires_at <= now]
        for tid in expired:
            del self._tasks[tid]
