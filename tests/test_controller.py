from __future__ import annotations

from typing import NoReturn

from xt_aegis.controller import ControllerBudgets, ControllerStopReason, DiagnoseRepairController
from xt_aegis.models import ActionRequest
from xt_aegis.proposals import (
    FakeProposalProvider,
    ProposalOutcome,
    ProposalStatus,
    ProviderProfile,
    SamplingProfile,
    TrustedEnvelopeConfig,
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
