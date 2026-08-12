from __future__ import annotations

from xt_aegis.identity import RequestIdentity
from xt_aegis.models import FileWriteAction, Provenance
from xt_aegis.proposals import (
    FakeProposalProvider,
    Proposal,
    ProposalOutcome,
    ProposalRequest,
    ProposalStatus,
    ProviderProfile,
    SamplingProfile,
    TrustedEnvelopeConfig,
    TrustedRequestIds,
    build_action_request,
)


class FixedIdentitySource:
    def __init__(self, value: TrustedRequestIds) -> None:
        self.value = value

    def new_request_ids(self) -> TrustedRequestIds:
        return self.value


def test_valid_proposal_builds_trusted_action_envelope(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    proposal = Proposal(
        kind="replace_file",
        content="def calculate_tax(amount: float) -> float:\n    return amount * 0.07\n",
        explanation="Adjust the declared tax rate.",
        profile=ProviderProfile(
            provider="fake",
            model="deterministic",
            version="1.0",
            sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
        ),
    )
    trusted = TrustedEnvelopeConfig(
        target_path="sample_project/app.py",
        expected_sha256="a" * 64,
        actor_id="agent:test",
    )
    ids = TrustedRequestIds(
        thread_id="thread:trusted",
        action_id="action:trusted",
        idempotency_key="idem:trusted:0001",
    )

    envelope = build_action_request(
        proposal,
        trusted=trusted,
        skill=compiled_skill,
        identity_source=FixedIdentitySource(ids),
    )

    assert envelope.request.thread_id == "thread:trusted"
    assert envelope.request.action_id == "action:trusted"
    assert envelope.request.idempotency_key == "idem:trusted:0001"
    assert envelope.request.actor_id == "agent:test"
    assert envelope.request.provenance == Provenance.AGENT_PROPOSAL
    assert envelope.request.approval_id is None
    assert envelope.provider_profile == proposal.profile
    assert isinstance(envelope.request.action, FileWriteAction)
    assert envelope.request.action.relative_path == "sample_project/app.py"
    assert envelope.request.action.content == proposal.content
    assert envelope.request.action.expected_sha256 == "a" * 64
    assert envelope.request_identity == RequestIdentity.from_request(
        envelope.request, skill=compiled_skill
    )


def test_fake_provider_refusal_is_a_typed_non_execution_result() -> None:
    profile = ProviderProfile(
        provider="fake",
        model="deterministic",
        version="1.0",
        sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
    )
    provider = FakeProposalProvider(
        outcomes=[
            ProposalOutcome(
                status=ProposalStatus.REFUSED,
                profile=profile,
                diagnostic="provider refused the request",
            )
        ]
    )

    outcome = provider.propose(ProposalRequest(task="Replace the declared tax implementation."))

    assert outcome.status == ProposalStatus.REFUSED
    assert outcome.proposal is None
    assert outcome.diagnostic == "provider refused the request"
    assert outcome.profile == profile
