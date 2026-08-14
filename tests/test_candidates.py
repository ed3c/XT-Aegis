from __future__ import annotations

import pytest

from xt_aegis.candidates import (
    CandidateBudget,
    CandidateOutcome,
    DisqualificationReason,
    admit_candidate,
    select_candidate,
)
from xt_aegis.models import ExecutionStatus

BASELINE = "a" * 64
DRIFTED = "b" * 64


def _outcome(index: int, digest_prefix: str, **overrides: object) -> CandidateOutcome:
    values: dict[str, object] = {
        "index": index,
        "proposal_sha256": digest_prefix * 64,
        "workspace_before_sha256": BASELINE,
        "workspace_after_sha256": "c" * 64,
        "status": ExecutionStatus.SUCCEEDED,
        "success": True,
        "assertions_passed": True,
        "rollback_integrity": None,
        "isolation_verdict": True,
    }
    values.update(overrides)
    return CandidateOutcome(**values)  # type: ignore[arg-type]


def test_a_single_passing_candidate_is_selected() -> None:
    selection = select_candidate([_outcome(0, "1")], baseline_sha256=BASELINE)

    assert selection.selected_index == 0
    assert selection.eligible_indexes == [0]
    assert "selected candidate #0" in selection.diagnostic


def test_baseline_drift_disqualifies_even_a_passing_candidate() -> None:
    selection = select_candidate(
        [_outcome(0, "1", workspace_before_sha256=DRIFTED), _outcome(1, "2")],
        baseline_sha256=BASELINE,
    )

    assert selection.selected_index == 1
    drifted = next(verdict for verdict in selection.verdicts if verdict.index == 0)
    assert drifted.eligible is False
    assert drifted.reason is DisqualificationReason.BASELINE_DRIFT


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"assertions_passed": False}, DisqualificationReason.ASSERTIONS_FAILED),
        ({"status": ExecutionStatus.BLOCKED, "success": False}, DisqualificationReason.NOT_SUCCESSFUL),
        ({"status": ExecutionStatus.SUSPENDED, "success": False}, DisqualificationReason.NOT_SUCCESSFUL),
        ({"status": ExecutionStatus.ROLLED_BACK, "success": False}, DisqualificationReason.NOT_SUCCESSFUL),
        ({"rollback_integrity": False}, DisqualificationReason.ROLLBACK_UNVERIFIED),
    ],
    ids=lambda value: str(value),
)
def test_an_untrustworthy_candidate_is_disqualified_with_a_named_reason(
    overrides: dict[str, object], reason: DisqualificationReason
) -> None:
    selection = select_candidate([_outcome(0, "1", **overrides)], baseline_sha256=BASELINE)

    assert selection.selected_index is None
    assert selection.verdicts[0].reason is reason


def test_required_isolation_disqualifies_a_candidate_that_did_not_report_it() -> None:
    selection = select_candidate(
        [_outcome(0, "1", isolation_verdict=False), _outcome(1, "2", isolation_verdict=None)],
        baseline_sha256=BASELINE,
        require_isolation=True,
    )

    assert selection.selected_index is None
    assert {verdict.reason for verdict in selection.verdicts} == {
        DisqualificationReason.ISOLATION_NOT_ESTABLISHED
    }


def test_isolation_is_not_required_by_default() -> None:
    selection = select_candidate([_outcome(0, "1", isolation_verdict=None)], baseline_sha256=BASELINE)

    assert selection.selected_index == 0


def test_a_tie_is_broken_by_proposal_digest_and_is_order_independent() -> None:
    candidates = [_outcome(0, "9"), _outcome(1, "3"), _outcome(2, "5")]

    forward = select_candidate(candidates, baseline_sha256=BASELINE)
    reversed_input = select_candidate(list(reversed(candidates)), baseline_sha256=BASELINE)

    assert forward.selected_index == 1
    assert reversed_input.selected_index == 1
    assert forward.selected_proposal_sha256 == "3" * 64
    assert [verdict.index for verdict in reversed_input.verdicts] == [0, 1, 2]


def test_selection_is_reproducible_over_the_same_input() -> None:
    candidates = [_outcome(0, "4"), _outcome(1, "2"), _outcome(2, "8")]

    first = select_candidate(candidates, baseline_sha256=BASELINE)
    second = select_candidate(candidates, baseline_sha256=BASELINE)

    assert first == second


def test_no_adoptable_candidate_names_every_rejection() -> None:
    selection = select_candidate(
        [
            _outcome(0, "1", assertions_passed=False),
            _outcome(1, "2", workspace_before_sha256=DRIFTED),
        ],
        baseline_sha256=BASELINE,
    )

    assert selection.selected_index is None
    assert selection.eligible_indexes == []
    assert "assertions_failed" in selection.diagnostic
    assert "baseline_drift" in selection.diagnostic


def test_an_empty_candidate_set_is_reported_rather_than_selected() -> None:
    selection = select_candidate([], baseline_sha256=BASELINE)

    assert selection.selected_index is None
    assert selection.verdicts == []
    assert "no candidate was adoptable out of 0" in selection.diagnostic


def _budget(**overrides: object) -> CandidateBudget:
    values: dict[str, object] = {
        "max_candidates": 3,
        "max_prompt_tokens": 100,
        "max_completion_tokens": 100,
        "reserve_prompt_tokens": 10,
        "reserve_completion_tokens": 10,
    }
    values.update(overrides)
    return CandidateBudget(**values)  # type: ignore[arg-type]


def test_a_candidate_that_fits_the_remaining_budget_is_admitted() -> None:
    assert admit_candidate(_budget(), started=1, total_prompt_tokens=50, total_completion_tokens=50) is None


def test_the_candidate_count_is_a_ceiling() -> None:
    reason = admit_candidate(_budget(), started=3, total_prompt_tokens=0, total_completion_tokens=0)

    assert reason is not None
    assert "candidate budget exhausted" in reason


@pytest.mark.parametrize(
    ("prompt", "completion", "fragment"),
    [
        (95, 0, "prompt token budget cannot cover another candidate"),
        (0, 95, "completion token budget cannot cover another candidate"),
    ],
)
def test_a_candidate_that_does_not_fit_the_token_budget_is_refused(
    prompt: int, completion: int, fragment: str
) -> None:
    reason = admit_candidate(
        _budget(), started=1, total_prompt_tokens=prompt, total_completion_tokens=completion
    )

    assert reason is not None
    assert fragment in reason


def test_the_selection_rule_touches_no_filesystem_and_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule that executed anything could not be trusted to be reproducible from a record alone."""

    import builtins
    import subprocess

    def refuse_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("the selection rule must not open a file")

    def refuse_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("the selection rule must not run a process")

    monkeypatch.setattr(builtins, "open", refuse_open)
    monkeypatch.setattr(subprocess, "run", refuse_run)
    monkeypatch.setattr(subprocess, "Popen", refuse_run)

    selection = select_candidate([_outcome(0, "1"), _outcome(1, "2")], baseline_sha256=BASELINE)
    admit_candidate(_budget(), started=0, total_prompt_tokens=0, total_completion_tokens=0)

    assert selection.selected_index == 0
