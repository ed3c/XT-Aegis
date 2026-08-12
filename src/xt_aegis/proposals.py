"""Provider-neutral proposals and trusted action-envelope construction."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xt_aegis.identity import RequestIdentity
from xt_aegis.models import ActionRequest, CompiledSkill, FileWriteAction, Provenance


class SamplingProfile(BaseModel):
    """Bounded sampling metadata retained for exact-profile reproduction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float = Field(ge=0.0, le=2.0)
    seed: int | None = None
    max_output_tokens: int = Field(ge=1, le=32_768)


class ProviderProfile(BaseModel):
    """Provider identity metadata; it carries no execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    sampling: SamplingProfile


class Proposal(BaseModel):
    """Bounded model-authored content without control-plane fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["replace_file"]
    content: str = Field(min_length=1, max_length=262_144)
    explanation: str | None = Field(default=None, max_length=4_096)
    profile: ProviderProfile


class ProposalStatus(StrEnum):
    READY = "ready"
    REFUSED = "refused"
    TIMED_OUT = "timed_out"
    MALFORMED = "malformed"
    OVERSIZED = "oversized"
    TRUNCATED = "truncated"
    PROVIDER_ERROR = "provider_error"


class ProposalRequest(BaseModel):
    """Private task input passed to a provider but not retained as evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: str = Field(min_length=1, max_length=32_768)


class ProposalOutcome(BaseModel):
    """Typed provider result; only ready outcomes may contain a proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ProposalStatus
    profile: ProviderProfile
    proposal: Proposal | None = None
    diagnostic: str = Field(default="", max_length=4_096)

    @model_validator(mode="after")
    def validate_proposal_presence(self) -> ProposalOutcome:
        if self.status == ProposalStatus.READY and self.proposal is None:
            raise ValueError("ready proposal outcome requires proposal content")
        if self.status != ProposalStatus.READY and self.proposal is not None:
            raise ValueError("non-ready proposal outcome cannot contain proposal content")
        return self


class ProposalProvider(Protocol):
    """Provider-neutral proposal boundary."""

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        """Return one bounded typed outcome without executing it."""


class FakeProposalProvider:
    """Deterministic provider used to drive proposal and controller tests."""

    def __init__(self, *, outcomes: list[ProposalOutcome]) -> None:
        if not outcomes:
            raise ValueError("fake provider requires at least one outcome")
        self._outcomes = list(outcomes)
        self._index = 0

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        del request
        if self._index >= len(self._outcomes):
            raise RuntimeError("fake provider outcome sequence exhausted")
        outcome = self._outcomes[self._index]
        self._index += 1
        return outcome


class TrustedEnvelopeConfig(BaseModel):
    """Target and actor scope selected by trusted integration code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_path: str = Field(min_length=1, max_length=512)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    actor_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:@/-]{1,160}$")


class TrustedRequestIds(BaseModel):
    """Server-generated request identifiers, never provider output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{3,128}$")
    action_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{3,128}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,160}$")


class RequestIdentitySource(Protocol):
    """Trusted randomness boundary used to generate fresh request IDs."""

    def new_request_ids(self) -> TrustedRequestIds:
        """Return one fresh identity set."""


class SecureRequestIdentitySource:
    """Generate opaque identifiers with operating-system randomness."""

    def new_request_ids(self) -> TrustedRequestIds:
        return TrustedRequestIds(
            thread_id=f"thread:{secrets.token_hex(16)}",
            action_id=f"action:{secrets.token_hex(16)}",
            idempotency_key=f"idem:{secrets.token_hex(24)}",
        )


@dataclass(frozen=True, slots=True)
class TrustedActionEnvelope:
    """Executable request plus the policy-bound identity and profile that produced it."""

    request: ActionRequest
    request_identity: RequestIdentity
    provider_profile: ProviderProfile


def build_action_request(
    proposal: Proposal,
    *,
    trusted: TrustedEnvelopeConfig,
    skill: CompiledSkill,
    identity_source: RequestIdentitySource | None = None,
) -> TrustedActionEnvelope:
    """Build one policy-bound request without accepting provider authority fields."""

    source = identity_source or SecureRequestIdentitySource()
    identifiers = source.new_request_ids()
    request = ActionRequest(
        thread_id=identifiers.thread_id,
        action_id=identifiers.action_id,
        idempotency_key=identifiers.idempotency_key,
        actor_id=trusted.actor_id,
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(
            relative_path=trusted.target_path,
            content=proposal.content,
            expected_sha256=trusted.expected_sha256,
        ),
    )
    return TrustedActionEnvelope(
        request=request,
        request_identity=RequestIdentity.from_request(request, skill=skill),
        provider_profile=proposal.profile,
    )
