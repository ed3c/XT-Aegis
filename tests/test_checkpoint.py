from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.errors import ApprovalError, CheckpointSchemaError, IdempotencyConflictError
from xt_aegis.identity import RequestIdentity
from xt_aegis.models import (
    ActionRequest,
    ExecutionResult,
    ExecutionStatus,
    FileWriteAction,
    Provenance,
)


def _request(*, key: str = "approval-idempotency-0001", content: str = "pass\n") -> ActionRequest:
    return ActionRequest(
        thread_id="thread.approval.1",
        action_id="action.approval",
        idempotency_key=key,
        actor_id="user:alice",
        provenance=Provenance.OPERATOR,
        action=FileWriteAction(relative_path="sample/app.py", content=content),
    )


def test_approval_is_digest_bound_and_can_be_claimed_once(tmp_path: Path, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    store = CheckpointStore(tmp_path / "state.db")
    request = _request()
    identity = RequestIdentity.from_request(request, skill=compiled_skill)
    store.start_run(request.thread_id, "safe_demo")
    approval_id = store.get_or_create_approval(request, identity)
    assert not store.approval_is_valid(approval_id, request, identity)
    store.decide_approval(approval_id, decision="approved", reviewer="alice")
    assert store.approval_is_valid(approval_id, request, identity)
    assert store.claim_approval(approval_id, request, identity)
    assert not store.claim_approval(approval_id, request, identity)
    assert store.approval_state(approval_id, request, identity) == "consumed"
    replacement_id = store.get_or_create_approval(request, identity)
    assert replacement_id != approval_id
    assert store.approval_state(replacement_id, request, identity) == "pending"
    with pytest.raises(ApprovalError, match="already decided"):
        store.decide_approval(approval_id, decision="denied", reviewer="bob")


def test_idempotency_key_reuse_with_changed_request_is_rejected(
    tmp_path: Path,
    compiled_skill,
) -> None:  # type: ignore[no-untyped-def]
    store = CheckpointStore(tmp_path / "state.db")
    original = _request()
    changed = _request(content="changed\n")
    original_identity = RequestIdentity.from_request(original, skill=compiled_skill)
    changed_identity = RequestIdentity.from_request(changed, skill=compiled_skill)
    store.start_run(original.thread_id, "safe_demo")
    store.prepare_step(original, original_identity)
    with pytest.raises(IdempotencyConflictError, match="different canonical request"):
        store.prepare_step(changed, changed_identity)


def test_legacy_idempotency_records_fail_closed(tmp_path: Path, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE runs (
                thread_id TEXT PRIMARY KEY,
                skill_name TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE steps (
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
                UNIQUE(thread_id, step_number)
            );
            CREATE TABLE approvals (
                approval_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                UNIQUE(thread_id, action_id, idempotency_key)
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO runs VALUES ('thread.approval.1', 'safe_demo', 'running', 'now', 'now');
            INSERT INTO steps(
                thread_id, action_id, idempotency_key, step_number, status,
                request_json, result_json, created_at, updated_at
            ) VALUES (
                'thread.approval.1', 'action.approval', 'approval-idempotency-0001', 1,
                'received', '{}', NULL, 'now', 'now'
            );
            INSERT INTO approvals(
                approval_id, thread_id, action_id, idempotency_key, decision,
                reviewer, created_at, decided_at
            ) VALUES (
                'aaaaaaaaaaaaaaaaaaaaaaaa', 'thread.approval.1', 'action.approval',
                'approval-idempotency-0001', 'approved', 'alice', 'now', 'now'
            );
            """
        )
    store = CheckpointStore(database_path)
    request = _request()
    identity = RequestIdentity.from_request(request, skill=compiled_skill)
    with pytest.raises(IdempotencyConflictError, match="legacy idempotency record"):
        store.get_cached_result(request.idempotency_key, identity)
    assert store.approval_state("a" * 24, request, identity) == "mismatch"
    assert not store.approval_is_valid("a" * 24, request, identity)


def test_events_are_returned_in_order(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "state.db")
    store.append_event(trace_id="a", thread_id="thread.events", event_type="first", payload={"n": 1})
    store.append_event(trace_id="b", thread_id="thread.events", event_type="second", payload={"n": 2})
    events = store.list_events("thread.events")
    assert [event["event_type"] for event in events] == ["first", "second"]


def test_exact_idempotent_result_replays_after_store_restart(
    tmp_path: Path,
    compiled_skill,
) -> None:  # type: ignore[no-untyped-def]
    database_path = tmp_path / "state.db"
    request = _request(key="restart-idempotency-0001")
    identity = RequestIdentity.from_request(request, skill=compiled_skill)
    store = CheckpointStore(database_path)
    store.start_run(request.thread_id, "safe_demo")
    step_number = store.prepare_step(request, identity)
    result = ExecutionResult(
        thread_id=request.thread_id,
        action_id=request.action_id,
        idempotency_key=request.idempotency_key,
        step_number=step_number,
        status=ExecutionStatus.SUCCEEDED,
        success=True,
        workspace_before_sha256="a" * 64,
        workspace_after_sha256="b" * 64,
        request_digest_version=identity.version,
        request_digest=identity.digest,
        policy_digest=identity.policy_digest,
        started_at="2026-08-11T00:00:00+00:00",
        finished_at="2026-08-11T00:00:01+00:00",
    )
    store.save_result(result)

    reopened = CheckpointStore(database_path)
    cached = reopened.get_cached_result(request.idempotency_key, identity)
    assert cached is not None
    assert cached.cached_replay is True
    assert cached.request_digest == identity.digest


def test_future_checkpoint_schema_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "future.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '999')")
    with pytest.raises(CheckpointSchemaError, match="unsupported checkpoint schema version: 999"):
        CheckpointStore(database_path)
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert tables == {"metadata"}
