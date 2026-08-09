"""SQLite-backed checkpoints, idempotency, approvals, and audit events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xt_aegis.errors import ApprovalError
from xt_aegis.models import ActionRequest, ExecutionResult, ExecutionStatus


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


_FINAL_STATUSES = {
    ExecutionStatus.SUCCEEDED.value,
    ExecutionStatus.ROLLED_BACK.value,
    ExecutionStatus.BLOCKED.value,
    ExecutionStatus.FAILED.value,
}


class CheckpointStore:
    """Small durable state store with WAL and unique idempotency keys."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    thread_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    step_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(thread_id, step_number),
                    FOREIGN KEY(thread_id) REFERENCES runs(thread_id)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    UNIQUE(thread_id, action_id, idempotency_key),
                    FOREIGN KEY(thread_id) REFERENCES runs(thread_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_steps_thread ON steps(thread_id, step_number);
                CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id, id);
                """
            )

    def start_run(self, thread_id: str, skill_name: str) -> None:
        now = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs(thread_id, skill_name, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (thread_id, skill_name, "running", now, now),
            )

    def set_run_status(self, thread_id: str, status: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE thread_id = ?",
                (status, utc_now(), thread_id),
            )

    def get_cached_result(self, idempotency_key: str) -> ExecutionResult | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, result_json FROM steps WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None or row["status"] not in _FINAL_STATUSES or row["result_json"] is None:
            return None
        result = ExecutionResult.model_validate_json(row["result_json"])
        return result.model_copy(update={"cached_replay": True})

    def prepare_step(self, request: ActionRequest) -> int:
        """Reserve or reuse one step number for an idempotency key."""

        now = utc_now()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT step_number FROM steps WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                return int(existing["step_number"])

            row = connection.execute(
                "SELECT COALESCE(MAX(step_number), 0) + 1 AS next_step FROM steps WHERE thread_id = ?",
                (request.thread_id,),
            ).fetchone()
            step_number = int(row["next_step"])
            connection.execute(
                """
                INSERT INTO steps(
                    thread_id, action_id, idempotency_key, step_number, status,
                    request_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    request.thread_id,
                    request.action_id,
                    request.idempotency_key,
                    step_number,
                    "received",
                    request.model_dump_json(),
                    now,
                    now,
                ),
            )
            return step_number

    def save_result(self, result: ExecutionResult) -> None:
        now = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE steps
                SET status = ?, result_json = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (result.status.value, result.model_dump_json(), now, result.idempotency_key),
            )
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE thread_id = ?",
                (result.status.value, now, result.thread_id),
            )

    def get_or_create_approval(self, request: ActionRequest) -> str:
        seed = f"{request.thread_id}\0{request.action_id}\0{request.idempotency_key}".encode("utf-8")
        approval_id = hashlib.sha256(seed).hexdigest()[:24]
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO approvals(
                    approval_id, thread_id, action_id, idempotency_key,
                    decision, reviewer, created_at, decided_at
                ) VALUES (?, ?, ?, ?, 'pending', NULL, ?, NULL)
                """,
                (
                    approval_id,
                    request.thread_id,
                    request.action_id,
                    request.idempotency_key,
                    utc_now(),
                ),
            )
        return approval_id

    def approval_is_valid(self, approval_id: str | None, request: ActionRequest) -> bool:
        if approval_id is None:
            return False
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT decision, thread_id, action_id, idempotency_key
                FROM approvals WHERE approval_id = ?
                """,
                (approval_id,),
            ).fetchone()
        return bool(
            row
            and row["decision"] == "approved"
            and row["thread_id"] == request.thread_id
            and row["action_id"] == request.action_id
            and row["idempotency_key"] == request.idempotency_key
        )

    def decide_approval(self, approval_id: str, *, decision: str, reviewer: str) -> None:
        if decision not in {"approved", "denied"}:
            raise ApprovalError("decision must be approved or denied")
        if not reviewer.strip():
            raise ApprovalError("reviewer is required")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE approvals
                SET decision = ?, reviewer = ?, decided_at = ?
                WHERE approval_id = ? AND decision = 'pending'
                """,
                (decision, reviewer.strip(), utc_now(), approval_id),
            )
            if cursor.rowcount != 1:
                raise ApprovalError("approval does not exist or is already decided")

    def append_event(
        self,
        *,
        trace_id: str,
        thread_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO events(trace_id, thread_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    thread_id,
                    event_type,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    utc_now(),
                ),
            )

    def list_events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT trace_id, event_type, payload_json, created_at FROM events WHERE thread_id = ? ORDER BY id",
                (thread_id,),
            ).fetchall()
        return [
            {
                "trace_id": row["trace_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_resume_position(self, thread_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(step_number), 0) + 1 AS next_step
                FROM steps
                WHERE thread_id = ? AND status IN ('succeeded', 'rolled_back', 'blocked', 'failed')
                """,
                (thread_id,),
            ).fetchone()
        return int(row["next_step"])
