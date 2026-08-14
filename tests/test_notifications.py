from __future__ import annotations

import json

import pytest

from xt_aegis.notifications import (
    ApprovalNotifier,
    DecisionRejection,
    DecisionVerdict,
    Notification,
    PendingApproval,
    SignedDecision,
)

DIGEST = "a" * 64
NOW = 5_000.0


class RecordingChannel:
    """A synthetic transport. No test here sends a real message anywhere."""

    def __init__(self, *, results: list[bool | Exception] | None = None) -> None:
        self._results = list(results or [])
        self.published: list[Notification] = []

    def publish(self, notification: Notification) -> bool:
        self.published.append(notification)
        if not self._results:
            return True
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _pending(**overrides: object) -> PendingApproval:
    values: dict[str, object] = {
        "approval_id": "approval-1",
        "subject": "user:alice",
        "tool": "apply_patch",
        "action_digest": DIGEST,
        "policy_version": "1.0",
        "summary": "one bounded change to sample_project/app.py",
        "expires_at_epoch": NOW + 600,
    }
    values.update(overrides)
    return PendingApproval(**values)  # type: ignore[arg-type]


def _decision(**overrides: object) -> SignedDecision:
    values: dict[str, object] = {
        "approval_id": "approval-1",
        "subject": "user:alice",
        "action_digest": DIGEST,
        "policy_version": "1.0",
        "verdict": DecisionVerdict.APPROVED,
        "reason": "reviewed the diff",
        "nonce": "decision-nonce-1",
        "expires_at_epoch": NOW + 300,
    }
    values.update(overrides)
    return SignedDecision(**values)  # type: ignore[arg-type]


def _notifier(**overrides: object) -> ApprovalNotifier:
    channel = overrides.pop("channel", None) or RecordingChannel()
    return ApprovalNotifier(
        channel,  # type: ignore[arg-type]
        max_attempts_per_approval=int(overrides.pop("max_attempts_per_approval", 3)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


def test_a_notification_carries_no_payload_or_credential() -> None:
    channel = RecordingChannel()
    notifier = _notifier(channel=channel)

    notifier.notify(_pending())

    published = channel.published[0]
    serialized = json.dumps(published.model_dump(mode="json"))
    assert set(published.model_dump()) == {
        "approval_id",
        "subject",
        "tool",
        "action_digest",
        "summary",
        "expires_at_epoch",
        "attempt",
    }
    for absent in ("content", "payload", "prompt", "argv", "token", "password"):
        assert absent not in serialized


def test_a_resume_re_notifies_only_up_to_the_ceiling() -> None:
    channel = RecordingChannel()
    notifier = _notifier(channel=channel, max_attempts_per_approval=2)
    pending = _pending()

    first = notifier.notify(pending)
    second = notifier.notify(pending)
    third = notifier.notify(pending)

    assert first is not None and second is not None
    assert third is None
    assert [item.attempt for item in channel.published] == [1, 2]


def test_a_delivery_failure_is_recorded_and_then_reported_undelivered() -> None:
    channel = RecordingChannel(results=[False, RuntimeError("smtp is down")])
    notifier = _notifier(channel=channel, max_attempts_per_approval=2)
    pending = _pending()

    notifier.notify(pending)
    notifier.notify(pending)

    assert [record.delivered for record in notifier.attempt_log] == [False, False]
    assert "delivery failure" in notifier.attempt_log[0].detail
    assert "RuntimeError" in notifier.attempt_log[1].detail
    assert notifier.undelivered("approval-1") is True


def test_a_partially_delivered_approval_is_not_reported_undelivered() -> None:
    notifier = _notifier(channel=RecordingChannel(results=[False, True]), max_attempts_per_approval=2)
    pending = _pending()

    notifier.notify(pending)
    notifier.notify(pending)

    assert notifier.undelivered("approval-1") is False


def test_an_accepted_decision_is_recorded_with_its_verdict() -> None:
    notifier = _notifier()
    notifier.notify(_pending())

    record = notifier.accept(_decision())

    assert record.accepted is True
    assert record.verdict is DecisionVerdict.APPROVED
    assert record.detail == "reviewed the diff"
    assert notifier.decision_log == [record]


def test_a_denial_is_accepted_as_a_decision() -> None:
    notifier = _notifier()
    notifier.notify(_pending())

    record = notifier.accept(_decision(verdict=DecisionVerdict.DENIED, reason="rejects the approach"))

    assert record.accepted is True
    assert record.verdict is DecisionVerdict.DENIED


def test_a_decision_for_an_unknown_approval_is_rejected() -> None:
    record = _notifier().accept(_decision())

    assert record.accepted is False
    assert record.rejection is DecisionRejection.UNKNOWN_APPROVAL


@pytest.mark.parametrize(
    ("overrides", "rejection"),
    [
        ({"subject": "user:mallory"}, DecisionRejection.SUBJECT_MISMATCH),
        ({"action_digest": "b" * 64}, DecisionRejection.DIGEST_MISMATCH),
        ({"policy_version": "2.0"}, DecisionRejection.POLICY_VERSION_MISMATCH),
    ],
    ids=lambda value: str(value),
)
def test_a_decision_that_does_not_match_the_pending_approval_is_rejected(
    overrides: dict[str, object], rejection: DecisionRejection
) -> None:
    notifier = _notifier()
    notifier.notify(_pending())

    record = notifier.accept(_decision(**overrides))

    assert record.accepted is False
    assert record.rejection is rejection


def test_a_forged_subject_cannot_approve_someone_elses_approval() -> None:
    """The channel may deliver anything; only a decision bound to the addressed subject counts."""

    notifier = _notifier()
    notifier.notify(_pending(subject="user:alice"))

    record = notifier.accept(_decision(subject="user:mallory"))

    assert record.accepted is False
    assert record.rejection is DecisionRejection.SUBJECT_MISMATCH


def test_a_replayed_nonce_is_rejected() -> None:
    notifier = _notifier()
    notifier.notify(_pending(approval_id="approval-1"))
    notifier.notify(_pending(approval_id="approval-2"))
    assert notifier.accept(_decision(approval_id="approval-1")).accepted is True

    replay = notifier.accept(_decision(approval_id="approval-2", nonce="decision-nonce-1"))

    assert replay.accepted is False
    assert replay.rejection is DecisionRejection.NONCE_REPLAYED


@pytest.mark.parametrize(
    "overrides",
    [{"expires_at_epoch": NOW - 1}, {"expires_at_epoch": NOW}],
    ids=["past", "exactly-now"],
)
def test_an_expired_decision_is_rejected(overrides: dict[str, object]) -> None:
    notifier = _notifier()
    notifier.notify(_pending())

    record = notifier.accept(_decision(**overrides))

    assert record.accepted is False
    assert record.rejection is DecisionRejection.DECISION_EXPIRED


def test_a_decision_arriving_after_the_approval_window_closed_is_rejected() -> None:
    notifier = _notifier()
    notifier.notify(_pending(expires_at_epoch=NOW - 1))

    record = notifier.accept(_decision())

    assert record.accepted is False
    assert record.rejection is DecisionRejection.DECISION_EXPIRED


def test_an_approval_cannot_be_decided_twice() -> None:
    notifier = _notifier()
    notifier.notify(_pending())
    assert notifier.accept(_decision()).accepted is True

    second = notifier.accept(_decision(nonce="decision-nonce-2", verdict=DecisionVerdict.DENIED))

    assert second.accepted is False
    assert second.rejection is DecisionRejection.ALREADY_DECIDED


def test_every_attempt_and_decision_is_recorded_as_evidence() -> None:
    notifier = _notifier(channel=RecordingChannel(results=[False, True]))
    pending = _pending()
    notifier.notify(pending)
    notifier.notify(pending)
    notifier.accept(_decision(subject="user:mallory"))
    notifier.accept(_decision())

    assert [record.attempt for record in notifier.attempt_log] == [1, 2]
    assert [record.accepted for record in notifier.decision_log] == [False, True]
    assert all(record.at_epoch == NOW for record in notifier.decision_log)


def test_a_zero_attempt_ceiling_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ApprovalNotifier(RecordingChannel(), max_attempts_per_approval=0)


def test_the_channel_cannot_approve_by_returning_true() -> None:
    """A transport reporting success publishes; it does not decide."""

    notifier = _notifier()
    notifier.notify(_pending())

    assert notifier.decision_log == []
