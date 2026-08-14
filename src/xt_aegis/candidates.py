"""Deterministic selection over competing candidate executions.

This module decides; it does not execute. Nothing here forks a workspace, runs a command, or touches the
filesystem, which is what makes every disqualification testable from a record alone.

The hard part of comparing candidates is not the comparison. It is everything that must disqualify a
candidate before the comparison happens: a candidate that started from a workspace which had already
drifted observed a different world, so its pass says nothing about the baseline.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.models import ExecutionStatus

BoundedReason = Annotated[str, Field(max_length=240)]


class DisqualificationReason(StrEnum):
    """Why a candidate may not be considered. A candidate carries at most one."""

    BASELINE_DRIFT = "baseline_drift"
    ASSERTIONS_FAILED = "assertions_failed"
    NOT_SUCCESSFUL = "not_successful"
    ROLLBACK_UNVERIFIED = "rollback_unverified"
    ISOLATION_NOT_ESTABLISHED = "isolation_not_established"


class CandidateOutcome(BaseModel):
    """One candidate's execution evidence, already reduced to what a selection may depend on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    workspace_before_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    workspace_after_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: ExecutionStatus
    success: bool
    assertions_passed: bool
    rollback_integrity: bool | None = None
    isolation_verdict: bool | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class CandidateVerdict(BaseModel):
    """One candidate's eligibility, with the reason when it has none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    eligible: bool
    reason: DisqualificationReason | None = None
    detail: BoundedReason = ""


class CandidateSelection(BaseModel):
    """Terminal selection evidence: at most one adopted candidate, and every rejection named."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_index: int | None = None
    selected_proposal_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    verdicts: list[CandidateVerdict] = Field(default_factory=list, max_length=64)
    diagnostic: BoundedReason = ""

    @property
    def eligible_indexes(self) -> list[int]:
        return [verdict.index for verdict in self.verdicts if verdict.eligible]


def _disqualify(
    outcome: CandidateOutcome,
    baseline_sha256: str,
    *,
    require_isolation: bool,
) -> tuple[DisqualificationReason, str] | None:
    """Return the single reason this candidate cannot be considered, or ``None``.

    Baseline drift is checked first and independently of the outcome: a candidate that observed a
    different starting workspace cannot be compared with one that did not, whatever its result was.
    """

    if outcome.workspace_before_sha256 != baseline_sha256:
        return (
            DisqualificationReason.BASELINE_DRIFT,
            "the candidate started from a workspace that does not match the declared baseline",
        )
    if outcome.status is not ExecutionStatus.SUCCEEDED or not outcome.success:
        return (
            DisqualificationReason.NOT_SUCCESSFUL,
            f"the candidate terminated as {outcome.status.value}",
        )
    if not outcome.assertions_passed:
        return (DisqualificationReason.ASSERTIONS_FAILED, "the candidate did not pass its assertions")
    if outcome.rollback_integrity is False:
        return (
            DisqualificationReason.ROLLBACK_UNVERIFIED,
            "the candidate's rollback integrity could not be established",
        )
    if require_isolation and outcome.isolation_verdict is not True:
        return (
            DisqualificationReason.ISOLATION_NOT_ESTABLISHED,
            "strong isolation was required and this candidate did not report it",
        )
    return None


def select_candidate(
    outcomes: Sequence[CandidateOutcome],
    *,
    baseline_sha256: str,
    require_isolation: bool = False,
) -> CandidateSelection:
    """Select at most one adoptable candidate, deterministically, and name every rejection.

    Ties are broken by proposal digest rather than by arrival order, so two runs over the same candidates
    select the same one even when a provider returns them in a different order.
    """

    verdicts: list[CandidateVerdict] = []
    eligible: list[CandidateOutcome] = []
    for outcome in outcomes:
        disqualification = _disqualify(outcome, baseline_sha256, require_isolation=require_isolation)
        if disqualification is None:
            eligible.append(outcome)
            verdicts.append(
                CandidateVerdict(
                    index=outcome.index,
                    proposal_sha256=outcome.proposal_sha256,
                    eligible=True,
                    detail="passed its assertions against the declared baseline",
                )
            )
            continue
        reason, detail = disqualification
        verdicts.append(
            CandidateVerdict(
                index=outcome.index,
                proposal_sha256=outcome.proposal_sha256,
                eligible=False,
                reason=reason,
                detail=detail,
            )
        )

    verdicts.sort(key=lambda verdict: verdict.index)
    if not eligible:
        return CandidateSelection(
            verdicts=verdicts,
            diagnostic=(
                f"no candidate was adoptable out of {len(outcomes)}: "
                + ", ".join(
                    f"#{verdict.index} {verdict.reason.value if verdict.reason else 'unknown'}"
                    for verdict in verdicts
                )
            )[:240],
        )
    selected = min(eligible, key=lambda outcome: (outcome.proposal_sha256, outcome.index))
    return CandidateSelection(
        selected_index=selected.index,
        selected_proposal_sha256=selected.proposal_sha256,
        verdicts=verdicts,
        diagnostic=(
            f"selected candidate #{selected.index} of {len(outcomes)} "
            f"({len(eligible)} adoptable, ordered by proposal digest)"
        ),
    )


class CandidateBudget(BaseModel):
    """Limits shared by every candidate of one run, so N candidates cannot multiply the ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_candidates: int = Field(ge=1, le=64)
    max_prompt_tokens: int = Field(ge=1)
    max_completion_tokens: int = Field(ge=1)
    reserve_prompt_tokens: int = Field(default=1, ge=1)
    reserve_completion_tokens: int = Field(default=1, ge=1)


def admit_candidate(
    budget: CandidateBudget,
    *,
    started: int,
    total_prompt_tokens: int,
    total_completion_tokens: int,
) -> str | None:
    """Return why the next candidate may not start, or ``None`` when it fits the remaining budget."""

    if started >= budget.max_candidates:
        return f"candidate budget exhausted: {started} of {budget.max_candidates} already started"
    remaining_prompt = budget.max_prompt_tokens - total_prompt_tokens
    if remaining_prompt < budget.reserve_prompt_tokens:
        return (
            f"prompt token budget cannot cover another candidate: remaining {remaining_prompt} < "
            f"reserved {budget.reserve_prompt_tokens}"
        )
    remaining_completion = budget.max_completion_tokens - total_completion_tokens
    if remaining_completion < budget.reserve_completion_tokens:
        return (
            f"completion token budget cannot cover another candidate: remaining {remaining_completion} < "
            f"reserved {budget.reserve_completion_tokens}"
        )
    return None
