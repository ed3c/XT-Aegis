"""Finite provider orchestration outside the deterministic runner."""

from __future__ import annotations

import hashlib
import time
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.models import ActionRequest, CompiledSkill, ExecutionResult, ExecutionStatus
from xt_aegis.proposals import (
    ProposalProvider,
    ProposalRequest,
    ProposalStatus,
    RequestIdentitySource,
    SecureRequestIdentitySource,
    TrustedEnvelopeConfig,
    build_action_request,
)
from xt_aegis.redaction import redact_text


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


class ControllerAttempt(BaseModel):
    """Bounded evidence for one provider proposal and optional execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: int = Field(ge=1)
    proposal_status: ProposalStatus
    execution_status: ExecutionStatus | None = None
    classification: ControllerStopReason
    diagnostic: str
    proposal_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    request_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    action_id: str | None = None
    idempotency_key: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class ControllerResult(BaseModel):
    """Schema-valid terminal evidence for a finite controller run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    stop_reason: ControllerStopReason
    attempts: list[ControllerAttempt]
    total_attempts: int = Field(ge=0)
    total_prompt_tokens: int = Field(ge=0)
    total_completion_tokens: int = Field(ge=0)
    duration_ms: float = Field(ge=0.0)


class ActionExecutor(Protocol):
    """Public execution seam implemented by ``HarnessRunner``."""

    def execute(self, request: ActionRequest) -> ExecutionResult:
        """Execute one trusted action request."""


class InfrastructureUnavailableError(RuntimeError):
    """A required execution backend cannot safely run the trusted request."""


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
        identity_source: RequestIdentitySource | None = None,
    ) -> None:
        self.provider = provider
        self.executor = executor
        self.skill = skill
        self.trusted = trusted
        self.budgets = budgets
        self.identity_source = identity_source or SecureRequestIdentitySource()

    def run(self, *, task: str) -> ControllerResult:
        started = time.monotonic()
        attempts: list[ControllerAttempt] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        request = ProposalRequest(task=task)

        for attempt_number in range(1, self.budgets.max_attempts + 1):
            outcome = self.provider.propose(request)
            prompt_tokens = outcome.usage.prompt_tokens or 0
            completion_tokens = outcome.usage.completion_tokens or 0
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens
            if outcome.status != ProposalStatus.READY:
                attempts.append(
                    ControllerAttempt(
                        attempt_number=attempt_number,
                        proposal_status=outcome.status,
                        classification=ControllerStopReason.PROPOSAL_REJECTED,
                        diagnostic=redact_text(
                            outcome.diagnostic,
                            limit=self.budgets.max_diagnostic_bytes,
                        ),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
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
                execution = self.executor.execute(envelope.request)
            except InfrastructureUnavailableError as exc:
                attempts.append(
                    ControllerAttempt(
                        attempt_number=attempt_number,
                        proposal_status=outcome.status,
                        classification=ControllerStopReason.INFRASTRUCTURE_UNAVAILABLE,
                        diagnostic=redact_text(
                            str(exc),
                            limit=self.budgets.max_diagnostic_bytes,
                        ),
                        proposal_sha256=hashlib.sha256(outcome.proposal.content.encode()).hexdigest(),
                        request_digest=envelope.request_identity.digest,
                        action_id=envelope.request.action_id,
                        idempotency_key=envelope.request.idempotency_key,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                )
                return self._result(
                    started=started,
                    attempts=attempts,
                    stop_reason=ControllerStopReason.INFRASTRUCTURE_UNAVAILABLE,
                    total_prompt_tokens=total_prompt_tokens,
                    total_completion_tokens=total_completion_tokens,
                )
            classification = self._classify_execution(execution)
            diagnostic = self._execution_diagnostic(execution, classification)
            attempts.append(
                ControllerAttempt(
                    attempt_number=attempt_number,
                    proposal_status=outcome.status,
                    execution_status=execution.status,
                    classification=classification,
                    diagnostic=diagnostic,
                    proposal_sha256=hashlib.sha256(outcome.proposal.content.encode()).hexdigest(),
                    request_digest=envelope.request_identity.digest,
                    action_id=envelope.request.action_id,
                    idempotency_key=envelope.request.idempotency_key,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
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
            if classification not in {
                ControllerStopReason.EXECUTION_FAILED,
                ControllerStopReason.ASSERTION_FAILED,
            }:
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
                )
            request = ProposalRequest(
                task=(
                    f"{task}\n\nRepair attempt {attempt_number + 1}. "
                    f"Prior {classification.value}: {diagnostic}"
                )
            )

        raise AssertionError("finite controller loop exited without a terminal result")

    def _result(
        self,
        *,
        started: float,
        attempts: list[ControllerAttempt],
        stop_reason: ControllerStopReason,
        total_prompt_tokens: int,
        total_completion_tokens: int,
    ) -> ControllerResult:
        return ControllerResult(
            success=stop_reason == ControllerStopReason.PASSED,
            stop_reason=stop_reason,
            attempts=attempts,
            total_attempts=len(attempts),
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    @staticmethod
    def _classify_execution(execution: ExecutionResult) -> ControllerStopReason:
        if execution.success and execution.status == ExecutionStatus.SUCCEEDED:
            return ControllerStopReason.PASSED
        if execution.rollback_integrity is False:
            return ControllerStopReason.RECOVERY_FAILED
        if execution.status == ExecutionStatus.SUSPENDED:
            return ControllerStopReason.APPROVAL_REQUIRED
        if any(not check.passed for check in execution.preconditions):
            return ControllerStopReason.BASELINE_INVALID
        reasons = " ".join(execution.policy_reasons).lower()
        if execution.status == ExecutionStatus.BLOCKED:
            if "approval" in reasons:
                return ControllerStopReason.APPROVAL_REQUIRED
            if "isolation" in reasons or "backend" in reasons or "infrastructure" in reasons:
                return ControllerStopReason.INFRASTRUCTURE_UNAVAILABLE
            if "budget" in reasons:
                return ControllerStopReason.BUDGET_EXHAUSTED
            return ControllerStopReason.POLICY_DENIED
        if any(not check.passed for check in execution.postconditions):
            return ControllerStopReason.ASSERTION_FAILED
        return ControllerStopReason.EXECUTION_FAILED

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
        return redact_text("\n".join(parts), limit=self.budgets.max_diagnostic_bytes)
