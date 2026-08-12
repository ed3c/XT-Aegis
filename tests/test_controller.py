from __future__ import annotations

from typing import NoReturn

from xt_aegis.controller import ControllerBudgets, ControllerStopReason, DiagnoseRepairController
from xt_aegis.models import ActionRequest
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


class RejectingExecutor:
    def execute(self, request: ActionRequest) -> NoReturn:
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


def test_proposal_rejection_is_terminal_without_execution(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    provider = FakeProposalProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.REFUSED,
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
        budgets=ControllerBudgets(max_attempts=2),
    )

    result = controller.run(task="Replace the declared tax implementation.")

    assert result.success is False
    assert result.stop_reason == ControllerStopReason.PROPOSAL_REJECTED
    assert len(result.attempts) == 1
    assert result.attempts[0].proposal_status == ProposalStatus.REFUSED
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
    assert attempt.proposal_sha256 is not None
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
