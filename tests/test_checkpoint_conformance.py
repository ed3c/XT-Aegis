from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.checkpoint_backend import CheckpointBackend
from xt_aegis.checkpoint_postgres import PostgresCheckpointStore
from xt_aegis.errors import ApprovalError, IdempotencyConflictError, StateVersionConflict
from xt_aegis.identity import RequestIdentity
from xt_aegis.migrations import MIGRATIONS
from xt_aegis.models import (
    ActionRequest,
    ExecutionResult,
    ExecutionStatus,
    FileWriteAction,
    Provenance,
)

POSTGRES_DSN = os.getenv("XT_AEGIS_TEST_POSTGRES_DSN", "")
THREAD = "thread.conformance.001"


def _postgres_available() -> bool:
    if not POSTGRES_DSN:
        return False
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=3) as connection:
            connection.execute("SELECT 1")
    except Exception:
        return False
    return True


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[CheckpointBackend]:
    """One suite, both backends. PostgreSQL skips with a stated reason when no server is reachable."""

    if request.param == "sqlite":
        yield CheckpointStore(tmp_path / "state" / "checkpoints.db")
        return
    if not _postgres_available():
        pytest.skip("set XT_AEGIS_TEST_POSTGRES_DSN to a reachable PostgreSQL and install the postgres extra")
    import psycopg

    store = PostgresCheckpointStore(POSTGRES_DSN)
    with psycopg.connect(POSTGRES_DSN) as connection:
        for table in ("events", "approvals", "steps", "runs"):
            connection.execute(f"DELETE FROM {table}")
    yield store
    with psycopg.connect(POSTGRES_DSN) as connection:
        for table in ("events", "approvals", "steps", "runs"):
            connection.execute(f"DELETE FROM {table}")


def _request(
    *,
    key: str = "conformance-key-0001",
    action_id: str = "conformance.action",
    content: str = "VALUE = 1\n",
    actor_id: str | None = "user:test",
) -> ActionRequest:
    return ActionRequest(
        thread_id=THREAD,
        action_id=action_id,
        idempotency_key=key,
        actor_id=actor_id,
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="app.py", content=content),
    )


def _identity(request: ActionRequest, compiled_skill: object) -> RequestIdentity:
    return RequestIdentity.from_request(request, skill=compiled_skill)  # type: ignore[arg-type]


def _result(request: ActionRequest, identity: RequestIdentity, step_number: int) -> ExecutionResult:
    return ExecutionResult(
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
        started_at="2026-08-14T00:00:00+00:00",
        finished_at="2026-08-14T00:00:01+00:00",
    )


def test_a_run_and_step_are_reserved_once(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    request = _request()
    identity = _identity(request, compiled_skill)
    backend.start_run(THREAD, "safe_refactor")
    backend.start_run(THREAD, "safe_refactor")

    first = backend.prepare_step(request, identity)
    second = backend.prepare_step(request, identity)

    assert first == 1
    assert second == 1


def test_step_numbers_advance_per_thread(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    first = _request(key="conformance-key-0001")
    second = _request(key="conformance-key-0002", action_id="conformance.second")

    assert backend.prepare_step(first, _identity(first, compiled_skill)) == 1
    assert backend.prepare_step(second, _identity(second, compiled_skill)) == 2


def test_a_changed_payload_under_a_used_key_is_a_conflict(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    original = _request()
    backend.prepare_step(original, _identity(original, compiled_skill))
    substituted = _request(content="VALUE = 999\n")

    with pytest.raises(IdempotencyConflictError):
        backend.prepare_step(substituted, _identity(substituted, compiled_skill))


def test_a_terminal_result_round_trips_as_a_cached_replay(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    step_number = backend.prepare_step(request, identity)
    assert backend.get_cached_result(request.idempotency_key, identity) is None

    backend.save_result(_result(request, identity, step_number))
    cached = backend.get_cached_result(request.idempotency_key, identity)

    assert cached is not None
    assert cached.cached_replay is True
    assert cached.step_number == step_number
    assert cached.status is ExecutionStatus.SUCCEEDED


def test_a_result_with_a_foreign_identity_is_refused(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    step_number = backend.prepare_step(request, identity)
    foreign = _result(request, identity, step_number).model_copy(update={"request_digest": "f" * 64})

    with pytest.raises(IdempotencyConflictError):
        backend.save_result(foreign)


def test_a_result_without_an_identity_is_refused(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    step_number = backend.prepare_step(request, identity)
    unbound = _result(request, identity, step_number).model_copy(update={"request_digest": None})

    with pytest.raises(IdempotencyConflictError):
        backend.save_result(unbound)


def test_a_cached_result_lookup_with_a_different_identity_conflicts(  # type: ignore[no-untyped-def]
    backend: CheckpointBackend, compiled_skill
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    backend.prepare_step(request, _identity(request, compiled_skill))
    substituted = _request(content="VALUE = 42\n")

    with pytest.raises(IdempotencyConflictError):
        backend.get_cached_result(request.idempotency_key, _identity(substituted, compiled_skill))


def test_the_resume_position_advances_only_past_terminal_steps(  # type: ignore[no-untyped-def]
    backend: CheckpointBackend, compiled_skill
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    step_number = backend.prepare_step(request, identity)

    assert backend.get_resume_position(THREAD) == 1

    backend.save_result(_result(request, identity, step_number))

    assert backend.get_resume_position(THREAD) == 2


def test_the_approval_state_machine_agrees(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)

    assert backend.approval_state(None, request, identity) == "missing"
    assert backend.approval_state("absent-id", request, identity) == "missing"

    approval_id = backend.get_or_create_approval(request, identity)
    assert backend.approval_state(approval_id, request, identity) == "pending"
    assert backend.approval_is_valid(approval_id, request, identity) is False

    backend.decide_approval(approval_id, decision="approved", reviewer="reviewer")
    assert backend.approval_state(approval_id, request, identity) == "approved"
    assert backend.approval_is_valid(approval_id, request, identity) is True

    assert backend.claim_approval(approval_id, request, identity) is True
    assert backend.approval_state(approval_id, request, identity) == "consumed"
    assert backend.claim_approval(approval_id, request, identity) is False


def test_a_pending_approval_is_reused(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)

    first = backend.get_or_create_approval(request, identity)
    second = backend.get_or_create_approval(request, identity)

    assert first == second


def test_an_expired_approval_is_replaced_and_reported_expired(  # type: ignore[no-untyped-def]
    backend: CheckpointBackend, compiled_skill
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    approval_id = backend.get_or_create_approval(request, identity, ttl_seconds=1)
    time.sleep(1.2)

    assert backend.approval_state(approval_id, request, identity) == "expired"
    replacement = backend.get_or_create_approval(request, identity)
    assert replacement != approval_id
    assert backend.approval_state(replacement, request, identity) == "pending"


def test_an_approval_bound_to_another_request_is_a_mismatch(  # type: ignore[no-untyped-def]
    backend: CheckpointBackend, compiled_skill
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    approval_id = backend.get_or_create_approval(request, identity)
    other = _request(key="conformance-key-0009", action_id="conformance.other")

    assert backend.approval_state(approval_id, other, _identity(other, compiled_skill)) == "mismatch"
    assert backend.claim_approval(approval_id, other, _identity(other, compiled_skill)) is False


def test_creating_an_approval_for_a_changed_request_is_refused(  # type: ignore[no-untyped-def]
    backend: CheckpointBackend, compiled_skill
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    backend.get_or_create_approval(request, _identity(request, compiled_skill))
    substituted = _request(content="VALUE = 7\n")

    with pytest.raises(ApprovalError):
        backend.get_or_create_approval(substituted, _identity(substituted, compiled_skill))


def test_a_decision_requires_a_pending_approval_and_a_reviewer(  # type: ignore[no-untyped-def]
    backend: CheckpointBackend, compiled_skill
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    approval_id = backend.get_or_create_approval(request, identity)

    with pytest.raises(ApprovalError):
        backend.decide_approval(approval_id, decision="maybe", reviewer="reviewer")
    with pytest.raises(ApprovalError):
        backend.decide_approval(approval_id, decision="approved", reviewer="   ")

    backend.decide_approval(approval_id, decision="denied", reviewer="reviewer")
    assert backend.approval_state(approval_id, request, identity) == "denied"

    with pytest.raises(ApprovalError):
        backend.decide_approval(approval_id, decision="approved", reviewer="reviewer")


def test_events_are_appended_and_listed_in_order(backend: CheckpointBackend) -> None:
    backend.start_run(THREAD, "safe_refactor")
    for index in range(3):
        backend.append_event(
            trace_id="trace-1",
            thread_id=THREAD,
            event_type=f"event-{index}",
            payload={"index": index},
        )
    backend.append_event(trace_id="trace-2", thread_id="other.thread", event_type="elsewhere", payload={})

    events = backend.list_events(THREAD)

    assert [event["event_type"] for event in events] == ["event-0", "event-1", "event-2"]
    assert [event["payload"]["index"] for event in events] == [0, 1, 2]
    assert all(event["trace_id"] == "trace-1" for event in events)


def test_run_status_can_be_updated(backend: CheckpointBackend) -> None:
    backend.start_run(THREAD, "safe_refactor")

    backend.set_run_status(THREAD, "blocked")
    backend.set_run_status(THREAD, "blocked")

    state = backend.run_state(THREAD)
    assert state is not None
    assert state.status == "blocked"


def test_the_run_state_version_increases_on_every_transition(backend: CheckpointBackend) -> None:
    backend.start_run(THREAD, "safe_refactor")
    start = backend.run_state(THREAD)
    assert start is not None

    backend.set_run_status(THREAD, "blocked")
    backend.set_run_status(THREAD, "running")
    end = backend.run_state(THREAD)

    assert end is not None
    assert end.state_version == start.state_version + 2


def test_a_run_transition_from_a_stale_version_is_refused(backend: CheckpointBackend) -> None:
    """The losing writer of a concurrent pair must be told, not silently overwritten."""

    backend.start_run(THREAD, "safe_refactor")
    observed = backend.run_state(THREAD)
    assert observed is not None

    backend.set_run_status(THREAD, "blocked", expected_version=observed.state_version)

    with pytest.raises(StateVersionConflict):
        backend.set_run_status(THREAD, "failed", expected_version=observed.state_version)
    current = backend.run_state(THREAD)
    assert current is not None
    assert current.status == "blocked"


def test_a_transition_on_an_absent_run_is_refused(backend: CheckpointBackend) -> None:
    with pytest.raises(StateVersionConflict):
        backend.set_run_status("thread.does.not.exist", "failed")


def test_a_terminal_result_is_never_overwritten(backend: CheckpointBackend, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    step_number = backend.prepare_step(request, identity)
    backend.save_result(_result(request, identity, step_number))
    written = backend.step_state(request.idempotency_key)
    assert written is not None

    replacement = _result(request, identity, step_number).model_copy(
        update={"status": ExecutionStatus.FAILED, "success": False}
    )
    with pytest.raises(IdempotencyConflictError, match="terminal result"):
        backend.save_result(replacement)

    unchanged = backend.step_state(request.idempotency_key)
    assert unchanged is not None
    assert unchanged.status == ExecutionStatus.SUCCEEDED.value
    assert unchanged.state_version == written.state_version


def test_the_step_state_version_increases_when_a_result_is_written(
    backend: CheckpointBackend,
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    backend.start_run(THREAD, "safe_refactor")
    request = _request()
    identity = _identity(request, compiled_skill)
    step_number = backend.prepare_step(request, identity)
    reserved = backend.step_state(request.idempotency_key)
    assert reserved is not None
    assert reserved.status == "received"

    backend.save_result(_result(request, identity, step_number))

    written = backend.step_state(request.idempotency_key)
    assert written is not None
    assert written.state_version == reserved.state_version + 1


def test_the_migration_history_is_recorded_in_order(backend: CheckpointBackend) -> None:
    history = backend.migration_history()

    assert [entry["version"] for entry in history] == [migration.version for migration in MIGRATIONS]
    assert all(entry["applied_at"] for entry in history)
    assert all(entry["description"] for entry in history)


def test_both_backends_satisfy_the_protocol(backend: CheckpointBackend) -> None:
    for name in (
        "start_run",
        "set_run_status",
        "run_state",
        "step_state",
        "migration_history",
        "get_cached_result",
        "prepare_step",
        "save_result",
        "get_or_create_approval",
        "approval_state",
        "approval_is_valid",
        "claim_approval",
        "decide_approval",
        "append_event",
        "list_events",
        "get_resume_position",
    ):
        assert callable(getattr(backend, name))
