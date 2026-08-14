"""SQLite-backed checkpoints, idempotency, approvals, and audit events."""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from xt_aegis.checkpoint_backend import RunState, StepState
from xt_aegis.errors import ApprovalError, IdempotencyConflictError, StateVersionConflict
from xt_aegis.identity import RequestIdentity
from xt_aegis.migrations import SCHEMA_VERSION, apply_migrations, migration_history
from xt_aegis.models import ActionRequest, ExecutionResult, ExecutionStatus

_STATE_SCHEMA_VERSION = str(SCHEMA_VERSION)
_DEFAULT_APPROVAL_TTL_SECONDS = 900


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


_FINAL_STATUSES = {
    ExecutionStatus.SUCCEEDED.value,
    ExecutionStatus.ROLLED_BACK.value,
    ExecutionStatus.BLOCKED.value,
    ExecutionStatus.FAILED.value,
}
_FINAL_STATUS_ORDER = tuple(sorted(_FINAL_STATUSES))
_FINAL_STATUS_PLACEHOLDERS = ", ".join("?" for _ in _FINAL_STATUS_ORDER)


class CheckpointStore:
    """Small durable state store with WAL and request-bound idempotency."""

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
            # The ledger owns the schema. `_migrate_legacy_schema` still runs because databases predating
            # the ledger may be missing identity columns that no numbered migration ever added.
            apply_migrations(connection, dialect="sqlite")
            self._migrate_legacy_schema(connection)

    def migration_history(self) -> list[dict[str, Any]]:
        """The ordered record of how this database reached its current schema."""

        with self._connection() as connection:
            return migration_history(connection)

    def _migrate_legacy_schema(self, connection: sqlite3.Connection) -> None:
        self._ensure_column(connection, "steps", "request_digest_version", "TEXT")
        self._ensure_column(connection, "steps", "request_digest", "TEXT")
        self._ensure_column(connection, "steps", "policy_digest", "TEXT")
        self._ensure_column(connection, "approvals", "actor_id", "TEXT")
        self._ensure_column(connection, "approvals", "request_digest_version", "TEXT")
        self._ensure_column(connection, "approvals", "request_digest", "TEXT")
        self._ensure_column(connection, "approvals", "policy_digest", "TEXT")
        self._ensure_column(connection, "approvals", "expires_at", "TEXT")
        self._ensure_column(connection, "approvals", "consumed_at", "TEXT")

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {str(row["name"]) for row in rows}:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

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

    def set_run_status(self, thread_id: str, status: str, *, expected_version: int | None = None) -> None:
        with self._connection() as connection:
            self._set_run_status(connection, thread_id, status, expected_version=expected_version)

    @staticmethod
    def _set_run_status(
        connection: sqlite3.Connection,
        thread_id: str,
        status: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        """Compare-and-set the run row, bumping its version so a concurrent writer can tell it lost."""

        guard = "" if expected_version is None else " AND state_version = ?"
        parameters: tuple[Any, ...] = (status, utc_now(), thread_id)
        if expected_version is not None:
            parameters = (*parameters, expected_version)
        cursor = connection.execute(
            "UPDATE runs SET status = ?, updated_at = ?, state_version = state_version + 1 "
            f"WHERE thread_id = ?{guard}",
            parameters,
        )
        if cursor.rowcount != 1:
            raise StateVersionConflict(
                f"run {thread_id} was not at the expected state version, or does not exist"
            )

    def run_state(self, thread_id: str) -> RunState | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, state_version FROM runs WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return RunState(status=str(row["status"]), state_version=int(row["state_version"]))

    def step_state(self, idempotency_key: str) -> StepState | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, step_number, state_version FROM steps WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return StepState(
            status=str(row["status"]),
            step_number=int(row["step_number"]),
            state_version=int(row["state_version"]),
        )

    def get_cached_result(
        self,
        idempotency_key: str,
        identity: RequestIdentity,
    ) -> ExecutionResult | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT step_number, status, request_digest_version, request_digest,
                       policy_digest, result_json
                FROM steps WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        self._validate_identity(row, identity)
        if row["status"] not in _FINAL_STATUSES or row["result_json"] is None:
            return None
        result = ExecutionResult.model_validate_json(row["result_json"])
        return result.model_copy(
            update={
                "cached_replay": True,
                "request_digest_version": identity.version,
                "request_digest": identity.digest,
                "policy_digest": identity.policy_digest,
            }
        )

    def prepare_step(self, request: ActionRequest, identity: RequestIdentity) -> int:
        """Reserve or reuse one step number only for the same canonical request."""

        now = utc_now()
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT step_number, request_digest_version, request_digest, policy_digest
                FROM steps WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._validate_identity(existing, identity)
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
                    request_json, request_digest_version, request_digest, policy_digest,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    request.thread_id,
                    request.action_id,
                    request.idempotency_key,
                    step_number,
                    "received",
                    request.model_dump_json(),
                    identity.version,
                    identity.digest,
                    identity.policy_digest,
                    now,
                    now,
                ),
            )
            return step_number

    @staticmethod
    def _validate_identity(row: sqlite3.Row, identity: RequestIdentity) -> None:
        step_number = int(row["step_number"]) if "step_number" in row else 0
        stored_version = row["request_digest_version"]
        stored_digest = row["request_digest"]
        stored_policy_digest = row["policy_digest"]
        if not stored_version or not stored_digest or not stored_policy_digest:
            raise IdempotencyConflictError(
                "legacy idempotency record is not bound to a canonical request digest",
                step_number=step_number,
            )
        if (
            stored_version != identity.version
            or stored_digest != identity.digest
            or stored_policy_digest != identity.policy_digest
        ):
            raise IdempotencyConflictError(
                "idempotency key is already bound to a different canonical request or policy",
                step_number=step_number,
            )

    def save_result(self, result: ExecutionResult) -> None:
        if not result.request_digest or not result.request_digest_version or not result.policy_digest:
            raise IdempotencyConflictError("cannot persist a result without a request-bound identity")
        now = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE steps
                SET status = ?, result_json = ?, updated_at = ?, state_version = state_version + 1
                WHERE idempotency_key = ?
                  AND request_digest_version = ?
                  AND request_digest = ?
                  AND policy_digest = ?
                  AND status NOT IN ({_FINAL_STATUS_PLACEHOLDERS})
                """,
                (
                    result.status.value,
                    result.model_dump_json(),
                    now,
                    result.idempotency_key,
                    result.request_digest_version,
                    result.request_digest,
                    result.policy_digest,
                    *_FINAL_STATUS_ORDER,
                ),
            )
            if cursor.rowcount != 1:
                raise IdempotencyConflictError(
                    self._save_result_reason(connection, result),
                    step_number=result.step_number,
                )
            self._set_run_status(connection, result.thread_id, result.status.value)

    @staticmethod
    def _save_result_reason(connection: sqlite3.Connection, result: ExecutionResult) -> str:
        """Distinguish "someone else already finished this step" from "this is not your step"."""

        row = connection.execute(
            "SELECT status FROM steps WHERE idempotency_key = ?",
            (result.idempotency_key,),
        ).fetchone()
        if row is not None and str(row["status"]) in _FINAL_STATUSES:
            return "step already holds a terminal result and will not be overwritten"
        return "result identity does not match the reserved idempotency record"

    def get_or_create_approval(
        self,
        request: ActionRequest,
        identity: RequestIdentity,
        *,
        ttl_seconds: int = _DEFAULT_APPROVAL_TTL_SECONDS,
    ) -> str:
        created_at = utc_now()
        expires_at = _utc_after(ttl_seconds)
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT approval_id, actor_id, request_digest_version, request_digest,
                       policy_digest, decision, expires_at, consumed_at
                FROM approvals
                WHERE thread_id = ? AND action_id = ? AND idempotency_key = ?
                """,
                (request.thread_id, request.action_id, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["actor_id"] != request.actor_id
                    or existing["request_digest_version"] != identity.version
                    or existing["request_digest"] != identity.digest
                    or existing["policy_digest"] != identity.policy_digest
                ):
                    raise ApprovalError(
                        "existing approval is bound to a different canonical request or policy"
                    )
                if (
                    existing["decision"] == "pending"
                    and existing["consumed_at"] is None
                    and existing["expires_at"] is not None
                    and str(existing["expires_at"]) > created_at
                ):
                    return str(existing["approval_id"])

                approval_id = secrets.token_hex(12)
                connection.execute(
                    """
                    UPDATE approvals
                    SET approval_id = ?, decision = 'pending', reviewer = NULL,
                        created_at = ?, expires_at = ?, decided_at = NULL, consumed_at = NULL
                    WHERE thread_id = ? AND action_id = ? AND idempotency_key = ?
                    """,
                    (
                        approval_id,
                        created_at,
                        expires_at,
                        request.thread_id,
                        request.action_id,
                        request.idempotency_key,
                    ),
                )
                return approval_id

            approval_id = secrets.token_hex(12)
            connection.execute(
                """
                INSERT INTO approvals(
                    approval_id, thread_id, action_id, idempotency_key, actor_id,
                    request_digest_version, request_digest, policy_digest,
                    decision, reviewer, created_at, expires_at, decided_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, NULL, NULL)
                """,
                (
                    approval_id,
                    request.thread_id,
                    request.action_id,
                    request.idempotency_key,
                    request.actor_id,
                    identity.version,
                    identity.digest,
                    identity.policy_digest,
                    created_at,
                    expires_at,
                ),
            )
            return approval_id

    def approval_is_valid(
        self,
        approval_id: str | None,
        request: ActionRequest,
        identity: RequestIdentity,
    ) -> bool:
        return self.approval_state(approval_id, request, identity) == "approved"

    def approval_state(
        self,
        approval_id: str | None,
        request: ActionRequest,
        identity: RequestIdentity,
    ) -> str:
        if approval_id is None:
            return "missing"
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT decision, thread_id, action_id, idempotency_key, actor_id,
                       request_digest_version, request_digest, policy_digest,
                       expires_at, consumed_at
                FROM approvals WHERE approval_id = ?
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return "missing"
        if (
            row["thread_id"] != request.thread_id
            or row["action_id"] != request.action_id
            or row["idempotency_key"] != request.idempotency_key
            or row["actor_id"] != request.actor_id
            or row["request_digest_version"] != identity.version
            or row["request_digest"] != identity.digest
            or row["policy_digest"] != identity.policy_digest
        ):
            return "mismatch"
        if row["expires_at"] is None or str(row["expires_at"]) <= utc_now():
            return "expired"
        if row["consumed_at"] is not None:
            return "consumed"
        return str(row["decision"])

    def claim_approval(
        self,
        approval_id: str | None,
        request: ActionRequest,
        identity: RequestIdentity,
    ) -> bool:
        if approval_id is None:
            return False
        now = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE approvals
                SET consumed_at = ?
                WHERE approval_id = ?
                  AND decision = 'approved'
                  AND consumed_at IS NULL
                  AND expires_at > ?
                  AND thread_id = ?
                  AND action_id = ?
                  AND idempotency_key = ?
                  AND actor_id IS ?
                  AND request_digest_version = ?
                  AND request_digest = ?
                  AND policy_digest = ?
                """,
                (
                    now,
                    approval_id,
                    now,
                    request.thread_id,
                    request.action_id,
                    request.idempotency_key,
                    request.actor_id,
                    identity.version,
                    identity.digest,
                    identity.policy_digest,
                ),
            )
            return cursor.rowcount == 1

    def decide_approval(self, approval_id: str, *, decision: str, reviewer: str) -> None:
        if decision not in {"approved", "denied"}:
            raise ApprovalError("decision must be approved or denied")
        if not reviewer.strip():
            raise ApprovalError("reviewer is required")
        now = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE approvals
                SET decision = ?, reviewer = ?, decided_at = ?
                WHERE approval_id = ? AND decision = 'pending' AND expires_at > ?
                """,
                (decision, reviewer.strip(), now, approval_id, now),
            )
            if cursor.rowcount != 1:
                raise ApprovalError("approval does not exist, is expired, or is already decided")

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
