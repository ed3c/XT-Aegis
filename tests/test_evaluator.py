from __future__ import annotations

from xt_aegis.evaluator import evaluate_trajectory
from xt_aegis.models import ExecutionResult, ExecutionStatus


def _result(status: ExecutionStatus, *, rollback_integrity=None, reasons=None):
    return ExecutionResult(
        thread_id="thread.eval",
        action_id=status.value,
        idempotency_key=f"idempotency-{status.value}-0001",
        step_number=1,
        status=status,
        success=status == ExecutionStatus.SUCCEEDED,
        policy_reasons=reasons or [],
        rolled_back=status == ExecutionStatus.ROLLED_BACK,
        rollback_integrity=rollback_integrity,
        workspace_before_sha256="a" * 64,
        workspace_after_sha256="a" * 64,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )


def test_evaluator_scores_recovery_and_injection_block() -> None:
    score = evaluate_trajectory(
        [
            _result(ExecutionStatus.ROLLED_BACK, rollback_integrity=True),
            _result(ExecutionStatus.SUCCEEDED),
            _result(
                ExecutionStatus.BLOCKED,
                reasons=["external or retrieved content cannot directly invoke executable tools"],
            ),
        ]
    )
    assert score.outcome_score == 1.0
    assert score.safety_score == 1.0
    assert score.efficiency_score == 0.75
    assert score.blocked_injection_attempts == 1


def test_empty_evaluation_is_zero() -> None:
    score = evaluate_trajectory([])
    assert score.outcome_score == 0.0
    assert score.safety_score == 1.0
    assert score.efficiency_score == 0.0
