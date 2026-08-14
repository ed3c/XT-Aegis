"""PostgreSQL checkpoint backend with the same semantics as the SQLite store.

"Same semantics" is a claim that only a shared conformance suite can support, which is why this module
exists alongside `tests/test_checkpoint_conformance.py` rather than on its own.

Timestamps are stored as the same ISO-8601 strings the SQLite store writes, and compared the same way. A
`timestamptz` column would be the natural PostgreSQL choice, but it would also make expiry semantics differ
between backends — and a backend that is *nearly* identical is worse than one that is deliberately
identical, because the difference would only surface under an expiry race.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from xt_aegis.checkpoint import utc_now
from xt_aegis.checkpoint_backend import RunState, StepState
from xt_aegis.errors import ApprovalError, IdempotencyConflictError, StateVersionConflict
from xt_aegis.identity import RequestIdentity
from xt_aegis.migrations import SCHEMA_VERSION, apply_migrations, migration_history
from xt_aegis.models import ActionRequest, ExecutionResult

_FINAL_STATUSES = {"succeeded", "rolled_back", "blocked", "failed"}
_FINAL_STATUS_ORDER = tuple(sorted(_FINAL_STATUSES))
_FINAL_STATUS_PLACEHOLDERS = ", ".join("%s" for _ in _FINAL_STATUS_ORDER)
_DEFAULT_APPROVAL_TTL_SECONDS = 900
STATE_SCHEMA_VERSION = str(SCHEMA_VERSION)


def _utc_after(seconds: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


class PostgresCheckpointStore:
    """Durable state in PostgreSQL. ``psycopg`` is an optional extra required only to construct one."""

    def __init__(self, dsn: str) -> None:
        import psycopg  # local import: the driver is an optional extra

        self._psycopg = psycopg
        self.dsn = dsn
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with self._psycopg.connect(self.dsn) as connection:
            yield connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            apply_migrations(connection, dialect="postgres")

    def migration_history(self) -> list[dict[str, Any]]:
        """The ordered record of how this database reached its current schema."""

        with self._connection() as connection:
            return migration_history(connection)

    def start_run(self, thread_id: str, skill_name: str) -> None:
        now = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs(thread_id, skill_name, status, created_at, updated_at)
                VALUES (%s, %s, 'running', %s, %s)
                ON CONFLICT (thread_id) DO NOTHING
                """,
                (thread_id, skill_name, now, now),
            )

    def set_run_status(self, thread_id: str, status: str, *, expected_version: int | None = None) -> None:
        with self._connection() as connection:
            self._set_run_status(connection, thread_id, status, expected_version=expected_version)

    @staticmethod
    def _set_run_status(
        connection: Any,
        thread_id: str,
        status: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        guard = "" if expected_version is None else " AND state_version = %s"
        parameters: tuple[Any, ...] = (status, utc_now(), thread_id)
        if expected_version is not None:
            parameters = (*parameters, expected_version)
        cursor = connection.execute(
            "UPDATE runs SET status = %s, updated_at = %s, state_version = state_version + 1 "
            f"WHERE thread_id = %s{guard}",
            parameters,
        )
        if cursor.rowcount != 1:
            raise StateVersionConflict(
                f"run {thread_id} was not at the expected state version, or does not exist"
            )

    def run_state(self, thread_id: str) -> RunState | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, state_version FROM runs WHERE thread_id = %s",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return RunState(status=str(row[0]), state_version=int(row[1]))

    def step_state(self, idempotency_key: str) -> StepState | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, step_number, state_version FROM steps WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return StepState(status=str(row[0]), step_number=int(row[1]), state_version=int(row[2]))

    @staticmethod
    def _validate_identity(row: tuple[Any, ...], identity: RequestIdentity, step_number: int) -> None:
        stored_version, stored_digest, stored_policy_digest = row
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

    def get_cached_result(self, idempotency_key: str, identity: RequestIdentity) -> ExecutionResult | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT step_number, status, request_digest_version, request_digest,
                       policy_digest, result_json
                FROM steps WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        self._validate_identity((row[2], row[3], row[4]), identity, int(row[0]))
        if row[1] not in _FINAL_STATUSES or row[5] is None:
            return None
        result = ExecutionResult.model_validate_json(row[5])
        return result.model_copy(
            update={
                "cached_replay": True,
                "request_digest_version": identity.version,
                "request_digest": identity.digest,
                "policy_digest": identity.policy_digest,
            }
        )

    def prepare_step(self, request: ActionRequest, identity: RequestIdentity) -> int:
        now = utc_now()
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT step_number, request_digest_version, request_digest, policy_digest
                FROM steps WHERE idempotency_key = %s
                """,
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._validate_identity((existing[1], existing[2], existing[3]), identity, int(existing[0]))
                return int(existing[0])
            row = connection.execute(
                "SELECT COALESCE(MAX(step_number), 0) + 1 FROM steps WHERE thread_id = %s",
                (request.thread_id,),
            ).fetchone()
            step_number = int(row[0])
            connection.execute(
                """
                INSERT INTO steps(
                    thread_id, action_id, idempotency_key, step_number, status,
                    request_json, request_digest_version, request_digest, policy_digest,
                    result_json, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, 'received', %s, %s, %s, %s, NULL, %s, %s)
                """,
                (
                    request.thread_id,
                    request.action_id,
                    request.idempotency_key,
                    step_number,
                    request.model_dump_json(),
                    identity.version,
                    identity.digest,
                    identity.policy_digest,
                    now,
                    now,
                ),
            )
            return step_number

    def save_result(self, result: ExecutionResult) -> None:
        if not result.request_digest or not result.request_digest_version or not result.policy_digest:
            raise IdempotencyConflictError("cannot persist a result without a request-bound identity")
        now = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE steps
                SET status = %s, result_json = %s, updated_at = %s, state_version = state_version + 1
                WHERE idempotency_key = %s
                  AND request_digest_version = %s
                  AND request_digest = %s
                  AND policy_digest = %s
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
    def _save_result_reason(connection: Any, result: ExecutionResult) -> str:
        row = connection.execute(
            "SELECT status FROM steps WHERE idempotency_key = %s",
            (result.idempotency_key,),
        ).fetchone()
        if row is not None and str(row[0]) in _FINAL_STATUSES:
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
                WHERE thread_id = %s AND action_id = %s AND idempotency_key = %s
                """,
                (request.thread_id, request.action_id, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing[1] != request.actor_id
                    or existing[2] != identity.version
                    or existing[3] != identity.digest
                    or existing[4] != identity.policy_digest
                ):
                    raise ApprovalError(
                        "existing approval is bound to a different canonical request or policy"
                    )
                if (
                    existing[5] == "pending"
                    and existing[7] is None
                    and existing[6] is not None
                    and str(existing[6]) > created_at
                ):
                    return str(existing[0])
                approval_id = secrets.token_hex(12)
                connection.execute(
                    """
                    UPDATE approvals
                    SET approval_id = %s, decision = 'pending', reviewer = NULL,
                        created_at = %s, expires_at = %s, decided_at = NULL, consumed_at = NULL
                    WHERE thread_id = %s AND action_id = %s AND idempotency_key = %s
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
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NULL, %s, %s, NULL, NULL)
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
        self, approval_id: str | None, request: ActionRequest, identity: RequestIdentity
    ) -> bool:
        return self.approval_state(approval_id, request, identity) == "approved"

    def approval_state(
        self, approval_id: str | None, request: ActionRequest, identity: RequestIdentity
    ) -> str:
        if approval_id is None:
            return "missing"
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT decision, thread_id, action_id, idempotency_key, actor_id,
                       request_digest_version, request_digest, policy_digest,
                       expires_at, consumed_at
                FROM approvals WHERE approval_id = %s
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return "missing"
        if (
            row[1] != request.thread_id
            or row[2] != request.action_id
            or row[3] != request.idempotency_key
            or row[4] != request.actor_id
            or row[5] != identity.version
            or row[6] != identity.digest
            or row[7] != identity.policy_digest
        ):
            return "mismatch"
        if row[8] is None or str(row[8]) <= utc_now():
            return "expired"
        if row[9] is not None:
            return "consumed"
        return str(row[0])

    def claim_approval(
        self, approval_id: str | None, request: ActionRequest, identity: RequestIdentity
    ) -> bool:
        if approval_id is None:
            return False
        now = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE approvals
                SET consumed_at = %s
                WHERE approval_id = %s
                  AND decision = 'approved'
                  AND consumed_at IS NULL
                  AND expires_at > %s
                  AND thread_id = %s
                  AND action_id = %s
                  AND idempotency_key = %s
                  AND actor_id IS NOT DISTINCT FROM %s
                  AND request_digest_version = %s
                  AND request_digest = %s
                  AND policy_digest = %s
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
            return bool(cursor.rowcount == 1)

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
                SET decision = %s, reviewer = %s, decided_at = %s
                WHERE approval_id = %s AND decision = 'pending' AND expires_at > %s
                """,
                (decision, reviewer.strip(), now, approval_id, now),
            )
            if cursor.rowcount != 1:
                raise ApprovalError("approval does not exist, is expired, or is already decided")

    def append_event(
        self, *, trace_id: str, thread_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO events(trace_id, thread_id, event_type, payload_json, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (trace_id, thread_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
            )

    def list_events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT trace_id, thread_id, event_type, payload_json, created_at
                FROM events WHERE thread_id = %s ORDER BY id
                """,
                (thread_id,),
            ).fetchall()
        return [
            {
                "trace_id": row[0],
                "thread_id": row[1],
                "event_type": row[2],
                "payload": json.loads(row[3]),
                "created_at": row[4],
            }
            for row in rows
        ]

    def get_resume_position(self, thread_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(step_number), 0) + 1
                FROM steps
                WHERE thread_id = %s AND status IN ('succeeded', 'rolled_back', 'blocked', 'failed')
                """,
                (thread_id,),
            ).fetchone()
        return int(row[0])
