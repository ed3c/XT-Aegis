from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from crash_child import CRASH_EXIT_CODE, GOOD_CODE, build_runner
from xt_aegis.lifecycle import (
    CancellationToken,
    DeadlineExceeded,
    ExecutionCancelled,
    Transition,
)
from xt_aegis.models import (
    ActionRequest,
    ExecutionReasonCode,
    ExecutionStatus,
    FileWriteAction,
    Provenance,
)
from xt_aegis.workspace import IsolatedWorkspace

CHILD = Path(__file__).resolve().parent / "crash_child.py"
ORIGINAL_CODE = "VALUE = 1\n"

#: Transitions the child can be killed at, with the state a restart must reach. "clean" means the workspace
#: still matches its pre-run content; "terminal" means a terminal step row already exists.
CRASH_TRANSITIONS: tuple[tuple[Transition, str], ...] = (
    (Transition.REQUEST_RECEIVED, "clean"),
    (Transition.POLICY_EVALUATED, "clean"),
    (Transition.STEP_PREPARED, "clean"),
    (Transition.SNAPSHOT_CREATED, "clean"),
    (Transition.PRECONDITION_CHECKED, "clean"),
    (Transition.ACTION_STARTED, "clean"),
    (Transition.ACTION_COMPLETED, "mutated"),
    (Transition.POSTCONDITION_CHECKED, "mutated"),
    (Transition.RESULT_SAVED, "terminal"),
)


def _prepare(tmp_path: Path) -> Path:
    """Create an owned workspace and the files the child fixture expects."""

    run_root = tmp_path / "run"
    template = tmp_path / "template"
    template.mkdir(parents=True)
    (template / "app.py").write_text(ORIGINAL_CODE, encoding="utf-8")
    (template / "check.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    run_root.mkdir(parents=True)
    workspace = IsolatedWorkspace.from_template(template, run_root=run_root / "workspace")
    (run_root / "ownership.txt").write_text(workspace.ownership_token, encoding="utf-8")
    return run_root


def _run_child(run_root: Path, crash_at: str, action_id: str, key: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHILD), str(run_root), crash_at, action_id, key],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _workspace_content(run_root: Path) -> str:
    return (run_root / "workspace" / "workspace" / "app.py").read_text(encoding="utf-8")


@pytest.mark.parametrize(("transition", "expected_state"), CRASH_TRANSITIONS, ids=lambda value: str(value))
def test_kill_at_every_transition_reaches_a_documented_state(
    tmp_path: Path, transition: Transition, expected_state: str
) -> None:
    run_root = _prepare(tmp_path)

    killed = _run_child(run_root, transition.value, "crash.patch", "crash-recovery-0001")

    assert killed.returncode == CRASH_EXIT_CODE, killed.stderr
    assert (run_root / "crashed_at.txt").read_text(encoding="utf-8") == transition.value

    # Restart against the same database and run directory.
    runner = build_runner(run_root, None)
    resume_position = runner.store.get_resume_position("thread.crash.001")

    if expected_state == "terminal":
        assert resume_position == 2
    else:
        assert resume_position == 1
        assert _workspace_content(run_root) in {ORIGINAL_CODE, GOOD_CODE}

    replay = runner.execute(
        ActionRequest(
            thread_id="thread.crash.001",
            action_id="crash.patch",
            idempotency_key="crash-recovery-0001",
            actor_id="user:test",
            provenance=Provenance.AGENT_PROPOSAL,
            action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
        ),
        timeout_seconds=30.0,
    )

    assert replay.status == ExecutionStatus.SUCCEEDED
    assert _workspace_content(run_root) == GOOD_CODE
    if expected_state == "terminal":
        assert replay.cached_replay is True
        assert replay.step_number == 1
    else:
        assert replay.cached_replay is False


def test_a_completed_protected_action_is_not_repeated_after_a_crash(tmp_path: Path) -> None:
    run_root = _prepare(tmp_path)

    completed = _run_child(run_root, "none", "crash.patch", "crash-recovery-0002")
    assert completed.returncode == 0, completed.stderr
    first = json.loads(completed.stdout)

    killed = _run_child(run_root, Transition.REQUEST_RECEIVED.value, "crash.patch", "crash-recovery-0002")
    assert killed.returncode == CRASH_EXIT_CODE

    runner = build_runner(run_root, None)
    replay = runner.execute(
        ActionRequest(
            thread_id="thread.crash.001",
            action_id="crash.patch",
            idempotency_key="crash-recovery-0002",
            actor_id="user:test",
            provenance=Provenance.AGENT_PROPOSAL,
            action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
        ),
        timeout_seconds=30.0,
    )

    assert replay.cached_replay is True
    assert replay.step_number == first["step_number"]
    assert runner.store.get_resume_position("thread.crash.001") == first["step_number"] + 1


def test_cancellation_before_execution_fails_closed_without_mutation(tmp_path: Path) -> None:
    run_root = _prepare(tmp_path)
    runner = build_runner(run_root, None)
    token = CancellationToken()
    token.cancel()

    result = runner.execute(
        ActionRequest(
            thread_id="thread.crash.001",
            action_id="cancelled.patch",
            idempotency_key="crash-cancel-0001",
            actor_id="user:test",
            provenance=Provenance.AGENT_PROPOSAL,
            action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
        ),
        cancellation=token,
    )

    assert result.success is False
    assert result.reason_code == ExecutionReasonCode.CANCELLED
    assert _workspace_content(run_root) == ORIGINAL_CODE


def test_cancellation_after_the_snapshot_rolls_back_the_workspace(tmp_path: Path) -> None:
    run_root = _prepare(tmp_path)
    token = CancellationToken()

    def cancel_after_snapshot(transition: Transition) -> None:
        if transition == Transition.SNAPSHOT_CREATED:
            token.cancel()

    runner = build_runner(run_root, None)
    runner.fault_hook = cancel_after_snapshot

    result = runner.execute(
        ActionRequest(
            thread_id="thread.crash.001",
            action_id="cancelled.midway",
            idempotency_key="crash-cancel-0002",
            actor_id="user:test",
            provenance=Provenance.AGENT_PROPOSAL,
            action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
        ),
        cancellation=token,
    )

    assert result.status == ExecutionStatus.ROLLED_BACK
    assert result.reason_code == ExecutionReasonCode.CANCELLED
    assert result.rollback_integrity is True
    assert _workspace_content(run_root) == ORIGINAL_CODE


def test_an_expired_deadline_is_typed_and_distinct_from_cancellation(tmp_path: Path) -> None:
    run_root = _prepare(tmp_path)
    runner = build_runner(run_root, None)
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    token = CancellationToken.with_timeout(1.0, clock=lambda: next(ticks))

    result = runner.execute(
        ActionRequest(
            thread_id="thread.crash.001",
            action_id="expired.patch",
            idempotency_key="crash-deadline-0001",
            actor_id="user:test",
            provenance=Provenance.AGENT_PROPOSAL,
            action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
        ),
        cancellation=token,
    )

    assert result.success is False
    assert result.reason_code == ExecutionReasonCode.DEADLINE_EXCEEDED
    assert _workspace_content(run_root) == ORIGINAL_CODE


def test_a_cancelled_request_is_not_executable_after_restart_without_a_new_request(
    tmp_path: Path,
) -> None:
    run_root = _prepare(tmp_path)
    runner = build_runner(run_root, None)
    token = CancellationToken()
    token.cancel()
    request = ActionRequest(
        thread_id="thread.crash.001",
        action_id="cancelled.persisted",
        idempotency_key="crash-cancel-0003",
        actor_id="user:test",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
    )

    cancelled = runner.execute(request, cancellation=token)
    assert cancelled.reason_code == ExecutionReasonCode.CANCELLED

    restarted = build_runner(run_root, None)
    replayed = restarted.execute(request)

    assert replayed.cached_replay is True
    assert replayed.success is False
    assert replayed.reason_code == ExecutionReasonCode.CANCELLED
    assert _workspace_content(run_root) == ORIGINAL_CODE


def test_cancellation_wins_over_an_expired_deadline() -> None:
    token = CancellationToken.with_timeout(-1.0)
    token.cancel()

    with pytest.raises(ExecutionCancelled):
        token.raise_if_unavailable()


def test_an_unexpired_token_allows_the_transition() -> None:
    token = CancellationToken.with_timeout(60.0)
    token.raise_if_unavailable()

    expired = CancellationToken.with_timeout(0.0)
    with pytest.raises(DeadlineExceeded):
        expired.raise_if_unavailable()


def test_every_transition_is_covered_by_the_crash_matrix() -> None:
    """A new transition must be added to the matrix, not silently left untested."""

    exercised = {transition for transition, _ in CRASH_TRANSITIONS}
    rollback_only = {Transition.ROLLBACK_STARTED, Transition.ROLLBACK_COMPLETED}
    approval_only = {Transition.APPROVAL_RESOLVED}
    assert exercised | rollback_only | approval_only == set(Transition)
