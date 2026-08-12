from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import pytest

import xt_aegis
from xt_aegis.controller import (
    ControllerBudgets,
    ControllerResult,
    ControllerRunContext,
    ControllerStopReason,
    DiagnoseRepairController,
    InfrastructureUnavailableError,
)
from xt_aegis.identity import RequestIdentity
from xt_aegis.models import (
    ActionRequest,
    CheckResult,
    ExecutionReasonCode,
    ExecutionResult,
    ExecutionStatus,
)
from xt_aegis.proposals import (
    FakeProposalProvider,
    Proposal,
    ProposalOutcome,
    ProposalRequest,
    ProposalStatus,
    ProviderProfile,
    ProviderUsage,
    SamplingProfile,
    TrustedEnvelopeConfig,
    TrustedRequestIds,
)

ROOT = Path(__file__).resolve().parents[1]


def _profile() -> ProviderProfile:
    return ProviderProfile(
        provider="fake",
        model="deterministic",
        version="1.0",
        sampling=SamplingProfile(
            temperature=0.0,
            seed=7,
            context_tokens=8192,
            max_output_tokens=256,
        ),
    )


def _context() -> ControllerRunContext:
    return ControllerRunContext(
        source_commit="f" * 40,
        source_dirty=False,
        backend_profile="workspace-transaction:test",
        readiness_verdict=True,
        isolation_verdict=False,
        limitations=["workspace transaction is rollback, not strong process isolation"],
    )


def test_controller_contract_is_public_and_matches_checked_in_schema() -> None:
    assert xt_aegis.DiagnoseRepairController is DiagnoseRepairController
    assert xt_aegis.ControllerResult is ControllerResult
    checked_in = json.loads(
        (ROOT / "verification/schemas/controller-result.schema.json").read_text(encoding="utf-8")
    )
    assert checked_in.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert checked_in.pop("$id") == "https://github.com/ed3c/XT-Aegis/controller-result.schema.json"
    assert checked_in == ControllerResult.model_json_schema()


class RejectingExecutor:
    def execute(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> NoReturn:
        del timeout_seconds, max_output_bytes
        raise AssertionError(f"executor must not receive {request.action_id}")


class FixedIdentitySource:
    def new_request_ids(self) -> TrustedRequestIds:
        return TrustedRequestIds(
            thread_id="thread:controller",
            action_id="action:controller",
            idempotency_key="idem:controller:0001",
        )


class SequenceIdentitySource:
    def __init__(self, values: list[TrustedRequestIds]) -> None:
        self._values = iter(values)

    def new_request_ids(self) -> TrustedRequestIds:
        return next(self._values)


class RecordingProvider(FakeProposalProvider):
    def __init__(self, *, outcomes: list[ProposalOutcome]) -> None:
        super().__init__(outcomes=outcomes)
        self.requests: list[ProposalRequest] = []

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        self.requests.append(request)
        return super().propose(request)


class SequenceExecutor:
    def __init__(
        self,
        outcomes: list[ExecutionResult | InfrastructureUnavailableError],
        *,
        skill,  # type: ignore[no-untyped-def]
        bind_identity: bool = True,
    ) -> None:
        self._outcomes = iter(outcomes)
        self._skill = skill
        self._bind_identity = bind_identity
        self.requests: list[ActionRequest] = []

    def execute(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> ExecutionResult:
        del timeout_seconds, max_output_bytes
        self.requests.append(request)
        outcome = next(self._outcomes)
        if isinstance(outcome, InfrastructureUnavailableError):
            raise outcome
        if self._bind_identity:
            identity = RequestIdentity.from_request(request, skill=self._skill)
            return outcome.model_copy(
                update={
                    "thread_id": request.thread_id,
                    "action_id": request.action_id,
                    "idempotency_key": request.idempotency_key,
                    "request_digest_version": identity.version,
                    "request_digest": identity.digest,
                    "policy_digest": identity.policy_digest,
                }
            )
        return outcome


def _execution_result(
    *,
    status: ExecutionStatus,
    reason_code: ExecutionReasonCode | None = None,
    policy_reasons: list[str] | None = None,
    preconditions: list[CheckResult] | None = None,
    postconditions: list[CheckResult] | None = None,
    rollback_integrity: bool | None = True,
    action_stdout: str = "",
    action_stderr: str = "",
) -> ExecutionResult:
    return ExecutionResult(
        thread_id="thread:fake",
        action_id="action:fake",
        idempotency_key="idem:fake:0001",
        step_number=1,
        status=status,
        success=status == ExecutionStatus.SUCCEEDED,
        reason_code=reason_code,
        policy_reasons=policy_reasons or [],
        preconditions=preconditions or [],
        postconditions=postconditions or [],
        rolled_back=status == ExecutionStatus.ROLLED_BACK,
        rollback_integrity=rollback_integrity,
        action_stdout=action_stdout,
        action_stderr=action_stderr,
        workspace_before_sha256="a" * 64,
        workspace_after_sha256="a" * 64,
        started_at="2026-08-12T00:00:00+00:00",
        finished_at="2026-08-12T00:00:01+00:00",
    )


@pytest.mark.parametrize(
    "status",
    [
        ProposalStatus.REFUSED,
        ProposalStatus.TIMED_OUT,
        ProposalStatus.MALFORMED,
        ProposalStatus.OVERSIZED,
        ProposalStatus.TRUNCATED,
        ProposalStatus.PROVIDER_ERROR,
    ],
)
def test_proposal_rejection_is_terminal_without_execution(
    compiled_skill,  # type: ignore[no-untyped-def]
    status: ProposalStatus,
) -> None:
    provider = FakeProposalProvider(
        outcomes=[
            ProposalOutcome(
                status=status,
                profile=_profile(),
                diagnostic="provider refused the request",
            )
        ]
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=RejectingExecutor(),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2),
    )

    result = controller.run(task="Replace the declared tax implementation.")

    assert result.success is False
    assert result.stop_reason == ControllerStopReason.PROPOSAL_REJECTED
    assert len(result.attempts) == 1
    assert result.attempts[0].proposal_status == status
    assert result.attempts[0].execution_status is None
    assert result.attempts[0].diagnostic == "provider refused the request"
    assert result.total_attempts == 1
    assert result.total_prompt_tokens == 0
    assert result.total_completion_tokens == 0


def test_ready_proposal_executes_once_and_records_passed_evidence(
    compiled_skill,
    runner,  # type: ignore[no-untyped-def]
) -> None:
    content = (
        "TAX_RATE = 0.05\n\n"
        "def calculate_tax(amount: float) -> float:\n"
        "    if amount < 0:\n"
        "        raise ValueError('Amount cannot be negative')\n"
        "    return round(amount * TAX_RATE, 2)\n"
    )
    provider = FakeProposalProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content=content),
                usage=ProviderUsage(prompt_tokens=11, completion_tokens=29),
            )
        ]
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=runner,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Preserve behavior while extracting the tax rate.")

    assert result.success is True
    assert result.stop_reason == ControllerStopReason.PASSED
    assert result.total_attempts == 1
    assert result.total_prompt_tokens == 11
    assert result.total_completion_tokens == 29
    attempt = result.attempts[0]
    assert attempt.classification == ControllerStopReason.PASSED
    assert attempt.execution_status == "succeeded"
    assert attempt.action_id == "action:controller"
    assert attempt.idempotency_key == "idem:controller:0001"
    assert attempt.request_digest is not None
    assert attempt.policy_digest is not None
    assert attempt.proposal_sha256 is not None
    assert attempt.provider_profile == _profile()
    assert attempt.target_path == "sample_project/app.py"
    assert attempt.execution_success is True
    assert attempt.assertions_passed is True
    assert attempt.action_exit_code == 0
    assert attempt.action_expected_exit_codes == [0]
    assert attempt.preconditions[0].passed is True
    assert attempt.preconditions[0].expected_exit_codes == [0]
    assert attempt.postconditions[0].passed is True
    assert attempt.rollback_integrity is None
    assert attempt.next_transition == "stop"
    assert attempt.workspace_before_sha256 is not None
    assert attempt.artifact_identities["workspace_after_sha256"]
    assert attempt.limitations == _context().limitations
    assert result.context == _context()
    assert result.budgets.max_attempts == 2
    assert "TAX_RATE" in (runner.workspace.root / "sample_project/app.py").read_text(encoding="utf-8")


def test_assertion_failure_repairs_with_fresh_identity_and_preserves_both_attempts(
    compiled_skill,
    runner,  # type: ignore[no-untyped-def]
) -> None:
    broken = "def calculate_tax(amount: float) -> float:\n    return amount * 0.10\n"
    repaired = (
        "def calculate_tax(amount: float) -> float:\n"
        "    if amount < 0:\n"
        "        raise ValueError('Amount cannot be negative')\n"
        "    return round(amount * 0.05, 2)\n"
    )
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content=broken),
                usage=ProviderUsage(prompt_tokens=10, completion_tokens=20),
            ),
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content=repaired),
                usage=ProviderUsage(prompt_tokens=18, completion_tokens=31),
            ),
        ]
    )
    identities = SequenceIdentitySource(
        [
            TrustedRequestIds(
                thread_id="thread:controller:first",
                action_id="action:controller:first",
                idempotency_key="idem:controller:first",
            ),
            TrustedRequestIds(
                thread_id="thread:controller:second",
                action_id="action:controller:second",
                idempotency_key="idem:controller:second",
            ),
        ]
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=runner,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2),
        identity_source=identities,
    )

    result = controller.run(task="Preserve the declared tax behavior.")

    assert result.success is True
    assert result.stop_reason == ControllerStopReason.PASSED
    assert [attempt.classification for attempt in result.attempts] == [
        ControllerStopReason.ASSERTION_FAILED,
        ControllerStopReason.PASSED,
    ]
    assert result.attempts[0].request_digest != result.attempts[1].request_digest
    assert result.attempts[0].action_id != result.attempts[1].action_id
    assert result.attempts[0].idempotency_key != result.attempts[1].idempotency_key
    assert result.total_prompt_tokens == 28
    assert result.total_completion_tokens == 51
    assert len(provider.requests) == 2
    assert "postcondition failed" in provider.requests[1].task


def test_execution_failure_is_retryable_and_can_reach_passed(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="first\n"),
                usage=ProviderUsage(prompt_tokens=2, completion_tokens=2),
            ),
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="second\n"),
                usage=ProviderUsage(prompt_tokens=3, completion_tokens=3),
            ),
        ]
    )
    executor = SequenceExecutor(
        [
            _execution_result(status=ExecutionStatus.ROLLED_BACK, action_stderr="command failed"),
            _execution_result(status=ExecutionStatus.SUCCEEDED),
        ],
        skill=compiled_skill,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2),
        identity_source=SequenceIdentitySource(
            [
                TrustedRequestIds(
                    thread_id="thread:execution:first",
                    action_id="action:execution:first",
                    idempotency_key="idem:execution:first",
                ),
                TrustedRequestIds(
                    thread_id="thread:execution:second",
                    action_id="action:execution:second",
                    idempotency_key="idem:execution:second",
                ),
            ]
        ),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.PASSED
    assert [attempt.classification for attempt in result.attempts] == [
        ControllerStopReason.EXECUTION_FAILED,
        ControllerStopReason.PASSED,
    ]
    assert "Prior execution_failed" in provider.requests[1].task


def test_execution_result_identity_mismatch_fails_closed_without_retry(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="safe\n"),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            )
        ]
    )
    executor = SequenceExecutor(
        [_execution_result(status=ExecutionStatus.SUCCEEDED)],
        skill=compiled_skill,
        bind_identity=False,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.RECOVERY_FAILED
    assert result.attempts[0].execution_request_digest is None
    assert "identity mismatch" in result.diagnostic
    assert len(provider.requests) == 1


def test_policy_reason_text_cannot_impersonate_typed_budget_code(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    execution = _execution_result(
        status=ExecutionStatus.BLOCKED,
        reason_code=ExecutionReasonCode.POLICY_DENIED,
        policy_reasons=["policy denies file named budget-notes.txt"],
    )
    controller = DiagnoseRepairController(
        provider=RecordingProvider(
            outcomes=[
                ProposalOutcome(
                    status=ProposalStatus.READY,
                    profile=_profile(),
                    proposal=Proposal(content="safe\n"),
                )
            ]
        ),
        executor=SequenceExecutor([execution], skill=compiled_skill),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.POLICY_DENIED


@pytest.mark.parametrize(
    ("execution_outcome", "expected_reason"),
    [
        (
            _execution_result(
                status=ExecutionStatus.BLOCKED,
                reason_code=ExecutionReasonCode.POLICY_DENIED,
                policy_reasons=["request denied by active policy"],
            ),
            ControllerStopReason.POLICY_DENIED,
        ),
        (
            _execution_result(
                status=ExecutionStatus.SUSPENDED,
                reason_code=ExecutionReasonCode.APPROVAL_REQUIRED,
                policy_reasons=["human approval is required"],
                rollback_integrity=None,
            ),
            ControllerStopReason.APPROVAL_REQUIRED,
        ),
        (
            _execution_result(
                status=ExecutionStatus.ROLLED_BACK,
                preconditions=[CheckResult(description="baseline", passed=False, stderr="invalid")],
            ),
            ControllerStopReason.BASELINE_INVALID,
        ),
        (
            InfrastructureUnavailableError("required backend is not ready"),
            ControllerStopReason.INFRASTRUCTURE_UNAVAILABLE,
        ),
        (
            _execution_result(
                status=ExecutionStatus.FAILED,
                rollback_integrity=False,
            ),
            ControllerStopReason.RECOVERY_FAILED,
        ),
        (
            _execution_result(
                status=ExecutionStatus.BLOCKED,
                reason_code=ExecutionReasonCode.BUDGET_EXHAUSTED,
                policy_reasons=["step budget exceeded: 3 > 2"],
            ),
            ControllerStopReason.BUDGET_EXHAUSTED,
        ),
    ],
)
def test_non_retryable_execution_outcomes_stop_immediately(
    compiled_skill,  # type: ignore[no-untyped-def]
    execution_outcome: ExecutionResult | InfrastructureUnavailableError,
    expected_reason: ControllerStopReason,
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="safe content\n"),
            )
        ]
    )
    executor = SequenceExecutor([execution_outcome], skill=compiled_skill)
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=3),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.success is False
    assert result.stop_reason == expected_reason
    assert result.total_attempts == 1
    assert result.attempts[0].classification == expected_reason
    assert len(provider.requests) == 1
    assert len(executor.requests) == 1


def test_provider_token_budget_violation_stops_before_execution(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="safe content\n"),
                usage=ProviderUsage(prompt_tokens=11, completion_tokens=4),
            )
        ]
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=RejectingExecutor(),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(
            max_attempts=2,
            max_prompt_tokens=10,
            max_completion_tokens=8,
        ),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.attempts[0].classification == ControllerStopReason.BUDGET_EXHAUSTED
    assert "prompt token budget" in result.attempts[0].diagnostic
    assert provider.requests[0].max_prompt_tokens == 10
    assert provider.requests[0].max_completion_tokens == 8


@pytest.mark.parametrize(
    ("outcome", "budgets", "diagnostic"),
    [
        (
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="safe content\n"),
                usage=ProviderUsage(prompt_tokens=4, completion_tokens=9),
            ),
            ControllerBudgets(max_completion_tokens=8),
            "completion token budget exceeded",
        ),
        (
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="123456789"),
                usage=ProviderUsage(prompt_tokens=4, completion_tokens=4),
            ),
            ControllerBudgets(max_proposal_bytes=8),
            "proposal byte budget exceeded",
        ),
    ],
)
def test_provider_completion_and_proposal_budgets_stop_before_execution(
    compiled_skill,  # type: ignore[no-untyped-def]
    outcome: ProposalOutcome,
    budgets: ControllerBudgets,
    diagnostic: str,
) -> None:
    controller = DiagnoseRepairController(
        provider=RecordingProvider(outcomes=[outcome]),
        executor=RejectingExecutor(),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=budgets,
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert diagnostic in result.diagnostic


def test_attempt_budget_stops_after_last_allowed_execution(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="broken\n"),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            )
        ]
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=SequenceExecutor(
            [_execution_result(status=ExecutionStatus.ROLLED_BACK, action_stderr="failed")],
            skill=compiled_skill,
        ),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=1),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.attempts[0].classification == ControllerStopReason.EXECUTION_FAILED
    assert result.diagnostic == "attempt budget exhausted: 1"
    assert len(provider.requests) == 1


def test_repeated_equivalent_proposal_failure_cycle_stops_before_third_attempt(
    compiled_skill,
    runner,  # type: ignore[no-untyped-def]
) -> None:
    broken = "def calculate_tax(amount: float) -> float:\n    return amount * 0.10\n"
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content=broken),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            ),
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content=broken),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            ),
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="must not be requested\n"),
            ),
        ]
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=runner,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=3, equivalent_failure_limit=2),
        identity_source=SequenceIdentitySource(
            [
                TrustedRequestIds(
                    thread_id="thread:repeat:first",
                    action_id="action:repeat:first",
                    idempotency_key="idem:repeat:first",
                ),
                TrustedRequestIds(
                    thread_id="thread:repeat:second",
                    action_id="action:repeat:second",
                    idempotency_key="idem:repeat:second",
                ),
            ]
        ),
    )

    result = controller.run(task="Preserve the declared tax behavior.")

    assert result.stop_reason == ControllerStopReason.REPEATED_FAILURE
    assert result.total_attempts == 2
    assert result.attempts[0].classification == ControllerStopReason.ASSERTION_FAILED
    assert result.attempts[1].classification == ControllerStopReason.REPEATED_FAILURE
    assert result.attempts[0].cycle_fingerprint == result.attempts[1].cycle_fingerprint
    assert len(provider.requests) == 2


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ClockAdvancingExecutor(SequenceExecutor):
    def __init__(
        self,
        outcome: ExecutionResult,
        *,
        skill,  # type: ignore[no-untyped-def]
        clock: MutableClock,
        advance_to: float,
    ) -> None:
        super().__init__([outcome], skill=skill)
        self.clock = clock
        self.advance_to = advance_to

    def execute(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> ExecutionResult:
        result = super().execute(
            request,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        self.clock.value = self.advance_to
        return result


class ClockAdvancingProvider(RecordingProvider):
    def __init__(
        self,
        *,
        outcomes: list[ProposalOutcome],
        clock: MutableClock,
        advance_to: float,
    ) -> None:
        super().__init__(outcomes=outcomes)
        self.clock = clock
        self.advance_to = advance_to

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        outcome = super().propose(request)
        self.clock.value = self.advance_to
        return outcome


def test_provider_wall_overrun_stops_before_execution(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    clock = MutableClock()
    provider = ClockAdvancingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="safe content\n"),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            )
        ],
        clock=clock,
        advance_to=1.1,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=RejectingExecutor(),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2, max_wall_seconds=1.0),
        clock=clock,
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.attempts[0].execution_status is None
    assert "wall-clock budget exceeded" in result.diagnostic


def test_wall_budget_stops_before_requesting_another_repair(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    clock = MutableClock()
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="broken\n"),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            ),
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="must not be requested\n"),
            ),
        ]
    )
    executor = ClockAdvancingExecutor(
        _execution_result(status=ExecutionStatus.ROLLED_BACK, action_stderr="command failed"),
        skill=compiled_skill,
        clock=clock,
        advance_to=1.1,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=3, max_wall_seconds=1.0),
        identity_source=FixedIdentitySource(),
        clock=clock,
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.total_attempts == 1
    assert result.duration_ms == 1100.0
    assert "wall-clock budget exceeded" in result.diagnostic
    assert len(provider.requests) == 1


def test_execution_output_budget_stops_before_repair(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="broken\n"),
            )
        ]
    )
    executor = SequenceExecutor(
        [
            _execution_result(
                status=ExecutionStatus.ROLLED_BACK,
                action_stderr="x" * 33,
            )
        ],
        skill=compiled_skill,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2, max_output_bytes=32),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.attempts[0].classification == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.attempts[0].output_bytes == 32
    assert result.attempts[0].output_truncated is True
    assert result.total_output_bytes == 32
    assert len(provider.requests) == 1


def test_missing_token_usage_fails_closed_before_retry(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="broken\n"),
            ),
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="must not be requested\n"),
            ),
        ]
    )
    executor = SequenceExecutor(
        [_execution_result(status=ExecutionStatus.ROLLED_BACK, action_stderr="command failed")],
        skill=compiled_skill,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert result.token_usage_complete is False
    assert result.attempts[0].prompt_tokens is None
    assert result.attempts[0].completion_tokens is None
    assert len(provider.requests) == 1


def test_repair_diagnostic_is_redacted_and_byte_bounded_before_provider_reuse(
    compiled_skill,  # type: ignore[no-untyped-def]
) -> None:
    provider = RecordingProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.READY,
                profile=_profile(),
                proposal=Proposal(content="broken\n"),
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            ),
            ProposalOutcome(
                status=ProposalStatus.REFUSED,
                profile=_profile(),
                diagnostic="done",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=0),
            ),
        ]
    )
    executor = SequenceExecutor(
        [
            _execution_result(
                status=ExecutionStatus.ROLLED_BACK,
                action_stderr="password=supersecret " + "界" * 100,
            )
        ],
        skill=compiled_skill,
    )
    controller = DiagnoseRepairController(
        provider=provider,
        executor=executor,
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=_context(),
        budgets=ControllerBudgets(max_attempts=2, max_diagnostic_bytes=64, max_output_bytes=1024),
        identity_source=FixedIdentitySource(),
    )

    result = controller.run(task="Propose one bounded change.")

    assert result.stop_reason == ControllerStopReason.PROPOSAL_REJECTED
    first_diagnostic = result.attempts[0].diagnostic
    assert "supersecret" not in first_diagnostic
    assert "[REDACTED]" in first_diagnostic
    assert len(first_diagnostic.encode()) <= 64
    assert "supersecret" not in provider.requests[1].task
    assert first_diagnostic in provider.requests[1].task
