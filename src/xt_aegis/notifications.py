"""Publish a pending approval without giving the channel any authority over it.

Two rules shape this module.

A notification carries no payload. It names what is waiting and where to decide it, and nothing else — a
channel that carries the content is a channel that leaks it, and a pending approval is exactly the moment
when the content is most sensitive.

A channel never decides. A transport that returns "approved" is reporting data, not exercising authority.
Only a decision bound to an authenticated subject, the exact action digest, the policy version, an expiry,
and a single-use nonce changes anything, so compromising the channel is not equivalent to compromising
approval.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field

BoundedText = Annotated[str, Field(max_length=240)]


class DecisionVerdict(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"


class DecisionRejection(StrEnum):
    """Why a returned decision was not accepted. A rejection carries exactly one."""

    UNKNOWN_APPROVAL = "unknown_approval"
    SUBJECT_MISMATCH = "subject_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    NONCE_REPLAYED = "nonce_replayed"
    DECISION_EXPIRED = "decision_expired"
    ALREADY_DECIDED = "already_decided"


class PendingApproval(BaseModel):
    """What is waiting. Deliberately not what it contains."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    tool: str = Field(min_length=1, max_length=64)
    action_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_version: str = Field(min_length=1, max_length=32)
    summary: BoundedText
    expires_at_epoch: float


class Notification(BaseModel):
    """The message handed to a channel. Its fields are the whole contract of what may leave."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    tool: str = Field(min_length=1, max_length=64)
    action_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    summary: BoundedText
    expires_at_epoch: float
    attempt: int = Field(ge=1)


class DeliveryAttempt(BaseModel):
    """Audit evidence for one publish."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(max_length=64)
    attempt: int = Field(ge=1)
    delivered: bool
    detail: BoundedText = ""
    at_epoch: float


class SignedDecision(BaseModel):
    """A decision as it arrives from a transport that already authenticated the human."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    action_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_version: str = Field(min_length=1, max_length=32)
    verdict: DecisionVerdict
    reason: BoundedText
    nonce: str = Field(min_length=8, max_length=128)
    expires_at_epoch: float


class DecisionRecord(BaseModel):
    """The accepted or rejected outcome, with the single reason when it is rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(max_length=64)
    accepted: bool
    verdict: DecisionVerdict | None = None
    subject: str = Field(max_length=160)
    rejection: DecisionRejection | None = None
    detail: BoundedText = ""
    at_epoch: float


class NotificationChannel(Protocol):
    """A transport. It publishes; it never decides."""

    def publish(self, notification: Notification) -> bool:
        """Return whether the notification was delivered."""


class ApprovalNotifier:
    """Bounded publishing plus decision verification. The channel is never consulted for authority."""

    def __init__(
        self,
        channel: NotificationChannel,
        *,
        max_attempts_per_approval: int = 3,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_attempts_per_approval < 1:
            raise ValueError("max_attempts_per_approval must be at least 1")
        self.channel = channel
        self.max_attempts_per_approval = max_attempts_per_approval
        self._clock = clock or time.time
        self._pending: dict[str, PendingApproval] = {}
        self._attempts: dict[str, int] = {}
        self._used_nonces: set[str] = set()
        self.attempt_log: list[DeliveryAttempt] = []
        self.decision_log: list[DecisionRecord] = []

    def notify(self, pending: PendingApproval) -> DeliveryAttempt | None:
        """Publish once, up to the declared ceiling.

        A resume calls this again. The ceiling is what stops a restart loop from flooding the channel;
        returning ``None`` says the ceiling is reached, not that delivery succeeded.
        """

        self._pending[pending.approval_id] = pending
        attempts = self._attempts.get(pending.approval_id, 0)
        if attempts >= self.max_attempts_per_approval:
            return None
        attempt_number = attempts + 1
        self._attempts[pending.approval_id] = attempt_number
        notification = Notification(
            approval_id=pending.approval_id,
            subject=pending.subject,
            tool=pending.tool,
            action_digest=pending.action_digest,
            summary=pending.summary,
            expires_at_epoch=pending.expires_at_epoch,
            attempt=attempt_number,
        )
        try:
            delivered = bool(self.channel.publish(notification))
            detail = "delivered" if delivered else "the channel reported a delivery failure"
        except Exception as exc:  # a transport fault is a delivery failure, never a decision
            delivered = False
            detail = f"the channel raised {type(exc).__name__}"
        record = DeliveryAttempt(
            approval_id=pending.approval_id,
            attempt=attempt_number,
            delivered=delivered,
            detail=detail[:240],
            at_epoch=self._clock(),
        )
        self.attempt_log.append(record)
        return record

    def undelivered(self, approval_id: str) -> bool:
        """True when every permitted attempt was made and none succeeded."""

        attempts = [record for record in self.attempt_log if record.approval_id == approval_id]
        if len(attempts) < self.max_attempts_per_approval:
            return False
        return not any(record.delivered for record in attempts)

    def _reject(self, decision: SignedDecision, rejection: DecisionRejection, detail: str) -> DecisionRecord:
        record = DecisionRecord(
            approval_id=decision.approval_id,
            accepted=False,
            subject=decision.subject,
            rejection=rejection,
            detail=detail[:240],
            at_epoch=self._clock(),
        )
        self.decision_log.append(record)
        return record

    def accept(self, decision: SignedDecision) -> DecisionRecord:
        """Verify a decision against the pending approval it claims to answer."""

        pending = self._pending.get(decision.approval_id)
        if pending is None:
            return self._reject(
                decision,
                DecisionRejection.UNKNOWN_APPROVAL,
                "no pending approval matches this decision",
            )
        if any(
            record.accepted and record.approval_id == decision.approval_id for record in self.decision_log
        ):
            return self._reject(
                decision, DecisionRejection.ALREADY_DECIDED, "this approval was already decided"
            )
        if decision.nonce in self._used_nonces:
            return self._reject(decision, DecisionRejection.NONCE_REPLAYED, "this nonce was already used")
        now = self._clock()
        if decision.expires_at_epoch <= now or pending.expires_at_epoch <= now:
            return self._reject(decision, DecisionRejection.DECISION_EXPIRED, "the decision window closed")
        if decision.subject != pending.subject:
            return self._reject(
                decision,
                DecisionRejection.SUBJECT_MISMATCH,
                "this approval is addressed to a different subject",
            )
        if decision.action_digest != pending.action_digest:
            return self._reject(
                decision, DecisionRejection.DIGEST_MISMATCH, "the decision covers a different action"
            )
        if decision.policy_version != pending.policy_version:
            return self._reject(
                decision,
                DecisionRejection.POLICY_VERSION_MISMATCH,
                "the policy version changed since the approval was published",
            )

        self._used_nonces.add(decision.nonce)
        record = DecisionRecord(
            approval_id=decision.approval_id,
            accepted=True,
            verdict=decision.verdict,
            subject=decision.subject,
            detail=decision.reason[:240],
            at_epoch=now,
        )
        self.decision_log.append(record)
        return record
