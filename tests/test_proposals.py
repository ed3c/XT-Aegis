from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import xt_aegis
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

ROOT = Path(__file__).resolve().parents[1]


class FixedIdentitySource:
    def __init__(self, value: TrustedRequestIds) -> None:
        self.value = value

    def new_request_ids(self) -> TrustedRequestIds:
        return self.value


class SequenceIdentitySource:
    def __init__(self, values: list[TrustedRequestIds]) -> None:
        self.values = iter(values)

    def new_request_ids(self) -> TrustedRequestIds:
        return next(self.values)


def test_proposal_boundary_is_part_of_public_package_api() -> None:
    assert xt_aegis.Proposal is Proposal
    assert xt_aegis.ProposalProvider.__name__ == "ProposalProvider"
    assert xt_aegis.build_action_request is build_action_request


def test_checked_in_proposal_schema_matches_runtime_model() -> None:
    checked_in = json.loads(
        (ROOT / "verification/schemas/trusted-proposal.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_in.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert checked_in.pop("$id") == "https://github.com/ed3c/XT-Aegis/trusted-proposal.schema.json"
    assert checked_in == Proposal.model_json_schema()


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


def test_trusted_builder_rejects_content_over_active_skill_byte_limit(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    limited_skill = compiled_skill.model_copy(
        update={
            "contract": compiled_skill.contract.model_copy(update={"max_write_bytes": 8})
        }
    )
    proposal = Proposal(
        kind="replace_file",
        content="é" * 5,
        profile=ProviderProfile(
            provider="fake",
            model="deterministic",
            version="1.0",
            sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
        ),
    )
    trusted = TrustedEnvelopeConfig(target_path="sample_project/app.py")
    ids = TrustedRequestIds(
        thread_id="thread:trusted",
        action_id="action:trusted",
        idempotency_key="idem:trusted:0002",
    )

    with pytest.raises(ValueError, match="proposal content is 10 bytes; skill limit is 8"):
        build_action_request(
            proposal,
            trusted=trusted,
            skill=limited_skill,
            identity_source=FixedIdentitySource(ids),
        )


@pytest.mark.parametrize("target_path", ["/tmp/outside.py", "../outside.py", "other.py"])
def test_trusted_builder_rejects_target_outside_active_skill_scope(
    compiled_skill, target_path: str  # type: ignore[no-untyped-def]
) -> None:
    proposal = Proposal(
        kind="replace_file",
        content="safe content\n",
        profile=ProviderProfile(
            provider="fake",
            model="deterministic",
            version="1.0",
            sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
        ),
    )
    ids = TrustedRequestIds(
        thread_id="thread:trusted",
        action_id="action:trusted",
        idempotency_key="idem:trusted:0003",
    )

    with pytest.raises(ValueError, match="target path is outside active skill scope"):
        build_action_request(
            proposal,
            trusted=TrustedEnvelopeConfig(target_path=target_path),
            skill=compiled_skill,
            identity_source=FixedIdentitySource(ids),
        )


def test_proposal_schema_rejects_provider_control_plane_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Proposal.model_validate(
            {
                "kind": "replace_file",
                "content": "safe content\n",
                "profile": {
                    "provider": "fake",
                    "model": "deterministic",
                    "version": "1.0",
                    "sampling": {
                        "temperature": 0.0,
                        "seed": 7,
                        "max_output_tokens": 256,
                    },
                },
                "target_path": "outside.py",
                "thread_id": "provider-controlled",
                "approval_id": "0" * 24,
            }
        )


def test_changed_proposal_gets_fresh_request_identity(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    profile = ProviderProfile(
        provider="fake",
        model="deterministic",
        version="1.0",
        sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
    )
    identities = SequenceIdentitySource(
        [
            TrustedRequestIds(
                thread_id="thread:first",
                action_id="action:first",
                idempotency_key="idem:first:0001",
            ),
            TrustedRequestIds(
                thread_id="thread:second",
                action_id="action:second",
                idempotency_key="idem:second:0002",
            ),
        ]
    )
    trusted = TrustedEnvelopeConfig(target_path="sample_project/app.py")

    first = build_action_request(
        Proposal(kind="replace_file", content="first\n", profile=profile),
        trusted=trusted,
        skill=compiled_skill,
        identity_source=identities,
    )
    second = build_action_request(
        Proposal(kind="replace_file", content="second\n", profile=profile),
        trusted=trusted,
        skill=compiled_skill,
        identity_source=identities,
    )

    assert first.request.action_id != second.request.action_id
    assert first.request.idempotency_key != second.request.idempotency_key
    assert first.request_identity.digest != second.request_identity.digest
