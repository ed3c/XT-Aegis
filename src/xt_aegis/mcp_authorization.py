"""Deny-by-default admission for a mutating MCP call.

One question is answered here — may this exact call proceed? — and every refusal names exactly one reason.

The order of the checks is itself a security property. The protection profile is evaluated first, because a
call that would run without isolation, egress control, credential brokerage, approval, or audit must be
refused regardless of how well the caller authenticates. Authenticating a request that cannot be safely
executed only tells the caller which credentials work.

Nothing here opens a socket or starts a process. Verifying a bearer credential belongs to the transport;
this component consumes an already-verified assertion and decides what it is allowed to do.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

BoundedText = Annotated[str, Field(max_length=240)]


class DenyReason(StrEnum):
    """Machine-readable refusal cause. A denial carries exactly one."""

    PROTECTION_UNAVAILABLE = "protection_unavailable"
    ASSERTION_EXPIRED = "assertion_expired"
    ISSUER_NOT_TRUSTED = "issuer_not_trusted"
    AUDIENCE_MISMATCH = "audience_mismatch"
    NONCE_REPLAYED = "nonce_replayed"
    TOOL_NOT_DECLARED = "tool_not_declared"
    SCOPE_MISSING = "scope_missing"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_CONSUMED = "approval_consumed"
    REQUEST_IN_PROGRESS = "request_in_progress"


class ProtectionProfile(BaseModel):
    """What must be available before any mutating call is considered.

    Every field defaults to ``False``: a protection that nobody declared is treated as absent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    isolation_ready: bool = False
    egress_ready: bool = False
    credential_broker_ready: bool = False
    approval_ready: bool = False
    audit_ready: bool = False

    def missing(self) -> list[str]:
        return sorted(name for name, ready in self.model_dump().items() if not ready)


class SubjectAssertion(BaseModel):
    """An already-verified statement about the caller. This component does not verify signatures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=160)
    issuer: str = Field(min_length=1, max_length=160)
    audience: str = Field(min_length=1, max_length=160)
    expires_at_epoch: float
    nonce: str = Field(min_length=8, max_length=128)
    scopes: frozenset[str] = frozenset()


class ToolApproval(BaseModel):
    """A human decision bound to one exact call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    tool: str = Field(min_length=1, max_length=64)
    action_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_version: str = Field(min_length=1, max_length=32)
    reason: BoundedText
    expires_at_epoch: float


class AdmissionDecision(BaseModel):
    """The terminal answer, with the single reason when it is no."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    admitted: bool
    request_id: str = Field(max_length=160)
    tool: str = Field(max_length=64)
    subject: str = Field(max_length=160)
    reason: DenyReason | None = None
    detail: BoundedText = ""
    replayed: bool = False


class MutatingToolAdmission:
    """Decide whether one mutating call may proceed. Deny-by-default at every layer."""

    def __init__(
        self,
        *,
        profile: ProtectionProfile,
        trusted_issuer: str,
        expected_audience: str,
        tool_scopes: Mapping[str, frozenset[str]],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.profile = profile
        self.trusted_issuer = trusted_issuer
        self.expected_audience = expected_audience
        # A tool absent from this mapping is not "unrestricted"; it is undeclared, and undeclared is denied.
        self.tool_scopes = dict(tool_scopes)
        self._clock = clock or time.time
        self._seen_nonces: set[str] = set()
        self._consumed_approvals: set[str] = set()
        self._decisions: dict[str, AdmissionDecision] = {}
        self._in_progress: set[str] = set()

    def _deny(
        self,
        *,
        request_id: str,
        tool: str,
        subject: str,
        reason: DenyReason,
        detail: str,
        record: bool = True,
    ) -> AdmissionDecision:
        decision = AdmissionDecision(
            admitted=False,
            request_id=request_id,
            tool=tool,
            subject=subject,
            reason=reason,
            detail=detail[:240],
        )
        if record:
            self._decisions[request_id] = decision
        return decision

    def admit(
        self,
        *,
        request_id: str,
        tool: str,
        assertion: SubjectAssertion,
        action_digest: str,
        policy_version: str,
        approval: ToolApproval | None,
    ) -> AdmissionDecision:
        """Return the admission decision for this exact call."""

        prior = self._decisions.get(request_id)
        if prior is not None:
            # A repeated request id never executes again; it replays the decision that was already made.
            return prior.model_copy(update={"replayed": True})
        if request_id in self._in_progress:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.REQUEST_IN_PROGRESS,
                detail="an execution for this request id has not reported a terminal result",
                record=False,
            )

        missing = self.profile.missing()
        if missing:
            # First, deliberately: a call that cannot be executed safely must not learn whether its
            # credentials were otherwise acceptable.
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.PROTECTION_UNAVAILABLE,
                detail=f"required protections are unavailable: {', '.join(missing)}",
            )

        now = self._clock()
        if assertion.expires_at_epoch <= now:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.ASSERTION_EXPIRED,
                detail="the caller's assertion expired",
            )
        if assertion.issuer != self.trusted_issuer:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.ISSUER_NOT_TRUSTED,
                detail=f"issuer {assertion.issuer!r} is not the configured issuer",
            )
        if assertion.audience != self.expected_audience:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.AUDIENCE_MISMATCH,
                detail=f"audience {assertion.audience!r} is not this server",
            )
        if assertion.nonce in self._seen_nonces:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.NONCE_REPLAYED,
                detail="this assertion nonce was already presented",
            )

        required = self.tool_scopes.get(tool)
        if required is None:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.TOOL_NOT_DECLARED,
                detail=f"tool {tool!r} declares no scope requirement and is therefore not callable",
            )
        absent = sorted(required - assertion.scopes)
        if absent:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.SCOPE_MISSING,
                detail=f"missing scopes: {', '.join(absent)}",
            )

        if approval is None:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.APPROVAL_MISSING,
                detail="a mutating call requires an approval bound to this exact action",
            )
        if approval.approval_id in self._consumed_approvals:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.APPROVAL_CONSUMED,
                detail="this approval was already used",
            )
        if approval.expires_at_epoch <= now:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.APPROVAL_EXPIRED,
                detail="the approval expired",
            )
        mismatched = [
            field
            for field, expected, observed in (
                ("subject", approval.subject, assertion.subject),
                ("tool", approval.tool, tool),
                ("action_digest", approval.action_digest, action_digest),
                ("policy_version", approval.policy_version, policy_version),
            )
            if expected != observed
        ]
        if mismatched:
            return self._deny(
                request_id=request_id,
                tool=tool,
                subject=assertion.subject,
                reason=DenyReason.APPROVAL_MISMATCH,
                detail=f"the approval does not cover this call: {', '.join(mismatched)}",
            )

        self._seen_nonces.add(assertion.nonce)
        self._consumed_approvals.add(approval.approval_id)
        self._in_progress.add(request_id)
        return AdmissionDecision(
            admitted=True,
            request_id=request_id,
            tool=tool,
            subject=assertion.subject,
            detail=f"admitted under approval {approval.approval_id}",
        )

    def record_terminal(self, decision: AdmissionDecision) -> None:
        """Record that an admitted call reached a terminal result, so a repeat replays it."""

        self._in_progress.discard(decision.request_id)
        self._decisions[decision.request_id] = decision

    @property
    def declared_tools(self) -> tuple[str, ...]:
        """The only tools that can ever be admitted; anything else is undeclared and denied."""

        return tuple(sorted(self.tool_scopes))
