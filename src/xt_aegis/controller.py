"""Finite provider orchestration outside the deterministic runner."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.controller_state import (
    ControllerStateError,
    ControllerStateRecord,
    ControllerStateStore,
    conditions_digest,
)
from xt_aegis.models import (
    ActionRequest,
    CheckResult,
    CommandSpec,
    CompiledSkill,
    ExecutionReasonCode,
    ExecutionResult,
    ExecutionStatus,
)
from xt_aegis.proposals import (
    ProposalOutcome,
    ProposalProvider,
    ProposalRequest,
    ProposalStatus,
    ProviderProfile,
    RequestIdentitySource,
    SecureRequestIdentitySource,
    TrustedEnvelopeConfig,
    build_action_request,
)
from xt_aegis.redaction import redact_text

BoundedEvidenceText = Annotated[str, Field(max_length=1_024)]
BoundedExitCode = Annotated[int, Field(ge=0, le=255)]


class ControllerStopReason(StrEnum):
    """Terminal controller outcomes kept distinct from runner statuses."""

    PROPOSAL_REJECTED = "proposal_rejected"
    POLICY_DENIED = "policy_denied"
    APPROVAL_REQUIRED = "approval_required"
    BASELINE_INVALID = "baseline_invalid"
    INFRASTRUCTURE_UNAVAILABLE = "infrastructure_unavailable"
    EXECUTION_FAILED = "execution_failed"
    ASSERTION_FAILED = "assertion_failed"
    RECOVERY_FAILED = "recovery_failed"
    REPEATED_FAILURE = "repeated_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PASSED = "passed"


class ControllerBudgets(BaseModel):
    """Finite limits owned by trusted controller configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=3, ge=1, le=100)
    max_prompt_tokens: int = Field(default=65_536, ge=1)
    max_completion_tokens: int = Field(default=8_192, ge=1)
    max_wall_seconds: float = Field(default=120.0, ge=0.001, le=86_400.0)
    max_proposal_bytes: int = Field(default=262_144, ge=1, le=10_485_760)
    max_diagnostic_bytes: int = Field(default=8_192, ge=1, le=1_048_576)
    max_output_bytes: int = Field(default=16_384, ge=1, le=10_485_760)
    equivalent_failure_limit: int = Field(default=2, ge=2, le=100)


class ProviderAdmission(BaseModel):
    """Declared provider identity and the per-call token reservation trusted code will spend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    reserve_prompt_tokens: int = Field(default=1, ge=1)
    reserve_completion_tokens: int = Field(default=1, ge=1)

    def profile_mismatch(self, profile: ProviderProfile) -> str | None:
        """Return the declared/observed differences, or ``None`` when the profile matches."""

        observed = {
            "provider": profile.provider,
            "model": profile.model,
            "version": profile.version,
        }
        declared = {"provider": self.provider, "model": self.model, "version": self.version}
        differences = [
            f"{name}: declared {declared[name]!r}, observed {value!r}"
            for name, value in observed.items()
            if declared[name] != value
        ]
        if not differences:
            return None
        return "provider profile mismatch: " + "; ".join(differences)


class ControllerRunContext(BaseModel):
    """Trusted source and backend identity attached to every run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_dirty: bool
    backend_profile: str = Field(min_length=1, max_length=160)
    readiness_verdict: bool
    isolation_verdict: bool | None = None
    limitations: list[BoundedEvidenceText] = Field(default_factory=list, max_length=32)


class ControllerCheckEvidence(BaseModel):
    """Secret-safe condition evidence sufficient to reconstruct a verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(max_length=240)
    passed: bool
    actual_exit_code: int | None = None
    expected_exit_codes: list[BoundedExitCode] = Field(default_factory=list, max_length=256)
    duration_ms: float = Field(ge=0.0)
    output_truncated: bool = False
    output_original_bytes: int = Field(default=0, ge=0)


class ControllerAttempt(BaseModel):
    """Bounded evidence for one provider proposal and optional execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: int = Field(ge=1)
    proposal_status: ProposalStatus | None = None
    provider_profile: ProviderProfile | None = None
    target_path: str = Field(max_length=512)
    backend_profile: str = Field(max_length=160)
    readiness_verdict: bool
    isolation_verdict: bool | None = None
    execution_status: ExecutionStatus | None = None
    execution_reason_code: ExecutionReasonCode | None = None
    execution_success: bool | None = None
    classification: ControllerStopReason
    next_transition: Literal["repair", "stop"]
    diagnostic: str = Field(max_length=1_048_576)
    proposal_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    request_digest_version: str | None = Field(default=None, max_length=32)
    request_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    execution_request_digest_version: str | None = Field(default=None, max_length=32)
    execution_request_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    execution_policy_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    cycle_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    action_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=160)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    output_bytes: int = Field(default=0, ge=0)
    output_truncated: bool = False
    preconditions: list[ControllerCheckEvidence] = Field(default_factory=list, max_length=16)
    postconditions: list[ControllerCheckEvidence] = Field(default_factory=list, max_length=16)
    assertions_passed: bool | None = None
    rollback_integrity: bool | None = None
    action_exit_code: int | None = None
    action_expected_exit_codes: list[BoundedExitCode] = Field(default_factory=list, max_length=256)
    execution_duration_ms: float | None = Field(default=None, ge=0.0)
    workspace_before_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    workspace_after_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    limitations: list[BoundedEvidenceText] = Field(default_factory=list, max_length=32)


class ControllerResult(BaseModel):
    """Schema-valid terminal evidence for a finite controller run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    stop_reason: ControllerStopReason
    diagnostic: str = Field(max_length=1_048_576)
    context: ControllerRunContext
    budgets: ControllerBudgets
    admission: ProviderAdmission | None = None
    attempts: list[ControllerAttempt] = Field(max_length=100)
    total_attempts: int = Field(ge=0)
    total_prompt_tokens: int = Field(ge=0)
    total_completion_tokens: int = Field(ge=0)
    total_output_bytes: int = Field(ge=0)
    token_usage_complete: bool
    duration_ms: float = Field(ge=0.0)


class ActionExecutor(Protocol):
    """Public execution seam implemented by ``HarnessRunner``."""

    def execute(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> ExecutionResult:
        """Execute one trusted action request."""


class InfrastructureUnavailableError(RuntimeError):
    """A required execution backend cannot safely run the trusted request."""


@dataclass
class _RunState:
    """Mutable per-run bookkeeping; it exists so the terminal exit can persist without extra arguments."""

    run_id: str | None
    digest: str
    next_attempt_number: int = 1
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    usage_reported: bool = True
    repair_task: str | None = None
    in_flight_attempt: int | None = None
    cycle_counts: dict[str, int] = field(default_factory=dict)


class DiagnoseRepairController:
    """Classify proposal outcomes before any deterministic execution."""

    def __init__(
        self,
        *,
        provider: ProposalProvider,
        executor: ActionExecutor,
        skill: CompiledSkill,
        trusted: TrustedEnvelopeConfig,
        budgets: ControllerBudgets,
        context: ControllerRunContext,
        admission: ProviderAdmission | None = None,
        identity_source: RequestIdentitySource | None = None,
        state_store: ControllerStateStore | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.provider = provider
        self.executor = executor
        self.skill = skill
        self.trusted = trusted
        self.budgets = budgets
        self.context = context
        self.admission = admission
        self.identity_source = identity_source or SecureRequestIdentitySource()
        self.state_store = state_store
        self.clock = clock or time.monotonic
        self._state = _RunState(run_id=None, digest="")

    def run(self, *, task: str, run_id: str | None = None) -> ControllerResult:
        started = self.clock()
        attempts: list[ControllerAttempt] = []
        digest = conditions_digest(
            task=task,
            context=self.context,
            budgets=self.budgets,
            admission=self.admission,
        )
        self._state = _RunState(run_id=run_id, digest=digest)
        refusal = self._resume(task=task, run_id=run_id, digest=digest, started=started)
        if refusal is not None:
            return refusal
        total_prompt_tokens = self._state.total_prompt_tokens
        total_completion_tokens = self._state.total_completion_tokens
        cycle_counts: dict[str, int] = dict(self._state.cycle_counts)
        usage_reported = self._state.usage_reported
        next_task = self._state.repair_task or task
        start_attempt = self._state.next_attempt_number
        if start_attempt > self.budgets.max_attempts:
            return self._result(
                started=started,
                attempts=attempts,
                stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                diagnostic=(
                    f"attempt budget exhausted before resume: {start_attempt - 1} of "
                    f"{self.budgets.max_attempts} attempts were already recorded"
                ),
            )

        for attempt_number in range(start_attempt, self.budgets.max_attempts + 1):
            admission_reason = self._admission_reason(
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                usage_reported=usage_reported,
            )
            if admission_reason is not None:
                attempts.append(
                    self._attempt(
                        attempt_number=attempt_number,
                        outcome=None,
                        classification=ControllerStopReason.BUDGET_EXHAUSTED,
                        next_transition="stop",
                        diagnostic=admission_reason,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                    diagnostic=admission_reason,
                )
            if self.clock() - started > self.budgets.max_wall_seconds:
                elapsed = self.clock() - started
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                    diagnostic=(
                        f"wall-clock budget exceeded: {elapsed:.3f}s > {self.budgets.max_wall_seconds:.3f}s"
                    ),
                )
            self._state.next_attempt_number = attempt_number
            self._state.in_flight_attempt = attempt_number
            self._state.total_prompt_tokens = total_prompt_tokens
            self._state.total_completion_tokens = total_completion_tokens
            self._state.usage_reported = usage_reported
            self._state.repair_task = next_task if attempt_number > 1 else None
            self._save_state()
            outcome = self.provider.propose(
                ProposalRequest(
                    task=next_task,
                    max_prompt_tokens=self.budgets.max_prompt_tokens - total_prompt_tokens,
                    max_completion_tokens=self.budgets.max_completion_tokens - total_completion_tokens,
                    timeout_seconds=max(
                        0.001,
                        self.budgets.max_wall_seconds - (self.clock() - started),
                    ),
                    max_proposal_bytes=self.budgets.max_proposal_bytes,
                    max_response_bytes=min(self.budgets.max_proposal_bytes + 16_384, 10_485_760),
                )
            )
            reported_prompt_tokens = outcome.usage.prompt_tokens
            reported_completion_tokens = outcome.usage.completion_tokens
            usage_reported = (
                usage_reported
                and reported_prompt_tokens is not None
                and reported_completion_tokens is not None
            )
            prompt_tokens = reported_prompt_tokens or 0
            completion_tokens = reported_completion_tokens or 0
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens
            profile_reason = (
                self.admission.profile_mismatch(outcome.profile) if self.admission is not None else None
            )
            if profile_reason is not None:
                attempts.append(
                    self._attempt(
                        attempt_number=attempt_number,
                        outcome=outcome,
                        classification=ControllerStopReason.PROPOSAL_REJECTED,
                        next_transition="stop",
                        diagnostic=profile_reason,
                        prompt_tokens=reported_prompt_tokens,
                        completion_tokens=reported_completion_tokens,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.PROPOSAL_REJECTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                    diagnostic=profile_reason,
                )
            elapsed = self.clock() - started
            if elapsed > self.budgets.max_wall_seconds:
                diagnostic = (
                    f"wall-clock budget exceeded: {elapsed:.3f}s > {self.budgets.max_wall_seconds:.3f}s"
                )
                attempts.append(
                    self._attempt(
                        attempt_number=attempt_number,
                        outcome=outcome,
                        classification=ControllerStopReason.BUDGET_EXHAUSTED,
                        next_transition="stop",
                        diagnostic=diagnostic,
                        proposal_sha256=(
                            hashlib.sha256(outcome.proposal.content.encode()).hexdigest()
                            if outcome.proposal is not None
                            else None
                        ),
                        prompt_tokens=reported_prompt_tokens,
                        completion_tokens=reported_completion_tokens,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                    diagnostic=diagnostic,
                )
            budget_reason = self._provider_budget_reason(
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                proposal_content=outcome.proposal.content if outcome.proposal is not None else None,
            )
            if budget_reason is not None:
                attempts.append(
                    self._attempt(
                        attempt_number=attempt_number,
                        outcome=outcome,
                        classification=ControllerStopReason.BUDGET_EXHAUSTED,
                        next_transition="stop",
                        diagnostic=budget_reason,
                        proposal_sha256=(
                            hashlib.sha256(outcome.proposal.content.encode()).hexdigest()
                            if outcome.proposal is not None
                            else None
                        ),
                        prompt_tokens=reported_prompt_tokens,
                        completion_tokens=reported_completion_tokens,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                )
            if outcome.status != ProposalStatus.READY:
                attempts.append(
                    self._attempt(
                        attempt_number=attempt_number,
                        outcome=outcome,
                        classification=ControllerStopReason.PROPOSAL_REJECTED,
                        next_transition="stop",
                        diagnostic=self._bounded_diagnostic(outcome.diagnostic),
                        prompt_tokens=reported_prompt_tokens,
                        completion_tokens=reported_completion_tokens,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.PROPOSAL_REJECTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                )

            if outcome.proposal is None:  # guarded by ProposalOutcome validation
                raise AssertionError("ready proposal outcome omitted proposal content")
            envelope = build_action_request(
                outcome,
                trusted=self.trusted,
                skill=self.skill,
                identity_source=self.identity_source,
            )
            try:
                remaining_seconds = max(
                    0.001,
                    self.budgets.max_wall_seconds - (self.clock() - started),
                )
                remaining_output_bytes = max(
                    1,
                    self.budgets.max_output_bytes - sum(attempt.output_bytes for attempt in attempts),
                )
                execution = self.executor.execute(
                    envelope.request,
                    timeout_seconds=remaining_seconds,
                    max_output_bytes=remaining_output_bytes,
                )
            except InfrastructureUnavailableError as exc:
                attempts.append(
                    self._attempt(
                        attempt_number=attempt_number,
                        outcome=outcome,
                        classification=ControllerStopReason.INFRASTRUCTURE_UNAVAILABLE,
                        next_transition="stop",
                        diagnostic=self._bounded_diagnostic(str(exc)),
                        proposal_sha256=hashlib.sha256(outcome.proposal.content.encode()).hexdigest(),
                        request_digest_version=envelope.request_identity.version,
                        request_digest=envelope.request_identity.digest,
                        policy_digest=envelope.request_identity.policy_digest,
                        action_id=envelope.request.action_id,
                        idempotency_key=envelope.request.idempotency_key,
                        prompt_tokens=reported_prompt_tokens,
                        completion_tokens=reported_completion_tokens,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.INFRASTRUCTURE_UNAVAILABLE,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                )
            identity_reason = self._execution_identity_reason(
                execution=execution,
                request=envelope.request,
                request_digest_version=envelope.request_identity.version,
                request_digest=envelope.request_identity.digest,
                policy_digest=envelope.request_identity.policy_digest,
            )
            elapsed = self.clock() - started
            wall_reason = (
                f"wall-clock budget exceeded: {elapsed:.3f}s > {self.budgets.max_wall_seconds:.3f}s"
                if elapsed > self.budgets.max_wall_seconds
                else None
            )
            classification = (
                ControllerStopReason.RECOVERY_FAILED
                if identity_reason is not None
                else (
                    ControllerStopReason.BUDGET_EXHAUSTED
                    if wall_reason is not None
                    else self._classify_execution(execution)
                )
            )
            diagnostic = self._execution_diagnostic(execution, classification)
            if identity_reason is not None:
                diagnostic = self._bounded_diagnostic(identity_reason)
            elif wall_reason is not None:
                diagnostic = wall_reason
            retained_output_bytes = len(execution.action_stdout.encode()) + len(
                execution.action_stderr.encode()
            )
            reported_output_bytes = max(execution.output_original_bytes, retained_output_bytes)
            output_bytes = min(reported_output_bytes, remaining_output_bytes)
            output_truncated = execution.output_truncated or reported_output_bytes > remaining_output_bytes
            if output_truncated and identity_reason is None and wall_reason is None:
                classification = ControllerStopReason.BUDGET_EXHAUSTED
                diagnostic = (
                    "execution output budget exceeded: "
                    f"{sum(attempt.output_bytes for attempt in attempts) + reported_output_bytes} > "
                    f"{self.budgets.max_output_bytes}"
                )
            proposal_sha256 = hashlib.sha256(outcome.proposal.content.encode()).hexdigest()
            cycle_fingerprint: str | None = None
            if self._is_retryable(classification):
                cycle_fingerprint = self._cycle_fingerprint(
                    proposal_sha256=proposal_sha256,
                    classification=classification,
                    execution=execution,
                )
                cycle_counts[cycle_fingerprint] = cycle_counts.get(cycle_fingerprint, 0) + 1
                if cycle_counts[cycle_fingerprint] >= self.budgets.equivalent_failure_limit:
                    classification = ControllerStopReason.REPEATED_FAILURE
            attempts.append(
                self._attempt(
                    attempt_number=attempt_number,
                    outcome=outcome,
                    execution_status=execution.status,
                    execution_reason_code=execution.reason_code,
                    execution_success=execution.success,
                    classification=classification,
                    next_transition=("repair" if self._is_retryable(classification) else "stop"),
                    diagnostic=diagnostic,
                    proposal_sha256=proposal_sha256,
                    request_digest_version=envelope.request_identity.version,
                    request_digest=envelope.request_identity.digest,
                    policy_digest=envelope.request_identity.policy_digest,
                    execution_request_digest_version=execution.request_digest_version,
                    execution_request_digest=execution.request_digest,
                    execution_policy_digest=execution.policy_digest,
                    cycle_fingerprint=cycle_fingerprint,
                    action_id=envelope.request.action_id,
                    idempotency_key=envelope.request.idempotency_key,
                    prompt_tokens=reported_prompt_tokens,
                    completion_tokens=reported_completion_tokens,
                    output_bytes=output_bytes,
                    output_truncated=output_truncated,
                    preconditions=self._check_evidence(
                        execution.preconditions,
                        self.skill.contract.preconditions,
                    ),
                    postconditions=self._check_evidence(
                        execution.postconditions,
                        self.skill.contract.postconditions,
                    ),
                    assertions_passed=(
                        all(check.passed for check in execution.postconditions)
                        if execution.postconditions
                        else None
                    ),
                    rollback_integrity=execution.rollback_integrity,
                    action_exit_code=execution.action_exit_code,
                    action_expected_exit_codes=execution.action_expected_exit_codes,
                    execution_duration_ms=execution.duration_ms,
                    workspace_before_sha256=execution.workspace_before_sha256,
                    workspace_after_sha256=execution.workspace_after_sha256,
                )
            )
            if classification == ControllerStopReason.PASSED:
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=classification,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                )
            if (
                self._is_retryable(classification)
                and sum(attempt.output_bytes for attempt in attempts) >= self.budgets.max_output_bytes
            ):
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                    diagnostic="no execution output budget remains for another attempt",
                )
            if not self._is_retryable(classification):
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=classification,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                )
            if attempt_number == self.budgets.max_attempts:
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.BUDGET_EXHAUSTED,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                    diagnostic=f"attempt budget exhausted: {attempt_number}",
                )
            next_task = (
                f"{task}\n\nRepair attempt {attempt_number + 1}. Prior {classification.value}: {diagnostic}"
            )
            self._state.next_attempt_number = attempt_number + 1
            self._state.in_flight_attempt = None
            self._state.total_prompt_tokens = total_prompt_tokens
            self._state.total_completion_tokens = total_completion_tokens
            self._state.usage_reported = usage_reported
            self._state.repair_task = next_task
            self._state.cycle_counts = dict(cycle_counts)
            self._save_state()

        raise AssertionError("finite controller loop exited without a terminal result")

    def _attempt(
        self,
        *,
        attempt_number: int,
        outcome: ProposalOutcome | None,
        classification: ControllerStopReason,
        next_transition: Literal["repair", "stop"],
        diagnostic: str,
        **evidence: Any,
    ) -> ControllerAttempt:
        """Construct every attempt through the same run-context binding."""

        return ControllerAttempt(
            attempt_number=attempt_number,
            proposal_status=outcome.status if outcome is not None else None,
            provider_profile=outcome.profile if outcome is not None else None,
            target_path=self.trusted.target_path,
            backend_profile=self.context.backend_profile,
            readiness_verdict=self.context.readiness_verdict,
            isolation_verdict=self.context.isolation_verdict,
            classification=classification,
            next_transition=next_transition,
            diagnostic=diagnostic,
            limitations=self.context.limitations,
            **evidence,
        )

    def _resume(
        self,
        *,
        task: str,
        run_id: str | None,
        digest: str,
        started: float,
    ) -> ControllerResult | None:
        """Seed the run from persisted state, or return the terminal refusal that replaces it."""

        del task
        if self.state_store is None or run_id is None:
            return None
        try:
            record = self.state_store.load(run_id)
        except ControllerStateError as exc:
            return self._refuse_resume(started, str(exc))
        if record is None:
            return None
        if record.terminal_stop_reason is not None:
            return self._refuse_resume(
                started,
                f"run {run_id} already reached the terminal state {record.terminal_stop_reason}",
            )
        if record.conditions_digest != digest:
            return self._refuse_resume(
                started,
                "the declared task, run context, budgets, or provider admission profile changed since "
                "this run was persisted",
            )
        if record.in_flight_attempt is not None:
            return self._refuse_resume(
                started,
                f"attempt {record.in_flight_attempt} was still in flight when the run stopped; its "
                "workspace outcome is unknown",
            )
        self._state = _RunState(
            run_id=run_id,
            digest=digest,
            next_attempt_number=record.next_attempt_number,
            total_prompt_tokens=record.total_prompt_tokens,
            total_completion_tokens=record.total_completion_tokens,
            usage_reported=record.usage_reported,
            repair_task=record.repair_task,
            cycle_counts=dict(record.cycle_counts),
        )
        return None

    def _refuse_resume(self, started: float, diagnostic: str) -> ControllerResult:
        """A resume that cannot be trusted is terminal; no provider call is made."""

        return self._result(
            started=started,
            attempts=[],
            stop_reason=ControllerStopReason.RECOVERY_FAILED,
            total_prompt_tokens=0,
            total_completion_tokens=0,
            diagnostic=diagnostic,
            persist=False,
        )

    def _save_state(self, *, terminal_stop_reason: str | None = None) -> None:
        """Persist the current run state; a run without a store or identifier is a no-op."""

        state = self._state
        if self.state_store is None or state.run_id is None:
            return
        self.state_store.save(
            ControllerStateRecord(
                run_id=state.run_id,
                conditions_digest=state.digest,
                next_attempt_number=state.next_attempt_number,
                total_prompt_tokens=state.total_prompt_tokens,
                total_completion_tokens=state.total_completion_tokens,
                usage_reported=state.usage_reported,
                repair_task=state.repair_task,
                in_flight_attempt=state.in_flight_attempt,
                cycle_counts=dict(state.cycle_counts),
                terminal_stop_reason=terminal_stop_reason,
            )
        )

    def _admission_reason(
        self,
        *,
        total_prompt_tokens: int,
        total_completion_tokens: int,
        usage_reported: bool,
    ) -> str | None:
        """Refuse the next provider call while the budget can still be enforced."""

        if not usage_reported:
            return (
                "provider reported no prompt or completion usage; the remaining token budget cannot be "
                "enforced for another call"
            )
        reserve_prompt = self.admission.reserve_prompt_tokens if self.admission is not None else 1
        reserve_completion = self.admission.reserve_completion_tokens if self.admission is not None else 1
        remaining_prompt = self.budgets.max_prompt_tokens - total_prompt_tokens
        remaining_completion = self.budgets.max_completion_tokens - total_completion_tokens
        if remaining_prompt < reserve_prompt:
            return (
                f"prompt token budget cannot cover the next call: remaining {remaining_prompt} < "
                f"reserved {reserve_prompt}"
            )
        if remaining_completion < reserve_completion:
            return (
                f"completion token budget cannot cover the next call: remaining {remaining_completion} < "
                f"reserved {reserve_completion}"
            )
        return None

    def _provider_budget_reason(
        self,
        *,
        total_prompt_tokens: int,
        total_completion_tokens: int,
        proposal_content: str | None,
    ) -> str | None:
        if total_prompt_tokens > self.budgets.max_prompt_tokens:
            return f"prompt token budget exceeded: {total_prompt_tokens} > {self.budgets.max_prompt_tokens}"
        if total_completion_tokens > self.budgets.max_completion_tokens:
            return (
                f"completion token budget exceeded: {total_completion_tokens} > "
                f"{self.budgets.max_completion_tokens}"
            )
        if proposal_content is not None and len(proposal_content.encode()) > self.budgets.max_proposal_bytes:
            return (
                f"proposal byte budget exceeded: {len(proposal_content.encode())} > "
                f"{self.budgets.max_proposal_bytes}"
            )
        return None

    def _result(
        self,
        *,
        started: float,
        attempts: list[ControllerAttempt],
        stop_reason: ControllerStopReason,
        total_prompt_tokens: int,
        total_completion_tokens: int,
        diagnostic: str | None = None,
        persist: bool = True,
    ) -> ControllerResult:
        if persist:
            # Every terminal path goes through here, so the terminal record cannot be forgotten at a
            # return site. A refused resume passes persist=False so it cannot overwrite the state it
            # refused to trust.
            self._state.total_prompt_tokens = total_prompt_tokens
            self._state.total_completion_tokens = total_completion_tokens
            self._state.in_flight_attempt = None
            self._save_state(terminal_stop_reason=stop_reason.value)
        return ControllerResult(
            success=stop_reason == ControllerStopReason.PASSED,
            stop_reason=stop_reason,
            diagnostic=diagnostic
            if diagnostic is not None
            else (attempts[-1].diagnostic if attempts else ""),
            context=self.context,
            budgets=self.budgets,
            admission=self.admission,
            attempts=attempts,
            total_attempts=len(attempts),
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_output_bytes=sum(attempt.output_bytes for attempt in attempts),
            token_usage_complete=all(
                attempt.prompt_tokens is not None and attempt.completion_tokens is not None
                for attempt in attempts
                if attempt.proposal_status is not None
            ),
            duration_ms=(self.clock() - started) * 1000,
        )

    @staticmethod
    def _classify_execution(execution: ExecutionResult) -> ControllerStopReason:
        if execution.rollback_integrity is False:
            return ControllerStopReason.RECOVERY_FAILED
        if execution.reason_code == ExecutionReasonCode.OUTPUT_BUDGET_EXHAUSTED:
            return ControllerStopReason.BUDGET_EXHAUSTED
        if execution.success and execution.status == ExecutionStatus.SUCCEEDED:
            return ControllerStopReason.PASSED
        if execution.status == ExecutionStatus.SUSPENDED:
            return ControllerStopReason.APPROVAL_REQUIRED
        if any(not check.passed for check in execution.preconditions):
            return ControllerStopReason.BASELINE_INVALID
        if execution.status == ExecutionStatus.BLOCKED:
            if execution.reason_code in {
                ExecutionReasonCode.APPROVAL_DENIED,
                ExecutionReasonCode.APPROVAL_REQUIRED,
            }:
                return ControllerStopReason.APPROVAL_REQUIRED
            if execution.reason_code == ExecutionReasonCode.BUDGET_EXHAUSTED:
                return ControllerStopReason.BUDGET_EXHAUSTED
            return ControllerStopReason.POLICY_DENIED
        if any(not check.passed for check in execution.postconditions):
            return ControllerStopReason.ASSERTION_FAILED
        return ControllerStopReason.EXECUTION_FAILED

    @staticmethod
    def _is_retryable(classification: ControllerStopReason) -> bool:
        return classification in {
            ControllerStopReason.EXECUTION_FAILED,
            ControllerStopReason.ASSERTION_FAILED,
        }

    @staticmethod
    def _execution_identity_reason(
        *,
        execution: ExecutionResult,
        request: ActionRequest,
        request_digest_version: str,
        request_digest: str,
        policy_digest: str,
    ) -> str | None:
        expected = {
            "thread_id": request.thread_id,
            "action_id": request.action_id,
            "idempotency_key": request.idempotency_key,
            "request_digest_version": request_digest_version,
            "request_digest": request_digest,
            "policy_digest": policy_digest,
        }
        actual = {
            "thread_id": execution.thread_id,
            "action_id": execution.action_id,
            "idempotency_key": execution.idempotency_key,
            "request_digest_version": execution.request_digest_version,
            "request_digest": execution.request_digest,
            "policy_digest": execution.policy_digest,
        }
        mismatches = [name for name, value in expected.items() if actual[name] != value]
        if not mismatches:
            return None
        return "execution result identity mismatch: " + ", ".join(mismatches)

    @staticmethod
    def _check_evidence(
        results: list[CheckResult],
        specifications: list[CommandSpec],
    ) -> list[ControllerCheckEvidence]:
        evidence: list[ControllerCheckEvidence] = []
        for index, result in enumerate(results):
            specification = specifications[index] if index < len(specifications) else None
            expected = sorted(specification.expected_exit_codes) if specification is not None else []
            evidence.append(
                ControllerCheckEvidence(
                    description=result.description,
                    passed=result.passed,
                    actual_exit_code=result.exit_code,
                    expected_exit_codes=expected,
                    duration_ms=result.duration_ms,
                    output_truncated=result.output_truncated,
                    output_original_bytes=result.output_original_bytes,
                )
            )
        return evidence

    def _execution_diagnostic(
        self,
        execution: ExecutionResult,
        classification: ControllerStopReason,
    ) -> str:
        parts: list[str] = []
        if classification == ControllerStopReason.BASELINE_INVALID:
            parts.extend(
                f"precondition failed: {check.description}: {check.stderr}"
                for check in execution.preconditions
                if not check.passed
            )
        elif classification == ControllerStopReason.ASSERTION_FAILED:
            parts.extend(
                f"postcondition failed: {check.description}: {check.stderr}"
                for check in execution.postconditions
                if not check.passed
            )
        elif execution.policy_reasons:
            parts.extend(execution.policy_reasons)
        else:
            parts.extend(filter(None, [execution.action_stderr, execution.action_stdout]))
        return self._bounded_diagnostic("\n".join(parts))

    def _bounded_diagnostic(self, value: str) -> str:
        redacted = redact_text(value, limit=1_048_576)
        encoded = redacted.encode()
        if len(encoded) <= self.budgets.max_diagnostic_bytes:
            return redacted
        suffix = b"\n...[truncated]"
        if self.budgets.max_diagnostic_bytes <= len(suffix):
            return suffix[: self.budgets.max_diagnostic_bytes].decode()
        prefix_limit = self.budgets.max_diagnostic_bytes - len(suffix)
        prefix = encoded[:prefix_limit].decode(errors="ignore")
        return prefix + suffix.decode()

    @staticmethod
    def _cycle_fingerprint(
        *,
        proposal_sha256: str,
        classification: ControllerStopReason,
        execution: ExecutionResult,
    ) -> str:
        components = [
            proposal_sha256,
            classification.value,
            str(execution.action_exit_code),
            str(execution.rollback_integrity),
            *execution.policy_reasons,
            *(
                f"pre:{check.description}:{check.exit_code}:{check.passed}"
                for check in execution.preconditions
            ),
            *(
                f"post:{check.description}:{check.exit_code}:{check.passed}"
                for check in execution.postconditions
            ),
        ]
        return hashlib.sha256("\n".join(components).encode()).hexdigest()
